"""Internal once-only experiment lifecycle; no production device adapter installed.

This composes the existing journal exclusion and controlled native write. It is
not a replacement replay state machine, a server driver, or an authority to run.
The trusted adapter must verify the original stopped-instance registry and exact
VM process identity. No caller JSON/boolean can install a production adapter.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid4

from swu_happyrun.agent.journal import RunJournal
from swu_happyrun.drivers.mumu.experiment_shutdown import observe_shutdown

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
    """Run an internal trusted adapter exactly once, retaining unresolved exclusion.

    adapter launch/prepare must be bounded and cancellation-aware. prepare verifies
    API35, approved same-source APKs, permissions (never auto-grants), fresh binding,
    boot and PID+creation time. capture_point uses capture_native_point above;
    observe_point uses OwnProbe location 1000ms/128 samples. Production discovery,
    process attribution and Windows ACL support are deliberately not available.
    """
    report = {
        "status": "needs_attention",
        "command_status": "not_attempted",
        "observation_status": "not_attempted",
        "sample_count": 0,
        "shutdown_status": "shutdown_not_attempted",
        "shutdown_reason": "not_started",
        "stop_status": "stop_unconfirmed",
        "replay_enabled": False,
        "primary_error": None,
        "evidence_error": None,
        "shutdown_error": None,
    }
    try:
        if (
            not isinstance(registration, Registration)
            or not isinstance(registration.stable_instance, str)
            or not registration.stable_instance
            or str(UUID(registration.device_id)) != registration.device_id
            or Path(registration.evidence_root).absolute() != store.root
            or not Path(registration.journal).is_absolute()
        ):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        report["primary_error"] = "registration_invalid"
        return report

    started = False
    storage_reliable = True
    session = str(uuid4())
    try:
        with RunJournal(registration.journal) as journal:
            # Crucially before preflight/launch, and held through all cleanup.
            with journal.device_lock(registration.device_id):
                if adapter.check_stopped_registration(registration) is not True:
                    report["primary_error"] = "registration_invalid"
                    return report
                journal.reserve_replay(registration.device_id, session, generation=1)
                journal.record_intent(session, 1, "start")
                store.claim_intent("launch")
                try:
                    started = True  # An exception may mean launch already happened.
                    adapter.launch()
                    adapter.prepare()
                    try:
                        store.claim_intent("location")
                    except BaseException:
                        storage_reliable = False
                        report["evidence_error"] = "location_intent_failed"
                        raise
                    capture = adapter.capture_point()
                    report["command_status"] = (
                        capture.status if capture.status in _WRITE_CODES else "write_capture_failed"
                    )
                    try:
                        store.put_once("command.stdout.bin", capture.stdout)
                        store.put_once("command.stderr.bin", capture.stderr)
                        store.put_once("command.json", _json(capture.metadata))
                    except BaseException:
                        storage_reliable = False
                        report["evidence_error"] = "private_evidence_failed"
                        raise
                    if capture.status == "write_ack_unconfirmed" and capture.complete is True:
                        observation = adapter.observe_point(duration_ms=1000, max_samples=128)
                        try:
                            store.put_once("observation.json", _json(observation))
                        except BaseException:
                            storage_reliable = False
                            report["evidence_error"] = "private_evidence_failed"
                            raise
                        count = observation.get("sample_count")
                        if type(count) is int and 0 <= count <= 128:
                            report["sample_count"] = count
                            report["observation_status"] = (
                                "samples_observed" if count else "no_samples"
                            )
                        else:
                            report["observation_status"] = "observation_invalid"
                except BaseException as error:
                    report["primary_error"] = _error(error)
                finally:
                    if started:
                        _close_experiment(adapter, store, clock, report, storage_reliable)
                    # Never record a successful native stop or clear reservation.
                    try:
                        journal.record_result(session, 1, "start", "uncertain")
                    except BaseException:
                        report["journal_error"] = "journal_result_failed"
    except BaseException as error:
        report["primary_error"] = report["primary_error"] or _error(error)
    return report


def _close_experiment(adapter, store, clock, report, storage_reliable):
    from dataclasses import asdict

    began = clock.monotonic()
    deadline = began + 45.0
    report["shutdown_started_monotonic"] = began

    def remaining(limit):
        value = min(limit, deadline - clock.monotonic())
        if value <= 0:
            raise TimeoutError
        return value

    try:
        adapter.seal()  # Permanent producer closure before any shutdown decision.
        drained = adapter.drain(timeout=remaining(0.5), deadline=deadline) is True
        report["capture_cleanup_confirmed"] = drained
        if not storage_reliable:
            report["shutdown_reason"] = "storage_unreliable"
            return
        if not drained:
            report["shutdown_reason"] = "capture_cleanup_unconfirmed"
            return
        if adapter.verify_shutdown_identity(timeout=remaining(1), deadline=deadline) is not True:
            report["shutdown_reason"] = "target_identity_unverified"
            return
        try:
            store.claim_intent("shutdown")
        except BaseException as error:
            report["shutdown_error"] = _error(error)
            report["shutdown_reason"] = "shutdown_intent_failed"
            return
        remaining(5)
        report["shutdown_status"] = "shutdown_unknown"
        report["shutdown_reason"] = "shutdown_attempted"
        adapter.shutdown(timeout=remaining(5), deadline=deadline)
        observation = observe_shutdown(adapter, clock=clock, deadline=deadline)
        # Persistence time is part of the SAME absolute 45 second budget.
        try:
            store.put_once("shutdown.json", _json(asdict(observation)))
        except BaseException:
            report["evidence_error"] = "private_evidence_failed"
            report["shutdown_reason"] = "storage_unreliable"
            return
        if clock.monotonic() <= deadline:
            report["shutdown_status"] = observation.status
        else:
            report["shutdown_reason"] = "shutdown_budget_expired"
    except BaseException as error:
        report["shutdown_error"] = _error(error)
        report["shutdown_reason"] = "shutdown_interrupted_or_failed"
    finally:
        report["shutdown_finished_monotonic"] = clock.monotonic()
