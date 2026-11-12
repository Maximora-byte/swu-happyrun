"""Synthetic, offline protocol checks; never invokes a connected Android device."""

import base64
import importlib
import json
from pathlib import Path

import pytest

from swu_happyrun.cli import main
from swu_happyrun.core.canonical import profile_revision
from swu_happyrun.core.models import RouteProfile


def adapter():
    return importlib.import_module("swu_happyrun.drivers.gps_locator")


def route(crs="WGS84"):
    value = RouteProfile(
        route_id="00000000-0000-4000-8000-000000000001",
        revision="0" * 64,
        input_crs=crs,
        source_ref="synthetic-test",
        points=[{"latitude": 30.0, "longitude": 110.0}, {"latitude": 30.001, "longitude": 110.001}],
    )
    return value.model_copy(update={"revision": profile_revision(value)})


def status(**updates):
    value = dict(
        schemaVersion=1,
        applicationId="com.gpsupdater.app",
        appVersion="2.1.0",
        versionCode=5,
        debug=False,
        tier="free",
        deviceId="PRIVATE-ID",
        mockLocationReady=True,
        simulationActive=False,
        enterprise=dict(organization="PRIVATE-ORG", expiresAt=0, active=False, deviceBound=False),
    )
    value.update(updates)
    return value


def broadcast(value):
    data = base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
    return f'Broadcasting: Intent {{ ... }}\nBroadcast completed: result=1, data="{data}"\n'


def test_export_revision_crs_units_and_no_loop():
    source = route("GCJ02")
    result = adapter().export_route(source, 2.5)
    assert result["speedKph"] == 9.0
    assert result["loop"] is False
    assert result["id"] == source.route_id
    assert len(result["waypoints"]) == 2
    assert result["waypoints"][0]["latitude"] != source.points[0].latitude
    assert source.revision == profile_revision(source)
    assert "source_ref" not in result


@pytest.mark.parametrize("speed", [0, -1, float("nan"), float("inf"), True, "2", 140])
def test_export_bad_speed(speed):
    with pytest.raises(ValueError):
        adapter().export_route(route(), speed)


def test_export_stale_revision():
    with pytest.raises(ValueError, match="revision"):
        adapter().export_route(route().model_copy(update={"revision": "f" * 64}), 2)


def test_export_degenerate():
    value = route()
    value = value.model_copy(update={"points": [value.points[0], value.points[0]]})
    value = value.model_copy(update={"revision": profile_revision(value)})
    with pytest.raises(ValueError, match="distinct"):
        adapter().export_route(value, 2)


def test_inspect_readonly_and_redacted(monkeypatch):
    calls = []

    def fake(path, *args, **kwargs):
        calls.append((path, args, kwargs))
        return broadcast(status())

    module = adapter()
    monkeypatch.setattr(module, "run_readonly", fake)
    result = module.inspect(Path("/synthetic/adb"), "emulator-5554")
    assert len(calls) == 1
    assert calls[0][1] == (
        "-s",
        "emulator-5554",
        "shell",
        "am",
        "broadcast",
        "--receiver-foreground",
        "-n",
        "com.gpsupdater.app/.enterprise.EnterpriseControlReceiver",
        "-a",
        "com.gpsupdater.app.enterprise.GET_DEVICE_STATUS",
    )
    assert calls[0][2]["timeout"] == 5
    assert result["execution_enabled"] is False
    assert result["fresh_location_verified"] is False
    assert result["mock_location_appop_reported"] is True
    assert "PRIVATE" not in json.dumps(result)
    assert "emulator" not in json.dumps(result)


@pytest.mark.parametrize("serial", ["", "all", "a,b", "-e", "x;id", " x", "x\ny"])
def test_no_broad_or_unsafe_serial(serial, monkeypatch):
    module = adapter()
    monkeypatch.setattr(module, "run_readonly", lambda *a, **kw: pytest.fail("command ran"))
    with pytest.raises(ValueError):
        module.inspect(Path("adb"), serial)


@pytest.mark.parametrize(
    "value",
    [
        status(schemaVersion=2),
        status(mockLocationReady="true"),
        status(simulationActive=1),
        status(applicationId="other"),
        status(versionCode=True),
        status(appVersion="x\nsecret"),
        status(enterprise={}),
        [],
        {"schemaVersion": 1},
    ],
)
def test_bad_status_fails_closed(value, monkeypatch):
    module = adapter()
    monkeypatch.setattr(module, "run_readonly", lambda *a, **kw: broadcast(value))
    with pytest.raises(ValueError, match="gps_locator_status_invalid"):
        module.inspect(Path("adb"), "device1")


@pytest.mark.parametrize(
    "raw",
    [
        "Broadcast completed: result=0",
        "PRIVATE garbage",
        'Broadcast completed: result=1, data="!"',
        "x" * 100001,
    ],
    ids=["rejected", "garbage", "invalid-base64", "oversized"],
)
def test_bad_wire_fails_without_raw_leak(raw, monkeypatch):
    module = adapter()
    monkeypatch.setattr(module, "run_readonly", lambda *a, **kw: raw)
    with pytest.raises(ValueError) as error:
        module.inspect(Path("adb"), "device1")
    assert str(error.value) == "gps_locator_status_invalid"


def test_cli_export_and_nonoverwrite(tmp_path, capsys):
    source, output = tmp_path / "source.json", tmp_path / "preview.json"
    source.write_text(route().model_dump_json())
    args = [
        "gps-locator",
        "export-route",
        "--route",
        str(source),
        "--output",
        str(output),
        "--speed-mps",
        "2",
    ]
    assert main(args) == 0
    result = json.loads(output.read_text())
    assert result["speedKph"] == 7.2
    first = output.read_bytes()
    assert main(args) == 2
    assert output.read_bytes() == first
    assert "PRIVATE" not in capsys.readouterr().out


def test_cli_no_execution_command(capsys):
    assert main(["gps-locator", "replay"]) == 2
    assert "usage_error" in capsys.readouterr().out


@pytest.mark.parametrize("crs", ["WGS84", "GCJ02", "BD09"])
def test_export_matches_existing_normalization(crs):
    from swu_happyrun.core.coordinates import normalize_points

    source = route(crs)
    expected = normalize_points(source)
    actual = adapter().export_route(source, 2)["waypoints"]
    for wanted, point in zip(expected, actual, strict=True):
        assert point["latitude"] == wanted.latitude
        assert point["longitude"] == wanted.longitude
        assert point["stopDurationSeconds"] == 0


def test_output_size_budget_includes_newline(tmp_path, monkeypatch):
    module = adapter()
    source = tmp_path / "route.json"
    source.write_text(route().model_dump_json())
    result = module.export_route(route(), 2)
    size = len(json.dumps(result, separators=(",", ":")).encode())
    monkeypatch.setattr(module, "MAX_DOCUMENT_BYTES", size - 1)
    with pytest.raises(ValueError, match="too_large"):
        module.export_file(source, tmp_path / "output.json", 2)
    assert not (tmp_path / "output.json").exists()


def test_duplicate_status_key_rejected(monkeypatch):
    module = adapter()
    data = json.dumps(status()).replace(
        '"schemaVersion": 1', '"schemaVersion": 2, "schemaVersion": 1'
    )
    encoded = base64.urlsafe_b64encode(data.encode()).decode().rstrip("=")
    raw = f'Broadcast completed: result=1, data="{encoded}"'
    monkeypatch.setattr(module, "run_readonly", lambda *a, **kw: raw)
    with pytest.raises(ValueError, match="gps_locator_status_invalid"):
        module.inspect(Path("adb"), "device1")


@pytest.mark.parametrize("ready,active", [(False, False), (True, True), (False, True)])
def test_reported_flags_never_enable_execution(ready, active, monkeypatch):
    module = adapter()
    monkeypatch.setattr(
        module,
        "run_readonly",
        lambda *a, **kw: broadcast(status(mockLocationReady=ready, simulationActive=active)),
    )
    value = module.inspect(Path("adb"), "device1")
    assert value["mock_location_appop_reported"] is ready
    assert value["simulation_active_reported"] is active
    assert value["execution_enabled"] is value["fresh_location_verified"] is False
    assert value["record_verified"] is False


def test_cli_inspect_errors_are_redacted(monkeypatch, capsys):
    module = adapter()

    def failed(*a, **kw):
        raise RuntimeError("PRIVATE device and location")

    monkeypatch.setattr(module, "run_readonly", failed)
    assert main(["gps-locator", "inspect", "--adb", "adb", "--serial", "device1"]) == 3
    assert "PRIVATE" not in capsys.readouterr().out


def test_cli_export_same_path_untouched(tmp_path):
    source = tmp_path / "source.json"
    source.write_text(route().model_dump_json())
    previous = source.read_bytes()
    with pytest.raises(FileExistsError):
        adapter().export_file(source, source, 2)
    assert source.read_bytes() == previous
