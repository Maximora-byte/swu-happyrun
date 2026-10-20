"""Private bounded capture receipts use synthetic host children, never devices."""

import dataclasses
import sys
import threading
import time
from pathlib import Path

import pytest

from swu_happyrun.drivers import command


@pytest.fixture(autouse=True)
def capture_isolation(monkeypatch):
    monkeypatch.setattr(command, "_PENDING_CAPTURE", None)
    yield
    pending = command._PENDING_CAPTURE
    if pending is not None:
        process, threads, _ = pending
        process.wait(timeout=2)
        for thread, pipe, done in threads:
            if thread.ident is None:
                # These tests inject start() failures without ever starting it.
                pipe.close()
            else:
                done.wait(2)
                thread.join(2)


def collector():
    assert hasattr(command, "CaptureEvidence"), "bounded private evidence collector is missing"
    return command.CaptureEvidence()


def child(source, evidence, **kwargs):
    return command._run_bounded_bytes(
        Path(sys.executable), "-c", source, evidence=evidence, **kwargs
    )


def test_success_preserves_binary_receipt_without_repr_disclosure():
    evidence = collector()
    result = child(
        "import os; os.write(1,b'private-out\\xff'); os.write(2,b'private-err')", evidence
    )
    snapshot = evidence.snapshot
    assert result == (b"private-out\xff", b"private-err", 0)
    assert (snapshot.stdout, snapshot.stderr, snapshot.returncode) == result
    assert snapshot.primary_code == snapshot.final_code == "ok"
    assert snapshot.cleanup_code == "confirmed"
    assert snapshot.output_complete and not snapshot.truncated
    assert snapshot.process_started
    assert snapshot.started_monotonic <= snapshot.finished_monotonic <= time.monotonic()
    assert "private" not in repr(evidence) + repr(snapshot)
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.stdout = b"replacement"


def test_nonzero_return_keeps_both_streams_and_existing_return_contract():
    evidence = collector()
    result = child(
        "import os; os.write(1,b'out'); os.write(2,b'err'); raise SystemExit(7)", evidence
    )
    assert result == (b"out", b"err", 7)
    assert evidence.snapshot.primary_code == "command_failed"
    assert evidence.snapshot.returncode == 7
    assert evidence.snapshot.output_complete


@pytest.mark.parametrize(
    "source,code",
    [
        (
            "import os,time; os.write(1,b'partial'); os.write(2,b'err'); time.sleep(5)",
            "command_timeout",
        ),
        ("import os; os.write(1,b'x'*10000)", "command_output_limit"),
    ],
)
def test_failures_keep_bounded_partial_bytes(monkeypatch, source, code):
    monkeypatch.setattr(command, "MAX_OUTPUT_BYTES", 1024)
    evidence = collector()
    with pytest.raises(command.ProbeError, match=code):
        child(source, evidence, timeout=0.15)
    snapshot = evidence.snapshot
    assert snapshot.stdout
    assert len(snapshot.stdout) <= 1024 and len(snapshot.stderr) <= 1024
    assert snapshot.primary_code == snapshot.final_code == code
    assert snapshot.cleanup_code == "confirmed"
    assert not snapshot.output_complete
    assert snapshot.truncated == (code == "command_output_limit")


def test_readonly_encoding_failure_retains_binary_bytes():
    evidence = collector()
    with pytest.raises(command.ProbeError, match="command_encoding_invalid"):
        command.run_readonly(
            Path(sys.executable), "-c", "import os; os.write(1,b'\\xff')", evidence=evidence
        )
    assert evidence.snapshot.stdout == b"\xff"
    assert (
        evidence.snapshot.primary_code == evidence.snapshot.final_code == "command_encoding_invalid"
    )
    assert evidence.snapshot.output_complete


@pytest.mark.parametrize(
    "mode,code",
    [
        ("missing", "executable_missing"),
        ("guard", "command_guard_failed"),
        ("busy", "command_capture_busy"),
        ("cancel", "command_cancelled"),
        ("budget", "command_budget_invalid"),
    ],
)
def test_no_spawn_paths_have_safe_empty_receipt(mode, code):
    evidence = collector()
    kwargs = {}
    path = Path(sys.executable)
    if mode == "missing":
        path = Path("/nonexistent-private-path/no-executable")
    if mode == "guard":

        def fail():
            raise ValueError("private-guard-detail")

        kwargs["before_spawn"] = fail
    if mode == "cancel":
        event = threading.Event()
        event.set()
        kwargs["cancel_event"] = event
    if mode == "budget":
        kwargs["timeout"] = -1
    if mode == "busy":
        command._CAPTURE_LOCK.acquire()
    try:
        with pytest.raises((command.ProbeError, ValueError)):
            command._run_bounded_bytes(path, "-c", "pass", evidence=evidence, **kwargs)
    finally:
        if mode == "busy":
            command._CAPTURE_LOCK.release()
    snapshot = evidence.snapshot
    assert snapshot.primary_code == snapshot.final_code == code
    assert not snapshot.process_started and not snapshot.output_complete
    assert snapshot.cleanup_code == "not_started"
    assert snapshot.stdout == snapshot.stderr == b""
    assert "private" not in repr(evidence) + repr(snapshot)


def test_reader_start_failure_preserves_first_reader_bytes(monkeypatch):
    evidence = collector()
    original = threading.Thread.start
    first_done = threading.Event()
    read_pipe = command._read_pipe

    def read(*args):
        try:
            read_pipe(*args)
        finally:
            first_done.set()

    def start(thread):
        if getattr(start, "started", False):
            assert first_done.wait(2)
            raise RuntimeError("private-start-detail")
        start.started = True
        original(thread)

    monkeypatch.setattr(command, "_read_pipe", read)
    monkeypatch.setattr(threading.Thread, "start", start)
    with pytest.raises(command.ProbeError, match="command_cleanup_unconfirmed"):
        child("import os; os.write(1,b'first-reader')", evidence)
    snapshot = evidence.snapshot
    assert snapshot.stdout == b"first-reader"
    assert snapshot.primary_code == "command_reader_failed"
    assert snapshot.cleanup_code == "unconfirmed"
    assert not snapshot.output_complete
    assert "private" not in repr(snapshot)


def test_interruption_keeps_partial_bytes_and_still_cleans_child(tmp_path):
    evidence = collector()
    marker = tmp_path / "ready"

    class Interrupt:
        def is_set(self):
            if marker.exists():
                time.sleep(0.03)
                raise KeyboardInterrupt()
            return False

    source = (
        "import os,time,pathlib; os.write(1,b'interrupted'); "
        f"pathlib.Path({str(marker)!r}).touch(); time.sleep(5)"
    )
    with pytest.raises(KeyboardInterrupt):
        child(source, evidence, cancel_event=Interrupt())
    assert evidence.snapshot.stdout == b"interrupted"
    assert evidence.snapshot.primary_code == "command_interrupted"
    assert evidence.snapshot.cleanup_code == "confirmed"
    assert not evidence.snapshot.output_complete


def test_absolute_cleanup_deadline_does_not_grant_fresh_half_second(monkeypatch):
    evidence = collector()
    original = threading.Thread.start

    def fail_start(thread):
        raise RuntimeError("synthetic-start-failure")

    monkeypatch.setattr(threading.Thread, "start", fail_start)
    started = time.monotonic()
    with pytest.raises(command.ProbeError, match="command_cleanup_unconfirmed"):
        child("import time; time.sleep(5)", evidence, cleanup_deadline_monotonic=started + 0.05)
    assert time.monotonic() - started < 0.3
    assert evidence.snapshot.cleanup_code == "unconfirmed"
    monkeypatch.setattr(threading.Thread, "start", original)


def test_native_optional_collector_records_only_manager_attempt(monkeypatch):
    import subprocess
    from datetime import UTC, datetime

    from swu_happyrun.core.clock import SystemClock
    from swu_happyrun.core.models import GeoPoint
    from swu_happyrun.drivers.base import DriverError
    from swu_happyrun.drivers.mumu.binding import MumuBinding
    from swu_happyrun.drivers.mumu.native_684 import MuMuNative684

    evidence = collector()
    binding = MumuBinding(
        "0",
        "synthetic-serial",
        "6.8.4.0",
        "15",
        "1",
        "org.happyrun.app",
        0,
        1,
        "synthetic-boot",
        "00000000-0000-4000-8000-000000000001",
        datetime.now(UTC),
        "a" * 64,
    )
    original = subprocess.Popen
    calls = []

    def spawn(argv, **kwargs):
        calls.append(argv[0])
        source = (
            "print('35')" if argv[0] == "adb" else "print('manager-private'); raise SystemExit(3)"
        )
        if argv[0] == "manager":
            assert evidence.snapshot is None  # SDK capture must not populate it.
        return original([sys.executable, "-c", source], **kwargs)

    monkeypatch.setattr(subprocess, "Popen", spawn)
    driver = MuMuNative684(
        Path("manager"),
        binding,
        adb=Path("adb"),
        binding_check=lambda: None,
        authorization_check=lambda: None,
        clock=SystemClock(),
        evidence=evidence,
    )
    with pytest.raises(DriverError, match="write_failed_unconfirmed"):
        driver.write_location(
            GeoPoint(latitude=12.25, longitude=34.75), deadline=time.monotonic() + 2
        )
    assert evidence.snapshot.stdout == b"manager-private\n"
    assert evidence.snapshot.returncode == 3
    with pytest.raises(DriverError, match="writer_closed"):
        driver.write_location(
            GeoPoint(latitude=12.25, longitude=34.75), deadline=time.monotonic() + 2
        )
    assert calls == ["adb", "manager"]


def test_unresolved_readers_snapshot_is_immutable_and_pending_gate_stays_closed(monkeypatch):
    evidence = collector()
    release = threading.Event()
    original = command._read_pipe
    readers = []

    def hold(*args):
        readers.append(threading.current_thread())
        original(*args)
        release.wait(5)

    monkeypatch.setattr(command, "_read_pipe", hold)
    try:
        with pytest.raises(command.ProbeError, match="command_cleanup_unconfirmed"):
            child("print('retained')", evidence, timeout=0.1)
        snapshot = evidence.snapshot
        assert snapshot.stdout == b"retained\n"
        assert not snapshot.output_complete
        assert snapshot.cleanup_code == "unconfirmed"
        blocked = collector()
        with pytest.raises(command.ProbeError, match="command_cleanup_unconfirmed"):
            child("raise AssertionError('must not spawn')", blocked)
        assert blocked.snapshot.cleanup_code == "unconfirmed"
        assert not blocked.snapshot.process_started
        assert blocked.snapshot.stdout == b""
    finally:
        release.set()
        for reader in readers:
            reader.join(2)
    assert evidence.snapshot is snapshot and snapshot.stdout == b"retained\n"
    assert not snapshot.output_complete  # Later EOF cannot rewrite historical evidence.


def test_cleanup_interruption_retains_primary_and_pending_ownership(monkeypatch):
    import subprocess

    evidence = collector()
    original = subprocess.Popen.wait
    interrupted = []

    def interrupt_once(process, *args, **kwargs):
        if not interrupted:
            interrupted.append(process)
            raise KeyboardInterrupt()
        return original(process, *args, **kwargs)

    monkeypatch.setattr(subprocess.Popen, "wait", interrupt_once)
    try:
        with pytest.raises(KeyboardInterrupt):
            child("import os,time; os.write(1,b'kept'); time.sleep(5)", evidence, timeout=0.15)
        assert evidence.snapshot.stdout == b"kept"
        assert evidence.snapshot.primary_code == "command_timeout"
        assert evidence.snapshot.final_code == "command_interrupted"
        assert evidence.snapshot.cleanup_code == "unconfirmed"
        assert command._PENDING_CAPTURE is not None
    finally:
        for process in interrupted:
            original(process, timeout=2)
        if command._PENDING_CAPTURE:
            for thread, _, done in command._PENDING_CAPTURE[1]:
                done.wait(2)
                thread.join(2)
