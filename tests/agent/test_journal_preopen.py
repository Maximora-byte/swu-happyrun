"""Original-device exclusion is acquired before any RW SQLite connection."""

import hashlib
import os
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from swu_happyrun.agent.journal import RunJournal, UnsafeReplay


def fixture(tmp_path):
    path = tmp_path / "runs.sqlite"
    with RunJournal(path) as journal:
        with journal.device_lock("device"):
            pass
    lock = tmp_path / ("device-" + hashlib.sha256(b"device").hexdigest() + ".lock")
    return path, lock


def test_lock_precedes_connect_and_does_not_double_lock(tmp_path, monkeypatch):
    path, _ = fixture(tmp_path)
    original = sqlite3.connect
    calls = []

    def connect(*args, **kwargs):
        with pytest.raises(UnsafeReplay):
            with RunJournal.lock_existing(path, "device"):
                pass
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    with RunJournal.lock_existing(path, "device") as token:
        assert calls == []
        with RunJournal.open_existing_locked(token) as journal:
            journal.record_intent("job", 1, "start")
            journal.record_result("job", 1, "start", "confirmed")
            assert journal.has_intent("job", "start")
            assert journal.read_replay_reservation("device") is None
            with pytest.raises(UnsafeReplay):
                with journal.device_lock("device"):
                    pass
    assert calls == [1]


def test_busy_and_missing_lock_cannot_open_or_create(tmp_path, monkeypatch):
    path, lock = fixture(tmp_path)
    with RunJournal.lock_existing(path, "device"):
        monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: pytest.fail("connect"))
        monkeypatch.setattr(Path, "mkdir", lambda *a, **k: pytest.fail("mkdir"))
        with pytest.raises(UnsafeReplay):
            with RunJournal.lock_existing(path, "device"):
                pass
    lock.unlink()
    with pytest.raises(UnsafeReplay):
        with RunJournal.lock_existing(path, "device"):
            pass
    assert not lock.exists()


def test_forged_released_and_reused_token_reject_before_connect(tmp_path, monkeypatch):
    path, _ = fixture(tmp_path)
    with RunJournal.lock_existing(path, "device") as token:
        with RunJournal.open_existing_locked(token):
            pass
        with pytest.raises(UnsafeReplay):
            with RunJournal.open_existing_locked(token):
                pass
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: pytest.fail("connect"))
    for value in (token, None, True, {}, object()):
        with pytest.raises(UnsafeReplay):
            with RunJournal.open_existing_locked(value):
                pass


def test_unresolved_reservation_rejects_before_connect(tmp_path, monkeypatch):
    path, _ = fixture(tmp_path)
    with RunJournal(path) as journal:
        with journal.device_lock("device"):
            journal.reserve_replay("device", str(uuid4()), generation=1)
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: pytest.fail("connect"))
    with pytest.raises(UnsafeReplay, match="replay_recovery_requires_stop"):
        with RunJournal.lock_existing(path, "device"):
            pass


def test_replacement_after_lock_rejects_before_connect(tmp_path, monkeypatch):
    path, _ = fixture(tmp_path)
    with RunJournal.lock_existing(path, "device") as token:
        replacement = tmp_path / "replacement"
        replacement.write_bytes(path.read_bytes())
        try:
            os.replace(replacement, path)
        except PermissionError:
            pytest.skip("OS handle prevents replacement")
        monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: pytest.fail("connect"))
        with pytest.raises(UnsafeReplay):
            with RunJournal.open_existing_locked(token):
                pass


def test_outer_exit_closes_database_before_unlock(tmp_path):
    path, _ = fixture(tmp_path)
    with RunJournal.lock_existing(path, "device") as token:
        context = RunJournal.open_existing_locked(token)
        journal = context.__enter__()
    with pytest.raises((sqlite3.ProgrammingError, UnsafeReplay)):
        journal.has_intent("job", "start")
    context.__exit__(None, None, None)
    with RunJournal.lock_existing(path, "device"):
        pass


def test_lock_failure_preserves_original_bytes(tmp_path):
    path, lock = fixture(tmp_path)
    before = path.read_bytes()
    lock.write_bytes(b"")
    with pytest.raises(UnsafeReplay):
        with RunJournal.lock_existing(path, "device"):
            pass
    assert path.read_bytes() == before
    assert lock.read_bytes() == b""


def test_mutable_journal_content_is_not_pinned(tmp_path):
    path, _ = fixture(tmp_path)
    with RunJournal.lock_existing(path, "device") as token:
        with RunJournal.open_existing_locked(token) as journal:
            journal.record_intent("job", 1, "start")
            journal.record_result("job", 1, "start", "uncertain")
            journal.stop_ack_intent("job", 1, 2)
    with RunJournal.lock_existing(path, "device") as token:
        with RunJournal.open_existing_locked(token) as journal:
            assert journal.has_intent("job", "start")
            with pytest.raises(UnsafeReplay):
                journal.record_intent("job", 2, "start")


@pytest.mark.parametrize("target", ["journal", "lock", "marker"])
def test_symlink_rejected_before_sqlite(tmp_path, monkeypatch, target):
    path, lock = fixture(tmp_path)
    victim = path if target == "journal" else lock
    if target == "marker":
        victim = tmp_path / ("replay-" + hashlib.sha256(b"device").hexdigest() + ".json")
        victim.write_text("{}")
    original = victim.with_suffix(".original")
    victim.rename(original)
    try:
        victim.symlink_to(original)
    except OSError:
        pytest.skip("symlinks unavailable")
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: pytest.fail("connect"))
    with pytest.raises(UnsafeReplay):
        with RunJournal.lock_existing(path, "device"):
            pass


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFO")
def test_fifo_journal_rejected_before_open(tmp_path, monkeypatch):
    path, _ = fixture(tmp_path)
    path.unlink()
    os.mkfifo(path)
    monkeypatch.setattr(os, "open", lambda *a, **k: pytest.fail("opened FIFO"))
    with pytest.raises(UnsafeReplay):
        with RunJournal.lock_existing(path, "device"):
            pass


def test_independent_process_cannot_enter_while_original_lock_held(tmp_path):
    import subprocess
    import sys

    path, _ = fixture(tmp_path)
    code = """
import sys
from pathlib import Path
from swu_happyrun.agent.journal import RunJournal, UnsafeReplay
try:
    with RunJournal.lock_existing(Path(sys.argv[1]), 'device'):
        print('acquired')
except UnsafeReplay:
    print('busy')
"""

    def invoke():
        return subprocess.run(
            [sys.executable, "-c", code, str(path)],
            text=True,
            capture_output=True,
            timeout=10,
            check=True,
        )

    with RunJournal.lock_existing(path, "device"):
        assert invoke().stdout.strip() == "busy"
    assert invoke().stdout.strip() == "acquired"


def test_reservation_appearing_after_lock_is_rechecked_before_connect(tmp_path, monkeypatch):
    import json

    path, _ = fixture(tmp_path)
    with RunJournal.lock_existing(path, "device") as token:
        marker = tmp_path / ("replay-" + hashlib.sha256(b"device").hexdigest() + ".json")
        marker.write_text(
            json.dumps(
                {
                    "schema": 1,
                    "owner": "local_virtual_replay",
                    "device_digest": hashlib.sha256(b"device").hexdigest(),
                    "session_id": str(uuid4()),
                    "status": "uncertain",
                    "generation": 1,
                    "probe_pending": False,
                }
            )
        )
        monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: pytest.fail("connect"))
        with pytest.raises(UnsafeReplay, match="replay_recovery_requires_stop"):
            with RunJournal.open_existing_locked(token):
                pass


def test_normal_reservation_is_still_owned_without_second_lock(tmp_path):
    path, _ = fixture(tmp_path)
    with RunJournal.lock_existing(path, "device") as token:
        with RunJournal.open_existing_locked(token) as journal:
            permit = journal.reserve_replay("device", str(uuid4()), generation=1)
            journal.verify_replay(permit, generation=1)
            journal.update_replay(permit, generation=1, status="stopped")
    with RunJournal.lock_existing(path, "device"):
        pass
