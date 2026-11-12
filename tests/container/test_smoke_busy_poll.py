"""Bounded probe recovery for documented busy errors, not historical CI attribution."""

import socket
import sqlite3
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import uvicorn
from test_smoke_contract import smoke

from swu_happyrun.server.app import create_app
from swu_happyrun.server.settings import ServerSettings


def test_real_http_busy_poll_recovers_after_writer_release(tmp_path, monkeypatch):
    settings = ServerSettings(tmp_path / "jobs.sqlite3", "synthetic-admin", {})
    app = create_app(settings)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    base = f"http://127.0.0.1:{sock.getsockname()[1]}"
    monkeypatch.setattr(smoke, "BASE", base)
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    api = None
    blocker = None
    try:
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        api = smoke.Api(base, "synthetic-admin", "synthetic-agent", "synthetic-other")
        spec = smoke._fixture.create_fixture(tmp_path, str(uuid4())).model_dump(mode="json")
        ids = {
            api.call("POST", "jobs", spec, key=str(uuid4()), expected=201)["job_id"]
            for _ in range(3)
        }
        blocker = sqlite3.connect(settings.database_path, isolation_level=None)
        blocker.execute("BEGIN IMMEDIATE")
        original_call = api.call
        observations = []

        def observed_call(method, path, **kwargs):
            assert (method, path) == ("GET", "jobs?limit=100")
            try:
                result = original_call(method, path, **kwargs)
            except smoke.ApiStatusFailure as error:
                observations.append((error.status, error.code, error.retryable))
                # Release only after a real HTTP busy response, not a timing guess.
                blocker.rollback()
                raise
            observations.append("success")
            return result

        monkeypatch.setattr(api, "call", observed_call)
        items = smoke.wait_for_scheduled_jobs(api, deadline=time.monotonic() + 10)
        assert observations == [(503, "database_busy", True), "success"]
        assert {item["job_id"] for item in items} == ids
    finally:
        if blocker is not None:
            blocker.rollback()
            blocker.close()
        if api is not None:
            api.http.close()
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive()


class PollClock:
    def __init__(self):
        self.now = 100.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        assert 0 < seconds <= 0.2
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.mark.parametrize("busy", [False, True])
def test_poll_never_extends_original_eighty_second_deadline(monkeypatch, busy):
    clock = PollClock()
    monkeypatch.setattr(smoke, "time", clock)
    deadline = clock.now + 80
    timeouts = []

    def call(method, path, *, timeout):
        assert (method, path) == ("GET", "jobs?limit=100")
        assert timeout == min(5, deadline - clock.now)
        timeouts.append(timeout)
        if busy:
            raise smoke.ApiStatusFailure(503, 200, "database_busy", True)
        return {"items": [1, 2]}

    with pytest.raises(smoke.SmokeFailure, match="Scheduler did not create one occurrence"):
        smoke.wait_for_scheduled_jobs(SimpleNamespace(call=call), deadline=deadline)
    assert clock.now == deadline
    assert sum(clock.sleeps) == pytest.approx(80)
    assert timeouts[-1] <= 0.2


@pytest.mark.parametrize("count", [0, 2, 4])
def test_poll_requires_exactly_three_jobs(monkeypatch, count):
    clock = PollClock()
    monkeypatch.setattr(smoke, "time", clock)
    responses = iter([{"items": list(range(count))}, {"items": ["a", "b", "c"]}])
    api = SimpleNamespace(call=lambda *args, **kwargs: next(responses))
    assert smoke.wait_for_scheduled_jobs(api, deadline=180) == ["a", "b", "c"]
    assert clock.sleeps == [0.2]


@pytest.mark.parametrize("late_by", [0, 0.1])
def test_poll_rejects_success_at_or_after_deadline(monkeypatch, late_by):
    clock = PollClock()
    monkeypatch.setattr(smoke, "time", clock)

    def call(*args, **kwargs):
        clock.now = 180 + late_by
        return {"items": [1, 2, 3]}

    with pytest.raises(smoke.SmokeFailure, match="Scheduler did not create one occurrence"):
        smoke.wait_for_scheduled_jobs(SimpleNamespace(call=call), deadline=180)
    assert not clock.sleeps


@pytest.mark.parametrize(
    "error",
    [
        smoke.ApiStatusFailure(500, 200, "internal_error", True),
        smoke.ApiStatusFailure(503, 200, "storage_unavailable", True),
        smoke.ApiStatusFailure(503, 200, "not_ready", True),
        smoke.ApiStatusFailure(503, 200, "database_busy", False),
        smoke.ApiStatusFailure(429, 200, "database_busy", True),
        smoke.ApiStatusFailure(401, 200, "unauthorized", False),
        httpx.ReadTimeout("synthetic timeout"),
        ValueError("invalid JSON"),
    ],
)
def test_poll_fails_fast_for_every_other_error(monkeypatch, error):
    clock = PollClock()
    monkeypatch.setattr(smoke, "time", clock)
    calls = []

    def call(*args, **kwargs):
        calls.append(args)
        raise error

    with pytest.raises(type(error)) as caught:
        smoke.wait_for_scheduled_jobs(SimpleNamespace(call=call), deadline=180)
    assert caught.value is error
    assert len(calls) == 1
    assert not clock.sleeps


@pytest.mark.parametrize(
    "payload,code,retryable",
    [
        ({"error": {"code": "database_busy", "retryable": True}}, "database_busy", True),
        ({"error": {"code": "database_busy", "retryable": "true"}}, "database_busy", False),
        ({"error": {"code": "private-secret", "retryable": True}}, "unclassified", False),
        ({"error": {"code": ["private-secret"]}}, "unclassified", False),
        ({"error": "private-secret"}, "unclassified", False),
        (["private-secret"], "unclassified", False),
        ({"error": {"code": "database_busy"}, "padding": "x" * 8192}, "unclassified", False),
    ],
)
def test_status_diagnostics_are_whitelisted_and_redacted(payload, code, retryable):
    response = httpx.Response(503, json=payload)
    error = smoke._status_failure(response, 200)
    assert (error.status, error.code, error.retryable) == (503, code, retryable)
    assert str(error) == f"Unexpected API status 503; expected 200; code={code}"
    assert "private-secret" not in str(smoke.failure_report(error))


def test_non_json_status_is_sanitized():
    error = smoke._status_failure(httpx.Response(500, text="private-secret"), 200)
    assert (error.status, error.code, error.retryable) == (500, "unclassified", False)
    assert "private-secret" not in str(error)
