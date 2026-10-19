"""Durable local reservations also fence the unchanged remote AgentRunner."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from swu_happyrun.agent.journal import RunJournal, UnsafeReplay


def marker_path(path, device):
    return path.parent / ("replay-" + hashlib.sha256(device.encode()).hexdigest() + ".json")


def reserved(path, device="device"):
    with RunJournal(path) as journal, journal.device_lock(device):
        token = journal.reserve_replay(device, str(uuid4()), generation=1)
        journal.record_intent(token.marker["session_id"], 1, "start")
    return token


def test_replay_reservation_survives_actual_process_exit_and_blocks_remote_job(tmp_path):
    from test_runner import Client, Clock, Driver

    from swu_happyrun.agent.runner import AgentRunner

    path = tmp_path / "runs.sqlite"
    clock = Clock()
    client, driver = Client(clock), Driver()
    device = client.job.spec.device_id
    code = """
import os,sys
from pathlib import Path
from swu_happyrun.agent.journal import RunJournal
j=RunJournal(Path(sys.argv[1]))
with j.device_lock(sys.argv[2]):
    j.reserve_replay(sys.argv[2],sys.argv[3],generation=1)
    j.record_intent(sys.argv[3],1,'start')
    os._exit(0)
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(path), device, str(uuid4())],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")},
        timeout=10,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    with RunJournal(path) as journal:
        runner = AgentRunner(
            client, driver, journal, clock, device_id=device, sleep=clock.sleep, run_seconds=2
        )
        with pytest.raises(UnsafeReplay, match="recovery_requires_stop"):
            runner.run_once()
    assert driver.calls == []
    assert client.states == []


def test_replay_recovery_permit_is_bound_and_stop_only(tmp_path):
    path = tmp_path / "runs.sqlite"
    stale = reserved(path)
    with RunJournal(path) as journal:
        with journal.replay_recovery_lock("device") as token:
            with pytest.raises(UnsafeReplay):
                journal.verify_replay(token, generation=1)
            with pytest.raises(UnsafeReplay):
                journal.update_replay(token, generation=2, status="active")
            for bogus in ("arbitrary-token", stale, object()):
                with pytest.raises(UnsafeReplay):
                    journal.update_replay(bogus, generation=2, status="stopped")
            journal.update_replay(token, generation=2, status="stopped")
        with pytest.raises(UnsafeReplay):
            journal.update_replay(token, generation=3, status="stopped")
        with journal.device_lock("device"):
            pass


def test_replay_permit_cannot_cross_device_or_session(tmp_path):
    path = tmp_path / "runs.sqlite"
    reserved(path, "one")
    reserved(path, "two")
    with RunJournal(path) as first, RunJournal(path) as second:
        with first.replay_recovery_lock("one") as token:
            with second.replay_recovery_lock("two"):
                with pytest.raises(UnsafeReplay):
                    second.update_replay(token, generation=2, status="stopped")
            value = dict(token.marker, session_id=str(uuid4()))
            marker_path(path, "one").write_text(json.dumps(value), encoding="utf-8")
            with pytest.raises(UnsafeReplay):
                first.update_replay(token, generation=2, status="stopped")


@pytest.mark.parametrize(
    "mutation",
    [
        "bad_json",
        "duplicate_key",
        "extra",
        "session",
        "negative",
        "wrong_device",
        "owner",
        "too_large",
    ],
)
def test_replay_corrupt_markers_fail_closed(tmp_path, mutation):
    path = tmp_path / "runs.sqlite"
    reserved(path)
    marker = marker_path(path, "device")
    value = json.loads(marker.read_text())
    if mutation == "bad_json":
        raw = "{"
    elif mutation == "duplicate_key":
        raw = json.dumps(value)[:-1] + ',"status":"stopped"}'
    elif mutation == "too_large":
        raw = " " * 4097
    else:
        if mutation == "extra":
            value["trusted"] = True
        elif mutation == "session":
            value["session_id"] = "invalid"
        elif mutation == "negative":
            value["generation"] = -1
        elif mutation == "wrong_device":
            value["device_digest"] = "0" * 64
        else:
            value["owner"] = "unknown"
        raw = json.dumps(value)
    marker.write_text(raw, encoding="utf-8")
    with RunJournal(path) as journal:
        for factory in (journal.device_lock, journal.replay_recovery_lock):
            with pytest.raises(UnsafeReplay, match="journal_invalid"):
                with factory("device"):
                    pytest.fail("corrupt reservation accepted")


@pytest.mark.parametrize("dangling", [False, True])
def test_replay_symlink_marker_fails_closed(tmp_path, symlink_or_skip, dangling):
    path = tmp_path / "runs.sqlite"
    target = tmp_path / "target.json"
    if not dangling:
        target.write_text("{}", encoding="utf-8")
    symlink_or_skip(marker_path(path, "device"), target)
    with RunJournal(path) as journal:
        with pytest.raises(UnsafeReplay, match="journal_invalid"):
            with journal.device_lock("device"):
                pytest.fail("symlink reservation accepted")


def test_replay_reservation_requires_held_lock(tmp_path):
    with RunJournal(tmp_path / "runs.sqlite") as journal:
        with pytest.raises(UnsafeReplay):
            journal.read_replay_reservation("device")
        with pytest.raises(UnsafeReplay):
            journal.reserve_replay("device", str(uuid4()), generation=1)


def test_replay_confirmed_stop_allows_ordinary_remote_job(tmp_path):
    from test_runner import Client, Clock, Driver

    from swu_happyrun.agent.runner import AgentRunner

    clock = Clock()
    client, driver = Client(clock), Driver()
    path = tmp_path / "runs.sqlite"
    reserved(path, client.job.spec.device_id)
    with RunJournal(path) as journal:
        with journal.replay_recovery_lock(client.job.spec.device_id) as token:
            journal.update_replay(token, generation=2, status="stopped")
        runner = AgentRunner(
            client,
            driver,
            journal,
            clock,
            device_id=client.job.spec.device_id,
            sleep=clock.sleep,
            run_seconds=2,
        )
        assert runner.run_once().state == "completed"
    assert driver.calls.count("start") == 1


def test_replay_contradictory_stopped_pending_marker_blocks_remote_job(tmp_path):
    from test_runner import Client, Clock, Driver

    from swu_happyrun.agent.runner import AgentRunner

    clock = Clock()
    client, driver = Client(clock), Driver()
    path = tmp_path / "runs.sqlite"
    reserved(path, client.job.spec.device_id)
    marker = marker_path(path, client.job.spec.device_id)
    value = json.loads(marker.read_text())
    value.update(status="stopped", probe_pending=True)
    marker.write_text(json.dumps(value), encoding="utf-8")
    with RunJournal(path) as journal:
        runner = AgentRunner(
            client,
            driver,
            journal,
            clock,
            device_id=client.job.spec.device_id,
            sleep=clock.sleep,
            run_seconds=2,
        )
        with pytest.raises(UnsafeReplay, match="journal_invalid"):
            runner.run_once()
    assert driver.calls == []
    assert client.states == []
