import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "install_mumu_probe.py"
SPEC = importlib.util.spec_from_file_location("happyrun_probe_installer", SCRIPT)
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class FakeTransport:
    host_version = "6.8.4.0"
    android_api = 35
    adb = Path("synthetic-adb.exe")
    serial = "private-serial-must-not-be-printed"

    def __init__(self):
        self.connected = []
        self.current_checks = 0
        self.change_at = None

    def inventory(self):
        return [{"index": "5", "running": True}]

    def connect(self, index):
        self.connected.append(index)

    def assert_current(self):
        self.current_checks += 1
        if self.current_checks == self.change_at:
            raise installer.InstallError("binding_changed")


@pytest.fixture
def package(tmp_path):
    directory = tmp_path / "Android"
    directory.mkdir()
    for name in ("probe.apk", "probe-test.apk"):
        (directory / name).write_bytes(b"synthetic APK fixture; never installed")
    return tmp_path


def fake_runner(
    *, failure_at=None, failure=(b"Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE]", b"", 0)
):
    calls = []

    def run(path, *args, timeout):
        calls.append((path, args, timeout))
        assert path == FakeTransport.adb
        assert args[:2] == ("-s", FakeTransport.serial)
        assert 0 < timeout <= 60
        if len(calls) == failure_at:
            return failure
        if args[2] == "install":
            return b"Performing Streamed Install\r\nSuccess\r\n", b"", 0
        if args[2:5] == ("shell", "pm", "grant"):
            return b"", b"", 0
        if args[2:5] == ("shell", "dumpsys", "package"):
            return (
                b"\n".join(
                    permission.encode() + b": granted=true, flags=[ USER_SET ]"
                    for permission in installer.PERMISSIONS
                ),
                b"",
                0,
            )
        if args[2:5] == ("shell", "am", "start"):
            return b"Status: ok\nActivity: org.happyrun.app/.MainActivity\n", b"", 0
        raise AssertionError("unexpected installer command")

    return run, calls


def test_success_installs_both_before_own_permissions_and_optional_own_activity(package):
    transport = FakeTransport()
    runner, calls = fake_runner()
    installer.install_probe(
        package, "5", transport_factory=lambda: transport, runner=runner, open_app=True
    )
    assert transport.connected == ["5"]
    commands = [args[2:] for _, args, _ in calls]
    assert commands[:2] == [
        ("install", "-r", str((package / "Android" / name).absolute()))
        for name in ("probe.apk", "probe-test.apk")
    ]
    assert commands[2:4] == [
        ("shell", "pm", "grant", "org.happyrun.app", permission)
        for permission in installer.PERMISSIONS
    ]
    assert commands[4] == ("shell", "dumpsys", "package", "org.happyrun.app")
    assert commands[5] == ("shell", "am", "start", "-W", "-n", "org.happyrun.app/.MainActivity")
    assert len(calls) == 6


@pytest.mark.parametrize("failure_at", [1, 2])
@pytest.mark.parametrize(
    "failure",
    [
        (b"Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE]", b"", 0),
        (b"Performing Streamed Install", b"", 0),
        (b"Success", b"", 1),
        (b"Success", b"error: transport closed", 0),
        (b"Success\nFailure [INSTALL_FAILED_INVALID_APK]", b"", 0),
    ],
)
def test_any_install_failure_or_signature_mismatch_halts_without_grants(
    package, failure_at, failure
):
    runner, calls = fake_runner(failure_at=failure_at, failure=failure)
    with pytest.raises(installer.InstallError, match="probe_install_failed"):
        installer.install_probe(package, "5", transport_factory=FakeTransport, runner=runner)
    assert len(calls) == failure_at
    assert all(args[2] == "install" for _, args, _ in calls)


@pytest.mark.parametrize("failure_at", [3, 4, 5])
def test_permission_failure_halts_without_later_grant_or_activity(package, failure_at):
    runner, calls = fake_runner(failure_at=failure_at, failure=(b"Error: denied", b"", 0))
    expected = "permission_readback_failed" if failure_at == 5 else "permission_grant_failed"
    with pytest.raises(installer.InstallError, match=expected):
        installer.install_probe(
            package, "5", transport_factory=FakeTransport, runner=runner, open_app=True
        )
    assert len(calls) == failure_at


def test_binding_change_between_installs_stops_before_second_apk(package):
    transport = FakeTransport()
    transport.change_at = 2
    runner, calls = fake_runner()
    with pytest.raises(installer.InstallError, match="binding_changed"):
        installer.install_probe(package, "5", transport_factory=lambda: transport, runner=runner)
    assert len(calls) == 1


def test_timeout_after_spawn_never_retries_or_grants(package):
    calls = []

    def timed_out(path, *args, timeout):
        calls.append(args)
        raise installer.InstallError("command_timeout")

    with pytest.raises(installer.InstallError, match="command_timeout"):
        installer.install_probe(package, "5", transport_factory=FakeTransport, runner=timed_out)
    assert len(calls) == 1
    assert calls[0][2:4] == ("install", "-r")


@pytest.mark.parametrize("index", ["５", "5&whoami", "-1", "123456789", "5 ", ""])
def test_invalid_index_never_discovers_or_runs_a_command(package, index):
    def forbidden():
        raise AssertionError("invalid input reached device discovery")

    with pytest.raises(installer.InstallError, match="instance_index_invalid"):
        installer.install_probe(package, index, transport_factory=forbidden)


def test_wrong_api_stops_before_install(package):
    transport = FakeTransport()
    transport.android_api = 34
    runner, calls = fake_runner()
    with pytest.raises(installer.InstallError, match="transport_version_unverified"):
        installer.install_probe(package, "5", transport_factory=lambda: transport, runner=runner)
    assert not calls


def test_missing_pair_does_not_even_discover(package):
    (package / "Android" / "probe-test.apk").unlink()

    def forbidden():
        raise AssertionError("missing APK reached device discovery")

    with pytest.raises(installer.InstallError, match="probe_apk_missing"):
        installer.install_probe(package, "5", transport_factory=forbidden)


def test_main_prompt_is_python_validated_and_does_not_print_private_output(package, monkeypatch):
    monkeypatch.setattr(installer, "__file__", str(package / "install_mumu_probe.py"))
    runner, calls = fake_runner(
        failure_at=1,
        failure=(b"Failure private-serial-must-not-be-printed secret-user-path", b"", 0),
    )
    output = []
    code = installer.main(
        [],
        transport_factory=FakeTransport,
        runner=runner,
        input_fn=lambda prompt: "5",
        output=output.append,
    )
    assert code == 3
    assert len(calls) == 1
    assert "probe_install_failed" in output[0]
    assert "private-serial" not in " ".join(output)
    assert "secret-user-path" not in " ".join(output)


def test_main_invalid_prompt_returns_two_without_device_discovery(package, monkeypatch):
    monkeypatch.setattr(installer, "__file__", str(package / "install_mumu_probe.py"))
    output = []
    assert installer.main([], input_fn=lambda prompt: "5&whoami", output=output.append) == 2
    assert "instance_index_invalid" in output[0]
