"""Independent I0: real loopback TCP and installed package; no ASGI mock transport."""

import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
import uvicorn

from swu_happyrun.server.app import create_app
from swu_happyrun.server.settings import ServerSettings

ADMIN = {"Authorization": "Bearer integration-admin"}
AGENT = {"Authorization": "Bearer integration-agent"}
AGENT_ID = "00000000-0000-0000-0000-000000000001"
DEVICE_ID = "00000000-0000-0000-0000-000000000005"


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 19, tzinfo=UTC)

    def utcnow(self):
        return self.now

    def monotonic(self):
        return time.monotonic()

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


class Service:
    def __init__(self, path):
        self.clock = Clock()
        self.settings = ServerSettings(
            database_path=path,
            admin_token="integration-admin",
            agent_tokens={
                AGENT_ID: "integration-agent",
                "00000000-0000-0000-0000-000000000002": "integration-other-agent",
            },
        )
        self.start()

    def start(self):
        self.app = create_app(self.settings, clock=self.clock)
        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", 0))
        self.socket.listen(128)
        self.url = "http://127.0.0.1:" + str(self.socket.getsockname()[1])
        self.server = uvicorn.Server(uvicorn.Config(self.app, log_level="warning"))
        self.thread = threading.Thread(
            target=lambda: self.server.run(sockets=[self.socket]), daemon=True
        )
        self.thread.start()
        self.http = httpx.Client(base_url=self.url, trust_env=False, timeout=5)
        for _ in range(100):
            if self.server.started:
                break
            time.sleep(0.02)
        assert self.server.started
        assert self.http.get("/api/v1/health").status_code == 200

    def stop(self):
        self.http.close()
        self.server.should_exit = True
        self.thread.join(timeout=10)
        assert not self.thread.is_alive()
        self.socket.close()

    def restart(self):
        self.stop()
        self.start()

    def post(self, path, body=None, *, admin=False, key=None):
        headers = dict(ADMIN if admin else AGENT)
        if key:
            headers["Idempotency-Key"] = key
        return self.http.post("/api/v1/" + path, json=body, headers=headers)

    def get(self, path):
        return self.http.get("/api/v1/" + path, headers=ADMIN)

    def hello(self):
        return self.post(
            "agents/hello",
            dict(
                protocol_version=1,
                agent_id=AGENT_ID,
                devices=[
                    dict(
                        device_id=DEVICE_ID,
                        backend="fake",
                        app_version=None,
                        capabilities=[],
                        observed_at=self.clock.now.isoformat().replace("+00:00", "Z"),
                        probe_id=str(uuid4()),
                    )
                ],
            ),
        )

    def create(self, key=None):
        return self.post("jobs", self.spec, admin=True, key=key or str(uuid4()))

    def claim(self):
        return self.post("leases/claim", {"device_id": DEVICE_ID})

    def prepared(self):
        job = self.create()
        assert job.status_code == 201, job.text
        grant = self.claim()
        assert grant.status_code == 200, grant.text
        return grant.json()

    def event(self, grant, state, *, eid=None, phase=None, reason=None):
        return self.post(
            "jobs/" + grant["job"]["job_id"] + "/events",
            {
                "lease": {k: grant[k] for k in ("lease_token", "fence")},
                "event": dict(
                    event_id=eid or str(uuid4()),
                    expected_revision=grant["job"]["revision"],
                    state=state,
                    reason_code=reason,
                    evidence=[],
                    resume_phase=phase,
                ),
            },
        )

    def advance(self, grant, states):
        for state in states:
            response = self.event(grant, state)
            assert response.status_code == 200, response.text
            grant["job"] = response.json()
        return grant


@pytest.fixture
def service(tmp_path):
    s = Service(tmp_path / "server.sqlite3")
    s.spec = dict(
        protocol_version=1,
        mode="simulation",
        expected_app_version=None,
        profile_id=str(uuid4()),
        profile_revision="a" * 64,
        route_id=str(uuid4()),
        route_revision="b" * 64,
        device_id=DEVICE_ID,
        not_before="2026-10-19T00:00:00Z",
        deadline="2026-10-19T01:00:00Z",
    )
    assert (
        s.post("devices", dict(device_id=DEVICE_ID, agent_id=AGENT_ID), admin=True).status_code
        == 201
    )
    assert s.hello().status_code == 200
    yield s
    s.stop()


def test_complete_never_fake_success(service):
    s = service
    g = s.prepared()
    s.advance(g, ["preflight", "ready", "running", "finishing", "verifying"])
    assert s.event(g, "succeeded").status_code == 422
    s.advance(g, ["completed"])
    assert g["job"]["state"] == "completed"
    s.restart()
    assert s.get("jobs/" + g["job"]["job_id"]).json() == g["job"]


def test_two_independent_tcp_claim_connections(service):
    s = service
    assert s.create().status_code == 201
    barrier = threading.Barrier(2)

    def request(_):
        with httpx.Client(base_url=s.url, trust_env=False) as c:
            barrier.wait()
            return c.post(
                "/api/v1/leases/claim", headers=AGENT, json={"device_id": DEVICE_ID}
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(request, range(2))) == [200, 204]


def test_expired_running_reservation_survives_restart(service):
    s = service
    g = s.prepared()
    s.advance(g, ["preflight", "ready", "running"])
    s.clock.advance(30)
    s.restart()
    assert s.hello().status_code == 200
    assert s.create().status_code == 201
    assert s.claim().status_code == 204
    view = s.get("jobs/" + g["job"]["job_id"]).json()
    assert view["state"] == "needs_attention"
    assert s.event(g, "finishing").status_code == 409


def test_verify_only_after_deadline_never_running(service):
    s = service
    g = s.prepared()
    s.advance(g, ["preflight", "ready", "running"])
    attention = s.event(g, "needs_attention", phase="running", reason="upload_uncertain").json()
    s.clock.advance(3601)
    assert (
        s.post(
            "jobs/" + g["job"]["job_id"] + "/resume",
            {"expected_revision": attention["revision"], "action": "verify_only"},
            admin=True,
        ).status_code
        == 200
    )
    r = s.claim()
    assert r.status_code == 200, r.text
    recovery = r.json()
    assert recovery["job"]["run_session_id"] == g["job"]["run_session_id"]
    for state in ["preflight", "ready", "running", "finishing"]:
        assert s.event(recovery, state).status_code == 409
    s.advance(recovery, ["verifying", "completed"])
    assert s.claim().status_code == 204


def test_cancel_stop_ack_lost_response_and_stale_fence(service):
    s = service
    g = s.prepared()
    s.advance(g, ["preflight", "ready", "running"])
    path = "jobs/" + g["job"]["job_id"]
    cancel = s.post(path + "/cancel", admin=True).json()
    body = {
        "lease": {k: g[k] for k in ("lease_token", "fence")},
        "event_id": str(uuid4()),
        "expected_revision": cancel["revision"],
    }
    # Discard first committed response, then replay over a separate real HTTP request.
    assert s.post(path + "/stop-ack", body).status_code == 200
    replay = s.post(path + "/stop-ack", body)
    assert replay.status_code == 200 and replay.json()["state"] == "cancelled"
    assert s.post(path + "/stop-ack", body).json() == replay.json()
    assert s.create().status_code == 201
    next_grant = s.claim().json()
    assert next_grant["fence"] > g["fence"]
    assert s.post(path + "/stop-ack", body).status_code == 409


def test_event_duplicate_payload_and_old_snapshot(service):
    s = service
    g = s.prepared()
    eid = str(uuid4())
    first = s.event(g, "preflight", eid=eid)
    assert first.status_code == 200
    updated = g | {"job": first.json()}
    s.advance(updated, ["ready"])
    assert s.event(g, "preflight", eid=eid).json() == first.json()
    assert s.event(g, "ready", eid=eid).status_code == 409
    s.clock.advance(30)
    assert s.event(g, "preflight", eid=eid).status_code == 409


def test_offline_cancel_requires_explicit_stop_recovery(service):
    s = service
    g = s.prepared()
    s.advance(g, ["preflight", "ready", "running"])
    s.clock.advance(3601)
    path = "jobs/" + g["job"]["job_id"]
    cancelled = s.post(path + "/cancel", admin=True)
    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == "needs_attention"
    assert cancelled.json()["desired_state"] == "cancel"
    assert s.claim().status_code == 204
    assert (
        s.post(
            path + "/resume",
            {
                "expected_revision": cancelled.json()["revision"],
                "action": "verify_only",
            },
            admin=True,
        ).status_code
        == 409
    )
    assert (
        s.post(
            path + "/resume",
            {"expected_revision": cancelled.json()["revision"], "action": "stop_only"},
            admin=True,
        ).status_code
        == 200
    )
    recovery = s.claim()
    assert recovery.status_code == 200
    recovered = recovery.json()
    assert recovered["job"]["run_session_id"] == g["job"]["run_session_id"]
    s.advance(recovered, ["cancelling"])
    ack = {
        "lease": {k: recovered[k] for k in ("lease_token", "fence")},
        "event_id": str(uuid4()),
        "expected_revision": recovered["job"]["revision"],
    }
    assert s.post(path + "/stop-ack", ack).json()["state"] == "cancelled"


def test_cancel_success_commit_orders(service):
    s = service
    g = s.prepared()
    s.advance(g, ["preflight", "ready", "running", "finishing", "verifying"])
    path = "jobs/" + g["job"]["job_id"]
    cancelled = s.post(path + "/cancel", admin=True)
    assert cancelled.status_code == 200
    g["job"] = cancelled.json()
    assert s.event(g, "completed").status_code == 409
    ack = {
        "lease": {k: g[k] for k in ("lease_token", "fence")},
        "event_id": str(uuid4()),
        "expected_revision": g["job"]["revision"],
    }
    assert s.post(path + "/stop-ack", ack).status_code == 200
    other = s.prepared()
    s.advance(other, ["preflight", "ready", "running", "finishing", "verifying", "completed"])
    terminal = s.post("jobs/" + other["job"]["job_id"] + "/cancel", admin=True)
    assert terminal.status_code == 200 and terminal.json() == other["job"]


def test_recovery_lease_loss_clears_approval_and_started_retry_refused(service):
    s = service
    g = s.prepared()
    s.advance(g, ["preflight", "ready", "running"])
    attention = s.event(g, "needs_attention", phase="running").json()
    path = "jobs/" + g["job"]["job_id"]
    assert (
        s.post(
            path + "/resume",
            {"expected_revision": attention["revision"], "action": "retry_preflight"},
            admin=True,
        ).status_code
        == 409
    )
    assert (
        s.post(
            path + "/resume",
            {"expected_revision": attention["revision"], "action": "verify_only"},
            admin=True,
        ).status_code
        == 200
    )
    recovery = s.claim().json()
    s.clock.advance(30)
    assert s.claim().status_code == 204
    current = s.get(path).json()
    assert current["state"] == "needs_attention" and current["recovery_action"] is None
    assert s.event(recovery, "verifying").status_code == 409
    assert (
        s.post(
            path + "/resume",
            {"expected_revision": current["revision"], "action": "verify_only"},
            admin=True,
        ).status_code
        == 200
    )
    renewed = s.claim().json()
    assert renewed["fence"] > recovery["fence"]
    s.advance(renewed, ["verifying", "completed"])


@pytest.mark.parametrize("phase", ["leased", "preflight", "ready"])
def test_safe_pre_running_expiry_requeues(service, phase):
    s = service
    g = s.prepared()
    if phase != "leased":
        s.advance(g, ["preflight"] if phase == "preflight" else ["preflight", "ready"])
    s.clock.advance(30)
    # Capability is stale at exact expiry: expiry runs, but no new grant is issued.
    assert s.claim().status_code == 204
    view = s.get("jobs/" + g["job"]["job_id"]).json()
    assert view["state"] == "queued"
    assert s.hello().status_code == 200
    recovered = s.claim().json()
    assert recovered["job"]["job_id"] == g["job"]["job_id"]
    assert recovered["fence"] > g["fence"]


def test_renew_heartbeat_and_wrong_lease(service):
    s = service
    g = s.prepared()
    path = "jobs/" + g["job"]["job_id"]
    lease = {k: g[k] for k in ("lease_token", "fence")}
    s.clock.advance(5)
    renewed = s.post(path + "/renew", lease)
    assert renewed.status_code == 200
    assert renewed.json()["expires_at"] == "2026-10-19T00:00:35Z"
    assert renewed.json()["desired_state"] == "run"
    assert s.post(path + "/renew", lease | {"lease_token": "wrong-secret"}).status_code == 409
    assert s.post(path + "/renew", lease | {"fence": 0}).status_code == 409
    s.clock.advance(29)
    assert (
        s.post(
            "agents/heartbeat",
            {"protocol_version": 1, "agent_id": AGENT_ID, "devices": []},
        ).status_code
        == 200
    )
    s.clock.advance(1)
    assert s.post(path + "/renew", lease).status_code == 409


def test_two_jobs_same_device_only_one_grant(service):
    s = service
    assert s.create().status_code == 201 and s.create().status_code == 201
    barrier = threading.Barrier(2)

    def request(_):
        with httpx.Client(base_url=s.url, trust_env=False) as client:
            barrier.wait()
            return client.post(
                "/api/v1/leases/claim", headers=AGENT, json={"device_id": DEVICE_ID}
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(request, range(2))) == [200, 204]


def test_start_not_before_and_unknown_capability(service):
    s = service
    s.spec["not_before"] = "2026-10-19T00:10:00Z"
    assert s.create().status_code == 201
    assert s.claim().status_code == 204
    assert s.post("leases/claim", {"device_id": str(uuid4())}).status_code == 404


def test_stale_revision_and_terminal_resume_rejected(service):
    s = service
    g = s.prepared()
    old = g.copy()
    s.advance(g, ["preflight"])
    assert s.event(old, "ready").status_code == 409
    s.advance(g, ["ready", "running", "finishing", "verifying", "completed"])
    path = "jobs/" + g["job"]["job_id"]
    assert (
        s.post(
            path + "/resume",
            {"expected_revision": g["job"]["revision"], "action": "verify_only"},
            admin=True,
        ).status_code
        == 409
    )
    assert s.event(g, "needs_attention", phase="verifying").status_code == 409


def test_device_unknown_capability_fails_closed(service):
    s = service
    s.spec.update(mode="device", expected_app_version="test-1")
    assert s.create().status_code == 201
    assert s.claim().status_code == 204


def test_wrong_agent_lease_and_recovery_cannot_read_or_claim(service):
    s = service
    g = s.prepared()
    path = "jobs/" + g["job"]["job_id"]
    headers = {"Authorization": "Bearer integration-other-agent"}
    lease = {k: g[k] for k in ("lease_token", "fence")}
    assert s.http.get("/api/v1/" + path, headers=headers).status_code == 404
    assert s.http.post("/api/v1/" + path + "/renew", headers=headers, json=lease).status_code == 404
    s.advance(g, ["preflight", "ready", "running"])
    attention = s.event(g, "needs_attention", phase="running").json()
    assert (
        s.post(
            path + "/resume",
            {"expected_revision": attention["revision"], "action": "verify_only"},
            admin=True,
        ).status_code
        == 200
    )
    assert (
        s.http.post(
            "/api/v1/leases/claim", headers=headers, json={"device_id": DEVICE_ID}
        ).status_code
        == 404
    )
    assert s.claim().status_code == 200
