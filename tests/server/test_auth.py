import pytest

from .conftest import ADMIN, AGENT, AGENT_B, create_job


@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": "Basic test-admin"}]
)
def test_invalid_auth_is_401(client, spec, headers):
    response = client.post("/api/v1/jobs", json=spec, headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["retryable"] is False
    assert "test-admin" not in response.text


def test_agent_cannot_create_job(client, spec):
    response = client.post("/api/v1/jobs", json=spec, headers=AGENT)
    assert response.status_code == 403


def test_admin_cannot_hello(client):
    response = client.post(
        "/api/v1/agents/hello",
        headers=ADMIN,
        json=dict(protocol_version=1, agent_id=AGENT_B, devices=[]),
    )
    assert response.status_code == 403


def test_agent_cannot_impersonate(client):
    response = client.post(
        "/api/v1/agents/hello",
        headers=AGENT,
        json=dict(protocol_version=1, agent_id=AGENT_B, devices=[]),
    )
    assert response.status_code == 403


def test_unassigned_job_hidden_from_agent(client, spec):
    view = create_job(client, spec).json()
    assert client.get("/api/v1/jobs/" + view["job_id"], headers=AGENT).status_code == 404


def test_public_view_and_database_exclude_token(client, spec, settings):
    response = create_job(client, spec)
    assert "token" not in response.text
    data = settings.database_path.read_bytes()
    for secret in (b"test-admin", b"test-agent-a", b"test-agent-b"):
        assert secret not in data
        assert secret.decode() not in repr(settings)


def test_reject_ambiguous_credentials(tmp_path):
    from swu_happyrun.server.settings import ServerSettings

    with pytest.raises(ValueError):
        ServerSettings(
            database_path=tmp_path / "bad.db", admin_token="same", agent_tokens={AGENT_B: "same"}
        )


def test_assigned_job_visible_only_to_owner(client, spec):
    from .test_leases import prepared

    _, grant = prepared(client, spec)
    assigned = grant["job"]
    path = "/api/v1/jobs/" + assigned["job_id"]
    assert client.get(path, headers=AGENT).json() == assigned
    assert client.get(path, headers={"Authorization": "Bearer test-agent-b"}).status_code == 404


def test_duplicate_authorization_headers_rejected(client):
    response = client.get(
        "/api/v1/jobs/anything",
        headers=[("Authorization", "Bearer test-admin"), ("Authorization", "Bearer test-agent-a")],
    )
    assert response.status_code == 401


@pytest.mark.parametrize("token", ["with space", "with\ttab", "with\nnewline", "x" * 4097])
def test_invalid_bearer_configuration_fails_closed(tmp_path, token):
    from swu_happyrun.server.settings import ServerSettings

    with pytest.raises(ValueError):
        ServerSettings(database_path=tmp_path / "bad.db", admin_token=token, agent_tokens={})
