"""Internal once-only experiment lifecycle; no production device adapter installed.

This composes the existing journal exclusion and controlled native write. It is
not a replacement replay state machine, a server driver, or an authority to run.
The trusted adapter must verify the original stopped-instance registry and exact
VM process identity. No caller JSON/boolean can install a production adapter.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

_WRITE_CODES = frozenset(
    {
        "write_ack_unconfirmed",
        "write_failed_unconfirmed",
        "write_encoding_invalid",
        "write_timeout",
        "write_cancelled_unconfirmed",
        "write_output_limit",
        "write_cleanup_unconfirmed",
        "write_capture_failed",
        "write_busy",
        "write_unavailable",
        "executable_missing",
        "experiment_interrupted",
    }
)


@dataclass(frozen=True, repr=False)
class Registration:
    """Private, stable pre-boot registry mapping, not an execution approval."""

    stable_instance: str
    device_id: str
    journal: Path
    evidence_root: Path


@dataclass(frozen=True)
class PointCapture:
    status: str
    complete: bool
    stdout: bytes = field(repr=False)
    stderr: bytes = field(repr=False)
    metadata: dict = field(repr=False)


def _error(error):
    return (
        "experiment_interrupted"
        if isinstance(error, (KeyboardInterrupt, SystemExit))
        else ("experiment_failed")
    )


def _json(value):
    return json.dumps(value, separators=(",", ":"), allow_nan=False).encode("utf-8")


def capture_native_point(native, evidence, point, *, deadline):
    """Adapt existing MuMuNative684; its last_delivery/UTF-8 gates stay unchanged.

    Construct native with this exact evidence collector before calling. A native
    return is not treated as success: the only observation gate remains the exact
    write_ack_unconfirmed exception plus confirmed complete capture/delivery.
    """
    status = "write_capture_failed"
    try:
        native.write_location(point, deadline=deadline)
    except BaseException as error:
        candidate = getattr(error, "reason_code", None)
        status = candidate if candidate in _WRITE_CODES else _error(error)
    snapshot = evidence.snapshot
    if snapshot is None:
        return PointCapture(status, False, b"", b"", {"capture_missing": True})
    delivery = native.last_delivery
    complete = (
        snapshot.output_complete is True
        and snapshot.cleanup_code == "confirmed"
        and not snapshot.truncated
        and delivery is not None
        and delivery.command_completed is True
    )
    metadata = {
        key: getattr(snapshot, key)
        for key in (
            "returncode",
            "primary_code",
            "final_code",
            "cleanup_code",
            "started_monotonic",
            "finished_monotonic",
            "output_complete",
            "truncated",
            "process_started",
        )
    }
    return PointCapture(status, complete, snapshot.stdout, snapshot.stderr, metadata)


def run_experiment(registration, *, adapter, store, clock):
    """Production admission precedes any registration, store or adapter access."""
    from swu_happyrun.drivers.mumu.enrollment import require_native_enrollment

    require_native_enrollment(registration)
