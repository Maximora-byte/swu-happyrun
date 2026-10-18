import json
import subprocess
from pathlib import Path

import pytest

from swu_happyrun.drivers.command import ProbeError
from swu_happyrun.drivers.mumu.manager import MuMuManager


def response(**changes):
    return {
        "0": dict(
            index="0",
            android_version="15.0",
            error_code=0,
            is_android_started=False,
            is_process_started=False,
        )
        | changes
    }


def stub(monkeypatch, payload, returncode=0):
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, returncode, json.dumps(payload), "private stderr")

    monkeypatch.setattr(subprocess, "run", run)
    return calls


def test_info_uses_explicit_vmindex(monkeypatch, tmp_path):
    calls = stub(monkeypatch, response())
    result = MuMuManager(tmp_path / "MuMuManager.exe").info("all")
    assert calls[0][0][1:] == ["info", "--vmindex", "all"]
    assert result[0].backend == "mumu"
    assert result[0].capabilities == []
    assert result[0].app_version is None


def test_path_with_spaces_is_one_argument(monkeypatch):
    calls = stub(monkeypatch, response())
    path = Path("C:/Program Files/模拟器/MuMuManager.exe")
    MuMuManager(path).info("0")
    assert calls[0][0][0] == str(path)
    assert calls[0][1]["shell"] is False
    assert calls[0][1]["timeout"] == 5


def test_cli_error_is_not_empty_success(monkeypatch, tmp_path):
    stub(monkeypatch, response(), returncode=1)
    with pytest.raises(ProbeError, match="command_failed") as caught:
        MuMuManager(tmp_path / "manager.exe").info("all")
    assert "private stderr" not in str(caught.value)


@pytest.mark.parametrize(
    "payload",
    [
        response(error_code=1),
        {"error_code": 1},
        [],
        {"x": {}},
        response(is_android_started="false"),
        response(index="1"),
    ],
)
def test_invalid_manager_response_fails_closed(monkeypatch, tmp_path, payload):
    stub(monkeypatch, payload)
    with pytest.raises(ProbeError):
        MuMuManager(tmp_path / "manager.exe").info("all")


def test_malformed_json_is_diagnosed(monkeypatch, tmp_path):
    monkeypatch.setattr(
        subprocess, "run", lambda args, **kw: subprocess.CompletedProcess(args, 0, "not-json", "")
    )
    with pytest.raises(ProbeError, match="invalid_response"):
        MuMuManager(tmp_path / "manager.exe").info("0")


def test_stable_identity_and_stopped_metadata(monkeypatch, tmp_path):
    stub(monkeypatch, response())
    manager = MuMuManager(tmp_path / "manager.exe")
    assert manager.info("0")[0].device_id == manager.info("0")[0].device_id
    assert manager.inspect("0")[0].android_started is False
    assert manager.inspect("0")[0].android_version == "15.0"


def test_single_instance_flat_response_from_real_cli(monkeypatch, tmp_path):
    # MuMu 6.8.4 returns a flat object for index 0, a keyed mapping for all.
    stub(monkeypatch, response()["0"])
    assert MuMuManager(tmp_path / "manager.exe").inspect("0")[0].index == "0"


def test_flat_response_is_not_an_all_inventory(monkeypatch, tmp_path):
    stub(monkeypatch, response()["0"])
    with pytest.raises(ProbeError):
        MuMuManager(tmp_path / "manager.exe").inspect("all")


def test_invalid_index_never_executes(monkeypatch, tmp_path):
    calls = stub(monkeypatch, response())
    with pytest.raises(ValueError):
        MuMuManager(tmp_path / "manager.exe").info("0 --start")
    assert not calls


@pytest.mark.parametrize(
    "error,code",
    [
        (subprocess.TimeoutExpired(["private"], 5), "command_timeout"),
        (FileNotFoundError("private path"), "executable_missing"),
        (PermissionError("private path"), "command_unavailable"),
    ],
)
def test_process_errors_are_bounded_and_sanitized(monkeypatch, tmp_path, error, code):
    def run(*args, **kwargs):
        raise error

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(ProbeError, match=code) as caught:
        MuMuManager(tmp_path / "manager.exe").info("all")
    assert "private" not in str(caught.value)
