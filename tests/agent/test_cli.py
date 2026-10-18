import json

from swu_happyrun.cli import main


def test_doctor_json_is_structured_without_implying_device_support(capsys):
    code = main(["doctor", "--json"])
    report = json.loads(capsys.readouterr().out)
    assert code in {0, 2}
    assert report["record_verified"] is False


def test_agent_missing_token_is_json_error_not_secret(capsys, monkeypatch):
    monkeypatch.delenv("HAPPYRUN_AGENT_TOKEN", raising=False)
    assert (
        main(
            [
                "agent",
                "--device-id",
                "00000000-0000-4000-8000-000000000001",
                "--agent-id",
                "00000000-0000-4000-8000-000000000002",
                "--once",
            ]
        )
        == 2
    )
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "configuration_error"


def test_device_backend_explicitly_reports_missing_adapter(capsys):
    assert (
        main(
            [
                "agent",
                "--backend",
                "mumu",
                "--device-id",
                "00000000-0000-4000-8000-000000000001",
                "--agent-id",
                "00000000-0000-4000-8000-000000000002",
                "--once",
            ]
        )
        == 2
    )
    result = json.loads(capsys.readouterr().out)
    assert result["error"]["code"] == "adapter_not_verified"


def test_invalid_profile_file_is_json_error(capsys, tmp_path):
    invalid = tmp_path / "job.json"
    invalid.write_text('{"token":"sensitive"}')
    assert main(["profiles", "check", "--job", str(invalid), "--root", str(tmp_path)]) == 2
    output = capsys.readouterr().out
    assert "sensitive" not in output
    assert json.loads(output)["error"]["code"] == "validation_error"


def test_cli_usage_errors_use_json(capsys):
    assert main(["jobs", "no-such-command"]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "usage_error"


def test_module_entrypoint_emits_json():
    import os
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "swu_happyrun", "doctor", "--json"],
        env={**os.environ, "PYTHONPATH": "src"},
        capture_output=True,
        text=True,
    )
    assert result.returncode in {0, 2}
    assert json.loads(result.stdout)["record_verified"] is False


def test_devices_register_rejects_invalid_identity_before_network(capsys, monkeypatch):
    monkeypatch.setenv("HAPPYRUN_ADMIN_TOKEN", "test-token")
    assert main(["devices", "register", "--agent-id", "bad", "--device-id", "bad"]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "configuration_error"
