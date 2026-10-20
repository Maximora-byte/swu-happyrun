"""One-shot reporter comparison, not a product fix or native acceptance test."""

import argparse
import faulthandler
import json
import os
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime

import pytest

NODE = (
    "tests/agent/test_enrollment_review_pin.py::"
    "test_journal_intent_and_result_changes_preserve_pin_not_ready"
)
OBSERVATION_SECONDS = 60


class PythonWatchdog(threading.Timer):
    """Acquire the GIL as a Python thread before the C stack-dump call.

    Unlike dump_traceback_later's C watchdog, dump_traceback is invoked through
    Python with the GIL held on the targeted regular CPython 3.11 build. This
    cannot observe a thread that indefinitely monopolizes the GIL; the unchanged
    finite outer CI job limit remains necessary. No locals or source are dumped.
    """

    def __init__(self, output, *, seconds=OBSERVATION_SECONDS):
        super().__init__(seconds, lambda: faulthandler.dump_traceback(file=output))
        self.name = "traceback-probe"
        self.daemon = True


def emit(event, **fields):
    print(json.dumps({"event": event, "utc": datetime.now(UTC).isoformat(), **fields}), flush=True)


def pytest_arguments(mode):
    timeout = OBSERVATION_SECONDS if mode == "async" else 0
    return ["-vv", "-o", f"faulthandler_timeout={timeout}", "--durations=1", NODE]


class TimingPlugin:
    def __init__(self, mode):
        self.mode = mode

    @pytest.hookimpl(wrapper=True, trylast=True)
    def pytest_runtest_protocol(self, item):
        started = time.monotonic()
        emit("node_start", node=item.nodeid, mode=self.mode, threshold_seconds=60)
        watchdog = None
        output = None
        if self.mode == "python-thread":
            # Own the descriptor through join; pytest capture must not close it.
            output = os.fdopen(os.dup(sys.__stderr__.fileno()), "wb", buffering=0)
            watchdog = PythonWatchdog(output)
            watchdog.start()
        try:
            return (yield)
        finally:
            if watchdog is not None:
                watchdog.cancel()
                watchdog.join()
                output.close()
            emit("node_finish", mode=self.mode, elapsed_seconds=time.monotonic() - started)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("async", "python-thread"))
    args = parser.parse_args()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    emit("process_start", head=head, python=sys.version, mode=args.mode)
    started = time.monotonic()
    result = pytest.main(pytest_arguments(args.mode), plugins=[TimingPlugin(args.mode)])
    emit("process_finish", exit_code=int(result), elapsed_seconds=time.monotonic() - started)
    return int(result)


if __name__ == "__main__":
    raise SystemExit(main())
