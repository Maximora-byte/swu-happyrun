from concurrent.futures import ThreadPoolExecutor

import pytest

from .conftest import ADMIN, FakeClock, create_job


def test_create_replay_returns_same_job(client, spec):
    first = create_job(client, spec)
    second = create_job(client, dict(reversed(list(spec.items()))))
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json() == second.json()


def test_key_reuse_with_changed_body_is_409(client, spec):
    first = create_job(client, spec)
    response = create_job(client, spec | {"route_revision": "c" * 64})
    assert response.status_code == 409
    assert create_job(client, spec).json() == first.json()


@pytest.mark.parametrize("key", [None, "", "   "])
def test_idempotency_key_required(client, spec, key):
    headers = dict(ADMIN)
    if key is not None:
        headers["Idempotency-Key"] = key
    assert client.post("/api/v1/jobs", json=spec, headers=headers).status_code == 422


def test_two_connections_create_one_job(settings, spec):
    from swu_happyrun.core.models import JobSpec
    from swu_happyrun.server.store import SqliteJobStore

    stores = [SqliteJobStore(settings.database_path, FakeClock()) for _ in range(2)]
    model = JobSpec.model_validate(spec)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda store: store.create(model, "same-key"), stores))
    assert sorted(created for _, created in results) == [False, True]
    assert len({view.job_id for view, _ in results}) == 1


def test_busy_database_returns_retryable_503(client, spec, settings):
    import sqlite3

    blocker = sqlite3.connect(settings.database_path, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        response = create_job(client, spec)
        assert response.status_code == 503
        assert response.json()["error"]["retryable"] is True
    finally:
        blocker.rollback()
        blocker.close()
    assert create_job(client, spec).status_code == 201


def test_transaction_rolls_back_both_records(settings, spec):
    import sqlite3

    from swu_happyrun.core.models import JobSpec
    from swu_happyrun.server.store import SqliteJobStore

    store = SqliteJobStore(settings.database_path, FakeClock())
    with sqlite3.connect(settings.database_path) as db:
        db.execute(
            "CREATE TRIGGER fail_request BEFORE INSERT ON job_requests "
            "BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        store.create(JobSpec.model_validate(spec), "atomic")
    with sqlite3.connect(settings.database_path) as db:
        assert db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM job_requests").fetchone()[0] == 0


def test_unknown_schema_version_fails_closed(tmp_path):
    import sqlite3

    from swu_happyrun.server.store import SqliteJobStore

    path = tmp_path / "future.db"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=99")
    with pytest.raises(ValueError, match="schema version"):
        SqliteJobStore(path, FakeClock())
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 99


def test_oversized_idempotency_key_rejected(client, spec):
    assert create_job(client, spec, "x" * 257).status_code == 422
