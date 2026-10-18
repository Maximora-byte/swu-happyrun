"""Synthetic ADB transcripts; no device access and no private device samples."""

import importlib.util
import json
from pathlib import Path

import pytest

from swu_happyrun.drivers.command import ProbeError

MODULE = "swu_happyrun.drivers.android_diagnostics"


@pytest.fixture
def diagnostic(monkeypatch):
    assert importlib.util.find_spec(MODULE) is not None, "standalone Android diagnostics missing"
    module = __import__(MODULE, fromlist=["collect_report"])
    transcript = {
        ("devices",): "List of devices attached\nfixture-1\tdevice\n",
        ("shell", "getprop", "ro.product.model"): "Fixture Phone",
        ("shell", "getprop", "ro.product.cpu.abilist"): "arm64-v8a,armeabi-v7a",
        ("shell", "getprop", "ro.build.version.release"): "15",
        ("shell", "getprop", "ro.build.version.sdk"): "35",
        (
            "shell",
            "dumpsys",
            "package",
            "org.example.app",
        ): "  versionCode=123 minSdk=23\n  versionName=1.2.3\n",
        ("shell", "dumpsys", "-l"): "Currently running services:\n  location\n  sensorservice\n",
        (
            "shell",
            "dumpsys",
            "location",
        ): "Location Manager State:\n  secret raw coordinates and accounts\n",
        ("shell", "dumpsys", "sensorservice"): "Sensor List:\n  secret raw samples\n",
    }
    calls = []

    def run(path, *args, **kwargs):
        calls.append(args)
        key = args if args == ("devices",) else args[2:]
        assert args == ("devices",) or args[:2] == ("-s", "fixture-1")
        value = transcript[key]
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(module, "run_readonly", run)
    return module, transcript, calls


def collect(diagnostic, **kwargs):
    return diagnostic[0].collect_report(adb=Path("/fixture/adb"), **kwargs)


def test_metadata_and_only_explicit_target_readonly_commands(diagnostic):
    report = collect(diagnostic, serial="fixture-1", package="org.example.app", samples=True)
    assert report["status"] == "ok"
    assert report["metadata"]["model"]["value"] == "Fixture Phone"
    assert report["metadata"]["abi"]["value"] == ["arm64-v8a", "armeabi-v7a"]
    assert report["metadata"]["android_version"]["value"] == "15"
    assert report["metadata"]["sdk"]["value"] == 35
    assert report["metadata"]["app_version"]["value"] == "1.2.3"
    assert report["metadata"]["app_version_code"]["value"] == "123"
    assert report["capabilities"] == []
    assert report["record_verified"] is False
    assert report["samples"]["location"]["status"] == "observed"
    assert report["samples"]["sensorservice"]["status"] == "observed"
    assert report["samples"]["location"]["live_read"] == "unknown"
    assert "secret" not in json.dumps(report)
    assert "fixture-1" not in json.dumps(report)


@pytest.mark.parametrize(
    ("devices", "serial", "reason"),
    [
        ("List of devices attached\n", None, "no_devices"),
        ("List of devices attached\nfixture-1\tdevice\n", None, "serial_required"),
        (
            "List of devices attached\nfixture-1\tdevice\nfixture-2\tdevice\n",
            None,
            "multiple_devices",
        ),
        ("List of devices attached\nfixture-1\tunauthorized\n", "fixture-1", "unauthorized"),
        ("List of devices attached\nfixture-1\toffline\n", "fixture-1", "offline"),
        ("List of devices attached\nfixture-2\tdevice\n", "fixture-1", "device_not_found"),
        ("List of devices attached\nfixture-1\trecovery\n", "fixture-1", "unsupported_state"),
        (
            "List of devices attached\nfixture-1\tno permissions (udev)\n",
            "fixture-1",
            "host_permission_denied",
        ),
        ("unexpected garbage", None, "invalid_response"),
        (ProbeError("command_timeout"), "fixture-1", "command_timeout"),
        (ProbeError("executable_missing"), "fixture-1", "executable_missing"),
    ],
)
def test_connection_reasons_stop_before_device_queries(diagnostic, devices, serial, reason):
    diagnostic[1][("devices",)] = devices
    report = collect(diagnostic, serial=serial)
    assert report["status"] == "blocked"
    assert report["reason"] == reason
    assert diagnostic[2] == [("devices",)]


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("Permission Denial: private identity", "permission_denied"),
        ("Can't find service: location", "unsupported"),
        ("unrecognized vendor dump with private coordinates", "unrecognized_output"),
        (ProbeError("command_timeout"), "command_timeout"),
        ("", "empty_response"),
    ],
)
def test_sample_failures_are_unknown_and_redacted(diagnostic, raw, reason):
    diagnostic[1][("shell", "dumpsys", "location")] = raw
    report = collect(diagnostic, serial="fixture-1", samples=True)
    sample = report["samples"]["location"]
    assert sample["status"] == "unknown"
    assert sample["reason"] == reason
    assert sample["live_read"] == "unknown"
    assert report["capabilities"] == []
    assert "private" not in json.dumps(report)


def test_no_samples_requested_does_not_dump_services(diagnostic):
    report = collect(diagnostic, serial="fixture-1")
    assert report["samples"]["location"]["reason"] == "not_requested"
    assert not any("dumpsys" in call for call in diagnostic[2])


def test_absent_service_is_unsupported_not_device_capability(diagnostic):
    diagnostic[1][("shell", "dumpsys", "-l")] = "Currently running services:\n  sensorservice\n"
    report = collect(diagnostic, serial="fixture-1", samples=True)
    assert report["samples"]["location"]["reason"] == "unsupported"
    assert ("-s", "fixture-1", "shell", "dumpsys", "location") not in diagnostic[2]


def test_metadata_failure_does_not_invent_version(diagnostic):
    diagnostic[1][("shell", "getprop", "ro.build.version.release")] = ""
    diagnostic[1][("shell", "dumpsys", "package", "org.example.app")] = "Unable to find package"
    report = collect(diagnostic, serial="fixture-1", package="org.example.app")
    assert report["status"] == "partial"
    assert report["metadata"]["android_version"]["value"] is None
    assert report["metadata"]["app_version"]["reason"] == "package_not_found"


@pytest.mark.parametrize(("serial", "package"), [("x;reboot", None), ("fixture-1", "x;reboot")])
def test_invalid_arguments_never_execute(diagnostic, serial, package):
    report = collect(diagnostic, serial=serial, package=package)
    assert report["status"] == "blocked"
    assert report["reason"] == "invalid_arguments"
    assert diagnostic[2] == []


def test_standalone_entrypoint_exists():
    assert importlib.util.find_spec(MODULE) is not None, "standalone Android diagnostics missing"


def test_requested_sample_failure_makes_report_partial(diagnostic):
    diagnostic[1][("shell", "dumpsys", "location")] = ProbeError("command_timeout")
    report = collect(diagnostic, serial="fixture-1", samples=True)
    assert report["status"] == "partial"


def test_module_entrypoint_returns_failure_for_requested_sample_failure(diagnostic, capsys):
    diagnostic[1][("shell", "dumpsys", "location")] = "Permission denied"
    result = diagnostic[0].main(["--adb", "/fixture/adb", "--serial", "fixture-1", "--samples"])
    assert result == 2
    assert json.loads(capsys.readouterr().out)["status"] == "partial"


def test_module_entrypoint_reports_metadata_without_mumu(diagnostic, capsys):
    assert diagnostic[0].main(["--adb", "/fixture/adb", "--serial", "fixture-1"]) == 0
    assert json.loads(capsys.readouterr().out)["metadata"]["sdk"]["value"] == 35
