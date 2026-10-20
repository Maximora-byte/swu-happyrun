"""Real process probes isolate deliberately unresolved thread-start ownership."""

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest


@pytest.mark.parametrize("reader_number", [1, 2])
@pytest.mark.parametrize(
    ("exception", "phase", "ready_delay"),
    [
        (exc, phase, 0)
        for exc in ("KeyboardInterrupt", "SystemExit")
        for phase in ("before_launch", "before_ident", "delayed_bootstrap")
    ]
    + [("RuntimeError", "before_launch", 0), ("KeyboardInterrupt", "before_ident", 2.1)],
)
def test_interrupted_reader_start_keeps_bounded_ownership(
    tmp_path, reader_number, exception, phase, ready_delay
):
    result = subprocess.run(
        [
            sys.executable,
            __file__,
            str(tmp_path),
            str(reader_number),
            exception,
            phase,
            str(ready_delay),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    assert observed["exception"] == ("ProbeError" if exception == "RuntimeError" else exception)
    if exception == "RuntimeError":
        assert observed["code"] == "command_cleanup_unconfirmed"
        assert observed["primary_code"] == "command_reader_failed"
    assert observed["elapsed"] < 1.25, observed
    assert observed["lock_released"]
    assert observed["child_reaped"]
    assert observed["pending_readers"] == reader_number
    assert observed["blocked_codes"] == ["command_cleanup_unconfirmed"] * 3
    assert observed["popen_count_before_recovery"] == 1
    assert observed["reader_attempts_before_recovery"] == reader_number
    assert observed["target_has_ident"] == (phase == "before_ident")
    assert not observed["main_closed_attempted_pipe"]
    if phase != "before_launch":
        assert observed["recovered"] == "recovered\n"


def _probe(directory, reader_number, exception_name, phase, ready_delay=0):
    # Import the exact source tree beside this test in the isolated interpreter.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    from swu_happyrun.drivers import command

    exception_type = {
        "KeyboardInterrupt": KeyboardInterrupt,
        "SystemExit": SystemExit,
        "RuntimeError": RuntimeError,
    }[exception_name]
    original_popen = subprocess.Popen
    start_name = (
        "_start_joinable_thread"
        if hasattr(threading, "_start_joinable_thread")
        else "_start_new_thread"
    )
    original_start = getattr(threading, start_name)
    original_bootstrap = threading.Thread._bootstrap_inner
    entered, release, reading = (threading.Event() for _ in range(3))
    attempts, processes, attempted_pipes, main_closed = [], [], [], []
    marker = Path(directory) / "descendant-ready"
    descendant_release = Path(directory) / "descendant-release"
    descendant_done = Path(directory) / "descendant-done"
    injected_at = None
    main_ident = threading.get_ident()

    class Pipe:
        def __init__(self, pipe):
            self.pipe = pipe

        def read1(self, size):
            reading.set()
            return self.pipe.read1(size)

        def close(self):
            if threading.get_ident() == main_ident:
                main_closed.append(self)
            self.pipe.close()

    def bootstrap(thread):
        if thread is attempts[-1] and len(attempts) == reader_number:
            entered.set()
            assert release.wait(5)
        original_bootstrap(thread)

    def start(function, *args, **kwargs):
        nonlocal injected_at
        thread = function.__self__
        attempts.append(thread)
        if injected_at is not None or len(attempts) != reader_number:
            return original_start(function, *args, **kwargs)
        attempted_pipes.append(getattr(processes[0], ("stdout", "stderr")[reader_number - 1]))
        if phase != "before_launch":
            original_start(function, *args, **kwargs)
            assert entered.wait(2)
            assert thread.ident is None
        injected_at = time.monotonic()
        raise exception_type("synthetic interruption")

    def popen(*args, **kwargs):
        # A failed prerequisite must never turn a later forbidden call into
        # the first injected startup, or silently launch an extra child.
        assert not processes, "unexpected Popen while reader ownership is pending"
        process = original_popen(*args, **kwargs)
        processes.append(process)
        # Fixture setup is separate from the production cleanup budget.
        deadline = time.monotonic() + 5
        while not marker.exists():
            assert time.monotonic() < deadline, "descendant readiness was not established"
            time.sleep(0.005)
        target = ("stdout", "stderr")[reader_number - 1]
        setattr(process, target, Pipe(getattr(process, target)))
        original_kill = process.kill

        def kill():
            if phase == "before_ident":
                release.set()
                assert reading.wait(2)
                # Allow BufferedReader.read1 to acquire its lock before cleanup.
                time.sleep(0.03)
            original_kill()

        process.kill = kill
        return process

    descendant = (
        "import time; from pathlib import Path; "
        f"time.sleep({ready_delay!r}); Path({str(marker)!r}).touch(); "
        "deadline=time.monotonic()+8\n"
        f"while not Path({str(descendant_release)!r}).exists():\n"
        "    if time.monotonic() >= deadline: raise SystemExit('fixture release missing')\n"
        "    time.sleep(.005)\n"
        f"Path({str(descendant_done)!r}).touch()"
    )
    source = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-c',{descendant!r}]); time.sleep(5)"
    )
    command.subprocess.Popen = popen
    setattr(threading, start_name, start)
    threading.Thread._bootstrap_inner = bootstrap
    observed = {}
    began = time.monotonic()
    try:
        try:
            command.run_readonly(Path(sys.executable), "-c", source, timeout=0.1)
        except BaseException as exc:
            expected_type = (
                command.ProbeError if exception_name == "RuntimeError" else exception_type
            )
            if not isinstance(exc, expected_type) or injected_at is None:
                raise AssertionError(
                    f"initial capture failed before injection: {type(exc).__name__}; "
                    f"reader_attempts={len(attempts)}; descendant_ready={marker.exists()}"
                ) from exc
            observed["exception"] = type(exc).__name__
            observed["code"] = getattr(exc, "code", None)
            observed["primary_code"] = getattr(exc, "primary_code", None)
        assert injected_at is not None, "initial capture never reached the injected interruption"
        observed["elapsed"] = time.monotonic() - injected_at
        observed["total_elapsed"] = time.monotonic() - began
        observed["lock_released"] = not command._CAPTURE_LOCK.locked()
        observed["child_reaped"] = processes[0].poll() is not None
        pending = command._PENDING_CAPTURE
        observed["pending_readers"] = None if pending is None else len(pending[1])
        assert observed["pending_readers"] == reader_number, (
            f"initial capture ownership lost: {observed}"
        )
        observed["blocked_codes"] = []
        for _ in range(3):
            try:
                command.run_readonly(Path(sys.executable), "-c", "print('forbidden')")
            except command.ProbeError as exc:
                observed["blocked_codes"].append(exc.code)
        observed["popen_count_before_recovery"] = len(processes)
        observed["reader_attempts_before_recovery"] = len(attempts)
        observed["target_has_ident"] = attempts[-1].ident is not None
        observed["main_closed_attempted_pipe"] = any(p in main_closed for p in attempted_pipes)
    finally:
        setattr(threading, start_name, original_start)
        threading.Thread._bootstrap_inner = original_bootstrap
        command.subprocess.Popen = original_popen
        release.set()
        descendant_release.touch()
        # Cleanup belongs only to this disposable fixture. Assertions above
        # already recorded whether production reaped its direct child.
        for process in processes:
            if process.poll() is None:
                original_popen.kill(process)
            process.wait(timeout=2)
    deadline = time.monotonic() + 5
    while not descendant_done.exists():
        assert time.monotonic() < deadline, "fixture descendant did not acknowledge release"
        time.sleep(0.005)
    if phase != "before_launch":
        deadline = time.monotonic() + 5
        for thread in attempts:
            while thread.ident is None:
                assert time.monotonic() < deadline
                time.sleep(0.005)
            thread.join(max(0, deadline - time.monotonic()))
            assert not thread.is_alive()
        observed["recovered"] = command.run_readonly(
            Path(sys.executable), "-c", "print('recovered')"
        )
    print(json.dumps(observed))


if __name__ == "__main__":
    _probe(sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4], float(sys.argv[5]))
