import json
import sqlite3

import pytest

from .conftest import FakeClock


def legacy_db(path, spec, *, mode="simulation", claimed=False):
    spec = spec | {"mode": mode}
    spec.pop("expected_app_version", None)
    view = dict(
        job_id="00000000-0000-0000-0000-000000000099",
        spec=spec,
        state="queued",
        revision=0,
        desired_state="run",
        fence=1 if claimed else 0,
        agent_id=None,
        reason_code=None,
        resume_phase=None,
        recovery_action=None,
    )
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE jobs(job_id TEXT PRIMARY KEY,view_json TEXT,created_at TEXT)")
        db.execute(
            "CREATE TABLE job_requests(idempotency_key TEXT PRIMARY KEY,"
            "request_json TEXT,job_id TEXT)"
        )
        db.execute(
            "INSERT INTO jobs VALUES (?,?,?)", (view["job_id"], json.dumps(view), "2026-10-19")
        )
        db.execute(
            "INSERT INTO job_requests VALUES (?,?,?)", ("old", json.dumps(spec), view["job_id"])
        )
        db.execute("PRAGMA user_version=1")
    return view


def test_simulation_s0_migration_preserves_id_and_replay(tmp_path, spec):
    from swu_happyrun.core.models import JobSpec
    from swu_happyrun.server.store import SqliteJobStore

    path = tmp_path / "legacy.db"
    old = legacy_db(path, spec)
    store = SqliteJobStore(path, FakeClock())
    view, created = store.create(JobSpec.model_validate(spec), "old")
    assert not created
    assert view.job_id == old["job_id"]
    assert view.run_session_id is None
    assert view.spec.expected_app_version is None


@pytest.mark.parametrize("kwargs", [{"mode": "device"}, {"claimed": True}])
def test_unsafe_migration_rolls_back_entire_database(tmp_path, spec, kwargs):
    from swu_happyrun.server.store import SqliteJobStore

    path = tmp_path / "legacy.db"
    legacy_db(path, spec, **kwargs)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="legacy job migration"):
        SqliteJobStore(path, FakeClock())
    assert path.read_bytes() == before


def test_existing_invalid_c1_payload_rejected_at_startup(tmp_path, spec):
    from swu_happyrun.server.store import SqliteJobStore

    path = tmp_path / "corrupt.db"
    legacy_db(path, spec)
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=2")
    with pytest.raises(ValueError):
        SqliteJobStore(path, FakeClock())
