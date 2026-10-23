import json
import threading
import time
from pathlib import Path
from uuid import uuid4

import pytest

from swu_happyrun.core.canonical import profile_revision
from swu_happyrun.core.coordinates import to_wgs84
from swu_happyrun.core.models import GeoPoint, RouteProfile
from swu_happyrun.desktop.mumu import (
    TrajectoryController,
    choose_calibration_points,
    validate_local_route,
)
from swu_happyrun.drivers.command import ProbeError


def route(points=None):
    value = RouteProfile(
        route_id=str(uuid4()),
        revision="0" * 64,
        input_crs="WGS84",
        source_ref="unit-fixture",
        points=points
        or [dict(latitude=30.0, longitude=110.0), dict(latitude=30.001, longitude=110.002)],
    )
    value.revision = profile_revision(value)
    return value


def test_route_revision_checked_before_any_hardware():
    value = route()
    assert validate_local_route(value) == value
    value.points[0].latitude = 0.21
    with pytest.raises(ValueError, match="route_revision_mismatch"):
        validate_local_route(value)


def test_calibration_requires_separated_real_route_points():
    value = route()
    first, second = choose_calibration_points(value)
    assert first != second
    short = route([dict(latitude=30.0, longitude=110.0), dict(latitude=30.0, longitude=110.000001)])
    with pytest.raises(ValueError, match="calibration_points_too_close"):
        choose_calibration_points(short)


def test_short_route_can_execute_after_separate_calibration():
    value = route([dict(latitude=30.0, longitude=110.0), dict(latitude=30.0, longitude=110.0001)])
    assert validate_local_route(value) == value


class FakeTransport:
    host_version = "6.8.4.0"
    android_api = 35
    manager = Path("unit-mumu-manager")
    observer = None
    binding = None
    fail_write = False
    changed = False

    def __init__(self):
        self.calls = []
        self.point = None
        self.sequence = 0
        self.start_ns = time.monotonic_ns()
        self.stopped = False
        self.connect_count = 0

    def inventory(self):
        return [dict(index="5", name="unit", running=True, android_version="15.0")]

    def connect(self, index):
        self.connect_count += 1
        if self.stopped:
            raise ProbeError("instance_not_ready")
        self.binding = dict(index=index, created_timestamp=12345, boot_id="unit-boot")
        return self.binding

    def inspect_identity(self, index):
        return dict(
            index=index,
            created_timestamp=12345,
            is_android_started=not self.stopped,
            is_process_started=not self.stopped,
        )

    def assert_current(self):
        if self.changed:
            raise ProbeError("binding_changed")

    def start_observation(self, root):
        self.calls.append("observe")
        self.observer = object()

    def prepare_probe(self, guard):
        guard()
        self.assert_current()

    def read_observation(self):
        self.sequence += 1
        now = time.monotonic_ns()
        return dict(
            schema=1,
            nonce="a" * 32,
            boot_id="unit-boot",
            state="observing",
            error_code=None,
            sequence=self.sequence if self.point else 0,
            window_start_ns=self.start_ns,
            reported_at_ns=now,
            sample=None
            if self.point is None
            else dict(
                latitude=self.point.latitude,
                longitude=self.point.longitude,
                accuracy=1.0,
                elapsed_realtime_ns=now,
            ),
        )

    def write_location(self, point):
        self.assert_current()
        self.calls.append("write")
        self.point = to_wgs84(longitude=point.longitude, latitude=point.latitude, source_crs="BD09")
        if self.fail_write:
            raise ProbeError("command_timeout")

    def stop_observation(self):
        self.calls.append("stop_observation")
        self.observer = None

    def read_retained_location(self):
        return self.point.latitude, self.point.longitude

    def shutdown(self, index, *, expected_created_timestamp):
        assert expected_created_timestamp == 12345
        self.calls.append("shutdown")
        self.observer = None


def wait_for(controller, state, *, idle=True):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        value = controller.snapshot()
        if value["state"] == state and (not idle or controller._pending is None):
            return value
        time.sleep(0.02)
    raise AssertionError(controller.snapshot())


@pytest.fixture
def controller(tmp_path, monkeypatch):
    import swu_happyrun.desktop.mumu as module

    monkeypatch.setattr(
        module,
        "pinned_host_namespace",
        lambda *args: ("c3024912-314d-45ec-a21e-1efc77601088", tmp_path / "namespace" / "host-id"),
    )
    monkeypatch.setattr(module, "legacy_roots", lambda *args: (tmp_path / "legacy",))
    transport = FakeTransport()
    controller = TrajectoryController(
        root=tmp_path / "private", transport_factory=lambda: transport
    )
    controller.snapshot()
    controller.submit("connect", instance_index="5")
    wait_for(controller, "connected")
    yield controller, transport
    controller.close()


def prepare(controller):
    controller.submit("route", route=route())
    wait_for(controller, "connected")
    controller.submit("calibrate")
    wait_for(controller, "ready")


def test_real_controller_serializes_calibration_pause_resume_and_stop(controller):
    control, transport = controller
    prepare(control)
    assert control.snapshot()["device_verified"] is True
    assert transport.calls.count("write") == 2
    control.submit("start", speed_mps=2.0, maximum_duration_seconds=30.0)
    wait_for(control, "running")
    assert json.loads(json.dumps(control.snapshot()))["progress"]["position"]["latitude"] > 0
    control.submit("pause")
    wait_for(control, "paused")
    writes = transport.calls.count("write")
    time.sleep(0.2)
    assert transport.calls.count("write") == writes
    control.submit("resume")
    wait_for(control, "running")
    control.submit("stop")
    value = wait_for(control, "stopped")
    assert value["stop_confirmed"] is True
    assert transport.calls[-1] == "stop_observation"
    assert "shutdown" not in transport.calls


def test_ambiguous_write_is_not_retried_and_explicit_stop_shuts_down(controller):
    control, transport = controller
    control.submit("route", route=route())
    wait_for(control, "connected")
    transport.fail_write = True
    control.submit("calibrate")
    value = wait_for(control, "needs_attention")
    assert value["error_code"] == "command_timeout"
    time.sleep(0.2)
    assert transport.calls.count("write") == 1
    with pytest.raises(ValueError):
        control.submit("calibrate")
    control.submit("stop")
    assert wait_for(control, "stopped")["stop_confirmed"] is True
    assert transport.calls[-1] == "shutdown"


def test_device_change_stops_before_another_location_write(controller):
    control, transport = controller
    prepare(control)
    transport.changed = True
    control.submit("start", speed_mps=2.0, maximum_duration_seconds=30.0)
    value = wait_for(control, "needs_attention")
    assert value["error_code"] == "binding_changed"
    assert transport.calls.count("write") == 2


def test_second_process_scope_cannot_take_the_device(controller, tmp_path):
    control, _ = controller
    other = TrajectoryController(root=control.root, transport_factory=FakeTransport)
    try:
        other.submit("connect", instance_index="5")
        assert wait_for(other, "needs_attention")["error_code"] == "device_busy"
    finally:
        other.close()


def test_stop_during_pending_calibration_never_starts_trajectory(controller):
    control, transport = controller
    control.submit("route", route=route())
    wait_for(control, "connected")
    control.submit("calibrate")
    control.submit("stop")
    assert wait_for(control, "stopped")["stop_confirmed"] is True
    assert transport.calls.count("write") <= 1


def test_queued_action_is_discarded_when_stop_wins_before_dispatch(tmp_path):
    entered, release = threading.Event(), threading.Event()
    transport = FakeTransport()
    original = transport.inventory

    def inventory():
        entered.set()
        assert release.wait(3)
        return original()

    transport.inventory = inventory
    control = TrajectoryController(root=tmp_path / "private", transport_factory=lambda: transport)
    try:
        control.snapshot()
        assert entered.wait(3)
        control._route = route()
        control._set(state="connected", instance_index="5")
        control.submit("calibrate")
        control.submit("stop")
        release.set()
        wait_for(control, "stopped")
        assert transport.calls == []
    finally:
        release.set()
        control.close()


def test_process_restart_preserves_reservation_and_only_explicit_stop_recovers(controller):
    control, first = controller
    prepare(control)
    # Simulate abrupt owner loss without the normal close/stop hook. Fake-only.
    control._closing.set()
    control.thread.join(3)
    assert not control.thread.is_alive()
    second_transport = FakeTransport()
    second_transport.stopped = True
    second = TrajectoryController(root=control.root, transport_factory=lambda: second_transport)
    try:
        second.submit("connect", instance_index="5")
        value = wait_for(second, "needs_attention")
        assert value["error_code"] == "replay_recovery_requires_stop"
        assert second_transport.calls == []
        assert second_transport.connect_count == 0
        second.submit("stop")
        assert wait_for(second, "stopped")["stop_confirmed"] is True
        assert second_transport.calls == ["shutdown"]
        assert first.calls.count("write") == 2
    finally:
        second.close()


def test_pause_accepts_retained_fix_without_claiming_a_new_gps_sample(controller):
    control, transport = controller
    prepare(control)
    control.submit("start", speed_mps=2.0, maximum_duration_seconds=30.0)
    wait_for(control, "running")
    original = transport.read_observation
    last = original()

    def stationary():
        value = original()
        value["sequence"] = last["sequence"]
        value["sample"] = last["sample"]
        return value

    transport.read_observation = stationary
    control.submit("pause")
    wait_for(control, "paused")
    control.submit("stop")
    assert wait_for(control, "stopped")["stop_confirmed"] is True
    assert "shutdown" not in transport.calls


def test_retained_system_position_must_match_confirmed_fix(controller):
    control, transport = controller
    prepare(control)
    transport.read_retained_location = lambda: (31.0, 111.0)
    control.submit("stop")
    value = wait_for(control, "needs_attention")
    assert value["error_code"] == "position_not_stable"
    assert value["stop_confirmed"] is False


def test_jump_before_hold_window_cannot_redefine_the_confirmed_anchor(controller):
    control, transport = controller
    prepare(control)
    transport.point = GeoPoint(latitude=31.0, longitude=111.0)
    control.submit("stop")
    value = wait_for(control, "needs_attention")
    assert value["error_code"] == "position_not_stable"
    assert value["stop_confirmed"] is False
