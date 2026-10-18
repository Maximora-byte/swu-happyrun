import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from swu_happyrun.core import models as m

ID = "00000000-0000-4000-8000-000000000004"
SESSION = "00000000-0000-4000-8000-000000000005"


def job(spec_data, **changes):
    return m.JobSpec(**(spec_data | {"expected_app_version": None} | changes))


def view(spec_data, **changes):
    return m.JobView(
        **(
            dict(
                job_id=ID,
                spec=job(spec_data),
                state="queued",
                revision=0,
                desired_state="run",
                fence=0,
                agent_id=None,
                reason_code=None,
                resume_phase=None,
                recovery_action=None,
                run_session_id=None,
            )
            | changes
        )
    )


def record(**changes):
    return m.EvidenceRef(
        **(
            dict(
                kind="app_record",
                sha256="a" * 64,
                captured_at=datetime.now(UTC),
                app_version="1",
                profile_revision="b" * 64,
                record_status="valid",
                job_id=ID,
                run_session_id=SESSION,
                record_namespace="fixture.adapter",
                record_id="c" * 64,
            )
            | changes
        )
    )


def test_app_version_is_required_even_when_null(spec_data):
    data = dict(spec_data)
    data.pop("expected_app_version", None)
    with pytest.raises(ValidationError):
        m.JobSpec(**data)


@pytest.mark.parametrize(
    "mode,version,valid",
    [
        ("simulation", None, True),
        ("simulation", "1", False),
        ("device", None, False),
        ("device", "", False),
        ("device", "   ", False),
        ("device", "\t\n", False),
        ("device", "1", True),
    ],
)
def test_mode_app_version(spec_data, mode, version, valid):
    if valid:
        assert job(spec_data, mode=mode, expected_app_version=version)
    else:
        with pytest.raises(ValidationError):
            job(spec_data, mode=mode, expected_app_version=version)


def test_preclaim_and_requeued_sessions(spec_data):
    assert view(spec_data).run_session_id is None
    assert view(spec_data, fence=2, agent_id=ID, run_session_id=SESSION).state == "queued"
    with pytest.raises(ValidationError):
        view(spec_data, fence=2, agent_id=ID)
    with pytest.raises(ValidationError):
        view(spec_data, agent_id=ID)
    with pytest.raises(ValidationError):
        view(spec_data, run_session_id=SESSION)


@pytest.mark.parametrize("field", ["job_id", "run_session_id", "record_namespace", "record_id"])
def test_app_record_requires_all_bindings(field):
    with pytest.raises(ValidationError):
        record(**{field: None})
    data = record().model_dump()
    del data[field]
    with pytest.raises(ValidationError):
        m.EvidenceRef(**data)


@pytest.mark.parametrize("kind", ["host_check", "device_probe"])
def test_nonrecord_rejects_record_bindings(kind):
    with pytest.raises(ValidationError):
        record(kind=kind, record_status=None)
    assert record(
        kind=kind,
        record_status=None,
        job_id=None,
        run_session_id=None,
        record_namespace=None,
        record_id=None,
    )


@pytest.mark.parametrize("namespace", ["", "https://example.com", "Contains spaces", "A", "a" * 65])
def test_record_namespace_is_bounded(namespace):
    with pytest.raises(ValidationError):
        record(record_namespace=namespace)


def test_record_id_is_digest():
    with pytest.raises(ValidationError):
        record(record_id="private-account-id")


def test_probe_id_required(spec_data):
    data = dict(
        device_id=spec_data["device_id"],
        backend="fake",
        app_version=None,
        capabilities=[],
        observed_at=datetime.now(UTC),
    )
    with pytest.raises(ValidationError):
        m.DeviceCapability(**data)
    assert m.DeviceCapability(**data, probe_id=ID).probe_id == ID


def test_request_models_compose_existing_protocol():
    event = m.JobEvent(
        event_id=ID,
        expected_revision=1,
        state="verifying",
        reason_code=None,
        evidence=[],
        resume_phase=None,
    )
    lease = m.LeaseCommand(lease_token="synthetic-only", fence=1)
    request = m.EventRequest(lease=lease, event=event)
    assert isinstance(request.lease, m.LeaseCommand)
    assert isinstance(request.event, m.JobEvent)
    assert m.EventRequest.model_validate_json(request.model_dump_json()) == request
    assert m.ClaimRequest(device_id=ID)
    assert m.ResumeRequest(expected_revision=1, action="verify_only")
    assert m.StopAckRequest(lease=lease, event_id=ID, expected_revision=1)
    assert m.DeviceRegistration(device_id=ID, agent_id=SESSION)
    assert "synthetic-only" not in repr(request)


def test_session_field_required_and_old_queued_session_retained(spec_data):
    data = view(spec_data).model_dump()
    del data["run_session_id"]
    with pytest.raises(ValidationError):
        m.JobView(**data)
    assert view(spec_data, fence=4, run_session_id=SESSION).run_session_id == SESSION


def test_conflicting_record_statuses_rejected():
    with pytest.raises(ValidationError):
        m.JobEvent(
            event_id=ID,
            expected_revision=1,
            state="verifying",
            reason_code=None,
            resume_phase=None,
            evidence=[record(), record(record_status="invalid")],
        )


@pytest.mark.parametrize(
    "name,data",
    [
        ("ClaimRequest", {"device_id": ID}),
        ("ResumeRequest", {"expected_revision": 1, "action": "verify_only"}),
        ("DeviceRegistration", {"device_id": ID, "agent_id": SESSION}),
    ],
)
def test_new_requests_reject_unknown_fields(name, data):
    with pytest.raises(ValidationError):
        getattr(m, name)(**data, unexpected=True)


def test_binding_schema_is_exported():
    schema = json.loads(
        (Path(__file__).parents[2] / "contracts/protocol-v1.schema.json").read_text()
    )
    for model in (
        "ClaimRequest",
        "ResumeRequest",
        "EventRequest",
        "StopAckRequest",
        "DeviceRegistration",
    ):
        assert model in schema["$defs"]
    assert "run_session_id" in schema["$defs"]["JobView"]["required"]
