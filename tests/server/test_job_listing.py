from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from swu_happyrun.server.app import create_app

from .conftest import ADMIN, AGENT, create_job
from .test_leases import advance, prepared


def test_listing_is_admin_only(client):
    assert client.get("/api/v1/jobs").status_code == 401
    assert client.get("/api/v1/jobs", headers=AGENT).status_code == 403
    assert client.get("/api/v1/jobs", headers=ADMIN).json() == {
        "items": [],
        "next_cursor": None,
    }


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "limit=no", "before=bad"])
def test_listing_rejects_invalid_input(client, query):
    response = client.get("/api/v1/jobs?" + query, headers=ADMIN)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_input"


def test_listing_rejects_unknown_cursor(client):
    response = client.get("/api/v1/jobs?before=" + str(uuid4()), headers=ADMIN)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_cursor"


def test_cursor_pages_are_stable_across_insert_and_restart(client, app, settings, spec):
    old = [create_job(client, spec, str(i)).json() for i in range(4)]
    expected = sorted(old, key=lambda item: item["job_id"], reverse=True)
    first = client.get("/api/v1/jobs?limit=2", headers=ADMIN).json()
    assert first == {"items": expected[:2], "next_cursor": expected[1]["job_id"]}
    app.state.clock.advance(1)
    newer = create_job(client, spec, "new").json()
    with TestClient(create_app(settings, clock=app.state.clock)) as restarted:
        second = restarted.get(
            "/api/v1/jobs",
            params={
                "limit": 2,
                "before": first["next_cursor"],
            },
            headers=ADMIN,
        ).json()
        assert second == {"items": expected[2:], "next_cursor": None}
        assert restarted.get("/api/v1/jobs", headers=ADMIN).json()["items"] == [newer, *expected]


def test_listing_processes_expiry_and_never_leaks_lease_token(client, app, spec):
    _, grant = prepared(client, spec)
    advance(client, grant, ["preflight", "ready", "running"])
    app.state.clock.advance(30)
    response = client.get("/api/v1/jobs", headers=ADMIN)
    assert response.status_code == 200
    assert response.json()["items"][0]["state"] == "needs_attention"
    assert grant["lease_token"] not in response.text
    assert "lease_token" not in response.text


def test_listing_default_limit_is_bounded(client, spec):
    for i in range(27):
        create_job(client, spec, str(i))
    response = client.get("/api/v1/jobs", headers=ADMIN).json()
    assert len(response["items"]) == 25
    assert response["next_cursor"] == response["items"][-1]["job_id"]
