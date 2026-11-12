"""Own simulation server bound only to the operator's explicit private IPv4 address.

Uses locally retained server key; never generates, copies or reports it. This fixture
is independent of the official AVD fixture's origin and safety assumptions.
"""

from __future__ import annotations

import secrets
import socket
import ssl
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import uvicorn
from check_mumu_https import private_host
from remote_https_fixture import FixtureLifecycleError, RequestEvidence

from swu_happyrun.server.app import create_app
from swu_happyrun.server.settings import ServerSettings


@contextmanager
def local_fixture(directory, certificate, key, host, port, scenario):
    host = private_host(host)
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("invalid_port")
    if scenario not in {"normal", "cancel", "lost_renew", "restart"}:
        raise ValueError("unknown_fault_scenario")
    # Fail synchronously before a listener exists, including a certificate/key mismatch.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(certificate), str(key))
    directory = Path(directory)
    if any(p.is_symlink() for p in (directory, *directory.parents)):
        raise ValueError("symlink_fixture_directory_rejected")
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    agent, device = str(uuid4()), str(uuid4())
    admin_token, agent_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    app = create_app(ServerSettings(directory / "server.sqlite", admin_token, {agent: agent_token}))
    evidence = RequestEvidence(app, scenario)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server = None
    thread = None
    primary = None
    try:
        sock.bind((host, port))
        port = sock.getsockname()[1]
        config = uvicorn.Config(
            evidence,
            host=host,
            port=port,
            access_log=False,
            log_level="critical",
            ssl_certfile=str(certificate),
            ssl_keyfile=str(key),
        )
        config.load()
        # Keep Uvicorn's normal TLS validation; minimum protocol is additionally bounded.
        config.ssl.minimum_version = ssl.TLSVersion.TLSv1_2
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        if not server.started:
            raise FixtureLifecycleError("startup")
        origin = f"https://{host}:{port}"
        yield {
            "origin": origin,
            "android_origin": origin,
            "port": port,
            "agent_id": agent,
            "device_id": device,
            "admin_token": admin_token,
            "agent_token": agent_token,
            "evidence": evidence,
            "app": app,
            "server": server,
            "thread": thread,
        }
    except BaseException as error:
        primary = error
        raise
    finally:
        cleanup_failed = False
        try:
            if server is not None:
                server.should_exit = True
            if thread is not None:
                thread.join(timeout=10)
        except BaseException:
            cleanup_failed = True
        try:
            sock.close()
        except OSError:
            cleanup_failed = True
        if cleanup_failed or (thread is not None and thread.is_alive()):
            if primary is None:
                raise FixtureLifecycleError("shutdown")
            # Preserve the original body exception and a separate fixed cleanup category.
            primary.add_note("fixture_shutdown_failed")
            primary.fixture_cleanup_error_type = "FixtureLifecycleError"
