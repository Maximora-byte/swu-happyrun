"""Assertions on offline rejection; synthetic data never creates app_record."""

from dataclasses import replace
from datetime import timedelta

import pytest
from test_budao_states import NOW, adapter_case


def record_case(**changes):
    from swu_happyrun.drivers.budao.records import RecordObservation, SessionObservation

    session = SessionObservation(
        session_id="synthetic-session",
        started_at=NOW - timedelta(minutes=5),
        app_session_id="synthetic-app-session",
    )
    record = RecordObservation(
        session_id=session.session_id,
        app_session_id=session.app_session_id,
        started_at=session.started_at,
        captured_at=NOW,
        status="valid",
        record_namespace="synthetic",
        record_id="synthetic-record",
    )
    return replace(record, **changes), session


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"status": "pending"}, "record_pending"),
        ({"status": "invalid"}, "record_invalid"),
        ({"status": "success_toast"}, "record_status_unknown"),
        ({"session_id": "wrong"}, "record_session_mismatch"),
        ({"app_session_id": "wrong"}, "record_session_mismatch"),
        ({"app_session_id": None}, "record_session_mismatch"),
        ({"started_at": NOW - timedelta(days=1)}, "record_session_mismatch"),
        ({"captured_at": NOW - timedelta(seconds=30)}, "stale_record"),
        ({"captured_at": NOW + timedelta(seconds=1)}, "stale_record"),
        ({"record_namespace": None}, "record_identity_missing"),
        ({"record_id": None}, "record_identity_missing"),
        ({}, "needs_samples"),
    ],
)
def test_record_candidate_cannot_become_evidence(changes, reason):
    from swu_happyrun.drivers.budao.records import verify_result

    record, session = record_case(**changes)
    result = verify_result(record, session=session, now=NOW)
    assert result.status == "unknown"
    assert result.evidence == []
    assert result.reason_code == reason


def test_unbound_record_is_not_correlated_by_attaching_server_ids():
    from swu_happyrun.drivers.budao.records import verify_result

    record, _ = record_case()
    result = verify_result(record, session=None, now=NOW)
    assert result.status == "unknown"
    assert result.reason_code == "session_missing"
    assert result.evidence == []


def test_adapter_authorization_gate_applies_to_record_read():
    adapter, adb = adapter_case(authorized=False)
    record, session = record_case()
    result = adapter.read_result(record=record, session=session)
    assert result.reason_code == "authorization_required"
    assert result.status == "unknown"
    assert result.evidence == []
    assert adb.mock_calls == []


def test_synthetic_matching_record_still_does_not_grant_success():
    adapter, adb = adapter_case()
    record, session = record_case()
    result = adapter.read_result(record=record, session=session)
    assert result.status == "unknown"
    assert result.reason_code == "needs_samples"
    assert result.evidence == []
    assert adb.mock_calls == []
