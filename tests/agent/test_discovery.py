import json
import os
import subprocess
import sys

import pytest

from swu_happyrun.drivers.mumu.discovery import (
    collect_report,
    discover_installations,
    host_version,
    select_instance,
)
from swu_happyrun.drivers.mumu.manager import MuMuInstance


def test_discovery_requires_real_executable_and_deduplicates(tmp_path):
    root = tmp_path / "Program Files/模拟器"
    exe = root / "nx_main/MuMuManager.exe"
    exe.parent.mkdir(parents=True)
    exe.touch()
    result = discover_installations(roots=[root, root], include_system=False)
    assert result == [exe.resolve()]
    exe.unlink()
    assert discover_installations(roots=[root], include_system=False) == []


def test_multiple_instances_require_selection():
    items = [MuMuInstance("0", "15.0", False, False), MuMuInstance("1", "12.0", False, False)]
    with pytest.raises(ValueError, match="instance_selection_required"):
        select_instance(items, None)
    assert select_instance(items, "1").index == "1"
    with pytest.raises(ValueError, match="instance_not_found"):
        select_instance(items, "2")


def test_missing_host_is_not_success(monkeypatch):
    monkeypatch.setattr(
        "swu_happyrun.drivers.mumu.discovery.discover_installations", lambda **kwargs: []
    )
    report = collect_report()
    assert report["status"] == "needs_attention"
    assert report["reason_code"] == "mumu_not_found"
    assert report["capabilities"] == []


def test_stopped_instance_does_not_contact_adb(stub_command_process, tmp_path):
    (tmp_path / "host-id").write_text("00000000-0000-4000-8000-000000000001\n")
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(
            args,
            0,
            json.dumps(
                {
                    "0": {
                        "index": "0",
                        "android_version": "15.0",
                        "error_code": 0,
                        "is_android_started": False,
                        "is_process_started": False,
                    }
                }
            ),
            "",
        )

    stub_command_process(run)
    report = collect_report(
        manager=tmp_path / "MuMuManager.exe",
        index="0",
        adb=tmp_path / "adb.exe",
        serial="fixture-serial",
    )
    assert report["reason_code"] == "android_not_started"
    assert report["device_check"] == "not_tested"
    assert len(calls) == 1
    assert "fixture-serial" not in json.dumps(report)


def test_cli_json_and_exit_status_for_missing_install(tmp_path):
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "swu_happyrun.drivers.mumu.discovery",
            "--json",
            "--manager",
            str(tmp_path / "missing.exe"),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )
    assert result.returncode == 2
    report = json.loads(result.stdout)
    assert report["status"] == "needs_attention"
    assert report["reason_code"] == "executable_missing"


def test_discovery_does_not_depend_on_windows(tmp_path):
    # Explicit roots work on Linux CI, without registry imports or platform mutation.
    assert discover_installations(roots=[tmp_path], include_system=False) == []


def test_host_version_is_installed_product_version_not_manager_resource(monkeypatch, tmp_path):
    import swu_happyrun.drivers.mumu.discovery as discovery

    monkeypatch.setattr(
        discovery, "_registered_installations", lambda: [(tmp_path, "6.8.4.0")], raising=False
    )
    assert host_version(tmp_path / "nx_main/MuMuManager.exe") == "6.8.4.0"
    assert host_version(tmp_path / "other/MuMuManager.exe") is None
