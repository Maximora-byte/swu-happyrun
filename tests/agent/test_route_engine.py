"""Synthetic geometry only; never school/device acceptance evidence."""

import importlib.util
import math

import pytest
from test_geo import profiles


def engine_fixture(speed=5.0):
    from swu_happyrun.core.route import RouteExecution

    school, route = profiles()
    route.points = [
        route.points[0],
        route.points[0].model_copy(),
        route.points[0].model_copy(update={"longitude": 0.201}),
        route.points[0].model_copy(update={"longitude": 0.201, "latitude": 0.201}),
    ]
    return RouteExecution(route, school, speed_mps=speed), route


def test_route_engine_exists():
    assert importlib.util.find_spec("swu_happyrun.core.route") is not None


def test_interpolation_waypoint_progress_and_completion():
    engine, route = engine_fixture()
    first = engine.start(now=10.0)
    assert first.position == route.points[0]
    assert first.progress == 0
    half = engine.tick(now=10 + engine.segment_distances[1] / 10)
    assert half.position.latitude == pytest.approx(0.2)
    assert half.position.longitude == pytest.approx(0.2005)
    assert half.speed_mps == 5
    turn = engine.tick(now=10 + engine.segment_distances[1] / 5)
    assert turn.position == route.points[2]
    end = engine.tick(now=10 + engine.duration_seconds + 100)
    assert end.position == route.points[-1]
    assert end.progress == 1
    assert end.distance_m == engine.total_distance_m
    assert end.elapsed_seconds == pytest.approx(engine.duration_seconds)
    assert end.state == "completed"
    assert end.speed_mps == 0
    assert engine.tick(now=1000) == end


def test_pause_resume_excludes_paused_time_and_stop_is_terminal():
    engine, _ = engine_fixture()
    engine.start(now=0)
    paused = engine.pause(now=2)
    assert paused.state == "paused"
    assert paused.distance_m == 10
    assert paused.speed_mps == 0
    assert engine.tick(now=100).distance_m == 10
    engine.resume(now=101)
    assert engine.tick(now=103).distance_m == 20
    stopped = engine.stop()
    assert stopped.state == "stopped"
    assert stopped.speed_mps == 0
    assert engine.stop() == stopped
    assert engine.tick(now=200) == stopped
    with pytest.raises(ValueError, match="invalid_route_state"):
        engine.resume(now=201)
    with pytest.raises(ValueError, match="invalid_route_state"):
        engine.start(now=201)


@pytest.mark.parametrize("now", [-1, True, float("nan"), float("inf"), "2"])
def test_bad_clock_readings_do_not_mutate_progress(now):
    engine, _ = engine_fixture()
    engine.start(now=0)
    before = engine.snapshot
    with pytest.raises(ValueError, match="invalid_monotonic_time"):
        engine.tick(now=now)
    assert engine.snapshot == before
    assert engine.tick(now=1).distance_m == 5


def test_regressing_clock_rejected_during_pause_and_resume():
    engine, _ = engine_fixture()
    engine.start(now=10)
    engine.pause(now=11)
    with pytest.raises(ValueError, match="invalid_monotonic_time"):
        engine.resume(now=10)
    assert engine.snapshot.state == "paused"
    engine.resume(now=12)
    assert engine.tick(now=13).distance_m == 10


@pytest.mark.parametrize("speed", [0, -1, True, math.nan, math.inf, 11, "5"])
def test_invalid_speed_is_rejected(speed):
    with pytest.raises(ValueError, match="invalid_route_speed"):
        engine_fixture(speed)


def test_rules_boundaries_crs_and_mutation_rejected():
    from swu_happyrun.core.route import RouteExecution

    for change in ("boundary", "crs", "duration", "minimum_speed", "nan"):
        school, route = profiles()
        if change == "boundary":
            route.points[1].longitude = 2
        elif change == "crs":
            route.input_crs = "GCJ02"
        elif change == "duration":
            school.rules["maximum_duration_seconds"] = 2000
        elif change == "minimum_speed":
            school.rules["minimum_speed_mps"] = 6
        else:
            route.points[0] = route.points[0].model_copy(update={"latitude": math.nan})
        with pytest.raises(ValueError):
            RouteExecution(route, school, speed_mps=5)


def test_clock_injection_and_input_snapshot_are_independent():
    from swu_happyrun.core.route import RouteExecution

    class Clock:
        value = 20

        def monotonic(self):
            return self.value

        def utcnow(self):
            raise AssertionError("wall clock must not drive routes")

    clock = Clock()
    school, route = profiles()
    engine = RouteExecution(route, school, speed_mps=5, clock=clock)
    start = engine.start()
    route.points[0].latitude = 90
    start.position.latitude = 90
    clock.value += 1
    assert engine.tick().distance_m == 5
    assert engine.snapshot.position.latitude < 1


def test_fake_driver_produces_real_synthetic_trajectory(tmp_path):
    from test_driver import driver_fixture

    job, driver = driver_fixture(tmp_path)
    driver.prepare(job)
    driver.start(job)
    start = driver.route_progress
    driver.tick(job, 1)
    first = driver.route_progress
    driver.tick(job, 2)
    second = driver.route_progress
    assert start.distance_m == 0
    assert first.distance_m == 10
    assert second.distance_m == 20
    assert start.position != first.position != second.position
    driver.stop()
    assert driver.route_progress.state == "stopped"
    assert driver.verify(job).evidence == []


def test_fake_finishes_route_and_persists_completion_for_verification(tmp_path):
    from test_driver import persistent_driver

    job, driver = persistent_driver(tmp_path)
    driver.prepare(job)
    driver.start(job)
    initial = driver.route_progress
    duration = initial.total_distance_m / initial.speed_mps
    for fraction in (0.25, 0.5, 0.75, 1.0):
        driver.tick(job, duration * fraction)
        assert driver.route_progress.progress == pytest.approx(fraction)
    assert driver.route_progress.finished
    driver.stop()
    assert driver.route_progress.finished
    _, recovered = persistent_driver(tmp_path)
    assert recovered.route_progress is None
    assert recovered.verify(job).reason_code == "simulation_only"
    assert recovered.verify(job).evidence == []


def test_partial_simulation_cannot_be_verified_as_complete_after_restart(tmp_path):
    from test_driver import persistent_driver

    job, driver = persistent_driver(tmp_path)
    driver.prepare(job)
    driver.start(job)
    driver.tick(job, 1)
    driver.stop()
    assert driver.verify(job).reason_code == "simulation_incomplete"
    _, recovered = persistent_driver(tmp_path)
    assert recovered.verify(job).reason_code == "simulation_incomplete"


def test_guard_blocks_position_change_and_recovery_never_restarts_motion(tmp_path):
    from test_driver import persistent_driver

    from swu_happyrun.drivers.base import DriverError

    job, driver = persistent_driver(tmp_path)
    driver.prepare(job)
    driver.start(job)
    before = driver.route_progress

    def expired():
        raise DriverError("lease_expired")

    driver.configure_execution_guard(expired)
    with pytest.raises(DriverError, match="lease_expired"):
        driver.tick(job, 10)
    assert driver.route_progress == before
    _, recovered = persistent_driver(tmp_path)
    with pytest.raises(DriverError, match="route_recovery_requires_stop"):
        recovered.tick(job, 10)
    recovered.stop()
    assert recovered.verify(job).reason_code == "simulation_incomplete"


def test_missing_legacy_completion_marker_fails_closed(tmp_path):
    import json

    from test_driver import persistent_driver

    job, driver = persistent_driver(tmp_path)
    driver.prepare(job)
    driver.start(job)
    driver.stop()
    path = tmp_path / "fake-state.json"
    data = json.loads(path.read_text())
    data.pop("route_finished")
    path.write_text(json.dumps(data))
    _, recovered = persistent_driver(tmp_path)
    assert recovered.verify(job).reason_code == "simulation_incomplete"


def test_cancel_does_not_advance_position(tmp_path):
    from test_driver import driver_fixture, session_view

    from swu_happyrun.core.states import JobState
    from swu_happyrun.drivers.base import DriverError

    job, driver = driver_fixture(tmp_path)
    driver.prepare(job)
    driver.start(job)
    before = driver.route_progress
    driver.bind_session(
        session_view(job).model_copy(
            update={"state": JobState.CANCELLING, "desired_state": "cancel"}
        )
    )
    with pytest.raises(DriverError, match="cancel_requested"):
        driver.tick(job, 20)
    assert driver.route_progress == before
    driver.stop()
    assert driver.route_progress.distance_m == 0


def test_explicit_gcj_route_uses_detached_wgs84_points():
    from swu_happyrun.core.coordinates import normalize_points
    from swu_happyrun.core.models import GeoPoint
    from swu_happyrun.core.route import RouteExecution

    school, route = profiles()
    # Synthetic algorithm-domain geometry, not a school or surveyed point.
    school.allowed_region = [
        GeoPoint(longitude=x, latitude=y) for x, y in [(110, 30), (111, 30), (111, 31), (110, 31)]
    ]
    route.input_crs = "GCJ02"
    route.points = [
        GeoPoint(longitude=110.5, latitude=30.5),
        GeoPoint(longitude=110.501, latitude=30.501),
    ]
    source = route.model_dump()
    expected = normalize_points(route)
    engine = RouteExecution(route, school, speed_mps=5)
    assert engine.start(now=0).position == expected[0]
    assert engine.tick(now=engine.duration_seconds).position == expected[-1]
    assert route.model_dump() == source
