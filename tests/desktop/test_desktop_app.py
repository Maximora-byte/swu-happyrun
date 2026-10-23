from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def workstation(tmp_path):
    from swu_happyrun.desktop.app import create_desktop_app
    from swu_happyrun.desktop.workspace import Workspace

    workspace = Workspace.open(tmp_path / "desktop")
    app = create_desktop_app(workspace, port=8765)
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    return workspace, app, client


def login(app, client):
    return client.post(
        "/api/v1/desktop/session",
        json={"nonce": app.state.desktop_nonce},
        headers={"Origin": "http://127.0.0.1:8765"},
    )


def test_bootstrap_is_one_use_and_cookie_is_http_only(workstation):
    _, app, client = workstation
    nonce = app.state.desktop_nonce
    response = login(app, client)
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert "path=/api/v1/desktop" in cookie
    assert "token" not in response.text and nonce not in response.text
    assert client.get("/api/v1/desktop/workspace").status_code == 200
    assert (
        client.post(
            "/api/v1/desktop/session",
            json={"nonce": nonce},
            headers={"Origin": "http://127.0.0.1:8765"},
        ).status_code
        == 401
    )
    assert client.get("/api/v1/devices").status_code == 401


@pytest.mark.parametrize("origin", [None, "null", "http://evil.test", "http://localhost:8765"])
def test_bootstrap_rejects_foreign_or_absent_origin_without_consuming_nonce(workstation, origin):
    _, app, client = workstation
    headers = {} if origin is None else {"Origin": origin}
    response = client.post(
        "/api/v1/desktop/session", json={"nonce": app.state.desktop_nonce}, headers=headers
    )
    assert response.status_code == 403
    assert login(app, client).status_code == 200


def test_dns_rebinding_host_is_rejected(workstation):
    _, app, client = workstation
    assert (
        client.post(
            "/api/v1/desktop/session",
            json={"nonce": app.state.desktop_nonce},
            headers={"Host": "evil.test:8765", "Origin": "http://127.0.0.1:8765"},
        ).status_code
        == 403
    )


def test_simulation_create_is_idempotent_and_cannot_select_physical_device(workstation):
    workspace, app, client = workstation
    assert login(app, client).status_code == 200
    headers = {"Origin": "http://127.0.0.1:8765", "Idempotency-Key": str(uuid4())}
    spec = workspace.job_spec().model_dump(mode="json")
    first = client.post("/api/v1/desktop/jobs", json=spec, headers=headers)
    assert first.status_code == 201
    replay = client.post("/api/v1/desktop/jobs", json=spec, headers=headers)
    assert replay.status_code == 200
    assert first.json()["job_id"] == replay.json()["job_id"]
    spec["device_id"] = str(uuid4())
    assert client.post("/api/v1/desktop/jobs", json=spec, headers=headers).status_code == 422
    assert len(client.get("/api/v1/desktop/workspace").json()["jobs"]) == 1


def test_cookie_alone_cannot_mutate_or_read_another_job(workstation):
    workspace, app, client = workstation
    login(app, client)
    spec = workspace.job_spec().model_dump(mode="json")
    assert client.post("/api/v1/desktop/jobs", json=spec).status_code == 403
    foreign = workspace.job_spec().model_copy(update={"device_id": str(uuid4())})
    job, _ = app.state.store.create(foreign, str(uuid4()))
    assert (
        client.post(
            f"/api/v1/desktop/jobs/{job.job_id}/cancel",
            json={},
            headers={"Origin": "http://127.0.0.1:8765"},
        ).status_code
        == 404
    )


def test_desktop_assets_do_not_contain_bootstrap_secret(workstation):
    _, app, client = workstation
    for path in ("/desktop/", "/desktop/app.js", "/desktop/styles.css"):
        response = client.get(path)
        assert response.status_code == 200
        assert app.state.desktop_nonce not in response.text
        assert response.headers["cache-control"] == "no-store"
    assert client.get("/desktop/../../workspace.json").status_code == 404
