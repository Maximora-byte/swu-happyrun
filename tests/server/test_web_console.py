import pytest

from .conftest import ADMIN


@pytest.mark.parametrize(
    "path", ["/console/", "/console/app.js", "/console/styles.css", "/api/v1/jobs", "/unknown"]
)
def test_responses_have_security_headers(client, path):
    response = client.get(path, headers=ADMIN)
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-frame-options"] == "DENY"
    csp = response.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp
    assert "unsafe-inline" not in csp
    assert "unsafe-eval" not in csp
    assert "access-control-allow-origin" not in response.headers


def test_root_redirects_to_console(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/console/"


@pytest.mark.parametrize(
    ("path", "content_type"),
    [
        ("/console/", "text/html"),
        ("/console/app.js", "text/javascript"),
        ("/console/styles.css", "text/css"),
    ],
)
def test_console_shell_is_public_and_contains_no_secrets(client, path, content_type):
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(content_type)
    assert response.content
    for secret in ["test-admin", "test-agent-a", "test-agent-b", "jobs.sqlite3"]:
        assert secret not in response.text


@pytest.mark.parametrize(
    "path",
    [
        "/console/settings.py",
        "/console/web.py",
        "/console/%2e%2e/settings.py",
        "/console/unknown.js",
    ],
)
def test_static_routes_are_an_explicit_allowlist(client, path):
    assert client.get(path).status_code == 404


def test_internal_failures_keep_security_headers_and_redact_details(client, app, monkeypatch):
    def fail(*args):
        raise RuntimeError("private database detail test-admin")

    monkeypatch.setattr(app.state.store, "list_jobs", fail)
    response = client.get("/api/v1/jobs", headers=ADMIN)
    assert response.status_code == 500
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.json()["error"]["code"] == "internal_error"
    assert "private database detail" not in response.text
    assert "test-admin" not in response.text
