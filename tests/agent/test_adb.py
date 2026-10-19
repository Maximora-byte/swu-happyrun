import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from swu_happyrun.drivers.adb import AdbClient
from swu_happyrun.drivers.command import ProbeError


def adb_stub(
    stub_command_process,
    *,
    state="device\n",
    version="15\n",
    ui="<hierarchy/>",
    package="versionName=1.0\n",
):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        if args[-1] == "get-state":
            value = state
        elif args[-1] == "ro.build.version.release":
            value = version
        elif "dumpsys" in args:
            value = package
        else:
            value = ui
        return subprocess.CompletedProcess(args, 0, value, "")

    stub_command_process(run)
    return calls


def test_adb_always_selects_explicit_serial(stub_command_process, tmp_path):
    calls = adb_stub(stub_command_process)
    result = AdbClient(tmp_path / "adb.exe", "fixture-serial").inspect()
    assert all(args[1:3] == ["-s", "fixture-serial"] for args in calls)
    assert result.backend == "android"
    assert result.capabilities == []  # get-state/getprop do not prove app_ui/location.
    assert result.app_version is None
    assert (datetime.now(UTC) - result.observed_at).total_seconds() < 2


@pytest.mark.parametrize("state", ["unauthorized", "offline", "", "unknown"])
def test_unusable_adb_is_not_success(stub_command_process, tmp_path, state):
    calls = adb_stub(stub_command_process, state=state)
    with pytest.raises(ProbeError, match="adb_not_ready"):
        AdbClient(tmp_path / "adb.exe", "fixture").inspect()
    assert len(calls) == 1


def test_empty_android_version_is_error(stub_command_process, tmp_path):
    adb_stub(stub_command_process, version="")
    with pytest.raises(ProbeError, match="invalid_response"):
        AdbClient(tmp_path / "adb.exe", "fixture").inspect()


def test_package_version_lookup_is_explicit_and_readonly(stub_command_process, tmp_path):
    calls = adb_stub(stub_command_process)
    client = AdbClient(tmp_path / "adb.exe", "fixture", package="example.fixture")
    assert client.inspect().app_version == "1.0"
    assert calls[-1][-3:] == ["dumpsys", "package", "example.fixture"]
    assert not any("input" in args or "install" in args or "connect" in args for args in calls)


@pytest.mark.parametrize("serial", ["", "-d", "with spaces", "x;input"])
def test_invalid_serial_never_runs(serial):
    with pytest.raises(ValueError):
        AdbClient(Path("adb"), serial)


def test_invalid_package_never_runs():
    with pytest.raises(ValueError):
        AdbClient(Path("adb"), "fixture", package="example;input")
