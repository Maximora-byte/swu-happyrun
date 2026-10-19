import signal

import pytest

from swu_happyrun.agent.client import ControlError
from swu_happyrun.agent.lifecycle import Shutdown, ShutdownRequested, idle_liveness


def test_retries_have_finite_exponential_backoff():
    shutdown = Shutdown()
    waits = []
    shutdown.wait = waits.append
    calls = []

    def failed():
        calls.append(1)
        raise ControlError("network failed", retryable=True)

    with pytest.raises(ControlError):
        idle_liveness(failed, shutdown)
    assert len(calls) == 5
    assert waits == [1, 2, 4, 8]


def test_authentication_failure_is_not_retried():
    calls = []

    def rejected():
        calls.append(1)
        raise ControlError("HTTP 401")

    with pytest.raises(ControlError):
        idle_liveness(rejected, Shutdown())
    assert len(calls) == 1


def test_handlers_are_restored_and_backoff_is_interruptible():
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    shutdown = Shutdown()
    with shutdown.signals():
        shutdown.request(signal.SIGTERM)
        with pytest.raises(ShutdownRequested):
            shutdown.wait(100)
    assert {sig: signal.getsignal(sig) for sig in previous} == previous


def test_signal_handler_does_not_reenter_event_condition_in_real_process():
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    code = """
import signal
import threading
from swu_happyrun.agent.lifecycle import Shutdown, ShutdownRequested
shutdown = Shutdown()
# Retain the original synchronization primitive when testing the old version;
# the corrected version has no Event and must not acquire even an unrelated lock.
event = getattr(shutdown, "event", threading.Event())
previous = signal.getsignal(signal.SIGTERM)
with shutdown.signals():
    with event._cond:
        signal.raise_signal(signal.SIGINT)
        signal.raise_signal(signal.SIGTERM)
    try:
        shutdown.check()
    except ShutdownRequested:
        print("interrupted", flush=True)
    else:
        raise AssertionError("signal was ignored")
assert signal.getsignal(signal.SIGTERM) is previous
"""
    process = subprocess.Popen(
        [sys.executable, "-c", code],
        env={**os.environ, "PYTHONPATH": str(root / "src")},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        try:
            stdout, stderr = process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            pytest.fail("Signal handler deadlocked while the Event condition was held")
        assert process.returncode == 0, stderr
        assert stdout.strip() == "interrupted"
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=3)


def test_wait_uses_monotonic_deadline_without_early_return(monkeypatch):
    import swu_happyrun.agent.lifecycle as lifecycle

    now = [0.0]
    sleeps = []
    monkeypatch.setattr(lifecycle.time, "monotonic", lambda: now[0])

    def sleep(seconds):
        assert 0 < seconds <= 0.05
        sleeps.append(seconds)
        now[0] += seconds / 2 if len(sleeps) == 1 else seconds

    monkeypatch.setattr(lifecycle.time, "sleep", sleep)
    Shutdown().wait(0.12)
    assert now[0] >= 0.12
    assert len(sleeps) < 10


def test_negative_wait_returns_without_sleep(monkeypatch):
    import swu_happyrun.agent.lifecycle as lifecycle

    def forbidden(seconds):
        raise AssertionError("negative wait slept")

    monkeypatch.setattr(lifecycle.time, "sleep", forbidden)
    Shutdown().wait(-1)


@pytest.mark.parametrize("seconds", [float("inf"), float("-inf"), float("nan")])
def test_nonfinite_wait_is_rejected(seconds):
    with pytest.raises(ValueError):
        Shutdown().wait(seconds)
