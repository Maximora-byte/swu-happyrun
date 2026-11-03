"""Offline record rejection gates; no canonical identity algorithm is guessed.

A caller-supplied namespace, app-session label, timestamp or screenshot digest
cannot establish provenance. Even a fully matching candidate is unknown until
actual record identity and session correlation rules have been reviewed.
"""

from dataclasses import dataclass
from datetime import datetime

from swu_happyrun.core.models import VerificationResult
from swu_happyrun.drivers.budao.selectors import fresh


@dataclass(frozen=True)
class SessionObservation:
    session_id: str
    app_session_id: str | None
    started_at: datetime


@dataclass(frozen=True)
class RecordObservation:
    session_id: str | None
    app_session_id: str | None
    started_at: datetime
    captured_at: datetime
    status: str
    record_namespace: str | None
    record_id: str | None


def _record_blocker(
    record: RecordObservation | None, session: SessionObservation | None, now: datetime
) -> str:
    if session is None or not session.session_id or not session.app_session_id:
        return "session_missing"
    if record is None:
        return "record_missing"
    if not fresh(record.captured_at, now):
        return "stale_record"
    if (
        record.session_id != session.session_id
        or record.app_session_id != session.app_session_id
        or record.started_at != session.started_at
        or not isinstance(session.started_at, datetime)
        or session.started_at.utcoffset() is None
        or session.started_at > record.captured_at
    ):
        return "record_session_mismatch"
    if not record.record_namespace or not record.record_id:
        return "record_identity_missing"
    if record.status == "pending":
        return "record_pending"
    if record.status == "invalid":
        return "record_invalid"
    if record.status != "valid":
        return "record_status_unknown"
    return "needs_samples"


def verify_result(
    record: RecordObservation | None, *, session: SessionObservation | None, now: datetime
) -> VerificationResult:
    """Reject-only offline review, never emits app_record or claims acceptance.

    Authorization, exact version and fresh page checks belong to the adapter.
    This helper cannot grant success even if invoked without those gates.
    """
    return VerificationResult(
        status="unknown", evidence=[], reason_code=_record_blocker(record, session, now)
    )
