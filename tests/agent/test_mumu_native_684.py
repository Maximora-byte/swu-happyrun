"""Isolated actual Python children; none of these tests invoke MuMu or ADB."""

import subprocess
import sys
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from swu_happyrun.core.clock import SystemClock
from swu_happyrun.core.models import GeoPoint
from swu_happyrun.drivers.base import DriverError
from swu_happyrun.drivers.mumu.binding import MumuBinding
from swu_happyrun.drivers.mumu.native_684 import MuMuNative684

POINT = GeoPoint(latitude=12.25, longitude=34.75)


def binding():
    return MumuBinding(
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


@pytest.fixture
def processes(monkeypatch):
    original = subprocess.Popen
    calls = []
    scripts = {"manager": "print('ok')", "adb": "print('35')"}

    def spawn(argv, **kwargs):
        kind = "adb" if argv[0] == str(Path("adb")) else "manager"
        calls.append((kind, argv, kwargs))
        return original([sys.executable, "-c", scripts[kind]], **kwargs)

    monkeypatch.setattr(subprocess, "Popen", spawn)
    return calls, scripts


def native(**kw):
    options = dict(
        adb=Path("adb"),
        binding_check=lambda: None,
        authorization_check=lambda: None,
        clock=SystemClock(),
    )
    options.update(kw)
    return MuMuNative684(Path("manager"), binding(), **options)


def test_expired_or_wrong_binding_starts_zero_processes(processes):
    calls, _ = processes
    driver = native()
    with pytest.raises(DriverError, match="write_deadline_expired"):
        driver.write_location(POINT, deadline=time.monotonic() - 1)

    def reject():
        raise DriverError("binding_changed")

    driver = native(binding_check=reject)
    with pytest.raises(DriverError, match="binding_changed"):
        driver.write_location(POINT, deadline=time.monotonic() + 4)
    assert calls == []


def test_actual_fixed_argv_exit_zero_is_not_device_ack(processes):
    calls, _ = processes
    driver = native()
    with pytest.raises(DriverError, match="write_ack_unconfirmed"):
        driver.write_location(POINT, deadline=time.monotonic() + 4)
    assert calls[-1][1] == [
        "manager",
        "control",
        "--vmindex",
        "0",
        "tool",
        "location",
        "--longitude",
        "34.75",
        "--latitude",
        "12.25",
    ]
    assert all(c[2]["shell"] is False for c in calls)
    assert driver.last_delivery.command_completed
    assert driver.capabilities == ()
    with pytest.raises(DriverError, match="writer_closed"):
        driver.write_location(POINT, deadline=time.monotonic() + 4)
    assert len(calls) == 2


def test_timeout_after_side_effect_is_not_retried(processes, tmp_path):
    calls, scripts = processes
    marker = tmp_path / "attempts"
    scripts["manager"] = (
        f"from pathlib import Path; import time; Path({str(marker)!r}).write_text('1'); "
        "time.sleep(5)"
    )
    driver = native()
    started = time.monotonic()
    with pytest.raises(DriverError, match="write_timeout"):
        driver.write_location(POINT, deadline=started + 2)
    assert time.monotonic() - started < 3.5
    assert marker.read_text() == "1"
    with pytest.raises(DriverError, match="writer_closed"):
        driver.write_location(POINT, deadline=time.monotonic() + 4)
    assert len([c for c in calls if c[0] == "manager"]) == 1


def test_stop_checks_all_channels_and_rejects_late_writes(processes):
    calls, _ = processes
    driver = native()
    with pytest.raises(DriverError, match="stop_unconfirmed"):
        driver.stop()
    for write in (
        lambda: driver.write_location(POINT, deadline=time.monotonic() + 4),
        lambda: driver.write_gyro((1.0, 2.0, 3.0), deadline=time.monotonic() + 4),
    ):
        with pytest.raises(DriverError, match="writer_closed"):
            write()
    assert calls == []


@pytest.mark.parametrize("sdk", ["34", "", "35 extra", "35\n36"])
def test_actual_sdk_rejection_never_invokes_manager(processes, sdk):
    calls, scripts = processes
    scripts["adb"] = f"print({sdk!r})"
    driver = native()
    with pytest.raises(DriverError, match="transport_version_unverified"):
        driver.write_location(POINT, deadline=time.monotonic() + 3)
    assert [c[0] for c in calls] == ["adb"]
    assert calls[0][1] == [
        "adb",
        "-s",
        "synthetic-serial",
        "shell",
        "getprop",
        "ro.build.version.sdk",
    ]


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("host_version", "6.8.5.0", "transport_version_unverified"),
        ("package", "com.lptiyu.tanke", "own_target_required"),
        ("instance_index", "0 & echo", "instance_index_invalid"),
    ],
)
def test_unknown_version_or_target_rejected_before_processes(processes, field, value, code):
    with pytest.raises(DriverError, match=code):
        MuMuNative684(
            Path("manager"),
            replace(binding(), **{field: value}),
            adb=Path("adb"),
            binding_check=lambda: None,
            authorization_check=lambda: None,
            clock=SystemClock(),
        )
    assert processes[0] == []


@pytest.mark.parametrize("deadline", [float("nan"), float("inf"), True, "1", 10**1000])
def test_invalid_deadline_starts_zero_processes(processes, deadline):
    with pytest.raises(DriverError, match="write_deadline_invalid"):
        native().write_location(POINT, deadline=deadline)
    assert processes[0] == []


def test_authority_is_rechecked_after_sdk_before_write(processes):
    calls, _ = processes

    def authority():
        if calls:
            raise DriverError("cancelled")

    with pytest.raises(DriverError, match="cancelled"):
        native(authorization_check=authority).write_location(POINT, deadline=time.monotonic() + 3)
    assert [c[0] for c in calls] == ["adb"]


def test_final_binding_observation_can_cancel_without_late_write(processes):
    calls, _ = processes
    driver = None

    def current():
        if calls:
            with pytest.raises(DriverError, match="stop_unconfirmed"):
                driver.stop()

    driver = native(binding_check=current)
    with pytest.raises(DriverError, match="writer_closed"):
        driver.write_location(POINT, deadline=time.monotonic() + 3)
    assert [c[0] for c in calls] == ["adb"]


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_actual_output_flood_is_bounded(processes, stream):
    _, scripts = processes
    scripts["manager"] = f"import sys; sys.{stream}.buffer.write(b'x'*2000000)"
    with pytest.raises(DriverError, match="write_output_limit"):
        native().write_location(POINT, deadline=time.monotonic() + 3)


def test_actual_dual_streams_keep_raw_byte_digest(processes):
    import hashlib

    _, scripts = processes
    scripts["manager"] = (
        "import sys; sys.stderr.buffer.write(b'e'*60000); sys.stderr.flush(); "
        "sys.stdout.buffer.write(b'raw\\r\\n')"
    )
    driver = native()
    with pytest.raises(DriverError, match="write_ack_unconfirmed"):
        driver.write_gyro((1.0, -2.0, 3.0), deadline=time.monotonic() + 3)
    assert driver.last_delivery.stdout_sha256 == hashlib.sha256(b"raw\r\n").hexdigest()
    assert driver.last_delivery.stdout_bytes == 5
    assert driver.last_delivery.stderr_bytes == 60000
    assert processes[0][-1][1][-6:] == ["--gyro_x", "1.0", "--gyro_y", "-2.0", "--gyro_z", "3.0"]


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_actual_write_output_decodes_strictly(processes, stream):
    _, scripts = processes
    scripts["manager"] = f"import sys; sys.{stream}.buffer.write(bytes([255]))"
    driver = native()
    with pytest.raises(DriverError, match="write_encoding_invalid"):
        driver.write_location(POINT, deadline=time.monotonic() + 3)
    assert driver.last_delivery is None


def test_actual_nonzero_is_not_retried_or_exposed(processes):
    calls, scripts = processes
    scripts["manager"] = "import sys; print('private fixture'); sys.exit(4)"
    driver = native()
    with pytest.raises(DriverError, match="write_failed_unconfirmed") as caught:
        driver.write_location(POINT, deadline=time.monotonic() + 3)
    assert "private" not in str(caught.value)
    with pytest.raises(DriverError, match="writer_closed"):
        driver.write_gyro((1.0, 2.0, 3.0), deadline=time.monotonic() + 3)
    assert [c[0] for c in calls] == ["adb", "manager"]


def test_actual_inherited_pipe_blocks_new_native_capture_until_eof(processes):
    calls, scripts = processes
    scripts["manager"] = (
        "import subprocess,sys; subprocess.Popen([sys.executable,'-c',"
        "'import time; time.sleep(3)'])"
    )
    driver = native()
    started = time.monotonic()
    with pytest.raises(DriverError, match="write_cleanup_unconfirmed"):
        driver.write_location(POINT, deadline=started + 1)
    assert time.monotonic() - started < 2.5
    before = len(calls)
    with pytest.raises(DriverError, match="write_cleanup_unconfirmed"):
        native().write_location(POINT, deadline=time.monotonic() + 3)
    assert len(calls) == before
    # The test owns this finite-lived synthetic descendant. Never kill a real tree.
    time.sleep(3)
    scripts["manager"] = "print('done')"
    with pytest.raises(DriverError, match="write_ack_unconfirmed"):
        native().write_location(POINT, deadline=time.monotonic() + 3)


def test_stop_during_actual_write_is_immediate_and_no_late_second_channel(processes, tmp_path):
    import threading

    calls, scripts = processes
    marker = tmp_path / "started"
    scripts["manager"] = (
        f"from pathlib import Path; import time; Path({str(marker)!r}).touch(); time.sleep(5)"
    )
    driver = native()
    errors = []

    def write():
        try:
            driver.write_location(POINT, deadline=time.monotonic() + 4)
        except DriverError as exc:
            errors.append(exc.reason_code)

    thread = threading.Thread(target=write)
    thread.start()
    until = time.monotonic() + 3
    while not marker.exists() and time.monotonic() < until:
        time.sleep(0.01)
    assert marker.exists()
    start = time.monotonic()
    with pytest.raises(DriverError, match="stop_unconfirmed"):
        driver.stop()
    assert time.monotonic() - start < 0.2
    thread.join(2)
    assert not thread.is_alive()
    assert errors == ["write_cancelled_unconfirmed"]
    with pytest.raises(DriverError, match="writer_closed"):
        driver.write_gyro((1.0, 2.0, 3.0), deadline=time.monotonic() + 3)
    assert len([c for c in calls if c[0] == "manager"]) == 1


def test_new_writer_after_restart_cannot_claim_stop(processes):
    with pytest.raises(DriverError, match="stop_unconfirmed"):
        native().stop()
    assert processes[0] == []


def test_authority_consuming_deadline_starts_no_write(processes):
    calls, _ = processes

    class Clock:
        value = 0.0

        def monotonic(self):
            return self.value

    clock = Clock()

    def authority():
        if calls:
            clock.value = 2.0

    with pytest.raises(DriverError, match="write_deadline_expired"):
        native(clock=clock, authorization_check=authority).write_location(POINT, deadline=1.0)
    assert [c[0] for c in calls] == ["adb"]


def test_actual_sdk_timeout_starts_no_write(processes):
    calls, scripts = processes
    scripts["adb"] = "import time; time.sleep(5)"
    with pytest.raises(DriverError, match="android_api_probe_failed"):
        native().write_location(POINT, deadline=time.monotonic() + 0.2)
    assert [c[0] for c in calls] == ["adb"]


def test_reader_start_failure_closes_child_and_next_capture_works(processes, monkeypatch):
    import threading

    original = threading.Thread.start

    def start(thread):
        if thread.name == "happyrun-readonly-capture" and processes[0][-1][0] == "manager":
            raise RuntimeError("private fixture")
        return original(thread)

    with monkeypatch.context() as patch:
        patch.setattr(threading.Thread, "start", start)
        with pytest.raises(DriverError, match="write_capture_failed"):
            native().write_location(POINT, deadline=time.monotonic() + 3)
    with pytest.raises(DriverError, match="write_ack_unconfirmed"):
        native().write_location(POINT, deadline=time.monotonic() + 3)


def test_actual_pending_direct_child_alone_blocks_next_capture(processes, monkeypatch):
    from swu_happyrun.drivers import command

    # Capture the real child before wrapping its lifecycle methods. Readers reach
    # EOF, but poll reports an unresolved direct child until the test releases it.
    fixture_spawn = subprocess.Popen
    state = {"blocked": True}

    def spawn(argv, **kwargs):
        process = fixture_spawn(argv, **kwargs)
        if argv[0] == "manager":
            poll = process.poll
            wait = process.wait

            def pending_poll():
                return None if state["blocked"] else poll()

            def failed_wait(*args, **kw):
                if state["blocked"]:
                    raise subprocess.TimeoutExpired("synthetic", 0)
                return wait(*args, **kw)

            process.poll = pending_poll
            process.wait = failed_wait
            state["process"] = process
        return process

    monkeypatch.setattr(subprocess, "Popen", spawn)
    try:
        with pytest.raises(DriverError, match="write_cleanup_unconfirmed"):
            native().write_location(POINT, deadline=time.monotonic() + 1)
        assert all(not t.is_alive() for t in command._PENDING_CAPTURE[1])
        before = len(processes[0])
        with pytest.raises(DriverError, match="write_cleanup_unconfirmed"):
            native().write_location(POINT, deadline=time.monotonic() + 3)
        assert len(processes[0]) == before
    finally:
        state["blocked"] = False
        state["process"].wait(timeout=3)
    with pytest.raises(DriverError, match="write_ack_unconfirmed"):
        native().write_location(POINT, deadline=time.monotonic() + 3)


def test_native_cleanup_preserves_primary_failure(processes, monkeypatch):
    original = subprocess.Popen

    def spawn(argv, **kwargs):
        process = original(argv, **kwargs)
        if argv[0] == "manager":
            original_wait = process.wait

            def wait(*args, **kw):
                original_wait(*args, **kw)
                raise subprocess.TimeoutExpired("synthetic", 0)

            process.wait = wait
        return process

    monkeypatch.setattr(subprocess, "Popen", spawn)
    with pytest.raises(DriverError, match="write_cleanup_unconfirmed") as caught:
        native().write_location(POINT, deadline=time.monotonic() + 3)
    assert caught.value.primary_code == "ok"


def test_binding_probe_precedes_guard_and_guard_precedes_manager(processes):
    from swu_happyrun.drivers.command import run_readonly

    calls, _ = processes
    sequence = []

    def current():
        sequence.append("binding")
        assert run_readonly(Path("adb"), "-s", "synthetic-serial", "get-state").strip() == "35"

    def authorized():
        sequence.append("authority")

    driver = native(binding_check=current, authorization_check=authorized)
    with pytest.raises(DriverError, match="write_ack_unconfirmed"):
        driver.write_location(POINT, deadline=time.monotonic() + 4)
    assert sequence == ["binding", "authority", "binding", "authority"]
    assert [c[0] for c in calls] == ["adb", "adb", "adb", "manager"]


def test_global_capture_busy_starts_no_native_or_sdk_process(processes):
    from swu_happyrun.drivers import command

    assert command._CAPTURE_LOCK.acquire(False)
    try:
        with pytest.raises(DriverError, match="write_busy"):
            native().write_location(POINT, deadline=time.monotonic() + 3)
        assert processes[0] == []
    finally:
        command._CAPTURE_LOCK.release()


@pytest.mark.parametrize("error_name", ["Cancelled", "LeaseLost"])
def test_final_guard_preserves_runner_cancellation_and_lease_loss(processes, error_name):
    from swu_happyrun.agent import runner

    calls, _ = processes
    error_type = getattr(runner, error_name)

    def authority():
        if calls:
            raise error_type()

    driver = native(authorization_check=authority)
    with pytest.raises(error_type):
        driver.write_location(POINT, deadline=time.monotonic() + 3)
    assert [c[0] for c in calls] == ["adb"]
    with pytest.raises(DriverError, match="writer_closed"):
        driver.write_location(POINT, deadline=time.monotonic() + 3)
    # The shared process guard must still be released after the final callback.
    with pytest.raises(DriverError, match="write_ack_unconfirmed"):
        native().write_location(POINT, deadline=time.monotonic() + 3)
