"""Test-only lifecycle harness. No product entry imports this module."""

from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

from swu_happyrun.agent.journal import RunJournal
from swu_happyrun.drivers.command import ProbeError
from swu_happyrun.drivers.mumu.evidence_experiment import (
    _WRITE_CODES,
    Registration,
    _error,
    _json,
)
from swu_happyrun.drivers.mumu.evidence_experiment import PointCapture as PointCapture
from swu_happyrun.drivers.mumu.evidence_experiment import (
    capture_native_point as capture_native_point,
)
from swu_happyrun.drivers.mumu.experiment_shutdown import observe_shutdown
from swu_happyrun.drivers.mumu.point_evidence import PointObservation


@contextmanager
def _locked_journal(registration, *, existing_only=False):
    journal = RunJournal(registration.journal, existing_only=existing_only)
    close_attempted = False
    try:
        with journal.device_lock(registration.device_id):
            try:
                yield journal
            finally:
                # Close SQLite while the original exclusion is still held.
                close_attempted = True
                journal.close()
    finally:
        if not close_attempted:  # Lock acquisition itself may have failed.
            journal.close()


@contextmanager
def _original_journal(registration):
    # Internal synthetic adapters retain their existing interface; a real loader
    # snapshot uses only the original files and holds path guards through cleanup.
    from swu_happyrun.drivers.mumu.original_registration import (
        OriginalRegistration,
        original_paths,
    )

    if isinstance(registration, OriginalRegistration):
        with original_paths(registration):
            with _locked_journal(registration, existing_only=True) as journal:
                yield journal
    else:
        with _locked_journal(registration) as journal:
            yield journal


def _recheck_original(registration):
    from swu_happyrun.drivers.mumu.original_registration import OriginalRegistration

    if isinstance(registration, OriginalRegistration):
        registration.revalidate()


class _ProducerApprovalClosed(RuntimeError):
    """Synthetic producer rejection, never a production permission decision."""


class _SyntheticProducerGate:
    def __init__(self, current_approval):
        self._current_approval = current_approval
        self._closed = False

    def close(self):
        self._closed = True

    def require(self):
        if self._closed:
            raise _ProducerApprovalClosed
        try:
            approved = self._current_approval is None or self._current_approval() is True
        except BaseException:
            self.close()
            raise
        if not approved:
            self.close()
            raise _ProducerApprovalClosed


class _ShutdownBudgetExpired(TimeoutError):
    """The one cleanup deadline has no remaining budget."""


def run_synthetic_experiment(registration, *, adapter, store, clock, current_approval=None):
    """Run an internal trusted adapter exactly once, retaining unresolved exclusion.

    adapter launch/prepare must be bounded and cancellation-aware. prepare verifies
    API35, approved same-source APKs, permissions (never auto-grants), fresh binding,
    boot and PID+creation time. capture_point uses capture_native_point above;
    observe_point uses OwnProbe location 1000ms/128 samples. Production discovery,
    and process attribution are not installed. Windows ACL support is implemented
    but awaits independent native Windows validation.

    current_approval is an optional TEST-ONLY, no-argument callback returning
    exactly True. Rejection/error irreversibly closes this invocation's producer
    gate; the retained reservation prevents a fresh invocation from restarting.
    It is checked immediately before each producer boundary, never for cleanup.
    It cannot preempt an in-flight adapter, observe a transient approval change
    between checks, or establish production approval/cleanup authority.
    """
    report = {
        "status": "needs_attention",
        "command_status": "not_attempted",
        "observation_status": "not_attempted",
        "sample_count": 0,
        "shutdown_status": "shutdown_not_attempted",
        "shutdown_attempted": False,
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
    producer_gate = _SyntheticProducerGate(current_approval)
    try:
        # Held before preflight/launch through cleanup, result and journal close.
        with _original_journal(registration) as journal:
            try:
                _recheck_original(registration)
                if adapter.check_stopped_registration(registration) is not True:
                    report["primary_error"] = "registration_invalid"
                    return report
                journal.reserve_replay(registration.device_id, session, generation=1)
                journal.record_intent(session, 1, "start")
                store.claim_intent("launch")
                try:
                    _recheck_original(registration)
                    producer_gate.require()
                    started = True  # An exception may mean launch already happened.
                    adapter.launch()
                    producer_gate.require()
                    adapter.prepare()
                    try:
                        store.claim_intent("location")
                    except BaseException:
                        storage_reliable = False
                        report["evidence_error"] = "location_intent_failed"
                        raise
                    producer_gate.require()
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
                        producer_gate.require()
                        report["observation_status"] = "observation_failed"
                        try:
                            observation = adapter.observe_point(duration_ms=1000, max_samples=128)
                        except ProbeError as error:
                            if error.code in {
                                "no_samples",
                                "permission_required",
                                "private_cleanup_unconfirmed",
                                "observation_cleanup_unconfirmed",
                                "observation_correlation_invalid",
                                "observation_payload_invalid",
                                "observation_window_invalid",
                                "observation_sample_invalid",
                                "observation_recovery_required",
                                "location_provider_unsupported",
                                "binding_changed",
                            }:
                                report["observation_status"] = error.code
                            raise
                        if not isinstance(observation, PointObservation):
                            report["observation_status"] = "observation_invalid"
                            raise ValueError("observation_invalid")
                        try:
                            store.put_once("observation.json", _json(observation.private_dict()))
                        except BaseException:
                            storage_reliable = False
                            report["evidence_error"] = "private_evidence_failed"
                            raise
                        report["sample_count"] = observation.sample_count
                        report["observation_status"] = observation.observation_status
                except BaseException as error:
                    report["primary_error"] = (
                        "producer_approval_closed"
                        if isinstance(error, _ProducerApprovalClosed)
                        else _error(error)
                    )
                finally:
                    producer_gate.close()
                    if started:
                        _close_experiment(adapter, store, clock, report, storage_reliable)
                    # Never record a successful native stop or clear reservation.
                    try:
                        journal.record_result(session, 1, "start", "uncertain")
                    except BaseException:
                        report["journal_error"] = "journal_result_failed"
            finally:
                producer_gate.close()
    except BaseException as error:
        report["primary_error"] = report["primary_error"] or _error(error)
    finally:
        if "shutdown_started_monotonic" in report:
            # Final journal persistence/close also consumes the original budget.
            _record_shutdown_finished(
                clock, report, deadline=report["shutdown_started_monotonic"] + 45.0
            )
    return report


def _record_shutdown_finished(clock, report, *, deadline):
    report["shutdown_finished_monotonic"] = clock.monotonic()
    if report["shutdown_finished_monotonic"] > deadline:
        report["shutdown_reason"] = "shutdown_budget_expired"
        if report["shutdown_attempted"]:
            report["shutdown_status"] = "shutdown_unknown"


def _close_experiment(adapter, store, clock, report, storage_reliable):
    """Synthetic bounded cleanup, independent of the current producer approval.

    All timed adapters receive one absolute deadline. seal and storage have no
    timeout API: elapsed time is charged and overruns become unknown/unconfirmed,
    but Python cannot forcibly interrupt these operations or guarantee hard
    real-time completion. No production cleanup capability is installed here.
    """
    from dataclasses import asdict

    began = clock.monotonic()
    deadline = began + 45.0
    report["shutdown_started_monotonic"] = began

    def remaining(limit):
        value = min(limit, deadline - clock.monotonic())
        if value <= 0:
            raise _ShutdownBudgetExpired
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
        remaining(5)
        try:
            store.claim_intent("shutdown")
        except BaseException as error:
            report["shutdown_error"] = _error(error)
            report["shutdown_reason"] = "shutdown_intent_failed"
            return
        shutdown_timeout = remaining(5)
        report["shutdown_attempted"] = True
        report["shutdown_status"] = "shutdown_unknown"
        report["shutdown_reason"] = "shutdown_attempted"
        adapter.shutdown(timeout=shutdown_timeout, deadline=deadline)
        remaining(1)
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
    except _ShutdownBudgetExpired:
        report["shutdown_reason"] = "shutdown_budget_expired"
    except BaseException as error:
        report["shutdown_error"] = _error(error)
        report["shutdown_reason"] = "shutdown_interrupted_or_failed"
    finally:
        _record_shutdown_finished(clock, report, deadline=deadline)
