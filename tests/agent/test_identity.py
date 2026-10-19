import json
import subprocess

import pytest

from swu_happyrun.drivers.adb import AdbClient
from swu_happyrun.drivers.command import ProbeError
from swu_happyrun.drivers.identity import load_host_id
from swu_happyrun.drivers.mumu.manager import MuMuInstance, MuMuManager

HOST_A = "00000000-0000-4000-8000-000000000001"
HOST_B = "00000000-0000-4000-8000-000000000002"


def test_host_namespace_persists_and_differs_between_hosts(tmp_path):
    first, second = tmp_path / "host-a/id", tmp_path / "host-b/id"
    value = load_host_id(first)
    assert load_host_id(first) == value
    assert load_host_id(second) != value


def test_corrupt_identity_never_silently_rotates(tmp_path):
    path = tmp_path / "host-id"
    path.write_text("invalid", encoding="utf-8")
    with pytest.raises(ProbeError, match="host_identity_invalid"):
        load_host_id(path)
    assert path.read_text() == "invalid"


def test_same_mumu_path_and_index_on_different_hosts_do_not_collide(tmp_path):
    path = tmp_path / "MuMuManager.exe"
    instance = MuMuInstance("0", "15.0", False, False)
    first = MuMuManager(path, host_id=HOST_A).capability(instance)
    assert first.device_id == MuMuManager(path, host_id=HOST_A).capability(instance).device_id
    assert first.device_id != MuMuManager(path, host_id=HOST_B).capability(instance).device_id


def test_same_adb_serial_on_different_hosts_does_not_collide(monkeypatch, tmp_path):
    def run(args, **kwargs):
        value = "device" if args[-1] == "get-state" else "15"
        return subprocess.CompletedProcess(args, 0, value, "")

    monkeypatch.setattr(subprocess, "run", run)
    first = AdbClient(tmp_path / "adb", "127.0.0.1:5555", host_id=HOST_A).inspect()
    second = AdbClient(tmp_path / "adb", "127.0.0.1:5555", host_id=HOST_B).inspect()
    assert first.device_id != second.device_id
    assert HOST_A not in json.dumps(first.model_dump(mode="json"))
