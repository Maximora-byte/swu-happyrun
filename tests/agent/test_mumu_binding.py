import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path, PureWindowsPath

import pytest

from swu_happyrun.drivers.command import ProbeError

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime.now(UTC)


def api():
    from swu_happyrun.drivers.mumu import binding

    return binding


def sample():
    return dict(
        instance_index="0",
        adb_serial="127.0.0.1:16384",
        host_version="6.8.4.0",
        engine_version="15",
        app_version="1.0",
        package="org.happyrun.app",
        display_id=0,
        task_id=12,
        boot_id="synthetic-boot-1",
        observation_id="00000000-0000-4000-8000-000000000001",
        observed_at=NOW.isoformat(),
        mapping_source="local_review",
        mapped_instance_index="0",
        mapped_adb_serial="127.0.0.1:16384",
        observed_display_id=0,
        observed_task_id=12,
        matching_task_count=1,
    )


def resolve(observation=None):
    return api().resolve_binding(
        instance_index="0",
        adb_serial="127.0.0.1:16384",
        observation=observation or sample(),
        now=NOW,
    )


def test_binding_is_local_only_and_never_grants_capabilities():
    binding = resolve()
    assert binding.capabilities == ()
    assert len(binding.digest) == 64
    assert binding.digest == resolve().digest
    assert binding.assert_current(sample(), now=NOW) is None


def test_wrong_adb_alias_has_no_capabilities():
    value = sample()
    value["mapped_adb_serial"] = "emulator-5554"
    with pytest.raises(ProbeError, match="binding_mismatch"):
        resolve(value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("observed_display_id", 1),
        ("observed_task_id", 13),
        ("matching_task_count", 2),
        ("observed_at", (NOW - timedelta(seconds=31)).isoformat()),
        ("observed_at", (NOW + timedelta(seconds=1)).isoformat()),
    ],
)
def test_wrong_display_or_stale_observation_blocks_actions(field, value):
    observation = sample()
    observation[field] = value
    with pytest.raises(ProbeError):
        resolve(observation)


@pytest.mark.parametrize(
    "field,value",
    [
        ("boot_id", "synthetic-boot-2"),
        ("host_version", "6.9"),
    ],
)
def test_instance_restart_invalidates_binding(field, value):
    binding = resolve()
    observation = sample()
    observation[field] = value
    with pytest.raises(ProbeError):
        binding.assert_current(observation, now=NOW)


@pytest.mark.parametrize("field", ["token", "session", "account", "url", "command", "raw"])
def test_sensitive_and_unknown_fields_rejected_without_echo(field):
    value = sample()
    value[field] = "secret-private-value"
    with pytest.raises(ProbeError) as caught:
        resolve(value)
    assert "secret" not in str(caught.value)


def collector():
    spec = importlib.util.spec_from_file_location(
        "collector", ROOT / "scripts/collect_device_context.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_collector_requires_explicit_selection_before_queries(tmp_path, monkeypatch):
    module = collector()
    calls = []
    monkeypatch.setattr(module.MuMuManager, "inspect", lambda *args: calls.append(args))
    result = module.collect_context(
        manager=tmp_path / "MuMu Manager.exe",
        adb=tmp_path / "adb.exe",
        instance_index=None,
        serial=None,
        package=None,
    )
    assert result["status"] == "blocked"
    assert set(result["missing"]) == {"instance_index", "adb_serial", "package"}
    assert calls == []
    assert result["capabilities"] == []


def test_collector_nonzero_command_is_safe(tmp_path, monkeypatch):
    module = collector()

    def failed(*args, **kwargs):
        raise ProbeError("command_failed")

    monkeypatch.setattr(module.MuMuManager, "inspect", failed)
    result = module.collect_context(
        manager=tmp_path / "MuMu Manager.exe",
        adb=tmp_path / "adb.exe",
        instance_index="0",
        serial="127.0.0.1:16384",
        package="org.happyrun.app",
    )
    assert result["reason"] == "command_failed"
    assert result["capabilities"] == []
    assert "127.0.0.1" not in json.dumps(result)


@pytest.mark.parametrize("path_type", [Path, PureWindowsPath], ids=["native", "windows"])
def test_readonly_command_keeps_space_path_one_argument(monkeypatch, path_type):
    from swu_happyrun.drivers import command

    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return type("Result", (), {"returncode": 0, "stdout": "ok"})()

    monkeypatch.setattr(command.subprocess, "run", run)
    path = path_type("C:/MuMu Player/adb.exe")
    assert command.run_readonly(path, "-s", "serial", "get-state") == "ok"
    assert calls[0][0] == [str(path), "-s", "serial", "get-state"]
    assert calls[0][1]["shell"] is False


def test_private_output_refuses_outside_local_and_symlinks(tmp_path, symlink_or_skip):
    module = collector()
    with pytest.raises(ProbeError):
        module.write_private(tmp_path / "public.json", {"raw": "private"}, root=tmp_path)
    (tmp_path / "local").mkdir()
    module.write_private(tmp_path / "local" / "context.json", {"raw": "private"}, root=tmp_path)
    assert json.loads((tmp_path / "local" / "context.json").read_text()) == {"raw": "private"}
    symlink_or_skip(tmp_path / "local" / "link", tmp_path, target_is_directory=True)
    with pytest.raises(ProbeError):
        module.write_private(tmp_path / "local" / "link" / "leak.json", {}, root=tmp_path)


def test_collector_uses_existing_inspect_and_redacts_metadata(tmp_path, monkeypatch):
    module = collector()
    from swu_happyrun.core.models import DeviceCapability
    from swu_happyrun.drivers.mumu.manager import MuMuInstance

    calls = []

    def manager_inspect(self, index):
        calls.append(("manager", index))
        return [MuMuInstance(index, "15", True, True)]

    def adb_inspect(self):
        calls.append(("adb", self.serial, self.package))
        return DeviceCapability(
            device_id="00000000-0000-4000-8000-000000000001",
            backend="android",
            app_version="secret-version",
            capabilities=[],
            observed_at=NOW,
            probe_id="00000000-0000-4000-8000-000000000002",
        )

    monkeypatch.setattr(module.MuMuManager, "inspect", manager_inspect)
    monkeypatch.setattr(module.AdbClient, "inspect", adb_inspect)
    result = module.collect_context(
        manager=tmp_path / "MuMu Manager.exe",
        adb=tmp_path / "adb.exe",
        instance_index="0",
        serial="private-serial",
        package="org.happyrun.app",
    )
    assert calls == [("manager", "0"), ("adb", "private-serial", "org.happyrun.app")]
    assert result["reason"] == "binding_evidence_required"
    assert "secret-version" not in json.dumps(result)
    assert "private-serial" not in json.dumps(result)


def test_task5_display_parser_reused_and_stale_bundle_rejected():
    module = collector()
    observation = sample()["observation_id"]
    signature = "a" * 64
    raw = "\n".join(
        "INSTRUMENTATION_STATUS: " + item
        for item in [
            "state=observed",
            "observation_id=" + observation,
            "display_id=0",
            "task_id=12",
            "signature_sha256=" + signature,
            "writes=0",
            "activity=org.happyrun.app.MainActivity",
            "visible_controls=app_scroll,framework_probe,wizard_refresh",
        ]
    )
    raw += "\nINSTRUMENTATION_STATUS_CODE: 0\nOK (1 test)\nINSTRUMENTATION_CODE: -1"
    assert module.validate_display_replay(
        raw,
        code=0,
        observation_id=observation,
        display_id=0,
        task_id=12,
        signature_sha256=signature,
    )
    assert not module.validate_display_replay(
        raw,
        code=1,
        observation_id=observation,
        display_id=0,
        task_id=12,
        signature_sha256=signature,
    )
    assert not module.validate_display_replay(
        raw, code=0, observation_id="stale", display_id=0, task_id=12, signature_sha256=signature
    )


@pytest.mark.parametrize(
    "arguments",
    [
        ["--token", "secret-private-value"],
        ["--manager", "secret-private-value"],
    ],
)
def test_cli_errors_do_not_echo_sensitive_arguments(arguments, capsys):
    with pytest.raises(SystemExit):
        collector().main(arguments)
    captured = capsys.readouterr()
    assert "secret-private-value" not in captured.err


def test_cli_unknown_sensitive_arguments_do_not_echo(capsys):
    args = [
        "--manager",
        "manager.exe",
        "--adb",
        "adb.exe",
        "--instance",
        "0",
        "--serial",
        "serial",
        "--package",
        "org.happyrun.app",
        "--token",
        "secret-private-value",
    ]
    with pytest.raises(SystemExit):
        collector().main(args)
    assert "secret-private-value" not in capsys.readouterr().err


def test_missing_app_version_is_explicit(tmp_path, monkeypatch):
    module = collector()
    from swu_happyrun.core.models import DeviceCapability
    from swu_happyrun.drivers.mumu.manager import MuMuInstance

    monkeypatch.setattr(
        module.MuMuManager, "inspect", lambda self, index: [MuMuInstance(index, "15", True, True)]
    )
    monkeypatch.setattr(
        module.AdbClient,
        "inspect",
        lambda self: DeviceCapability(
            device_id="00000000-0000-4000-8000-000000000001",
            backend="android",
            app_version=None,
            capabilities=[],
            observed_at=NOW,
            probe_id="00000000-0000-4000-8000-000000000002",
        ),
    )
    report = module.collect_context(
        manager=tmp_path / "manager.exe",
        adb=tmp_path / "adb.exe",
        instance_index="0",
        serial="serial",
        package="org.happyrun.app",
    )
    assert "app_version" in report["missing"]
    assert report["writes"] == 0
    assert report["capabilities"] == []


def test_guard_failure_leaves_write_counter_zero():
    binding = resolve()
    observations = [sample() for _ in range(4)]
    observations[0]["mapped_adb_serial"] = "wrong-alias"
    observations[1]["observed_display_id"] = 1
    observations[2]["observed_at"] = (NOW - timedelta(seconds=31)).isoformat()
    observations[3]["boot_id"] = "restart"
    writes = []
    for observation in observations:
        with pytest.raises(ProbeError):
            binding.assert_current(observation, now=NOW)
            writes.append("would-write")
    assert writes == []
    assert binding.capabilities == ()


def test_same_identity_fresh_observation_preserves_original_calibration_anchor():
    binding = resolve()
    fresh = sample()
    later = NOW + timedelta(seconds=60)
    fresh["observed_at"] = later.isoformat()
    fresh["observation_id"] = "00000000-0000-4000-8000-000000000002"
    new_binding = api().resolve_binding(
        instance_index="0", adb_serial="127.0.0.1:16384", observation=fresh, now=later
    )
    assert new_binding.digest != binding.digest
    assert new_binding.identity_digest == binding.identity_digest
    assert binding.assert_current(fresh, now=later) is None
    with pytest.raises(ProbeError, match="binding_stale"):
        binding.assert_current(sample(), now=later)


@pytest.mark.parametrize(
    "field,value",
    [
        ("boot_id", "restarted-boot"),
        ("engine_version", "16"),
        ("app_version", "2.0"),
        ("package", "org.other.app"),
        ("display_id", 1),
        ("task_id", 13),
    ],
)
def test_fresh_observation_rejects_changed_identity(field, value):
    binding = resolve()
    fresh = sample()
    later = NOW + timedelta(seconds=60)
    fresh.update(
        observed_at=later.isoformat(), observation_id="00000000-0000-4000-8000-000000000002"
    )
    fresh[field] = value
    if field in {"display_id", "task_id"}:
        fresh["observed_" + field] = value
    with pytest.raises(ProbeError, match="binding_changed"):
        binding.assert_current(fresh, now=later)
