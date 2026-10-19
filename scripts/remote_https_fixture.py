"""Disposable real TLS server fixture; never a production server or trust-store installer."""

from __future__ import annotations

import asyncio
import json
import re
import secrets
import socket
import ssl
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import httpx
import uvicorn

from swu_happyrun.server.app import create_app
from swu_happyrun.server.settings import ServerSettings

ERROR_TYPES = frozenset(
    {
        "AssertionError",
        "RuntimeError",
        "ReadTimeout",
        "ConnectTimeout",
        "ConnectError",
        "HTTPStatusError",
        "TimeoutExpired",
        "CalledProcessError",
        "OSError",
        "ValueError",
        "FixtureLifecycleError",
    }
)
STACK_ALLOWLIST = {
    "remote_https_fixture.py": {"server_fixture", "__call__", "checked_send"},
    "app.py": {"tick_loop", "lifespan", "safe_failures"},
    "store.py": {"connection", "get", "create"},
    "leases.py": {"expire", "claim", "renew", "event", "stop_ack"},
    "scheduler.py": {"tick"},
    "server.py": {"run", "serve", "_serve", "main_loop", "on_tick", "shutdown"},
    "base_events.py": {"_run_once", "run_forever", "run_until_complete"},
    "selectors.py": {"select"},
    "threading.py": {"run", "wait", "join", "_bootstrap", "_bootstrap_inner"},
    "queue.py": {"get"},
}


def error_type(error):
    if error is None:
        return None
    name = type(error).__name__
    return name if name in ERROR_TYPES else "other_exception"


class FixtureLifecycleError(RuntimeError):
    def __init__(self, phase):
        assert phase in {"startup", "shutdown"}
        self.phase = phase
        super().__init__("fixture_lifecycle_failed")


def thread_evidence(thread):
    """Read only fixed source coordinates; never arguments, locals, paths or source text."""
    frame = sys._current_frames().get(thread.ident)
    result = []
    omitted = 0
    while frame is not None:
        name = Path(frame.f_code.co_filename).name
        function = frame.f_code.co_name
        if function in STACK_ALLOWLIST.get(name, set()):
            result.append({"file": name, "function": function, "line": frame.f_lineno})
        else:
            omitted += 1
        frame = frame.f_back
    return {
        "alive": thread.is_alive(),
        "frames": result[:24],
        "omitted_frames": omitted,
    }


def project_thread_evidence():
    """Capture only known project frames, including SQLite/scheduler worker positions."""
    results = []
    project_files = {"app.py", "store.py", "leases.py", "scheduler.py"}
    for frame in sys._current_frames().values():
        frames = []
        while frame is not None:
            name = Path(frame.f_code.co_filename).name
            function = frame.f_code.co_name
            if name in project_files and function in STACK_ALLOWLIST[name]:
                frames.append({"file": name, "function": function, "line": frame.f_lineno})
            frame = frame.f_back
        if frames:
            results.append(frames[:16])
    return results[:16]


def instrumentation_evidence(output):
    combined = "\n".join(output)
    markers = []
    for line in output:
        if re.fullmatch(
            r"FOREGROUND_QA (?:WAITING|RUNNING|LATCHED|RECONNECTED|RAPID_DONE|TWO_DONE|"
            r"STOPPED starts=[012]|PASS starts=[012] stopped=true)",
            line,
        ):
            markers.append(line.removeprefix("FOREGROUND_QA "))
    # These are controlled Java assertion labels, never raw exception text.
    labels = (
        "Main entry did not open remote page",
        "Back stopped old Activity",
        "Home really backgrounded Activity",
        "worker session reference released",
        "first rapid session exits",
        "explicit reconnect waiting",
        "new executor work really starts",
        "new work completes visibly",
        "visible idle wait",
        "Automatic reconnect after leave",
        "Driver not stopped",
        "Credential persisted in app private data",
    )
    return {
        "markers": markers[:12],
        "junit_ok_one": len(re.findall(r"OK \(1 test\)", combined)),
        "platform_failure": bool(
            re.search(r"FAILURES|INSTRUMENTATION_(?:FAILED|ABORTED)", combined)
        ),
        "known_assertions": [label for label in labels if label in combined],
    }


def failure_evidence(error, diagnostics):
    chain = []
    current = error
    while current is not None and len(chain) < 6:
        chain.append(error_type(current))
        current = current.__cause__ or current.__context__
    return {"error_chain": chain, **diagnostics}


def issue_certificates(directory: Path) -> dict[str, Path]:
    """Generate ephemeral private keys. Only ca.pem may enter the remoteQa APK."""
    directory.mkdir(parents=True, exist_ok=True)
    paths = {
        name: directory / name
        for name in (
            "ca.pem",
            "ca.key",
            "server.pem",
            "server.key",
            "server.csr",
            "server.ext",
            "wrong.pem",
            "wrong.key",
            "wrong.csr",
            "wrong.ext",
            "other.pem",
            "other.key",
        )
    }

    def openssl(*args):
        subprocess.run(["openssl", *map(str, args)], check=True, capture_output=True, timeout=30)

    openssl(
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-days",
        "1",
        "-subj",
        "/CN=HappyRun disposable QA CA",
        "-keyout",
        paths["ca.key"],
        "-out",
        paths["ca.pem"],
        "-addext",
        "basicConstraints=critical,CA:TRUE",
        "-addext",
        "keyUsage=critical,keyCertSign,cRLSign",
    )
    for name, san in (
        ("server", "IP:127.0.0.1,IP:10.0.2.2"),
        ("wrong", "DNS:wrong.invalid"),
    ):
        openssl(
            "req",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-subj",
            "/CN=synthetic-only",
            "-keyout",
            paths[name + ".key"],
            "-out",
            paths[name + ".csr"],
        )
        paths[name + ".ext"].write_text(
            "basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n"
            "extendedKeyUsage=serverAuth\nsubjectAltName=" + san + "\n",
            encoding="utf-8",
        )
        openssl(
            "x509",
            "-req",
            "-in",
            paths[name + ".csr"],
            "-CA",
            paths["ca.pem"],
            "-CAkey",
            paths["ca.key"],
            "-CAcreateserial",
            "-days",
            "1",
            "-out",
            paths[name + ".pem"],
            "-extfile",
            paths[name + ".ext"],
        )
    openssl(
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-days",
        "1",
        "-subj",
        "/CN=untrusted-synthetic-only",
        "-keyout",
        paths["other.key"],
        "-out",
        paths["other.pem"],
        "-addext",
        "subjectAltName=IP:127.0.0.1,IP:10.0.2.2",
    )
    for path in directory.glob("*.key"):
        path.chmod(0o600)
    return paths


class RequestEvidence:
    """Only nonsecret request metadata; excludes headers, bodies and raw exception text."""

    def __init__(self, app, scenario="normal"):
        self.app = app
        self.scenario = scenario
        self.renew_count = 0
        self.event_count = 0
        self.barrier = threading.Event()
        self.release = threading.Event()
        self.fault_used = False
        self.committed_states = []
        self.records: list[dict] = []
        self.lock = threading.Lock()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        record = {"method": scope["method"], "path": scope["path"], "status": None}
        if scope["path"].endswith("/events"):
            self.event_count += 1
        if scope["path"].endswith("/renew"):
            self.renew_count += 1
            if self.renew_count == 4 and self.scenario in {
                "cancel",
                "lost_renew",
                "restart",
            }:
                self.barrier.set()
                if self.scenario == "cancel":
                    deadline = time.monotonic() + 3
                    while not self.release.is_set() and time.monotonic() < deadline:
                        await asyncio.sleep(0.01)
                    if not self.release.is_set():
                        raise RuntimeError("host cancellation barrier not released")
                else:
                    self.fault_used = True
                    await asyncio.sleep(7)
                    await send({"type": "http.response.start", "status": 503, "headers": []})
                    await send({"type": "http.response.body", "body": b""})
                    record["status"] = 503
                    with self.lock:
                        self.records.append(record)
                    return
        if self.scenario == "redirect" and scope["path"].endswith("/agents/hello"):
            await send(
                {
                    "type": "http.response.start",
                    "status": 307,
                    "headers": [(b"location", b"http://127.0.0.1:9/never")],
                }
            )
            await send({"type": "http.response.body", "body": b""})
            with self.lock:
                self.records.append({**record, "status": 307})
            return
        buffered = []
        fault_after_commit = False

        async def checked_send(message):
            if message["type"] == "http.response.start":
                record["status"] = message["status"]
            if (
                self.scenario == "lost_event"
                and scope["path"].endswith("/events")
                and not self.fault_used
            ):
                buffered.append(message)
            else:
                await send(message)

        try:
            await self.app(scope, receive, checked_send)
            if buffered:
                body = b"".join(m.get("body", b"") for m in buffered)
                try:
                    state = json.loads(body).get("state")
                    self.committed_states.append(state)
                    fault_after_commit = state == "finishing"
                except (ValueError, AttributeError):
                    pass
                if fault_after_commit:
                    self.fault_used = True
                    self.barrier.set()
                    await asyncio.sleep(7)
                for message in buffered:
                    await send(message)
        finally:
            with self.lock:
                self.records.append(record)


@contextmanager
def server_fixture(
    directory: Path,
    certificates: dict[str, Path],
    certificate="server",
    scenario="normal",
    diagnostics=None,
):
    """Run the actual candidate app over TLS on host loopback, with synthetic ownership."""
    if certificate not in {"server", "wrong", "other"}:
        raise ValueError("unknown fixture certificate")
    directory.mkdir(parents=True, exist_ok=True)
    agent_id, device_id = str(uuid4()), str(uuid4())
    admin_token, agent_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    app = create_app(
        ServerSettings(directory / "server.sqlite", admin_token, {agent_id: agent_token})
    )
    evidence = RequestEvidence(app, scenario)
    config = uvicorn.Config(
        evidence,
        host="127.0.0.1",
        port=port,
        access_log=False,
        log_level="critical",
        ssl_certfile=str(certificates[certificate + ".pem"]),
        ssl_keyfile=str(certificates[certificate + ".key"]),
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    diagnostics = diagnostics if diagnostics is not None else {}
    diagnostics["fixture_phase"] = "startup"
    primary = None
    try:
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        if not server.started:
            diagnostics["fixture_startup_code"] = "startup_failed"
            diagnostics["server_thread"] = thread_evidence(thread)
            raise FixtureLifecycleError("startup")
        diagnostics["fixture_phase"] = "body"
        yield {
            "origin": f"https://127.0.0.1:{port}",
            "android_origin": f"https://10.0.2.2:{port}",
            "agent_id": agent_id,
            "device_id": device_id,
            "admin_token": admin_token,
            "agent_token": agent_token,
            "evidence": evidence,
            "app": app,
            "port": port,
        }
    except BaseException as error:
        primary = error
        raise
    finally:
        diagnostics["fixture_primary_phase"] = diagnostics["fixture_phase"]
        diagnostics["fixture_body_error_type"] = (
            error_type(primary) if diagnostics["fixture_phase"] == "body" else None
        )
        diagnostics["fixture_primary_error_type"] = error_type(primary)
        diagnostics["fixture_phase"] = "shutdown"
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        if thread.is_alive():
            diagnostics["fixture_shutdown_code"] = "shutdown_failed"
            diagnostics["server_thread"] = thread_evidence(thread)
            diagnostics["project_thread_stacks"] = project_thread_evidence()
            diagnostics["server_started"] = bool(server.started)
            diagnostics["connections"] = len(server.server_state.connections)
            diagnostics["tasks"] = len(server.server_state.tasks)
            raise FixtureLifecycleError("shutdown") from primary
        diagnostics["fixture_phase"] = "closed"


def trusted_client(ca: Path) -> httpx.Client:
    return httpx.Client(
        verify=ssl.create_default_context(cafile=str(ca)), trust_env=False, timeout=5
    )


def redact_report(path: Path, result: dict) -> None:
    allowed = {
        "case",
        "result",
        "server_state",
        "driver_starts",
        "driver_stopped",
        "request_count",
    }
    if set(result) - allowed:
        raise ValueError("unapproved report field")
    path.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
