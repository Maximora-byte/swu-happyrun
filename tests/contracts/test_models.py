import json
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from swu_happyrun.core.models import (
    AgentHello,
    DeviceCapability,
    EvidenceRef,
    GeoPoint,
    JobEvent,
    JobSpec,
    JobView,
    LeaseCommand,
    LeaseGrant,
    RouteProfile,
    ScheduleSpec,
    SchoolProfile,
    VerificationResult,
)


def view_data(spec_data, **changes):
    data = dict(
        job_id="00000000-0000-4000-8000-000000000004",
        spec=JobSpec(**spec_data),
        state="queued",
        revision=0,
        desired_state="run",
        fence=0,
        agent_id=None,
        reason_code=None,
        resume_phase=None,
        recovery_action=None,
    )
    return data | changes


def test_rejects_naive_time(spec_data):
    spec_data["not_before"] = datetime(2026, 10, 18)
    with pytest.raises(ValidationError):
        JobSpec(**spec_data)


def test_rejects_unknown_fields(spec_data):
    with pytest.raises(ValidationError):
        JobSpec(**spec_data, token="not-a-real-token")


@pytest.mark.parametrize(
    "field,value",
    [
        ("protocol_version", True),
        ("protocol_version", "1"),
        ("mode", "unknown"),
        ("device_id", "mumu-0"),
        ("profile_revision", "latest"),
        ("deadline", 1792320000),
        ("not_before", "2026-10-18T08:00:00"),
    ],
)
def test_rejects_invalid_wire_values(spec_data, field, value):
    spec_data[field] = value
    with pytest.raises(ValidationError):
        JobSpec(**spec_data)


def test_window_is_ordered(spec_data):
    spec_data["deadline"] = spec_data["not_before"]
    with pytest.raises(ValidationError):
        JobSpec(**spec_data)


def test_json_and_python_roundtrip_normalize_utc(spec_data):
    spec_data["not_before"] = spec_data["not_before"].astimezone(timezone(timedelta(hours=8)))
    spec = JobSpec(**spec_data)
    wire = spec.model_dump_json()
    assert json.loads(wire)["not_before"] == "2026-10-18T08:00:00Z"
    assert JobSpec.model_validate_json(wire) == spec
    assert JobSpec.model_validate(json.loads(wire)) == spec


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -91, "30.0", True])
def test_coordinates_are_finite_strict_and_bounded(value):
    with pytest.raises(ValidationError):
        GeoPoint(latitude=value, longitude=100.0)


def test_route_requires_points_and_declared_crs(spec_data):
    data = dict(
        route_id=spec_data["route_id"],
        revision="a" * 64,
        input_crs="WGS84",
        points=[GeoPoint(latitude=0, longitude=0)],
        source_ref="manual:fixture",
    )
    with pytest.raises(ValidationError):
        RouteProfile(**data)
    data["points"] *= 2
    assert RouteProfile(**data).input_crs == "WGS84"
    del data["input_crs"]
    with pytest.raises(ValidationError):
        RouteProfile(**data)


def school_data(spec_data):
    return dict(
        profile_id=spec_data["profile_id"],
        revision="a" * 64,
        campus="fixture",
        app_package="example.fixture",
        app_version="1",
        confirmed=False,
        allowed_region=[
            GeoPoint(latitude=0, longitude=0),
            GeoPoint(latitude=0, longitude=1),
            GeoPoint(latitude=1, longitude=0),
        ],
        rules={"minimum_speed_mps": 1.0, "maximum_speed_mps": 3.0},
        checkpoint_source="manual_confirmed",
    )


@pytest.mark.parametrize(
    "rules",
    [
        {"unknown_rule": 1.0},
        {"minimum_distance_m": -1.0},
        {"minimum_speed_mps": 4.0, "maximum_speed_mps": 3.0},
        {"maximum_duration_seconds": float("inf")},
        {"minimum_distance_m": "1000"},
    ],
)
def test_school_rules_cannot_silently_be_accepted(spec_data, rules):
    with pytest.raises(ValidationError):
        SchoolProfile(**(school_data(spec_data) | {"rules": rules}))


def test_school_fixture_does_not_claim_verified(spec_data):
    assert SchoolProfile(**school_data(spec_data)).confirmed is False


def test_device_capabilities_are_explicit(spec_data):
    device = DeviceCapability(
        device_id=spec_data["device_id"],
        backend="mumu",
        app_version=None,
        capabilities=[],
        observed_at=datetime.now(UTC),
    )
    hello = AgentHello(protocol_version=1, agent_id=spec_data["profile_id"], devices=[device])
    assert hello.devices[0].capabilities == []
    with pytest.raises(ValidationError):
        DeviceCapability(**(device.model_dump() | {"capabilities": ["assume_supported"]}))


def evidence(spec_data, **changes):
    return EvidenceRef(
        **(
            dict(
                kind="app_record",
                sha256="d" * 64,
                captured_at=datetime.now(UTC),
                app_version="1",
                profile_revision="a" * 64,
                record_status="valid",
            )
            | changes
        )
    )


def test_simulation_cannot_succeed_or_carry_record(spec_data):
    with pytest.raises(ValidationError):
        JobView(**view_data(spec_data, state="succeeded"))
    with pytest.raises(ValidationError):
        JobEvent(
            event_id=spec_data["profile_id"],
            expected_revision=0,
            state="completed",
            reason_code=None,
            resume_phase=None,
            evidence=[evidence(spec_data)],
        )


def test_record_evidence_is_internally_consistent(spec_data):
    with pytest.raises(ValidationError):
        evidence(spec_data, kind="host_check")
    with pytest.raises(ValidationError):
        evidence(spec_data, app_version=None)
    with pytest.raises(ValidationError):
        VerificationResult(status="valid", evidence=[], reason_code=None)
    assert (
        VerificationResult(status="valid", evidence=[evidence(spec_data)], reason_code=None).status
        == "valid"
    )


def test_attention_requires_recovery_phase(spec_data):
    with pytest.raises(ValidationError):
        JobView(**view_data(spec_data, state="needs_attention"))
    assert JobView(**view_data(spec_data, state="needs_attention", resume_phase="running"))


def test_cancel_intent_cannot_resume_preflight(spec_data):
    with pytest.raises(ValidationError):
        JobView(
            **view_data(
                spec_data,
                state="needs_attention",
                resume_phase="preflight",
                desired_state="cancel",
                recovery_action="retry_preflight",
            )
        )


def test_lease_tokens_hidden_from_repr_and_fence_matches(spec_data):
    lease = LeaseCommand(lease_token="fixture-secret", fence=1)
    assert "fixture-secret" not in repr(lease)
    assert lease.model_dump()["lease_token"] == "fixture-secret"
    with pytest.raises(ValidationError):
        LeaseGrant(
            job=JobView(**view_data(spec_data, fence=1)),
            lease_token="fixture-secret",
            fence=2,
            expires_at=datetime.now(UTC),
        )
    with pytest.raises(ValidationError):
        LeaseCommand(lease_token="fixture-secret", fence=-1)


@pytest.mark.parametrize(
    "changes",
    [
        {"local_time": "24:00"},
        {"local_time": "8:00"},
        {"weekdays": [0]},
        {"weekdays": [True]},
        {"weekdays": [1, 1]},
        {"weekdays": []},
        {"timezone": "UTC"},
    ],
)
def test_schedules_reject_ambiguous_inputs(spec_data, changes):
    with pytest.raises(ValidationError):
        ScheduleSpec(
            **(
                dict(
                    schedule_id=spec_data["profile_id"],
                    job_template=JobSpec(**spec_data),
                    timezone="Asia/Shanghai",
                    local_time="08:00",
                    weekdays=[1],
                    enabled=True,
                )
                | changes
            )
        )


def test_public_job_never_includes_lease_token(spec_data):
    job = JobView(**view_data(spec_data))
    assert "lease_token" not in job.model_dump_json()
    with pytest.raises(ValidationError):
        JobView(**(view_data(spec_data) | {"lease_token": "fixture-secret"}))
