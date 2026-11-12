"""Deterministic controller boundaries with real journals and a fake device channel."""

from types import SimpleNamespace

import pytest
from test_mumu_controller import FakeTransport, prepare, route
from test_mumu_controller import controller as controller  # noqa: F401

from swu_happyrun.core.geo import distance_between_points_m
from swu_happyrun.desktop import mumu


@pytest.fixture
def synchronous_controller(tmp_path, monkeypatch):
    clock = SimpleNamespace(now=100.0)
    clock.monotonic = lambda: clock.now
    monkeypatch.setattr(mumu, "SystemClock", lambda: clock)
    monkeypatch.setattr(
        mumu,
        "pinned_host_namespace",
        lambda *args: ("c3024912-314d-45ec-a21e-1efc77601088", tmp_path / "host-id"),
    )
    monkeypatch.setattr(mumu, "legacy_roots", lambda *args: (tmp_path / "legacy",))
    transport = FakeTransport()
    control = mumu.TrajectoryController(
        root=tmp_path / "private", transport_factory=lambda: transport
    )
    control._transport = transport
    control._do_connect("5")
    control._do_route(route())
    control._do_calibrate()
    yield control, transport, clock
    control._stop()


@pytest.mark.parametrize("maximum,expected", [(1800, "completed"), (5, "stopped")])
def test_pause_at_execution_end_finishes_and_releases_session(
    synchronous_controller, maximum, expected
):
    control, transport, clock = synchronous_controller
    control._do_start(2.0, maximum)
    clock.now += control._execution.duration_seconds
    control._do_pause()
    assert control._view["state"] == expected
    assert control._view["progress"]["state"] == expected
    assert control._view["stop_confirmed"] is True
    assert control._permit is None
    assert transport.observer is None
    assert distance_between_points_m(transport.point, control._execution.snapshot.position) <= 5


def test_start_rejects_route_that_outlives_existing_observation(synchronous_controller):
    control, transport, clock = synchronous_controller
    clock.now += 1650  # Only 150 seconds of the original window remain.
    before = transport.calls.count("write")
    control._do_start(0.3, 1800)
    assert control._view["state"] == "ready"
    assert control._view["error_code"] == "observation_budget_insufficient"
    assert control._execution is None
    assert transport.calls.count("write") == before
    assert transport.calls.count("observe") == 1
    # A shorter explicit request is still allowed, without renewing observation.
    control._do_start(2.0, 5)
    assert control._view["state"] == "running"
    assert control._view["error_code"] is None
    assert transport.calls.count("observe") == 1


def test_resume_does_not_restart_after_pause_consumes_observation_budget(synchronous_controller):
    control, transport, clock = synchronous_controller
    control._do_start(2.0, 100)
    clock.now += 10
    control._do_pause()
    clock.now += 1740
    writes = transport.calls.count("write")
    control._do_resume()
    assert control._view["state"] == "paused"
    assert control._view["error_code"] == "observation_budget_insufficient"
    assert control._execution.snapshot.state == "paused"
    assert transport.calls.count("write") == writes
    assert transport.calls.count("observe") == 1


@pytest.mark.parametrize("state", ["ready", "paused", "running"])
def test_window_near_expiry_stops_without_new_location_or_renewal(synchronous_controller, state):
    control, transport, clock = synchronous_controller
    if state != "ready":
        control._do_start(2.0, 100)
    if state == "paused":
        control._do_pause()
    clock.now += 1770
    writes = transport.calls.count("write")
    assert control._stop_for_observation_deadline() is True
    assert control._view["state"] == "stopped"
    assert control._view["stop_confirmed"] is True
    assert transport.observer is None
    assert transport.calls.count("write") == writes
    assert transport.calls.count("observe") == 1


def test_calibration_reuse_does_not_extend_existing_window(synchronous_controller):
    control, transport, clock = synchronous_controller
    clock.now += 100
    control._do_calibrate()
    assert control._observation_remaining() == 1700
    assert transport.calls.count("observe") == 1


def test_late_recalibration_stops_instead_of_sending_three_new_points(synchronous_controller):
    control, transport, clock = synchronous_controller
    clock.now += 1750
    writes = transport.calls.count("write")
    control._do_calibrate()
    assert control._view["state"] == "stopped"
    assert control._view["stop_confirmed"] is True
    assert transport.calls.count("write") == writes
    assert transport.calls.count("observe") == 1


def test_deadline_stop_seals_new_commands_during_cleanup(controller, monkeypatch):
    import threading

    control, transport = controller
    prepare(control)
    entered, release = threading.Event(), threading.Event()
    original = transport.stop_observation

    def blocked_stop():
        entered.set()
        assert release.wait(5)
        original()

    transport.stop_observation = blocked_stop
    deadline = control._observation_deadline
    monkeypatch.setattr(control, "_clock", SimpleNamespace(monotonic=lambda: deadline - 30))
    try:
        assert entered.wait(5)
        with pytest.raises(ValueError, match="invalid_mumu_state"):
            control.submit("start", speed_mps=2.0, maximum_duration_seconds=5)
    finally:
        release.set()
        control.close()
    assert control._view["stop_confirmed"] is True
    assert control._view["state"] == "stopped"
    assert transport.calls.count("write") == 3
    assert transport.calls.count("observe") == 1


def test_command_queued_at_idle_boundary_wins_before_automatic_stop(synchronous_controller):
    control, transport, clock = synchronous_controller
    control._pending = "start"
    command = ("start", {"speed_mps": 2.0, "maximum_duration_seconds": 5})
    control._commands.put(command)
    clock.now += 1770
    # True also tells the owner loop to skip its running tick this iteration.
    assert control._stop_for_observation_deadline() is True
    assert control._view["state"] == "ready"
    assert control._commands.get_nowait() == command
    assert control._permit is not None
    assert transport.observer is not None
    assert transport.calls.count("write") == 3
