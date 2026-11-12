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


def stub(stub_command_process, payload, returncode=0):
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, returncode, json.dumps(payload), "private stderr")

    stub_command_process(run)
    return calls


def test_info_uses_explicit_vmindex(stub_command_process, tmp_path):
    calls = stub(stub_command_process, response())
    result = MuMuManager(
        tmp_path / "MuMuManager.exe", host_id="00000000-0000-4000-8000-000000000001"
    ).info("all")
    assert calls[0][0][1:] == ["info", "--vmindex", "all"]
    assert result[0].backend == "mumu"
    assert result[0].capabilities == []
    assert result[0].app_version is None


def test_path_with_spaces_is_one_argument(stub_command_process):
    calls = stub(stub_command_process, response())
    path = Path("C:/Program Files/模拟器/MuMuManager.exe")
    MuMuManager(path, host_id="00000000-0000-4000-8000-000000000001").info("0")
    assert calls[0][0][0] == str(path)
    assert calls[0][1]["shell"] is False
    assert calls[0][1]["stdin"] is subprocess.DEVNULL


def test_cli_error_is_not_empty_success(stub_command_process, tmp_path):
    stub(stub_command_process, response(), returncode=1)
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
def test_invalid_manager_response_fails_closed(stub_command_process, tmp_path, payload):
    stub(stub_command_process, payload)
    with pytest.raises(ProbeError):
        MuMuManager(tmp_path / "manager.exe").info("all")


def test_malformed_json_is_diagnosed(stub_command_process, tmp_path):
    stub_command_process(lambda args, **kw: subprocess.CompletedProcess(args, 0, "not-json", ""))
    with pytest.raises(ProbeError, match="invalid_response"):
        MuMuManager(tmp_path / "manager.exe").info("0")


def test_stable_identity_and_stopped_metadata(stub_command_process, tmp_path):
    stub(stub_command_process, response())
    manager = MuMuManager(tmp_path / "manager.exe", host_id="00000000-0000-4000-8000-000000000001")
    assert manager.info("0")[0].device_id == manager.info("0")[0].device_id
    assert manager.inspect("0")[0].android_started is False
    assert manager.inspect("0")[0].android_version == "15.0"


def test_single_instance_flat_response_from_real_cli(stub_command_process, tmp_path):
    # MuMu 6.8.4 returns a flat object for index 0, a keyed mapping for all.
    stub(stub_command_process, response()["0"])
    assert MuMuManager(tmp_path / "manager.exe").inspect("0")[0].index == "0"


def test_flat_response_is_not_an_all_inventory(stub_command_process, tmp_path):
    stub(stub_command_process, response()["0"])
    with pytest.raises(ProbeError):
        MuMuManager(tmp_path / "manager.exe").inspect("all")


def test_invalid_index_never_executes(stub_command_process, tmp_path):
    calls = stub(stub_command_process, response())
    with pytest.raises(ValueError):
        MuMuManager(tmp_path / "manager.exe").info("0 --start")
    assert not calls


@pytest.mark.parametrize(
    "error,code",
    [
        (FileNotFoundError("private path"), "executable_missing"),
        (PermissionError("private path"), "command_unavailable"),
    ],
)
def test_process_errors_are_bounded_and_sanitized(stub_command_process, tmp_path, error, code):
    def run(*args, **kwargs):
        raise error

    stub_command_process(run)
    with pytest.raises(ProbeError, match=code) as caught:
        MuMuManager(tmp_path / "manager.exe").info("all")
    assert "private" not in str(caught.value)
