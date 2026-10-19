"""Real isolated Python children, never MuMu/ADB or a physical write transport."""

import sys
import time
from pathlib import Path

import pytest

from swu_happyrun.drivers.command import ProbeError, run_readonly


def child(source, *, timeout=5):
    return run_readonly(Path(sys.executable), "-c", source, timeout=timeout)


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_real_output_flood_is_rejected_without_exposing_output(stream):
    with pytest.raises(ProbeError, match="command_output_limit") as caught:
        child(f"import sys; sys.{stream}.buffer.write(b'private' * 400000)")
    assert "private" not in str(caught.value)


def test_real_dual_streams_do_not_deadlock():
    assert (
        child(
            "import sys; "
            "sys.stderr.buffer.write(b'e' * 60000); sys.stderr.flush(); "
            "sys.stdout.buffer.write(b'o' * 60000)"
        )
        == "o" * 60000
    )


def test_real_timeout_is_bounded_and_sanitized():
    start = time.monotonic()
    with pytest.raises(ProbeError, match="command_timeout"):
        child("import time; time.sleep(10)", timeout=0.2)
    assert time.monotonic() - start < 2


def test_real_nonzero_does_not_disclose_either_stream():
    with pytest.raises(ProbeError, match="command_failed") as caught:
        child("import sys; print('private'); print('secret',file=sys.stderr); sys.exit(7)")
    assert str(caught.value) == "command_failed"


def test_real_invalid_utf8_stdout_is_rejected_not_replaced():
    with pytest.raises(ProbeError, match="command_encoding_invalid"):
        child("import sys; sys.stdout.buffer.write(b'\\xff')")


def test_real_utf8_and_space_arguments(tmp_path):
    script = tmp_path / "script with spaces.py"
    script.write_text("import sys; sys.stdout.buffer.write(sys.argv[1].encode('utf-8'))")
    assert (
        run_readonly(Path(sys.executable), str(script), "两个 words; literal")
        == "两个 words; literal"
    )


@pytest.mark.parametrize("timeout", [0, -1, True, float("nan"), float("inf"), "5"])
def test_invalid_timeout_rejected_before_launch(timeout, tmp_path):
    marker = tmp_path / "launched"
    with pytest.raises(ProbeError, match="command_budget_invalid"):
        child(f"from pathlib import Path; Path({str(marker)!r}).touch()", timeout=timeout)
    assert not marker.exists()


def test_inherited_pipe_reports_unconfirmed_cleanup_and_returns_bounded(tmp_path):
    # Descendant owns the pipe for three seconds. Killing only its parent cannot
    # establish EOF or terminate it, on Windows or POSIX. It exits on its own.
    marker = tmp_path / "descendant-finished"
    descendant = (
        f"import time; from pathlib import Path; time.sleep(3); Path({str(marker)!r}).touch()"
    )
    source = f"import subprocess,sys; subprocess.Popen([sys.executable,'-c',{descendant!r}])"
    started = time.monotonic()
    try:
        with pytest.raises(ProbeError, match="command_cleanup_unconfirmed") as caught:
            child(source, timeout=0.3)
        assert caught.value.primary_code == "command_timeout"
        for _ in range(3):
            with pytest.raises(ProbeError, match="command_cleanup_unconfirmed"):
                child("print('must-not-launch')")
        assert time.monotonic() - started < 2
    finally:
        # Test cleanup observes this known fixture's natural exit; no process-tree kill.
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert marker.exists()
        # A marker just before process exit is not pipe EOF; wait for the actual
        # readers to finish rather than clearing the production pending guard.
        import threading

        deadline = time.monotonic() + 2
        while any(t.name == "happyrun-readonly-capture" for t in threading.enumerate()):
            assert time.monotonic() < deadline
            time.sleep(0.01)
    assert child("print('after-eof')") == "after-eof\n"


def test_missing_executable_has_safe_error(tmp_path):
    with pytest.raises(ProbeError, match="executable_missing") as caught:
        run_readonly(tmp_path / "private-missing-program")
    assert "private" not in str(caught.value)


@pytest.mark.parametrize("failed_start", [1, 2])
def test_reader_start_failure_is_safe_and_cleans_direct_child(monkeypatch, failed_start):
    import threading

    original = threading.Thread.start
    starts = 0

    def start(thread):
        nonlocal starts
        starts += 1
        if starts == failed_start:
            raise RuntimeError("private resource error")
        return original(thread)

    monkeypatch.setattr(threading.Thread, "start", start)
    began = time.monotonic()
    with pytest.raises(ProbeError, match="command_reader_failed") as caught:
        child("import time; time.sleep(10)")
    assert "private" not in str(caught.value)
    assert time.monotonic() - began < 2


def test_exact_output_cap_is_allowed():
    assert len(child("import sys; sys.stdout.buffer.write(b'x' * 1048576)")) == 1048576


def test_valid_stdout_with_non_utf8_stderr_is_preserved():
    assert (
        child(
            "import sys; sys.stdout.buffer.write(b'15\\n'); "
            "sys.stderr.buffer.write(bytes.fromhex('d6d0cec4'))"
        )
        == "15\n"
    )


def test_simultaneous_capture_is_rejected_without_launch(tmp_path):
    import threading

    ready, release, forbidden = (tmp_path / name for name in ("ready", "release", "forbidden"))
    result = []
    source = (
        "from pathlib import Path; import time; "
        f"Path({str(ready)!r}).touch(); "
        "deadline=time.monotonic()+5\n"
        f"while not Path({str(release)!r}).exists() and time.monotonic()<deadline: "
        "time.sleep(.01)\n"
        "print('done')"
    )
    worker = threading.Thread(target=lambda: result.append(child(source)))
    worker.start()
    try:
        deadline = time.monotonic() + 3
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists()
        with pytest.raises(ProbeError, match="command_capture_busy"):
            child(f"from pathlib import Path; Path({str(forbidden)!r}).touch()")
        assert not forbidden.exists()
    finally:
        release.touch()
        worker.join(timeout=3)
        assert not worker.is_alive()
    assert result == ["done\n"]
    assert child("print('next')") == "next\n"


def test_unreaped_child_with_closed_pipes_blocks_new_capture(monkeypatch):
    from swu_happyrun.drivers import command

    original = command.subprocess.Popen
    processes = []

    def launch(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)

        def denied():
            raise PermissionError("private cleanup error")

        process.kill = denied
        return process

    monkeypatch.setattr(command.subprocess, "Popen", launch)
    try:
        with pytest.raises(ProbeError, match="command_cleanup_unconfirmed"):
            child("import os,time; os.close(1); os.close(2); time.sleep(2)", timeout=0.3)
        assert processes[0].poll() is None
        with pytest.raises(ProbeError, match="command_cleanup_unconfirmed"):
            child("print('must-not-launch')")
        assert len(processes) == 1
    finally:
        for process in processes:
            process.wait(timeout=5)  # Known isolated fixture exits naturally.
    assert child("print('recovered')") == "recovered\n"


def test_interrupted_cleanup_releases_lock_but_retains_live_child(monkeypatch):
    from swu_happyrun.drivers import command

    original = command.subprocess.Popen
    processes = []

    def launch(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)

        def interrupted():
            raise KeyboardInterrupt()

        process.kill = interrupted
        return process

    monkeypatch.setattr(command.subprocess, "Popen", launch)
    try:
        with pytest.raises(KeyboardInterrupt):
            child("import os,time; os.close(1); os.close(2); time.sleep(2)", timeout=0.3)
        with pytest.raises(ProbeError, match="command_cleanup_unconfirmed"):
            child("print('must-not-launch')")
        assert len(processes) == 1
    finally:
        for process in processes:
            process.wait(timeout=5)
    assert child("print('recovered')") == "recovered\n"
