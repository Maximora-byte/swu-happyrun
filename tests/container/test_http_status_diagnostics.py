"""Exercise bounded status diagnostics through the real HTTP client adapter."""

import importlib.util
from pathlib import Path

import httpx
import pytest

_spec = importlib.util.spec_from_file_location(
    "status_smoke", Path(__file__).resolve().parents[2] / "deploy/smoke_container.py"
)
smoke = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smoke)


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
@pytest.mark.parametrize(
    ("method", "path", "label"),
    [
        ("GET", "jobs?limit=100&before=private-token", "jobs"),
        ("GET", "jobs/private-token", "job"),
        ("POST", "jobs/private-token/renew", "job_renew"),
        ("POST", "private-token?secret=private-token", "unknown"),
        ("PRIVATE-TOKEN", "jobs/private-token/private-token", "unknown"),
    ],
)
def test_unexpected_status_has_only_fixed_fields(status, method, path, label):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            status,
            content=b"private-token invalid JSON",
            headers={"X-Private": "private-token"},
        )

    api = smoke.Api(smoke.BASE, "private-token", "agent-token", "other-token")
    assert api.http.timeout == httpx.Timeout(5)
    api.http.close()
    api.http = httpx.Client(
        base_url=smoke.BASE + "/api/v1/", transport=httpx.MockTransport(respond)
    )
    try:
        with pytest.raises(smoke.SmokeFailure) as caught:
            api.call(method, path)
        safe_method = method if method in {"GET", "POST"} else "unknown"
        assert str(caught.value) == (
            f"Unexpected API status method={safe_method} route={label} expected=200 actual={status}"
        )
        assert len(calls) == 1
        assert "private-token" not in str(caught.value)
    finally:
        api.http.close()


@pytest.mark.parametrize("status", [200, 201, 403])
def test_expected_status_keeps_original_return_and_single_request(status):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, json={"result": "ok"})

    api = smoke.Api(smoke.BASE, "admin-token", "agent-token", "other-token")
    api.http.close()
    api.http = httpx.Client(
        base_url=smoke.BASE + "/api/v1/", transport=httpx.MockTransport(respond)
    )
    try:
        assert api.call("GET", "jobs", expected=status) == {"result": "ok"}
        assert len(calls) == 1
    finally:
        api.http.close()
