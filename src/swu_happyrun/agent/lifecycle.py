"""Cooperative process shutdown and finite retries for idle liveness only."""

import signal
import threading
from contextlib import contextmanager

from swu_happyrun.agent.client import ControlError


class ShutdownRequested(RuntimeError):
    pass


class Shutdown:
    def __init__(self):
        self.event = threading.Event()
        self.signum = None

    def request(self, signum, frame=None):
        # Never interrupt an atomic journal write or perform I/O in a handler.
        self.signum = signum
        self.event.set()

    def check(self):
        if self.event.is_set():
            raise ShutdownRequested()

    def wait(self, seconds):
        self.event.wait(seconds)
        self.check()

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
