"""Real lock contention must produce a protocol error before the 5s HTTP timeout."""

import sqlite3
import threading
import time
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from swu_happyrun.core.models import JobSpec
from swu_happyrun.server.errors import ApiError

from .conftest import ADMIN, FakeClock, create_job
from .test_probe_batch_atomicity import serving


@contextmanager
def held_writer(path):
    db = sqlite3.connect(path, isolation_level=None)
    try:
        db.execute("BEGIN IMMEDIATE")
        yield db
    finally:
        db.rollback()
        db.close()


def assert_busy(response, elapsed):
    assert response.status_code == 503, response.text
    assert response.json()["error"] == {
        "code": "database_busy",
        "message": "Temporarily unavailable",
        "retryable": True,
    }
    assert response.json()["request_id"]
    # Leave margin for scheduling/serialization within the unchanged 5s client budget.
    assert elapsed < 4.0


@pytest.mark.parametrize("detail", [False, True], ids=["list", "detail"])
def test_real_http_get_returns_busy_before_client_timeout(settings, spec, detail):
    with serving(settings, FakeClock(), network=True) as client:
        job = create_job(client, spec).json()
        path = "/api/v1/jobs" + ("/" + job["job_id"] if detail else "")
        assert client.get(path, headers=ADMIN).status_code == 200
        with held_writer(settings.database_path):
            started = time.monotonic()
            response = client.get(path, headers=ADMIN)
            assert_busy(response, time.monotonic() - started)
        assert client.get(path, headers=ADMIN).status_code == 200


def test_real_http_post_busy_has_no_partial_writes(settings, spec):
    with serving(settings, FakeClock(), network=True) as client:
        with held_writer(settings.database_path):
            started = time.monotonic()
            response = create_job(client, spec)
            assert_busy(response, time.monotonic() - started)
        with sqlite3.connect(settings.database_path) as db:
            for table in ("jobs", "runtime", "job_requests"):
                assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        assert create_job(client, spec).status_code == 201
        assert create_job(client, spec).status_code == 200


def test_real_http_short_lock_waits_then_succeeds(settings, monkeypatch):
    with serving(settings, FakeClock(), network=True) as client:
        ready, release = threading.Event(), threading.Event()

        def hold():
            with held_writer(settings.database_path):
                ready.set()
                release.wait(10)

        holder = threading.Thread(target=hold)
        holder.start()
        assert ready.wait(3)
        attempted = threading.Event()
        timers = []
        connect = sqlite3.connect

        def observed_connect(*args, **kwargs):
            db = connect(*args, **kwargs)

            def trace(statement):
                # The HTTP endpoint uses an AnyIO worker, unlike the scheduler.
                # Start release only once that endpoint attempts its write transaction.
                if (
                    statement == "BEGIN IMMEDIATE"
                    and threading.current_thread().name == "AnyIO worker thread"
                ):
                    attempted.set()
                    timer = threading.Timer(0.2, release.set)
                    timers.append(timer)
                    timer.start()

            db.set_trace_callback(trace)
            return db

        monkeypatch.setattr(sqlite3, "connect", observed_connect)
        try:
            response = client.get("/api/v1/jobs", headers=ADMIN)
            assert attempted.is_set(), "HTTP transaction was not observed under the held lock"
            assert response.status_code == 200
        finally:
            release.set()
            for timer in timers:
                timer.join()
            holder.join(3)
            assert not holder.is_alive()


@pytest.mark.parametrize("detail", [False, True], ids=["list", "detail"])
def test_get_still_expires_at_exact_deadline_without_scheduler(app, spec, detail):
    # No lifespan: expiration must come from GET, not a background scheduler tick.
    client = TestClient(app)
    try:
        job = create_job(client, spec).json()
        path = "/api/v1/jobs" + ("/" + job["job_id"] if detail else "")
        app.state.clock.advance(3599)
        before = client.get(path, headers=ADMIN).json()
        before = before if detail else before["items"][0]
        assert before["state"] == "queued"
        app.state.clock.advance(1)
        after = client.get(path, headers=ADMIN).json()
        after = after if detail else after["items"][0]
        assert after["state"] == "failed"
        assert after["reason_code"] == "window_expired"
        assert after["revision"] == before["revision"] + 1
    finally:
        client.close()


def test_commit_read_lock_rolls_back_every_job_write(app, spec):
    store = app.state.store
    reader = sqlite3.connect(store.path, isolation_level=None)
    try:
        assert reader.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        reader.execute("BEGIN")
        reader.execute("SELECT * FROM jobs").fetchall()
        started = time.monotonic()
        with pytest.raises(ApiError) as caught:
            store.create(JobSpec.model_validate(spec), "commit-contention")
        assert caught.value.code == "database_busy"
        assert caught.value.status == 503
        assert caught.value.retryable is True
        assert time.monotonic() - started < 4.0
    finally:
        reader.rollback()
        reader.close()
    with store.connection() as db:
        for table in ("jobs", "runtime", "job_requests"):
            assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    _, created = store.create(JobSpec.model_validate(spec), "commit-contention")
    assert created


def test_scheduler_reports_unready_then_recovers_after_lock(settings):
    with serving(settings, FakeClock(), network=True) as client:
        with held_writer(settings.database_path):
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                response = client.get("/api/v1/ready")
                if response.status_code == 503:
                    break
                time.sleep(0.02)
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "not_ready"
            assert client.get("/api/v1/health").status_code == 200
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            response = client.get("/api/v1/ready")
            if response.status_code == 200:
                break
            time.sleep(0.02)
        assert response.status_code == 200
        assert client.get("/api/v1/jobs", headers=ADMIN).status_code == 200
