"""Disposable loopback HTTP/CLI smoke; never connects to a device or external server.

Run from a fully integrated checkout: uv run --no-sync python deploy/smoke_fake.py
The database, fake profiles and journal are removed with the temporary directory.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from swu_happyrun.core.canonical import profile_revision
from swu_happyrun.core.models import JobSpec, RouteProfile, SchoolProfile


class SmokeFailure(RuntimeError):
    """Safe, fixed diagnostic; never include raw HTTP responses or credentials."""


def require(condition, message):
    if not condition:
        raise SmokeFailure(message)


def create_fixture(root, device_id):
    school = SchoolProfile.model_validate(
        {
            "profile_id": str(uuid4()),
            "revision": "0" * 64,
            "campus": "synthetic-only",
            "app_package": "test.fake",
            "app_version": "test-1",
            "confirmed": True,
            "allowed_region": [
                {"latitude": y, "longitude": x} for x, y in [(0, 0), (1, 0), (1, 1), (0, 1)]
            ],
            "rules": {
                "minimum_distance_m": 1.0,
                "maximum_duration_seconds": 100000.0,
                "minimum_speed_mps": 0.0,
                "maximum_speed_mps": 10.0,
            },
            "checkpoint_source": "manual_confirmed",
        }
    )
    route = RouteProfile.model_validate(
        {
            "route_id": str(uuid4()),
            "revision": "0" * 64,
            "input_crs": "WGS84",
            "points": [
                {"latitude": 0.2, "longitude": 0.2},
                {"latitude": 0.3, "longitude": 0.3},
            ],
            "source_ref": "synthetic-only",
        }
    )
    for folder, identifier, model in [
        ("schools", school.profile_id, school),
        ("routes", route.route_id, route),
    ]:
        model.revision = profile_revision(model)
        path = root / "profiles" / folder / identifier / f"{model.revision}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(model.model_dump_json(), encoding="utf-8")
    now = datetime.now(UTC)
    job = JobSpec(
        protocol_version=1,
        mode="simulation",
        expected_app_version=None,
        profile_id=school.profile_id,
        profile_revision=school.revision,
        route_id=route.route_id,
        route_revision=route.revision,
        device_id=device_id,
        not_before=now - timedelta(seconds=1),
        deadline=now + timedelta(minutes=5),
    )
    (root / "job.json").write_text(job.model_dump_json(), encoding="utf-8")
    return job
