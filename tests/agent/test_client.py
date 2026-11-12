import httpx
import pytest

from swu_happyrun.agent.client import ControlClient, ControlError


def test_http_timeout_redacts_token():
    def fail(request):
        raise httpx.ReadTimeout("Bearer very-secret", request=request)

    with ControlClient(
        "http://127.0.0.1:8000", "very-secret", transport=httpx.MockTransport(fail)
    ) as client:
        with pytest.raises(ControlError) as caught:
            client.claim("device")
        assert "very-secret" not in str(caught.value)
        assert "very-secret" not in repr(client)
        assert caught.value.__cause__ is None


def test_request_has_bounded_timeout_prefix_and_no_retry():
    requests = []

    def receive(request):
        requests.append(request)
        assert request.url.path == "/api/v1/leases/claim"
        assert request.extensions["timeout"]["read"] == 5.0
        return httpx.Response(503, text="very-secret")

    with ControlClient(
        "http://localhost:8000/", "very-secret", transport=httpx.MockTransport(receive)
    ) as client:
        with pytest.raises(ControlError, match="503"):
            client.claim("device")
    assert len(requests) == 1


def test_empty_claim_returns_none():
    with ControlClient(
        "http://localhost:8000",
        "secret",
        transport=httpx.MockTransport(lambda r: httpx.Response(204)),
    ) as client:
        assert client.claim("device") is None


def test_remote_plain_http_is_rejected():
    with pytest.raises(ValueError):
        ControlClient("http://example.com", "secret")


def test_admin_job_creation_sends_idempotency_key():
    seen = []

    def receive(request):
        seen.append(request)
        return httpx.Response(201, json={"created": True})

    with ControlClient(
        "http://localhost:8000", "secret", transport=httpx.MockTransport(receive)
    ) as client:
        assert client.request("POST", "jobs", {"example": 1}, idempotency_key="key") == {
            "created": True
        }
    assert seen[0].headers["Idempotency-Key"] == "key"


def test_get_request_uses_exact_job_path():
    def receive(request):
        assert request.method == "GET"
        assert request.url.path == "/api/v1/jobs/123"
        return httpx.Response(200, json={"id": "123"})

    with ControlClient(
        "http://localhost:8000", "secret", transport=httpx.MockTransport(receive)
    ) as client:
        assert client.request("GET", "jobs/123") == {"id": "123"}


def test_path_traversal_and_absolute_urls_rejected():
    with ControlClient("http://localhost:8000", "secret") as client:
        for path in ["https://other.example/", "../health", "/jobs", "jobs?token=secret"]:
            with pytest.raises(ValueError):
                client.request("GET", path)
