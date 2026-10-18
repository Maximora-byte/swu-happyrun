"""Bounded control-plane HTTP calls. Never retry ambiguous mutations implicitly."""

import re
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from swu_happyrun.core.models import AgentHello, JobEvent, JobView, LeaseCommand, LeaseGrant


class ControlError(RuntimeError):
    """Safe diagnostic: excludes request credentials and remote response text."""


class ControlClient:
    def __init__(self, base_url: str, token: str, *, transport=None):
        url = urlsplit(base_url)
        if (
            url.scheme not in {"https", "http"}
            or url.username
            or url.password
            or url.query
            or url.fragment
            or (url.scheme == "http" and url.hostname not in {"localhost", "127.0.0.1", "::1"})
        ):
            raise ValueError("HTTPS required except for loopback; URL must not contain credentials")
        self._http = httpx.Client(
            base_url=base_url.rstrip("/") + "/api/v1/",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5.0,
            follow_redirects=False,
            transport=transport,
            trust_env=url.hostname not in {"localhost", "127.0.0.1", "::1"},
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self._http.close()

    def _post(self, path: str, payload: dict):
        return self.request("POST", path, payload)

    def request(self, method: str, path: str, payload=None, *, idempotency_key=None):
        if not re.fullmatch(r"[a-zA-Z0-9_/-]+", path) or path.startswith("/"):
            raise ValueError("invalid API path")
        headers = {} if idempotency_key is None else {"Idempotency-Key": idempotency_key}
        try:
            response = self._http.request(method, path, json=payload, headers=headers)
        except httpx.HTTPError:
            raise ControlError("control request failed or timed out") from None
        if response.status_code == 204:
            return None
        if response.status_code not in {200, 201}:
            raise ControlError(f"control request rejected: HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError:
            raise ControlError("invalid control response") from None

    def _model(self, model, payload):
        try:
            return model.model_validate(payload)
        except (ValidationError, TypeError):
            raise ControlError("invalid control response") from None

    def hello(self, hello: AgentHello):
        return self._post("agents/hello", hello.model_dump(mode="json"))

    def heartbeat(self, hello: AgentHello):
        return self._post("agents/heartbeat", hello.model_dump(mode="json"))

    def claim(self, device_id: str) -> LeaseGrant | None:
        result = self._post("leases/claim", {"device_id": device_id})
        return None if result is None else self._model(LeaseGrant, result)

    def get_job(self, job_id: str) -> JobView:
        return self._model(JobView, self.request("GET", f"jobs/{job_id}"))

    def renew(self, job_id: str, lease: LeaseCommand):
        return self._post(f"jobs/{job_id}/renew", lease.model_dump(mode="json"))

    def events(self, job_id: str, lease: LeaseCommand, event: JobEvent) -> JobView:
        return self._model(
            JobView,
            self._post(
                f"jobs/{job_id}/events",
                {
                    "lease": lease.model_dump(mode="json"),
                    "event": event.model_dump(mode="json"),
                },
            ),
        )

    def stop_ack(
        self, job_id: str, lease: LeaseCommand, event_id: str, expected_revision: int
    ) -> JobView:
        return self._model(
            JobView,
            self._post(
                f"jobs/{job_id}/stop-ack",
                {
                    "lease": lease.model_dump(mode="json"),
                    "event_id": event_id,
                    "expected_revision": expected_revision,
                },
            ),
        )
