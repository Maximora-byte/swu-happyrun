from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from .conftest import ADMIN, AGENT, AGENT_A, create_job


def register(client, spec, agent_id=AGENT_A):
    return client.post(
        "/api/v1/devices",
        headers=ADMIN,
        json={"device_id": spec["device_id"], "agent_id": agent_id},
    )


def hello(client, spec, *, probe_id=None, backend="fake", capabilities=None):
    payload = dict(
        protocol_version=1,
        agent_id=AGENT_A,
        devices=[
            dict(
                device_id=spec["device_id"],
                backend=backend,
                app_version=None,
                capabilities=[] if capabilities is None else capabilities,
                observed_at="2026-10-19T00:00:00Z",
                probe_id=probe_id or str(uuid4()),
            )
        ],
    )
    response = client.post("/api/v1/agents/hello", headers=AGENT, json=payload)
    return response, payload


def claim(client, spec):
    return client.post("/api/v1/leases/claim", headers=AGENT, json={"device_id": spec["device_id"]})


def prepared(client, spec):
    assert register(client, spec).status_code == 201
    assert hello(client, spec)[0].status_code == 200
    job = create_job(client, spec).json()
    response = claim(client, spec)
    assert response.status_code == 200, response.text
    return job, response.json()


def lease_of(grant):
    return {key: grant[key] for key in ("lease_token", "fence")}


def event(
    client,
    grant,
    state,
    *,
    revision=None,
    event_id=None,
    evidence=None,
    resume_phase=None,
    reason_code=None,
):
    return client.post(
        "/api/v1/jobs/" + grant["job"]["job_id"] + "/events",
        headers=AGENT,
        json={
            "lease": lease_of(grant),
            "event": {
                "event_id": event_id or str(uuid4()),
                "expected_revision": grant["job"]["revision"] if revision is None else revision,
                "state": state,
                "reason_code": reason_code,
                "evidence": evidence or [],
                "resume_phase": resume_phase,
            },
        },
    )


def advance(client, grant, states):
    for state in states:
        response = event(client, grant, state)
        assert response.status_code == 200, response.text
        grant["job"] = response.json()
    return grant


def test_two_claim_connections_only_one_grant(client, spec, app):
    from swu_happyrun.server.store import SqliteJobStore

    register(client, spec)
    hello(client, spec)
    create_job(client, spec)
    stores = [SqliteJobStore(app.state.store.path, app.state.clock) for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        grants = list(pool.map(lambda s: s.claim(AGENT_A, spec["device_id"]), stores))
    assert sum(grant is not None for grant in grants) == 1


def test_claim_assigns_session_and_lease_once(client, spec):
    _, grant = prepared(client, spec)
    assert grant["fence"] == 1
    assert grant["job"]["revision"] == 1
    assert grant["job"]["run_session_id"]
    assert claim(client, spec).status_code == 204
    assert client.get("/api/v1/jobs/" + grant["job"]["job_id"], headers=AGENT).status_code == 200


def test_heartbeat_does_not_refresh_probe(client, spec, app):
    register(client, spec)
    _, report = hello(client, spec)
    create_job(client, spec)
    app.state.clock.advance(30)
    assert client.post("/api/v1/agents/heartbeat", headers=AGENT, json=report).status_code == 200
    assert client.post("/api/v1/agents/hello", headers=AGENT, json=report).status_code == 200
    assert claim(client, spec).status_code == 204
    assert hello(client, spec)[0].status_code == 200
    assert claim(client, spec).status_code == 200


def test_unknown_device_report_cannot_register_owner(client, spec):
    assert hello(client, spec)[0].status_code == 404
    assert client.get("/api/v1/devices", headers=ADMIN).json() == []


def test_probe_id_conflicting_payload_rejected(client, spec):
    register(client, spec)
    _, report = hello(client, spec)
    report["devices"][0]["capabilities"] = ["location_write"]
    assert client.post("/api/v1/agents/hello", headers=AGENT, json=report).status_code == 409


def test_duplicate_event_returns_original_snapshot(client, spec):
    _, grant = prepared(client, spec)
    event_id = str(uuid4())
    first = event(client, grant, "preflight", event_id=event_id)
    assert first.status_code == 200
    grant2 = grant | {"job": first.json()}
    assert event(client, grant2, "ready").status_code == 200
    replay = event(client, grant, "preflight", event_id=event_id)
    assert replay.json() == first.json()
    assert event(client, grant, "ready", event_id=event_id).status_code == 409


def test_running_ack_loss_then_expiry_never_requeues(client, spec, app):
    _, grant = prepared(client, spec)
    advance(client, grant, ["preflight", "ready", "running"])
    app.state.clock.advance(30)
    assert claim(client, spec).status_code == 204
    view = client.get("/api/v1/jobs/" + grant["job"]["job_id"], headers=ADMIN).json()
    assert view["state"] == "needs_attention"
    assert view["resume_phase"] == "running"
    create_job(client, spec, key="next-job")
    hello(client, spec)
    assert claim(client, spec).status_code == 204


def test_renew_at_exact_expiry_fails(client, spec, app):
    _, grant = prepared(client, spec)
    app.state.clock.advance(30)
    response = client.post(
        "/api/v1/jobs/" + grant["job"]["job_id"] + "/renew", headers=AGENT, json=lease_of(grant)
    )
    assert response.status_code == 409


def test_verify_only_after_deadline_consumes_approval(client, spec, app):
    _, grant = prepared(client, spec)
    advance(client, grant, ["preflight", "ready", "running"])
    attention = event(client, grant, "needs_attention", resume_phase="running")
    assert attention.status_code == 200
    app.state.clock.advance(3601)
    response = client.post(
        "/api/v1/jobs/" + grant["job"]["job_id"] + "/resume",
        headers=ADMIN,
        json={"expected_revision": attention.json()["revision"], "action": "verify_only"},
    )
    assert response.status_code == 200
    assert response.json()["revision"] == attention.json()["revision"] + 1
    recovered = claim(client, spec)
    assert recovered.status_code == 200
    recovery = recovered.json()
    assert recovery["job"]["run_session_id"] == grant["job"]["run_session_id"]
    assert event(client, recovery, "preflight").status_code == 409
    advance(client, recovery, ["verifying", "completed"])
    assert recovery["job"]["state"] == "completed"
    assert claim(client, spec).status_code == 204


def test_stop_ack_replay_invalidated_by_next_device_fence(client, spec):
    _, grant = prepared(client, spec)
    response = client.post("/api/v1/jobs/" + grant["job"]["job_id"] + "/cancel", headers=ADMIN)
    assert response.status_code == 200
    body = {
        "lease": lease_of(grant),
        "event_id": str(uuid4()),
        "expected_revision": response.json()["revision"],
    }
    path = "/api/v1/jobs/" + grant["job"]["job_id"] + "/stop-ack"
    stopped = client.post(path, headers=AGENT, json=body)
    assert stopped.status_code == 200
    assert stopped.json()["state"] == "cancelled"
    assert client.post(path, headers=AGENT, json=body).json() == stopped.json()
    create_job(client, spec, key="next")
    next_grant = claim(client, spec).json()
    assert next_grant["fence"] > grant["fence"]
    assert client.post(path, headers=AGENT, json=body).status_code == 409
    assert event(client, next_grant, "preflight").status_code == 200


def test_cancel_prevents_success_and_requires_ack(client, spec):
    _, grant = prepared(client, spec)
    advance(client, grant, ["preflight", "ready", "running", "finishing", "verifying"])
    cancelled = client.post("/api/v1/jobs/" + grant["job"]["job_id"] + "/cancel", headers=ADMIN)
    grant["job"] = cancelled.json()
    assert grant["job"]["state"] == "cancelling"
    assert event(client, grant, "completed").status_code == 409
    assert event(client, grant, "cancelled").status_code == 409


def test_recovery_expiry_requires_new_approval(client, spec, app):
    _, grant = prepared(client, spec)
    attention = event(client, grant, "needs_attention", resume_phase="leased").json()
    path = "/api/v1/jobs/" + grant["job"]["job_id"]
    approved = client.post(
        path + "/resume",
        headers=ADMIN,
        json={"expected_revision": attention["revision"], "action": "retry_preflight"},
    )
    assert approved.status_code == 200
    recovery = claim(client, spec).json()
    app.state.clock.advance(30)
    hello(client, spec)
    assert claim(client, spec).status_code == 204
    view = client.get(path, headers=ADMIN).json()
    assert view["state"] == "needs_attention"
    assert view["recovery_action"] is None
    assert event(client, recovery, "preflight").status_code == 409


@pytest.mark.parametrize("action", ["verify_only", "stop_only"])
def test_recovery_actions_cannot_start_again(client, spec, action):
    _, grant = prepared(client, spec)
    advance(client, grant, ["preflight", "ready", "running"])
    attention = event(client, grant, "needs_attention", resume_phase="running").json()
    path = "/api/v1/jobs/" + grant["job"]["job_id"]
    response = client.post(
        path + "/resume",
        headers=ADMIN,
        json={"expected_revision": attention["revision"], "action": action},
    )
    assert response.status_code == 200
    recovery = claim(client, spec).json()
    for target in ["preflight", "ready", "running", "finishing"]:
        assert event(client, recovery, target).status_code == 409


def test_started_job_cannot_retry_preflight_or_fail(client, spec):
    _, grant = prepared(client, spec)
    advance(client, grant, ["preflight", "ready", "running"])
    assert event(client, grant, "failed").status_code == 409
    attention = event(client, grant, "needs_attention", resume_phase="running").json()
    response = client.post(
        "/api/v1/jobs/" + grant["job"]["job_id"] + "/resume",
        headers=ADMIN,
        json={"expected_revision": attention["revision"], "action": "retry_preflight"},
    )
    assert response.status_code == 409


def test_backward_clock_rejects_capability_freshness(client, spec, app):
    register(client, spec)
    hello(client, spec)
    app.state.clock.advance(-1)
    create_job(client, spec | {"not_before": "2026-10-18T00:00:00Z"})
    assert claim(client, spec).status_code == 204


def test_cancel_noop_does_not_increment_revision(client, spec):
    job = create_job(client, spec).json()
    path = "/api/v1/jobs/" + job["job_id"] + "/cancel"
    first = client.post(path, headers=ADMIN).json()
    assert first["state"] == "cancelled"
    assert first["revision"] == 1
    assert client.post(path, headers=ADMIN).json() == first


def test_running_window_checked_again(client, spec, app):
    spec = spec | {"deadline": "2026-10-19T00:00:20Z"}
    _, grant = prepared(client, spec)
    advance(client, grant, ["preflight", "ready"])
    app.state.clock.advance(20)
    assert event(client, grant, "running").status_code == 409


def test_event_replay_after_expiry_rejected(client, spec, app):
    _, grant = prepared(client, spec)
    event_id = str(uuid4())
    assert event(client, grant, "preflight", event_id=event_id).status_code == 200
    app.state.clock.advance(30)
    assert event(client, grant, "preflight", event_id=event_id).status_code == 409


def test_retry_preflight_then_running_preserves_real_uncertainty(client, spec, app):
    _, grant = prepared(client, spec)
    attention = event(client, grant, "needs_attention", resume_phase="leased").json()
    path = "/api/v1/jobs/" + grant["job"]["job_id"]
    assert (
        client.post(
            path + "/resume",
            headers=ADMIN,
            json={"expected_revision": attention["revision"], "action": "retry_preflight"},
        ).status_code
        == 200
    )
    recovery = claim(client, spec).json()
    advance(client, recovery, ["preflight", "ready", "running"])
    response = event(client, recovery, "needs_attention", resume_phase="running")
    assert response.status_code == 200
    assert response.json()["resume_phase"] == "running"


def test_restart_keeps_reserved_device_and_probe_age(client, spec, settings, app):
    from fastapi.testclient import TestClient

    from swu_happyrun.server.app import create_app

    _, grant = prepared(client, spec)
    advance(client, grant, ["preflight", "ready", "running"])
    app.state.clock.advance(31)
    with TestClient(create_app(settings, clock=app.state.clock)) as restarted:
        view = restarted.get("/api/v1/jobs/" + grant["job"]["job_id"], headers=ADMIN).json()
        assert view["state"] == "needs_attention"
        assert create_job(restarted, spec, key="restart-next").status_code == 201
        assert hello(restarted, spec)[0].status_code == 200
        assert claim(restarted, spec).status_code == 204


def test_stop_only_without_capabilities_after_deadline(client, spec, app):
    _, grant = prepared(client, spec)
    advance(client, grant, ["preflight", "ready", "running"])
    app.state.clock.advance(4000)
    path = "/api/v1/jobs/" + grant["job"]["job_id"]
    attention = client.get(path, headers=ADMIN).json()
    assert (
        client.post(
            path + "/resume",
            headers=ADMIN,
            json={"expected_revision": attention["revision"], "action": "stop_only"},
        ).status_code
        == 200
    )
    recovery = claim(client, spec).json()
    advance(client, recovery, ["cancelling"])
    response = client.post(
        path + "/stop-ack",
        headers=AGENT,
        json={
            "lease": lease_of(recovery),
            "event_id": str(uuid4()),
            "expected_revision": recovery["job"]["revision"],
        },
    )
    assert response.status_code == 200
    assert response.json()["state"] == "cancelled"
