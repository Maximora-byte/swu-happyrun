import sqlite3
import time
from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from .conftest import ADMIN, FakeClock


def schedule(spec, **changes):
    return (
        dict(
            schedule_id=str(uuid4()),
            job_template=spec,
            timezone="Asia/Shanghai",
            local_time="08:00",
            weekdays=[1, 2, 3, 4, 5, 6, 7],
            enabled=True,
        )
        | changes
    )


def test_tick_restart_does_not_duplicate_occurrence(client, app, settings, spec):
    from swu_happyrun.server.app import create_app

    body = schedule(spec)
    assert client.post("/api/v1/schedules", headers=ADMIN, json=body).status_code == 201
    assert app.state.scheduler.tick() == 1
    assert app.state.scheduler.tick() == 0
    with TestClient(create_app(settings, clock=app.state.clock)) as restarted:
        restarted.app.state.scheduler.tick()
    with sqlite3.connect(settings.database_path) as db:
        assert db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM occurrences").fetchone()[0] == 1


def test_expired_occurrence_skipped(client, app, settings, spec):
    body = schedule(spec, local_time="06:00")
    assert client.post("/api/v1/schedules", headers=ADMIN, json=body).status_code == 201
    assert app.state.scheduler.tick() == 0
    with sqlite3.connect(settings.database_path) as db:
        assert db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0
        assert db.execute("SELECT status FROM occurrences").fetchone()[0] == "skipped"


def test_midnight_shanghai_is_previous_utc_date(client, app, settings, spec):
    app.state.clock.now = datetime(2026, 10, 18, 16, tzinfo=UTC)
    body = schedule(spec, local_time="00:00")
    assert client.post("/api/v1/schedules", headers=ADMIN, json=body).status_code == 201
    assert app.state.scheduler.tick() == 1
    with sqlite3.connect(settings.database_path) as db:
        import json

        view = json.loads(db.execute("SELECT view_json FROM jobs").fetchone()[0])
    assert view["spec"]["not_before"] == "2026-10-18T16:00:00Z"
    assert view["spec"]["deadline"] == "2026-10-18T17:00:00Z"


def test_schedule_update_does_not_modify_generated_job(client, app, settings, spec):
    body = schedule(spec)
    assert client.post("/api/v1/schedules", headers=ADMIN, json=body).status_code == 201
    app.state.scheduler.tick()
    with sqlite3.connect(settings.database_path) as db:
        original = db.execute("SELECT view_json FROM jobs").fetchone()[0]
    changed = body | {"local_time": "08:30"}
    assert (
        client.put(
            "/api/v1/schedules/" + body["schedule_id"], headers=ADMIN, json=changed
        ).status_code
        == 200
    )
    app.state.clock.advance(1800)
    assert app.state.scheduler.tick() == 0
    with sqlite3.connect(settings.database_path) as db:
        assert db.execute("SELECT view_json FROM jobs").fetchone()[0] == original
    assert client.get("/api/v1/schedules", headers=ADMIN).json() == [changed]


def test_disabled_schedule_does_not_generate(client, app, settings, spec):
    body = schedule(spec, enabled=False)
    assert client.post("/api/v1/schedules", headers=ADMIN, json=body).status_code == 201
    assert app.state.scheduler.tick() == 0
    with sqlite3.connect(settings.database_path) as db:
        assert db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0


def test_schedule_duplicate_and_path_mismatch(client, spec):
    body = schedule(spec)
    assert client.post("/api/v1/schedules", headers=ADMIN, json=body).status_code == 201
    assert client.post("/api/v1/schedules", headers=ADMIN, json=body).status_code == 409
    assert (
        client.put("/api/v1/schedules/" + str(uuid4()), headers=ADMIN, json=body).status_code == 422
    )


def test_background_tick_and_shutdown_join(settings, spec):
    from swu_happyrun.server.app import create_app

    app = create_app(settings, clock=FakeClock())
    with TestClient(app) as client:
        assert (
            client.post("/api/v1/schedules", headers=ADMIN, json=schedule(spec)).status_code == 201
        )
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            with sqlite3.connect(settings.database_path) as db:
                count = db.execute("SELECT count(*) FROM jobs").fetchone()[0]
            if count:
                break
            time.sleep(0.05)
        assert count == 1
        assert app.state.ticker.is_alive()
    assert not app.state.ticker.is_alive()


def test_two_schedulers_atomic_occurrence(client, app, settings, spec):
    from concurrent.futures import ThreadPoolExecutor

    from swu_happyrun.server.scheduler import Scheduler
    from swu_happyrun.server.store import SqliteJobStore

    client.post("/api/v1/schedules", headers=ADMIN, json=schedule(spec))
    schedulers = [
        Scheduler(SqliteJobStore(settings.database_path, app.state.clock), app.state.clock)
        for _ in range(2)
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda scheduler: scheduler.tick(), schedulers))
    assert sum(results) == 1


def test_occurrence_insert_failure_rolls_back_job(client, app, settings, spec):
    import pytest

    client.post("/api/v1/schedules", headers=ADMIN, json=schedule(spec))
    with sqlite3.connect(settings.database_path) as db:
        db.execute(
            "CREATE TRIGGER reject_occurrence BEFORE INSERT ON occurrences "
            "BEGIN SELECT RAISE(ABORT,'injected failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        app.state.scheduler.tick()
    with sqlite3.connect(settings.database_path) as db:
        assert db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM runtime").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM occurrences").fetchone()[0] == 0
        db.execute("DROP TRIGGER reject_occurrence")
    assert app.state.scheduler.tick() == 1


def test_downtime_skips_past_dates_and_creates_current_only(client, app, settings, spec):
    client.post("/api/v1/schedules", headers=ADMIN, json=schedule(spec))
    app.state.clock.advance(3 * 86400)
    assert app.state.scheduler.tick() == 1
    with sqlite3.connect(settings.database_path) as db:
        assert (
            db.execute("SELECT count(*) FROM occurrences WHERE status='skipped'").fetchone()[0] == 3
        )
        assert db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1


def test_background_expiry_without_read_or_mutation(client, app, settings, spec):
    import json

    from .test_leases import advance, prepared

    _, grant = prepared(client, spec)
    advance(client, grant, ["preflight", "ready", "running"])
    app.state.clock.advance(31)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        with sqlite3.connect(settings.database_path) as db:
            view = json.loads(db.execute("SELECT view_json FROM jobs").fetchone()[0])
        if view["state"] == "needs_attention":
            break
        time.sleep(0.05)
    assert view["state"] == "needs_attention"
    assert view["resume_phase"] == "running"


def test_scheduler_uses_time_after_acquiring_write_lock(settings, spec, monkeypatch):
    from contextlib import contextmanager

    from swu_happyrun.core.models import ScheduleSpec
    from swu_happyrun.server.scheduler import Scheduler
    from swu_happyrun.server.store import SqliteJobStore

    # This tests tick's lock/time ordering, not lifespan scheduling. A live ticker
    # could consume the due occurrence before the simulated lock wait is installed.
    clock = FakeClock()
    store = SqliteJobStore(settings.database_path, clock)
    scheduler = Scheduler(store, clock)
    scheduler.create(ScheduleSpec.model_validate(schedule(spec)))
    original = store.connection
    write_entries = []

    @contextmanager
    def lock_crosses_deadline(*, write=False):
        with original(write=write) as db:
            if write:
                assert db.in_transaction
                write_entries.append(clock.utcnow())
                clock.advance(3601)
            yield db

    monkeypatch.setattr(store, "connection", lock_crosses_deadline)
    assert scheduler.tick() == 0
    assert len(write_entries) == 1
    with sqlite3.connect(settings.database_path) as db:
        assert db.execute("SELECT status FROM occurrences").fetchone()[0] == "skipped"
        assert db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0


def test_unicode_schedule_digits_rejected(client, spec):
    response = client.post(
        "/api/v1/schedules", headers=ADMIN, json=schedule(spec, local_time="0١:00")
    )
    assert response.status_code == 422


def test_unrepresentable_template_window_is_rejected(client, spec):
    template = spec | {"not_before": "0001-01-01T00:00:00Z", "deadline": "9999-12-31T23:59:59Z"}
    response = client.post("/api/v1/schedules", headers=ADMIN, json=schedule(template))
    assert response.status_code == 422
    assert client.get("/api/v1/schedules", headers=ADMIN).json() == []


def test_readiness_reports_ticker_failure_without_internal_detail(app, monkeypatch):
    from queue import Queue
    from threading import Event

    import swu_happyrun.server.app as app_module

    completed = Queue()
    advance = Queue()

    class TickBarrier:
        """Hold each tick after the lifecycle has published its health result."""

        def __init__(self):
            self.stopped = Event()

        def is_set(self):
            return self.stopped.is_set()

        def set(self):
            self.stopped.set()
            advance.put(None)  # Release the worker so lifespan shutdown can join it.

        def wait(self, timeout):
            completed.put(app.state.scheduler_healthy)
            advance.get()
            return self.is_set()

    real_tick = app.state.scheduler.tick
    outcomes = iter(("success", "failure", "recovered"))
    failure_detail = "private fixture-token /private/database.sqlite3"

    def controlled_tick():
        if next(outcomes) == "failure":
            raise RuntimeError(failure_detail)
        return real_tick()

    monkeypatch.setattr(app_module, "Event", TickBarrier)
    monkeypatch.setattr(app.state.scheduler, "tick", controlled_tick)
    with TestClient(app) as client:
        # These bounded queue waits are deadlock guards, not polling or timing assertions.
        # The worker is held after each actual lifecycle health update until we release it.
        assert completed.get(timeout=5) is True
        assert client.get("/api/v1/ready").status_code == 200

        advance.put(None)
        assert completed.get(timeout=5) is False
        response = client.get("/api/v1/ready")
        assert response.status_code == 503
        assert response.json()["error"] == {
            "code": "not_ready",
            "message": "Service temporarily unavailable",
            "retryable": True,
        }
        assert set(response.json()) == {"error", "request_id"}
        assert failure_detail not in response.text
        assert "fixture-token" not in response.text
        assert "database.sqlite3" not in response.text
        assert client.get("/api/v1/health").status_code == 200

        advance.put(None)
        assert completed.get(timeout=5) is True
        recovered = client.get("/api/v1/ready")
        assert recovered.status_code == 200
        assert recovered.json() == {"status": "ready", "protocol_version": 1}
    assert not app.state.ticker.is_alive()
