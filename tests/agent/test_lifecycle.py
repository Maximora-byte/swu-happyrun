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
