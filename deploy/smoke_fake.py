"""Disposable loopback HTTP/CLI smoke; never connects to a device or external server.

Run from a fully integrated checkout: uv run --no-sync python deploy/smoke_fake.py
The database, fake profiles and journal are removed with the temporary directory.
"""

import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from swu_happyrun.core.canonical import profile_revision
from swu_happyrun.core.models import JobSpec, RouteProfile, SchoolProfile


class SmokeFailure(RuntimeError):
    """Safe, fixed diagnostic; never include raw HTTP responses or credentials."""


def require(condition, message):
    if not condition:
        raise SmokeFailure(message)


def create_fixture(root, device_id):
    school = SchoolProfile.model_validate(
        {
            "profile_id": str(uuid4()),
            "revision": "0" * 64,
            "campus": "synthetic-only",
            "app_package": "test.fake",
            "app_version": "test-1",
            "confirmed": True,
            "allowed_region": [
                {"latitude": y, "longitude": x} for x, y in [(0, 0), (1, 0), (1, 1), (0, 1)]
            ],
            "rules": {
                "minimum_distance_m": 1.0,
                "maximum_duration_seconds": 100000.0,
                "minimum_speed_mps": 1.0,
                "maximum_speed_mps": 10.0,
            },
            "checkpoint_source": "manual_confirmed",
        }
    )
    route = RouteProfile.model_validate(
        {
            "route_id": str(uuid4()),
            "revision": "0" * 64,
            "input_crs": "WGS84",
            "points": [
                {"latitude": 0.2, "longitude": 0.2},
                {"latitude": 0.20001, "longitude": 0.20001},
            ],
            "source_ref": "synthetic-only",
        }
    )
    for folder, identifier, model in [
        ("schools", school.profile_id, school),
        ("routes", route.route_id, route),
    ]:
        model.revision = profile_revision(model)
        path = root / "profiles" / folder / identifier / f"{model.revision}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(model.model_dump_json(), encoding="utf-8")
    now = datetime.now(UTC)
    job = JobSpec(
        protocol_version=1,
        mode="simulation",
        expected_app_version=None,
        profile_id=school.profile_id,
        profile_revision=school.revision,
        route_id=route.route_id,
        route_revision=route.revision,
        device_id=device_id,
        not_before=now - timedelta(seconds=1),
        deadline=now + timedelta(minutes=5),
    )
    (root / "job.json").write_text(job.model_dump_json(), encoding="utf-8")
    return job


def request(base, method, path, token=None, body=None, key=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if key:
        headers["Idempotency-Key"] = key
    req = urllib.request.Request(
        base + "/api/v1/" + path,
        method=method,
        headers=headers,
        data=None if body is None else json.dumps(body).encode(),
    )
    # Disable ambient HTTP proxies for this isolated localhost-only check.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=5) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        raise SmokeFailure(f"HTTP {error.code} at {method} {path.split('/')[0]}") from None


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def start(root, port, env, logfile):
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "swu_happyrun",
            "server",
            "--database",
            str(root / "server.sqlite3"),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env=env,
        stdout=logfile,
        stderr=logfile,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            require(process.poll() is None, "server exited before health check")
            try:
                _, health = request(base, "GET", "health")
                require(health == {"status": "ok", "protocol_version": 1}, "health mismatch")
                _, ready = request(base, "GET", "ready")
                require(ready == {"status": "ready", "protocol_version": 1}, "readiness mismatch")
                return process, base
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                time.sleep(0.1)
        raise SmokeFailure("server health timed out")
    except BaseException:
        stop(process)
        raise


def run_smoke(root):
    agent_id, device_id = str(uuid4()), str(uuid4())
    admin_token, agent_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    spec = create_fixture(root, device_id)
    env = {
        **os.environ,
        "HAPPYRUN_ADMIN_TOKEN": admin_token,
        "HAPPYRUN_AGENT_TOKENS": json.dumps({agent_id: agent_token}),
        "HAPPYRUN_AGENT_TOKEN": agent_token,
        "SWU_HAPPYRUN_HOST_ID_FILE": str(root / "host-id"),
    }
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    # The OS port choice has a small handoff race; startup failure is an honest failure.
    with (root / "server.log").open("w", encoding="utf-8") as log:
        process, base = start(root, port, env, log)
        try:
            status, _ = request(
                base,
                "POST",
                "devices",
                admin_token,
                {"device_id": device_id, "agent_id": agent_id},
            )
            require(status in {200, 201}, "device registration failed")
            body = spec.model_dump(mode="json")
            key = str(uuid4())
            status, created = request(base, "POST", "jobs", admin_token, body, key)
            require(status == 201, "job was not created")
            status, replay = request(base, "POST", "jobs", admin_token, body, key)
            require(
                status == 200 and replay["job_id"] == created["job_id"],
                "idempotent creation mismatch",
            )
            agent = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "swu_happyrun",
                    "agent",
                    "--url",
                    base,
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
                env=env,
                check=False,
                capture_output=True,
                text=True,
                timeout=45,
            )
            require(agent.returncode == 0, f"fake agent exit {agent.returncode}")
            result = json.loads(agent.stdout)
            require(
                result["job_id"] == created["job_id"] and result["state"] == "completed",
                "fake agent did not complete the same job",
            )
            require(not result.get("evidence"), "simulation emitted record evidence")
            fake_state = json.loads((root / "fake.json").read_text(encoding="utf-8"))
            require(fake_state.get("route_finished") is True, "synthetic route did not finish")
            require(
                all(
                    token not in agent.stdout + agent.stderr for token in (admin_token, agent_token)
                ),
                "agent leaked credentials",
            )
            _, read = request(base, "GET", "jobs/" + created["job_id"], admin_token)
            require(read == result, "final HTTP query mismatch")
        finally:
            stop(process)
        process, base = start(root, port, env, log)
        try:
            _, persisted = request(base, "GET", "jobs/" + created["job_id"], admin_token)
            require(persisted == read, "job changed after server restart")
        finally:
            stop(process)
    logs = (root / "server.log").read_text(encoding="utf-8")
    require(
        all(token not in logs for token in (admin_token, agent_token)),
        "server leaked credentials",
    )
    return {
        "status": "passed",
        "transport": "loopback_tcp_http",
        "mode": "simulation",
        "checks": [
            "health",
            "readiness",
            "device_registration",
            "create",
            "idempotent_replay",
            "fake_agent_completed",
            "synthetic_route_finished",
            "query",
            "restart_persistence",
            "token_redaction",
        ],
        "device_verified": False,
        "record_verified": False,
    }


def main():
    try:
        with tempfile.TemporaryDirectory(prefix="happyrun-smoke-") as directory:
            result = run_smoke(Path(directory))
        print(json.dumps(result))
        return 0
    except SmokeFailure as error:
        print(json.dumps({"status": "failed", "reason": str(error)}))
        return 1
    except Exception:
        print(json.dumps({"status": "failed", "reason": "Unexpected error; run component tests"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
