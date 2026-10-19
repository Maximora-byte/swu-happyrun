from uuid import uuid4

import pytest

from .conftest import ADMIN, AGENT, AGENT_A, create_job
from .test_leases import advance, claim, event, register


def device_job(client, spec, *, key="device"):
    register(client, spec)
    spec = spec | {"mode": "device", "expected_app_version": "fixture-v1"}
    report = dict(
        protocol_version=1,
        agent_id=AGENT_A,
        devices=[
            dict(
                device_id=spec["device_id"],
                backend="mumu",
                app_version="fixture-v1",
                capabilities=[
                    "location_read",
                    "location_write",
                    "sensor_probe",
                    "app_ui",
                    "record_read",
                ],
                observed_at="2026-10-19T00:00:00Z",
                probe_id=str(uuid4()),
            )
        ],
    )
    assert client.post("/api/v1/agents/hello", headers=AGENT, json=report).status_code == 200
    assert create_job(client, spec, key=key).status_code == 201
    response = claim(client, spec)
    assert response.status_code == 200, response.text
    grant = response.json()
    return advance(client, grant, ["preflight", "ready", "running", "finishing", "verifying"])


def record(grant, **changes):
    return (
        dict(
            kind="app_record",
            sha256="c" * 64,
            captured_at="2026-10-19T00:00:00Z",
            app_version="fixture-v1",
            profile_revision=grant["job"]["spec"]["profile_revision"],
            record_status="valid",
            job_id=grant["job"]["job_id"],
            run_session_id=grant["job"]["run_session_id"],
            record_namespace="fixture",
            record_id="d" * 64,
        )
        | changes
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("job_id", str(uuid4())),
        ("run_session_id", str(uuid4())),
        ("profile_revision", "f" * 64),
        ("app_version", "wrong-version"),
    ],
)
def test_wrong_record_binding_never_succeeds(client, spec, field, value):
    grant = device_job(client, spec)
    response = event(client, grant, "succeeded", evidence=[record(grant, **{field: value})])
    assert response.status_code == 409
    assert (
        client.get("/api/v1/jobs/" + grant["job"]["job_id"], headers=ADMIN).json()["state"]
        == "verifying"
    )


@pytest.mark.parametrize("same_identity", [True, False])
def test_record_or_digest_cannot_cross_jobs(client, spec, same_identity):
    first = device_job(client, spec)
    assert event(client, first, "succeeded", evidence=[record(first)]).status_code == 200
    second = device_job(client, spec, key="second")
    evidence = (
        record(second, sha256="e" * 64) if same_identity else record(second, record_id="e" * 64)
    )
    assert event(client, second, "succeeded", evidence=[evidence]).status_code == 409


def test_contradictory_record_status_rejected(client, spec):
    grant = device_job(client, spec)
    response = event(
        client, grant, "succeeded", evidence=[record(grant), record(grant, record_status="pending")]
    )
    assert response.status_code == 422  # Shared C1 model rejects contradictory records.


def test_simulation_record_rejected_even_for_attention(client, spec):
    from .test_leases import prepared

    _, grant = prepared(client, spec)
    response = event(
        client, grant, "needs_attention", resume_phase="leased", evidence=[record(grant)]
    )
    assert response.status_code == 409


def test_same_digest_conflicting_status_under_alias_rejected(client, spec):
    grant = device_job(client, spec)
    response = event(
        client,
        grant,
        "succeeded",
        evidence=[record(grant), record(grant, record_id="e" * 64, record_status="invalid")],
    )
    assert response.status_code == 422
