from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from .conftest import ADMIN, AGENT, AGENT_A, FakeClock, create_job


def test_health(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "protocol_version": 1}


def test_create_and_get_job(client, spec):
    response = create_job(client, spec)
    assert response.status_code == 201
    view = response.json()
    UUID(view["job_id"])
    assert view["spec"] == spec
    assert view["state"] == "queued"
    assert view["revision"] == view["fence"] == 0
    assert view["agent_id"] is None
    assert client.get("/api/v1/jobs/" + view["job_id"], headers=ADMIN).json() == view


def test_restart_reads_same_job(client, settings, spec):
    from swu_happyrun.server.app import create_app

    original = create_job(client, spec).json()
    with TestClient(create_app(settings, clock=FakeClock())) as restarted:
        assert restarted.get("/api/v1/jobs/" + original["job_id"], headers=ADMIN).json() == original
        assert create_job(restarted, spec).status_code == 200


def test_missing_job_returns_contract_error(client):
    response = client.get("/api/v1/jobs/" + str(UUID(int=99)), headers=ADMIN)
    assert response.status_code == 404
    assert response.json()["error"]["retryable"] is False
    UUID(response.json()["request_id"])


@pytest.mark.parametrize(
    "change",
    [
        dict(extra="secret-sentinel"),
        dict(protocol_version=True),
        dict(deadline="2026-10-18T00:00:00Z"),
    ],
)
def test_validation_is_redacted(client, spec, change):
    response = create_job(client, spec | change)
    assert response.status_code == 422
    assert set(response.json()) == {"error", "request_id"}
    assert "secret-sentinel" not in response.text


def test_hello_and_heartbeat(client):
    hello = dict(protocol_version=1, agent_id=AGENT_A, devices=[])
    response = client.post("/api/v1/agents/hello", headers=AGENT, json=hello)
    assert response.status_code == 200
    assert response.json() == dict(agent_id=AGENT_A, heartbeat_seconds=10, lease_seconds=30)
    response = client.post("/api/v1/agents/heartbeat", headers=AGENT, json=hello)
    assert response.status_code == 200
    assert response.json() == {"server_time": "2026-10-19T00:00:00Z"}


@pytest.mark.parametrize("suffix", ["cancel", "resume", "renew", "events", "stop-ack"])
def test_unimplemented_commands_do_not_succeed(client, spec, suffix):
    view = create_job(client, spec).json()
    response = client.post(f"/api/v1/jobs/{view['job_id']}/{suffix}", json={}, headers=ADMIN)
    assert response.status_code >= 400
    assert "error" in response.json()
    assert client.get("/api/v1/jobs/" + view["job_id"], headers=ADMIN).json() == view


def test_malformed_json_is_safe(client):
    response = client.post(
        "/api/v1/jobs",
        content='{"secret-sentinel":',
        headers={**ADMIN, "Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert "secret-sentinel" not in response.text


def test_unexpected_failure_is_redacted(app, client, spec, monkeypatch):
    def fail(*args):
        raise RuntimeError("secret-sentinel")

    monkeypatch.setattr(app.state.store, "create", fail)
    with TestClient(app, raise_server_exceptions=False) as safe_client:
        response = create_job(safe_client, spec)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "secret-sentinel" not in response.text
