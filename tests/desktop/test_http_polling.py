"""The HTTP acceptance poll follows only the explicit retryable-busy contract."""

import sqlite3

import httpx
import pytest
import test_desktop_http as polling

from swu_happyrun.desktop.workspace import Workspace


def busy_response():
    return httpx.Response(503, json={"error": {"code": "database_busy", "retryable": True}})


def test_poll_recovers_after_real_database_lock(tmp_path):
    workspace = Workspace.open(tmp_path / "desktop")
    with polling.serve(workspace) as client:
        polling.wait_for(client, lambda state: state["worker_status"] == "ready")
        db = sqlite3.connect(workspace.root / "server.sqlite", isolation_level=None)
        db.execute("BEGIN IMMEDIATE")
        responses = []

        class ReleaseAfterBusy:
            def get(self, path):
                response = client.get(path)
                responses.append(response.status_code)
                if response.status_code == 503:
                    assert response.json()["error"]["code"] == "database_busy"
                    db.rollback()
                return response

        try:
            state = polling.wait_for(
                ReleaseAfterBusy(), lambda state: state["mode"] == "simulation"
            )
        finally:
            db.rollback()
            db.close()
        assert responses[0] == 503
        assert responses[-1] == 200
        assert state["record_verified"] is False


def test_persistent_busy_keeps_original_deadline(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(polling.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(polling.time, "sleep", lambda delay: now.__setitem__(0, now[0] + delay))

    class BusyClient:
        def get(self, path):
            return busy_response()

    with pytest.raises(AssertionError, match="deadline expired"):
        polling.wait_for(BusyClient(), lambda state: True, seconds=0.3)
    assert 0.3 <= now[0] < 0.41


@pytest.mark.parametrize(
    "status,code,retryable",
    [
        (500, "internal_error", True),
        (503, "storage_unavailable", True),
        (503, "database_busy", False),
        (503, "database_busy", "true"),
        (403, "database_busy", True),
    ],
)
def test_other_errors_fail_immediately(monkeypatch, status, code, retryable):
    calls = []
    monkeypatch.setattr(polling.time, "sleep", lambda _: pytest.fail("must not retry"))

    class ErrorClient:
        def get(self, path):
            calls.append(path)
            return httpx.Response(status, json={"error": {"code": code, "retryable": retryable}})

    with pytest.raises(AssertionError):
        polling.wait_for(ErrorClient(), lambda state: True)
    assert len(calls) == 1


@pytest.mark.parametrize("body", [b"invalid JSON", b'{"error":null}', b"[]"])
def test_malformed_busy_response_fails_immediately(monkeypatch, body):
    calls = []
    monkeypatch.setattr(polling.time, "sleep", lambda _: pytest.fail("must not retry"))

    class MalformedClient:
        def get(self, path):
            calls.append(path)
            return httpx.Response(503, content=body)

    with pytest.raises((ValueError, AttributeError)):
        polling.wait_for(MalformedClient(), lambda state: True)
    assert len(calls) == 1
