"""Real TCP and subprocess shutdown/reconnect; synthetic state only."""

import importlib.util
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import uvicorn
from starlette.responses import JSONResponse

from swu_happyrun.server.app import create_app
from swu_happyrun.server.settings import ServerSettings

ROOT = Path(__file__).resolve().parents[2]
AGENT = str(uuid4())
DEVICE = str(uuid4())


@pytest.fixture
def service(tmp_path):
    app = create_app(
        ServerSettings(
            database_path=tmp_path / "server.db",
            admin_token="test-admin",
            agent_tokens={AGENT: "test-agent"},
        )
    )
    faults = {
        "hello": 0,
        "heartbeat": 0,
        "claim": 0,
        "renew": 0,
        "renew_calls": 0,
        "renew_active_state": None,
        "renew_failed_at": None,
        "renew_active_snapshot": None,
        "hello_calls": 0,
        "heartbeat_calls": 0,
        "claim_calls": 0,
    }

    @app.middleware("http")
    async def transient(request, call_next):
        name = request.url.path.rsplit("/", 1)[-1]
        if name == "claim":
            faults["claim_calls"] += 1
            if faults["claim"]:
                faults["claim"] -= 1
                await call_next(request)
                return JSONResponse({"error": "lost response"}, status_code=503)
        if name in {"hello", "heartbeat", "renew"}:
            faults[name + "_calls"] += 1
            # The child cannot finish a route before this synchronous request
            # returns. Arm before launch and inject only after durable start,
            # rather than racing a parent's poll against the brief active window.
            state_path = faults["renew_active_state"] if name == "renew" else None
            if state_path is not None and state_path.exists():
                saved = json.loads(state_path.read_text())
                if saved["active"]:
                    faults["renew_active_snapshot"] = saved
                    faults["renew_failed_at"] = faults["renew_calls"]
                    faults["renew_active_state"] = None
                    return JSONResponse({"error": "active renewal failed"}, status_code=503)
            if faults[name]:
                faults[name] -= 1
                return JSONResponse({"error": "transient"}, status_code=503)
        return await call_next(request)

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.02)
    url = "http://127.0.0.1:" + str(sock.getsockname()[1])
    with httpx.Client(
        base_url=url + "/api/v1/", headers={"Authorization": "Bearer test-admin"}, trust_env=False
    ) as client:
        assert (
            client.post("devices", json={"agent_id": AGENT, "device_id": DEVICE}).status_code == 201
        )
        yield url, client, faults
    server.should_exit = True
    thread.join(10)
    sock.close()


def launch(root, url, *extra):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "HAPPYRUN_AGENT_TOKEN": "test-agent"}
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "swu_happyrun",
            "agent",
            "--url",
            url,
            "--agent-id",
            AGENT,
            "--device-id",
            DEVICE,
            "--journal",
            str(root / "journal.db"),
            "--profiles",
            str(root / "profiles"),
            "--run-seconds",
            "60",
            *extra,
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def wait_until(predicate, timeout=10):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.03)
    raise AssertionError("condition did not become true")


@pytest.mark.skipif(os.name == "nt", reason="Windows terminate is not a catchable SIGTERM")
@pytest.mark.parametrize(
    "signum,scenario",
    [(signal.SIGTERM, "normal"), (signal.SIGINT, "normal"), (signal.SIGTERM, "stop_failure")],
)
def test_sigterm_stops_active_fake_and_reports_uncertainty(service, tmp_path, signum, scenario):
    url, client, _ = service
    spec = importlib.util.spec_from_file_location("smoke_fixture", ROOT / "deploy/smoke_fake.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    job = module.create_fixture(tmp_path, DEVICE)
    response = client.post(
        "jobs", json=job.model_dump(mode="json"), headers={"Idempotency-Key": str(uuid4())}
    )
    assert response.status_code == 201
    job_id = response.json()["job_id"]
    process = launch(tmp_path, url, "--scenario", scenario)
    state = tmp_path / "journal.fake.json"
    try:
        wait_until(lambda: state.exists() and json.loads(state.read_text())["active"])
        process.send_signal(signum)
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 128 + signum, (stdout, stderr)
        saved = json.loads(state.read_text())
        assert not saved["active"] and saved["stop_count"] == 1 and saved["start_count"] == 1
        assert client.get("jobs/" + job_id).json()["state"] == "needs_attention"
        assert "test-agent" not in stdout + stderr
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()


def test_daemon_reconnects_transient_hello_without_crashing(service, tmp_path):
    url, _, faults = service
    faults["hello"] = 1
    process = launch(tmp_path, url)
    try:
        wait_until(lambda: faults["hello_calls"] >= 2 or process.poll() is not None)
        assert faults["hello_calls"] >= 2
        assert process.poll() is None
    finally:
        process.terminate()
        process.communicate(timeout=10)


def test_idle_heartbeat_reconnects_without_claim_replay(service, tmp_path):
    url, _, faults = service
    faults["heartbeat"] = 1
    process = launch(tmp_path, url)
    try:
        wait_until(lambda: faults["heartbeat_calls"] >= 2 or process.poll() is not None)
        assert faults["heartbeat_calls"] >= 2
        assert process.poll() is None
    finally:
        process.terminate()
        process.communicate(timeout=10)


def test_lost_claim_response_is_not_retried(service, tmp_path):
    url, client, faults = service
    spec = importlib.util.spec_from_file_location("smoke_fixture", ROOT / "deploy/smoke_fake.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    job = module.create_fixture(tmp_path, DEVICE)
    created = client.post(
        "jobs", json=job.model_dump(mode="json"), headers={"Idempotency-Key": str(uuid4())}
    )
    assert created.status_code == 201
    faults["claim"] = 1
    process = launch(tmp_path, url)
    stdout, stderr = process.communicate(timeout=10)
    assert process.returncode == 3
    assert faults["claim_calls"] == 1
    assert client.get("jobs/" + created.json()["job_id"]).json()["state"] == "leased"
    assert not (tmp_path / "journal.fake.json").exists()
    assert "test-agent" not in stdout + stderr


def test_active_renewal_failure_stops_without_retrying_lease(service, tmp_path):
    url, client, faults = service
    spec = importlib.util.spec_from_file_location("smoke_fixture", ROOT / "deploy/smoke_fake.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    job = module.create_fixture(tmp_path, DEVICE)
    response = client.post(
        "jobs", json=job.model_dump(mode="json"), headers={"Idempotency-Key": str(uuid4())}
    )
    assert response.status_code == 201
    state = tmp_path / "journal.fake.json"
    faults["renew_active_state"] = state
    process = launch(tmp_path, url, "--once")
    try:
        # Observe only after exit: fault injection must not require parent
        # scheduling during the short active interval (the old CI race).
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 3, (stdout, stderr)
        assert faults["renew_failed_at"] is not None
        assert faults["renew_calls"] == faults["renew_failed_at"]
        assert faults["renew_active_snapshot"]["active"]
        assert faults["renew_active_snapshot"]["start_count"] == 1
        assert faults["renew_active_snapshot"]["stop_count"] == 0
        saved = json.loads(state.read_text())
        assert not saved["active"] and saved["start_count"] == 1 and saved["stop_count"] == 1
        result = client.get("jobs/" + response.json()["job_id"]).json()
        assert result["state"] == "needs_attention"
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
