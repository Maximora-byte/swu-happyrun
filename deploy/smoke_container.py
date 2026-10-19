"""Disposable Docker Compose + real Python fake-agent HTTP acceptance.

Never point this at an existing server. Only the generated Compose project/volume
is removed. Reports contain fixed check names, never tokens, logs, or databases.
"""

import importlib.util
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8080"
_spec = importlib.util.spec_from_file_location("fake_fixture", ROOT / "deploy/smoke_fake.py")
_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture)
SmokeFailure = _fixture.SmokeFailure
require = _fixture.require


class Api:
    def __init__(self, base, admin, agent, other):
        require(base == BASE, "Container probe requires fixed private loopback")
        self.tokens = {"admin": admin, "agent": agent, "other": other}
        self.http = httpx.Client(base_url=base + "/api/v1/", trust_env=False, timeout=5)

    def call(self, method, path, body=None, *, role="admin", expected=200, key=None):
        headers = {} if role is None else {"Authorization": "Bearer " + self.tokens[role]}
        if key:
            headers["Idempotency-Key"] = key
        response = self.http.request(method, path, json=body, headers=headers)
        require(response.status_code == expected, "Unexpected API status at " + path.split("/")[0])
        require(
            all(t not in response.text for t in self.tokens.values()), "Response leaked credential"
        )
        return response.json() if response.content else None

    def ready(self):
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            try:
                if self.call("GET", "ready", role=None) == {
                    "status": "ready",
                    "protocol_version": 1,
                }:
                    return
            except (httpx.HTTPError, SmokeFailure):
                time.sleep(0.2)
        raise SmokeFailure("Container readiness deadline")


class Container:
    def __init__(self, root, env, *, run=subprocess.run):
        self.env = env
        self.run = run
        self.project = "happyrun-smoke-" + uuid4().hex
        self.prefix = [
            "docker",
            "compose",
            "--project-name",
            self.project,
            "--file",
            str(ROOT / "deploy/compose.yaml"),
        ]
        self.root = root
        self.previous_logs = ""

    def command(self, *args, timeout=120, check=True):
        result = self.run(
            self.prefix + list(args),
            env=self.env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        require(not check or result.returncode == 0, "Compose operation failed: " + args[0])
        return result.stdout

    def start(self):
        self.command("config", "--quiet")
        self.command("build", timeout=600)
        self.command("up", "--detach", "--no-build")

    def recreate(self):
        self.previous_logs += self.command("logs", "--no-color", "server")
        before = self.command("ps", "--quiet", "server").strip()
        require(bool(before), "Missing container before recreation")
        self.command("down", "--timeout", "10")  # Preserve this project's named volume.
        self.command("up", "--detach", "--no-build")
        after = self.command("ps", "--quiet", "server").strip()
        require(bool(after) and after != before, "Container was not recreated")

    def runtime_checks(self):
        code = (
            "import os,sqlite3; assert os.getuid()==10001; "
            "db=sqlite3.connect('/data/happyrun.sqlite3'); "
            "assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'; "
            "assert db.execute('PRAGMA user_version').fetchone()[0]==3; "
            "print('private_sqlite_ok')"
        )
        require(
            self.command("exec", "-T", "server", "python", "-c", code).strip()
            == "private_sqlite_ok",
            "Nonroot SQLite integrity check failed",
        )
        cid = self.command("ps", "--quiet", "server").strip()
        result = self.run(
            ["docker", "inspect", "--format", "{{json .HostConfig}}", cid],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        require(result.returncode == 0, "Cannot verify container hardening")
        config = json.loads(result.stdout)
        require(
            config["ReadonlyRootfs"] and not config["Privileged"],
            "Container filesystem isolation lost",
        )
        require("ALL" in config["CapDrop"], "Container capabilities not dropped")
        require(
            "no-new-privileges:true" in config["SecurityOpt"], "Privilege escalation not disabled"
        )
        require(
            config["PortBindings"] == {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8080"}]},
            "Container port is not loopback-only",
        )

        deadline = time.monotonic() + 45
        while True:
            health = self.run(
                ["docker", "inspect", "--format", "{{.State.Health.Status}}", cid],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if health.returncode == 0 and health.stdout.strip() == "healthy":
                break
            require(time.monotonic() < deadline, "Docker HEALTHCHECK did not become healthy")
            time.sleep(0.5)

    def provenance(self):
        cid = self.command("ps", "--quiet", "server").strip()
        image = self.run(
            ["docker", "inspect", "--format", "{{.Image}}", cid],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        require(
            image.returncode == 0
            and re.fullmatch(r"sha256:[0-9a-f]{64}", image.stdout.strip()) is not None,
            "Invalid local image digest observation",
        )
        version = self.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        require(
            version.returncode == 0
            and len(version.stdout.strip()) <= 64
            and re.fullmatch(
                r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+.][A-Za-z0-9.-]+)?", version.stdout.strip()
            )
            is not None,
            "Invalid Docker version observation",
        )
        # A local image configuration digest is not a published registry manifest digest.
        return {
            "image_id": image.stdout.strip(),
            "docker_server_version": version.stdout.strip(),
            "registry_digest": None,
        }

    def cleanup(self):
        self.command("down", "--volumes", "--remove-orphans", "--timeout", "10")


def hello(api, agent_id, device_id):
    return api.call(
        "POST",
        "agents/hello",
        {
            "protocol_version": 1,
            "agent_id": agent_id,
            "devices": [
                {
                    "device_id": device_id,
                    "backend": "fake",
                    "app_version": None,
                    "capabilities": [],
                    "observed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    "probe_id": str(uuid4()),
                }
            ],
        },
        role="agent",
    )


def lease(grant):
    return {key: grant[key] for key in ("lease_token", "fence")}


def agent_environment(env):
    return {
        key: value
        for key, value in env.items()
        if key not in {"HAPPYRUN_ADMIN_TOKEN", "HAPPYRUN_AGENT_TOKENS"}
    }


def exercise(api, root, env, agent_id, device_id, recreate):
    api.ready()
    api.call("GET", "health", role=None)
    api.call("GET", "jobs", role=None, expected=401)
    api.call("GET", "jobs", role="agent", expected=403)
    api.call("POST", "leases/claim", {"device_id": device_id}, role="admin", expected=403)
    api.call("POST", "devices", {"device_id": device_id, "agent_id": agent_id}, expected=201)
    spec = _fixture.create_fixture(root, device_id).model_dump(mode="json")
    key = str(uuid4())
    job = api.call("POST", "jobs", spec, key=key, expected=201)
    require(
        api.call("POST", "jobs", spec, key=key)["job_id"] == job["job_id"], "Idempotency mismatch"
    )
    agent = subprocess.run(
        [
            sys.executable,
            "-m",
            "swu_happyrun",
            "agent",
            "--url",
            BASE,
            "--agent-id",
            agent_id,
            "--device-id",
            device_id,
            "--backend",
            "fake",
            "--profiles",
            str(root / "profiles"),
            "--journal",
            str(root / "agent.sqlite3"),
            "--app-version",
            "test-1",
            "--fake-state",
            str(root / "fake.json"),
            "--run-seconds",
            "2",
            "--route-speed-mps",
            "2",
            "--once",
        ],
        env=agent_environment(env),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    require(agent.returncode == 0, "Python fake agent failed")
    require(
        all(t not in agent.stdout + agent.stderr for t in api.tokens.values()),
        "Agent credential leak",
    )
    result = json.loads(agent.stdout)
    require(
        result["job_id"] == job["job_id"] and result["state"] == "completed",
        "Fake job not completed",
    )
    require(not result.get("evidence"), "Simulation produced record evidence")
    require(json.loads((root / "fake.json").read_text())["route_finished"], "Fake route incomplete")
    require(api.call("GET", "jobs/" + job["job_id"]) == result, "Agent HTTP result differs")
    api.call("GET", "jobs/" + job["job_id"], role="other", expected=404)

    # Real time lease expiry, with no injected server clock or direct DB mutation.
    pending = api.call("POST", "jobs", spec, key=str(uuid4()), expected=201)
    hello(api, agent_id, device_id)
    old = api.call("POST", "leases/claim", {"device_id": device_id}, role="agent")
    path = "jobs/" + pending["job_id"]
    require(old["job"]["job_id"] == pending["job_id"], "Wrong claimed job")
    api.call("POST", path + "/renew", lease(old), role="other", expected=404)
    require("lease_token" not in api.call("GET", path), "Public view contains lease token")
    expires = datetime.fromisoformat(old["expires_at"].replace("Z", "+00:00"))
    time.sleep(max(0, (expires - datetime.now(UTC)).total_seconds()) + 0.5)
    api.call("POST", path + "/renew", lease(old), role="agent", expected=409)
    hello(api, agent_id, device_id)
    newer = api.call("POST", "leases/claim", {"device_id": device_id}, role="agent")
    require(newer["fence"] > old["fence"], "Lease fence did not advance")
    api.call("POST", path + "/renew", lease(old), role="agent", expected=409)
    for state in ("preflight", "ready", "running"):
        newer["job"] = api.call(
            "POST",
            path + "/events",
            {
                "lease": lease(newer),
                "event": {
                    "event_id": str(uuid4()),
                    "expected_revision": newer["job"]["revision"],
                    "state": state,
                    "reason_code": None,
                    "evidence": [],
                    "resume_phase": None,
                },
            },
            role="agent",
        )
    cancelling = api.call("POST", path + "/cancel")
    require(cancelling["state"] == "cancelling", "Cancel falsely claimed stop")
    ack = {
        "lease": lease(newer),
        "event_id": str(uuid4()),
        "expected_revision": cancelling["revision"],
    }
    cancelled = api.call("POST", path + "/stop-ack", ack, role="agent")
    require(cancelled["state"] == "cancelled", "Stop ack not applied")
    require(
        api.call("POST", path + "/stop-ack", ack, role="agent") == cancelled, "Ack replay mismatch"
    )

    # Next-minute occurrence avoids a date boundary race; no server clock injection.
    now = (datetime.now(ZoneInfo("Asia/Shanghai")) + timedelta(minutes=1)).replace(
        second=0, microsecond=0
    )
    schedule = {
        "schedule_id": str(uuid4()),
        "job_template": spec,
        "timezone": "Asia/Shanghai",
        "local_time": now.strftime("%H:%M"),
        "weekdays": [now.isoweekday()],
        "enabled": True,
    }
    api.call("POST", "schedules", schedule, expected=201)
    deadline = time.monotonic() + 80
    while True:
        items = api.call("GET", "jobs?limit=100")["items"]
        if len(items) == 3:
            break
        require(time.monotonic() < deadline, "Scheduler did not create one occurrence")
        time.sleep(0.2)
    ids = {item["job_id"] for item in items}
    recreate()
    api.ready()
    time.sleep(2)  # Observe multiple real scheduler ticks after new-container startup.
    require(
        api.call("GET", "jobs/" + job["job_id"]) == result, "Completed job lost after recreation"
    )
    require(api.call("GET", path) == cancelled, "Cancellation lost after recreation")
    require(
        {i["job_id"] for i in api.call("GET", "jobs?limit=100")["items"]} == ids,
        "Schedule duplicated or jobs lost after recreation",
    )
    require(api.call("GET", "schedules") == [schedule], "Schedule lost after recreation")
    require(
        api.call("POST", "jobs", spec, key=key)["job_id"] == job["job_id"],
        "Idempotency lost after recreation",
    )
    api.call("GET", "jobs", role="agent", expected=403)
    api.call("GET", "jobs/" + job["job_id"], role="other", expected=404)
    hello(api, agent_id, device_id)
    recovered = api.call("POST", "leases/claim", {"device_id": device_id}, role="agent")
    require(recovered["fence"] > newer["fence"], "Device fence not durable across recreation")
    api.call("POST", path + "/renew", lease(old), role="agent", expected=409)
    api.call("POST", path + "/stop-ack", ack, role="agent", expected=409)
    return [
        "health_ready",
        "admin_agent_isolation",
        "python_fake_agent_http_completed",
        "lease_expiry_and_fence",
        "cancel_stop_ack_replay",
        "schedule_occurrence_dedup",
        "new_container_named_volume_persistence",
        "idempotency_persistence",
    ]


def failure_report(error):
    return {
        "status": "failed",
        "reason": str(error)
        if isinstance(error, SmokeFailure)
        else "Unexpected probe failure; no private diagnostics published",
        "container_verified": False,
    }


def verify_docker_target(env, run=subprocess.run):
    require(
        not any(
            env.get(name)
            for name in ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH")
        ),
        "Docker endpoint overrides are not allowed in disposable probe",
    )
    context = run(
        ["docker", "context", "show"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    require(
        context.returncode == 0 and context.stdout.strip() == "default",
        "Disposable probe requires default Docker context",
    )
    endpoint = run(
        ["docker", "context", "inspect", "default", "--format", "{{.Endpoints.docker.Host}}"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    require(
        endpoint.returncode == 0 and endpoint.stdout.strip() == "unix:///var/run/docker.sock",
        "Disposable probe requires local runner Docker socket",
    )


def run():
    require(
        os.environ.get("HAPPYRUN_DISPOSABLE_DOCKER") == "1"
        and os.environ.get("GITHUB_ACTIONS") == "true"
        and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted",
        "Container probe requires explicitly disposable GitHub-hosted runner",
    )
    verify_docker_target(os.environ)
    # Fixed port is deliberate: exercise the unmodified deployment file on a fresh runner.
    with socket.socket() as sock:
        require(
            sock.connect_ex(("127.0.0.1", 8080)) != 0,
            "Loopback port already occupied; refusing existing service",
        )
    with tempfile.TemporaryDirectory(prefix="happyrun-container-") as directory:
        root = Path(directory)
        agent_id, device_id, other_id = str(uuid4()), str(uuid4()), str(uuid4())
        admin, agent, other = (secrets.token_urlsafe(32) for _ in range(3))
        env = {
            **os.environ,
            "HAPPYRUN_ADMIN_TOKEN": admin,
            "HAPPYRUN_AGENT_TOKENS": json.dumps({agent_id: agent, other_id: other}),
            "HAPPYRUN_AGENT_TOKEN": agent,
            "SWU_HAPPYRUN_HOST_ID_FILE": str(root / "host-id"),
        }
        container = Container(root, env)
        api = Api(BASE, admin, agent, other)
        try:
            container.start()
            checks = exercise(api, root, env, agent_id, device_id, container.recreate)
            container.runtime_checks()
            provenance = container.provenance()
            logs = container.previous_logs + container.command("logs", "--no-color", "server")
            require(
                all(t not in logs for t in api.tokens.values()), "Container log credential leak"
            )
        finally:
            api.http.close()
            container.cleanup()
    return {
        "status": "passed",
        "container_verified": True,
        "provenance": provenance,
        "mode": "simulation",
        "checks": checks + ["nonroot_hardening", "sqlite_integrity_schema3", "log_redaction"],
        "device_verified": False,
        "record_verified": False,
        "android_agent_connected": False,
    }


if __name__ == "__main__":
    try:
        report = run()
    except Exception as error:
        report = failure_report(error)
    print(json.dumps(report))
    raise SystemExit(0 if report["status"] == "passed" else 1)
