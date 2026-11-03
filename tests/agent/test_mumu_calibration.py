"""Synthetic observations only; no claimed MuMu gateway or real calibration."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from swu_happyrun.core.models import GeoPoint
from swu_happyrun.drivers.base import DriverError
from swu_happyrun.drivers.mumu.location import MuMuLocation

NOW = datetime(2026, 10, 19, tzinfo=UTC)
POINT = GeoPoint(longitude=120, latitude=30)


def setup_location(**changes):
    from swu_happyrun.drivers.mumu.calibration import CalibrationRecord, CalibrationSample

    binding = SimpleNamespace(
        digest="a" * 64,
        host_version="host-test",
        engine_version="engine-test",
        app_version="app-test",
    )
    record = CalibrationRecord(
        binding_digest=binding.digest,
        host_version=binding.host_version,
        engine_version=binding.engine_version,
        app_version=binding.app_version,
        channel="synthetic",
        input_crs="WGS84",
        observed_at=NOW,
        expires_at=NOW + timedelta(seconds=30),
        max_error_m=1,
        samples=(CalibrationSample(target=POINT, observed=POINT, observed_crs="WGS84"),),
    )
    record = replace(record, **changes)
    transport = Transport()
    checks = []
    location = MuMuLocation.for_synthetic_testing(
        transport=transport,
        calibration=record,
        binding=binding,
        binding_check=lambda: checks.append("binding"),
        clock=lambda: NOW,
    )
    location.configure_execution_guard(lambda: checks.append("guard"))
    return location, transport, checks


class Transport:
    def __init__(self):
        self.writes = []
        self.observed = POINT
        self.cleared = True

    def write(self, point):
        self.writes.append(point)

    def read(self):
        return self.observed

    def stop_and_confirm_empty(self):
        return self.cleared


def test_default_is_closed():
    with pytest.raises(DriverError, match="coordinate_mapping_unverified"):
        MuMuLocation().write(POINT, input_crs="WGS84")


@pytest.mark.parametrize(
    "changes",
    [
        {"input_crs": "unknown"},
        {"expires_at": NOW},
        {"observed_at": NOW + timedelta(seconds=1)},
        {"binding_digest": "b" * 64},
        {"host_version": "other"},
        {"engine_version": "other"},
        {"app_version": "other"},
        {"max_error_m": float("nan")},
        {"max_error_m": -1},
        {"samples": ()},
        {"channel": ""},
    ],
)
def test_invalid_calibration_has_zero_writes(changes):
    location, transport, _ = setup_location(**changes)
    with pytest.raises(DriverError):
        location.write(POINT, input_crs="WGS84")
    assert transport.writes == []


@pytest.mark.parametrize(
    "point,crs",
    [
        (GeoPoint.model_construct(longitude=30, latitude=120), "WGS84"),
        (GeoPoint.model_construct(longitude=float("nan"), latitude=30), "WGS84"),
        (POINT, "unknown"),
        (POINT, "GCJ02"),
    ],
)
def test_bad_input_has_zero_writes(point, crs):
    location, transport, _ = setup_location()
    with pytest.raises(DriverError):
        location.write(point, input_crs=crs)
    assert transport.writes == []


def test_guard_and_binding_checked_for_every_write_and_readback_required():
    location, transport, checks = setup_location()
    location.write(POINT, input_crs="WGS84")
    location.write(POINT, input_crs="WGS84")
    assert checks == ["binding", "guard", "binding", "guard"]
    assert len(transport.writes) == location.write_count == 2
    transport.observed = GeoPoint(longitude=121, latitude=30)
    with pytest.raises(DriverError, match="coordinate_readback_mismatch"):
        location.write(POINT, input_crs="WGS84")
    with pytest.raises(DriverError):
        location.write(POINT, input_crs="WGS84")
    assert len(transport.writes) == 3


def test_explicit_error_threshold_boundary():
    from swu_happyrun.core.geo import distance_between_points_m
    from swu_happyrun.drivers.mumu.calibration import CalibrationSample

    observed = GeoPoint(longitude=120.00001, latitude=30)
    error = distance_between_points_m(POINT, observed)
    sample = CalibrationSample(target=POINT, observed=observed, observed_crs="WGS84")
    location, transport, _ = setup_location(samples=(sample,), max_error_m=error)
    location.write(POINT, input_crs="WGS84")
    assert len(transport.writes) == 1
    location, transport, _ = setup_location(samples=(sample,), max_error_m=error / 2)
    with pytest.raises(DriverError):
        location.write(POINT, input_crs="WGS84")
    assert transport.writes == []


def test_binding_or_guard_failure_cannot_be_retried_as_backlog():
    location, transport, _ = setup_location()

    def reject():
        raise DriverError("stale_fence")

    location.configure_execution_guard(reject)
    with pytest.raises(DriverError, match="stale_fence"):
        location.write(POINT, input_crs="WGS84")
    location.configure_execution_guard(lambda: None)
    with pytest.raises(DriverError):
        location.write(POINT, input_crs="WGS84")
    assert transport.writes == []


def test_reentrant_stop_during_guard_cannot_write_after_confirmation():
    location, transport, _ = setup_location()
    location.configure_execution_guard(location.stop)
    with pytest.raises(DriverError):
        location.write(POINT, input_crs="WGS84")
    assert transport.writes == []


def test_calibration_expiry_during_guard_has_zero_writes():
    location, transport, _ = setup_location()
    location.configure_execution_guard(
        lambda: setattr(location, "_clock", lambda: NOW + timedelta(seconds=31))
    )
    with pytest.raises(DriverError):
        location.write(POINT, input_crs="WGS84")
    assert transport.writes == []


def test_missing_guard_has_zero_writes():
    from swu_happyrun.drivers.mumu.sensors import _unguarded

    location, transport, _ = setup_location()
    location.configure_execution_guard(_unguarded)
    with pytest.raises(DriverError, match="execution_guard_missing"):
        location.write(POINT, input_crs="WGS84")
    assert transport.writes == []


def test_current_binding_failure_has_zero_writes():
    location, transport, _ = setup_location()

    def reject():
        raise DriverError("binding_stale")

    location._binding_check = reject
    with pytest.raises(DriverError, match="binding_stale"):
        location.write(POINT, input_crs="WGS84")
    assert transport.writes == []


def test_location_stop_requires_empty_device_queue_ack():
    location, transport, _ = setup_location()
    transport.cleared = False
    with pytest.raises(DriverError, match="stop_unconfirmed"):
        location.stop()
    with pytest.raises(DriverError):
        location.write(POINT, input_crs="WGS84")
    transport.cleared = True
    location.stop()
    location.stop()
    assert transport.writes == []


def test_in_range_axis_swap_in_readback_exceeds_explicit_threshold():
    from swu_happyrun.drivers.mumu.calibration import CalibrationSample

    sample = CalibrationSample(
        target=GeoPoint(longitude=10, latitude=20),
        observed=GeoPoint(longitude=20, latitude=10),
        observed_crs="WGS84",
    )
    location, transport, _ = setup_location(samples=(sample,))
    with pytest.raises(DriverError, match="calibration_error_exceeded"):
        location.write(POINT, input_crs="WGS84")
    assert transport.writes == []


def test_readback_timeout_poison_channel_and_requires_stop_confirmation():
    location, transport, _ = setup_location()

    def timeout():
        raise TimeoutError()

    transport.read = timeout
    with pytest.raises(TimeoutError):
        location.write(POINT, input_crs="WGS84")
    with pytest.raises(DriverError, match="channel_halted"):
        location.write(POINT, input_crs="WGS84")
    assert len(transport.writes) == 1
    location.stop()


def bound_r1_location():
    """Real R1 resolver, using only explicit synthetic identity metadata."""
    from swu_happyrun.drivers.mumu.binding import resolve_binding

    observation = dict(
        instance_index="0",
        adb_serial="synthetic-serial",
        host_version="6.8.4.0",
        engine_version="15",
        app_version="1.0",
        package="org.happyrun.app",
        display_id=0,
        task_id=12,
        boot_id="synthetic-boot",
        observation_id="00000000-0000-4000-8000-000000000001",
        observed_at=NOW.isoformat(),
        mapping_source="local_review",
        mapped_instance_index="0",
        mapped_adb_serial="synthetic-serial",
        observed_display_id=0,
        observed_task_id=12,
        matching_task_count=1,
    )
    binding = resolve_binding(
        instance_index="0", adb_serial="synthetic-serial", observation=observation, now=NOW
    )
    later = NOW + timedelta(seconds=60)
    fresh = dict(
        observation,
        observed_at=later.isoformat(),
        observation_id="00000000-0000-4000-8000-000000000002",
    )
    location, transport, _ = setup_location(
        binding_digest=binding.digest,
        host_version=binding.host_version,
        engine_version=binding.engine_version,
        app_version=binding.app_version,
        expires_at=NOW + timedelta(seconds=120),
    )
    location._binding = binding
    location._clock = lambda: later
    location._binding_check = lambda: binding.assert_current(fresh, now=later)
    return location, transport, binding, fresh


def test_real_r1_fresh_identity_preserves_initial_calibration_digest():
    from swu_happyrun.drivers.mumu.binding import resolve_binding

    location, transport, binding, fresh = bound_r1_location()
    refreshed = resolve_binding(
        instance_index="0",
        adb_serial="synthetic-serial",
        observation=fresh,
        now=NOW + timedelta(seconds=60),
    )
    assert refreshed.digest != binding.digest
    assert refreshed.identity_digest == binding.identity_digest
    location.write(POINT, input_crs="WGS84")
    assert len(transport.writes) == 1
    assert location._calibration.binding_digest == binding.digest
    assert location._binding is binding
    assert binding.capabilities == ()


@pytest.mark.parametrize(
    "field,value",
    [
        ("boot_id", "restarted-boot"),
        ("engine_version", "16"),
        ("app_version", "2.0"),
        ("mapped_adb_serial", "wrong-serial"),
        ("observed_display_id", 1),
    ],
)
def test_real_r1_current_identity_mismatch_stops_before_write(field, value):
    from swu_happyrun.drivers.command import ProbeError

    location, transport, _, fresh = bound_r1_location()
    fresh[field] = value
    with pytest.raises(ProbeError):
        location.write(POINT, input_crs="WGS84")
    assert transport.writes == []
