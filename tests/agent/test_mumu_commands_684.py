"""Argument preparation only: no subprocess, device, or vendor semantics inferred."""

import pytest

from swu_happyrun.drivers.base import DriverError


def commands(**kwargs):
    from swu_happyrun.drivers.mumu.commands_684 import MuMu684Commands

    return MuMu684Commands(host_version="6.8.4.0", android_api=35, instance_index="0", **kwargs)


def test_location_order_and_no_coordinate_conversion():
    assert commands().location(longitude=123.25, latitude=-45.5) == (
        "control",
        "--vmindex",
        "0",
        "tool",
        "location",
        "--longitude",
        "123.25",
        "--latitude",
        "-45.5",
    )


def test_gyro_axis_order_is_not_step_count_or_unit_conversion():
    assert commands().gyro(x=-1.25, y=2, z=0.000001) == (
        "control",
        "--vmindex",
        "0",
        "tool",
        "gyro",
        "--gyro_x",
        "-1.25",
        "--gyro_y",
        "2",
        "--gyro_z",
        "0.000001",
    )


@pytest.mark.parametrize("longitude,latitude", [(-180, -90), (180, 90), (0, 0)])
def test_documented_location_boundaries(longitude, latitude):
    args = commands().location(longitude=longitude, latitude=latitude)
    assert args[6] == str(longitude) and args[8] == str(latitude)


@pytest.mark.parametrize("longitude,latitude", [(180.01, 0), (-180.01, 0), (0, 90.01), (0, -90.01)])
def test_outside_documented_range(longitude, latitude):
    with pytest.raises(DriverError, match="command_value_invalid"):
        commands().location(longitude=longitude, latitude=latitude)


@pytest.mark.parametrize(
    "value", [True, None, "1", float("nan"), float("inf"), -float("inf"), 10**1000]
)
@pytest.mark.parametrize("axis", ["longitude", "latitude", "x", "y", "z"])
def test_invalid_values_cannot_be_encoded(value, axis):
    if axis in ("longitude", "latitude"):
        values = dict(longitude=0, latitude=0)
        operation = commands().location
    else:
        values = dict(x=0, y=0, z=0)
        operation = commands().gyro
    values[axis] = value
    with pytest.raises(DriverError, match="command_value_invalid"):
        operation(**values)


@pytest.mark.parametrize(
    "field,value",
    [
        ("host_version", "6.8.4.1"),
        ("host_version", "12"),
        ("host_version", None),
        ("android_api", 31),
        ("android_api", 35.0),
        ("android_api", "35"),
        ("android_api", True),
        ("instance_index", "all"),
        ("instance_index", "-1"),
        ("instance_index", "0; stop"),
        ("instance_index", "０"),
        ("instance_index", ""),
        ("instance_index", 0),
        ("instance_index", "1" * 129),
    ],
)
def test_identity_is_strict_and_single_instance(field, value):
    from swu_happyrun.drivers.mumu.commands_684 import MuMu684Commands

    values = dict(host_version="6.8.4.0", android_api=35, instance_index="0")
    values[field] = value
    with pytest.raises(DriverError):
        MuMu684Commands(**values)


@pytest.mark.parametrize("channel", ["location", "gyro"])
def test_preparation_never_unlocks_real_transport(channel):
    prepared = commands()
    prepared.location(longitude=1, latitude=2)
    prepared.gyro(x=1, y=2, z=3)
    assert prepared.capabilities == ()
    with pytest.raises(DriverError, match="physical_transport_unverified"):
        prepared.require_physical_transport(channel)
    with pytest.raises(TypeError):
        prepared.require_physical_transport(channel, verified=True)


def test_unknown_channel_is_rejected():
    with pytest.raises(DriverError, match="channel_invalid"):
        commands().require_physical_transport("steps")


def test_version_identity_cannot_change_after_validation():
    from dataclasses import FrozenInstanceError

    prepared = commands()
    with pytest.raises(FrozenInstanceError):
        prepared.host_version = "12"


def test_no_executable_or_private_index_in_repr():
    from swu_happyrun.drivers.mumu.commands_684 import MuMu684Commands

    prepared = MuMu684Commands(host_version="6.8.4.0", android_api=35, instance_index="123456")
    assert "123456" not in repr(prepared)
    assert prepared.gyro(x=1, y=2, z=3)[2] == "123456"
