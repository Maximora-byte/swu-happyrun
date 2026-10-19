"""Cooperative process shutdown and finite retries for idle liveness only."""

import math
import signal
import time
from contextlib import contextmanager

from swu_happyrun.agent.client import ControlError


class ShutdownRequested(RuntimeError):
    pass


class Shutdown:
    def __init__(self):
        self.signum = None

    def request(self, signum, frame=None):
        # Python handlers may run while any non-reentrant lock is held.
        # A plain assignment is deliberate: no Event/Condition, I/O or exceptions.
        self.signum = signum

    def check(self):
        if self.signum is not None:
            raise ShutdownRequested()

    def wait(self, seconds):
        if not math.isfinite(seconds):
            raise ValueError("wait duration must be finite")
        deadline = time.monotonic() + max(0, seconds)
        while True:
            self.check()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            # Bounded polling avoids locks in the signal handler while keeping
            # idle/backoff interruption prompt even if sleep is restarted by Python.
            time.sleep(min(0.05, remaining))

    @contextmanager
    def signals(self):
        previous = {}
        try:
            for signum in (signal.SIGINT, signal.SIGTERM):
                previous[signum] = signal.signal(signum, self.request)
            yield self
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)


def idle_liveness(call, shutdown, *, attempts=5):
    """Retry only hello/idle heartbeat, never claims, renewals or device actions."""
    for attempt in range(attempts):
        shutdown.check()
        try:
            result = call()
            shutdown.check()
            return result
        except ControlError as exc:
            if not exc.retryable or attempt == attempts - 1:
                raise
            shutdown.wait(min(2**attempt, 8))
