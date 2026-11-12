"""Synthetic public conversion vectors over loopback HTTP, without source mutation."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from test_http_protocol import AGENT_ID, DEVICE_ID, Service

from swu_happyrun.agent.client import ControlClient
from swu_happyrun.agent.journal import RunJournal
from swu_happyrun.agent.runner import AgentRunner
from swu_happyrun.core.canonical import profile_revision
from swu_happyrun.core.clock import SystemClock
from swu_happyrun.core.coordinates import normalize_points
from swu_happyrun.core.models import JobSpec, RouteProfile, SchoolProfile
from swu_happyrun.core.profiles import LocalProfileStore
from swu_happyrun.drivers.fake import FakeDriver


@pytest.mark.parametrize(
    "crs,lon,lat",
    [
        ("GCJ02", 116.41024449916938, 39.91640428150164),
        ("BD09", 116.41662724378733, 39.922699552216216),
    ],
)
def test_converted_source_runs_real_http_without_rewriting_revision(tmp_path, crs, lon, lat):
    school = SchoolProfile(
        profile_id=str(uuid4()),
        revision="0" * 64,
        campus="synthetic",
        app_package="test.fake",
        app_version="test-1",
        confirmed=True,
        allowed_region=[
            {"longitude": x, "latitude": y}
            for x, y in [
                (116.403, 39.914),
                (116.405, 39.914),
                (116.405, 39.916),
                (116.403, 39.916),
            ]
        ],
        rules={
            "minimum_distance_m": 1,
            "maximum_duration_seconds": 100,
            "minimum_speed_mps": 1,
            "maximum_speed_mps": 10,
        },
        checkpoint_source="manual_confirmed",
    )
    route = RouteProfile(
        route_id=str(uuid4()),
        revision="0" * 64,
        input_crs=crs,
        points=[
            {"longitude": lon, "latitude": lat},
            {"longitude": lon + 0.00002, "latitude": lat},
        ],
        source_ref="synthetic_public_algorithm_vector",
    )
    for folder, model, identifier in [
        ("schools", school, school.profile_id),
        ("routes", route, route.route_id),
    ]:
        model.revision = profile_revision(model)
        path = tmp_path / "profiles" / folder / identifier / (model.revision + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(model.model_dump_json())
    route_path = tmp_path / "profiles" / "routes" / route.route_id / (route.revision + ".json")
    before = route_path.read_bytes()
    points = normalize_points(route)
    assert points[0].longitude == pytest.approx(116.404, abs=2e-6)
    s = Service(tmp_path / "server.sqlite")
    try:
        s.clock.now = datetime.now(UTC)
        spec = JobSpec(
            protocol_version=1,
            mode="simulation",
            profile_id=school.profile_id,
            profile_revision=school.revision,
            route_id=route.route_id,
            route_revision=route.revision,
            device_id=DEVICE_ID,
            not_before=s.clock.now - timedelta(seconds=1),
            deadline=s.clock.now + timedelta(minutes=5),
            expected_app_version=None,
        )
        s.spec = spec.model_dump(mode="json")
        assert s.post(
            "devices", {"device_id": DEVICE_ID, "agent_id": AGENT_ID}, admin=True
        ).status_code in (200, 201)
        assert s.hello().status_code == 200
        created = s.create()
        assert created.status_code == 201
        with (
            ControlClient(s.url, "integration-agent") as client,
            RunJournal(tmp_path / "journal.sqlite") as journal,
        ):
            driver = FakeDriver(
                DEVICE_ID,
                LocalProfileStore(tmp_path / "profiles"),
                state_path=tmp_path / "fake.json",
                route_speed_mps=2,
            )
            runner = AgentRunner(
                client,
                driver,
                journal,
                SystemClock(),
                device_id=DEVICE_ID,
                run_seconds=2,
                tick_seconds=0.05,
            )
            result = runner.run_once()
            assert result.state == "completed", result
            assert result.spec.route_revision == route.revision
            assert driver.route_progress.finished
            assert driver.route_progress.position == points[-1]
            assert driver.start_count == 1 and driver.stop_count == 1
            assert driver.verify(spec).evidence == []
            assert journal.has_intent(result.job_id, "start") and not journal.has_intent(
                result.job_id, "upload"
            )
            assert route_path.read_bytes() == before
            assert profile_revision(route) == route.revision
            assert client.get_job(result.job_id).state == "completed"
    finally:
        s.stop()
