"""Mock-only ACL boundary tests; never changes host permissions."""

import importlib.util
import json
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("kvm_probe", ROOT / "scripts/check_ci_kvm.py")
assert SPEC and SPEC.loader
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)


@pytest.fixture
def setup(monkeypatch, tmp_path):
    for key, value in {
        "HAPPYRUN_KVM_APPROVED_THIS_RUN": "true",
        "GITHUB_ACTIONS": "true",
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_REF": "refs/heads/dot/android-app",
        "GITHUB_SHA": "a" * 40,
        "GITHUB_REPOSITORY": "Maximora-byte/swu-happyrun",
        "RUNNER_ENVIRONMENT": "github-hosted",
        "RUNNER_OS": "Linux",
        "HAPPYRUN_ANDROID_API": "31",
        "ANDROID_HOME": "/synthetic-sdk",
    }.items():
        monkeypatch.setenv(key, value)
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps(
            {
                "before": "629f2e9b86d7a72502f528abd1c1edf999d6a842",
                "after": "a" * 40,
                "ref": "refs/heads/dot/android-app",
                "repository": {"full_name": "Maximora-byte/swu-happyrun"},
            }
        )
    )
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    fake = SimpleNamespace(exists=lambda: True, stat=lambda: SimpleNamespace(st_mode=stat.S_IFCHR))

    class Device:
        def exists(self):
            return fake.exists()

        def stat(self):
            return fake.stat()

        def __str__(self):
            return "/dev/kvm"

    monkeypatch.setattr(PROBE, "Path", lambda p: Device() if p == "/dev/kvm" else Path(p))
    monkeypatch.setattr(PROBE.os, "getuid", lambda: 1001, raising=False)
    monkeypatch.setattr(PROBE.os, "access", lambda *args: True)
    commands = []
    monkeypatch.setattr(PROBE.subprocess, "run", lambda cmd, **kwargs: commands.append(cmd))
    return fake, commands


@pytest.mark.parametrize(
    "key,value",
    [
        ("HAPPYRUN_KVM_APPROVED_THIS_RUN", "false"),
        ("GITHUB_EVENT_NAME", "pull_request"),
        ("GITHUB_REF", "refs/heads/main"),
        ("GITHUB_ACTIONS", "false"),
        ("GITHUB_REPOSITORY", "other/repo"),
        ("RUNNER_ENVIRONMENT", "self-hosted"),
        ("RUNNER_OS", "Windows"),
        ("HAPPYRUN_ANDROID_API", "30"),
    ],
)
def test_unapproved_environment_never_calls_acl(setup, monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(SystemExit):
        PROBE.main()
    assert setup[1] == []


def test_only_current_named_user_acl_and_accel_check(setup):
    assert PROBE.main() == 0
    assert setup[1] == [
        ["sudo", "-n", "setfacl", "-n", "-m", "u:1001:rw", "/dev/kvm"],
        ["getfacl", "-n", "/dev/kvm"],
        ["/synthetic-sdk/emulator/emulator", "-accel-check"],
    ]


@pytest.mark.parametrize("kind", ["absent", "regular", "root", "acl", "access", "accel"])
def test_missing_device_or_failed_verification_blocks(setup, monkeypatch, kind):
    fake, commands = setup
    if kind == "absent":
        fake.exists = lambda: False
    elif kind == "regular":
        fake.stat = lambda: SimpleNamespace(st_mode=stat.S_IFREG)
    elif kind == "root":
        monkeypatch.setattr(PROBE.os, "getuid", lambda: 0)
    elif kind == "access":
        monkeypatch.setattr(PROBE.os, "access", lambda *args: False)
    else:

        def failed(cmd, **kwargs):
            commands.append(cmd)
            if (kind == "acl" and "setfacl" in cmd) or (kind == "accel" and "-accel-check" in cmd):
                raise subprocess.CalledProcessError(1, cmd)

        monkeypatch.setattr(PROBE.subprocess, "run", failed)
    with pytest.raises((SystemExit, subprocess.CalledProcessError)):
        PROBE.main()
    if kind in {"absent", "regular", "root"}:
        assert commands == []


def test_workflow_gate_binds_exact_single_transition():
    workflow = (ROOT / ".github/workflows/checks.yml").read_text()
    assert "github.event.before == '629f2e9b86d7a72502f528abd1c1edf999d6a842'" in workflow
    assert "github.ref == 'refs/heads/dot/android-app'" in workflow
    assert "github.event_name == 'push'" in workflow
    assert "workflow_dispatch:" not in workflow
    assert "sudo chmod" not in workflow


@pytest.mark.parametrize(
    "field,value",
    [
        ("before", "b" * 40),
        ("before", None),
        ("ref", "refs/heads/main"),
        ("after", "c" * 40),
        ("repository", {"full_name": "other/repo"}),
    ],
)
def test_future_or_wrong_event_never_grants(setup, monkeypatch, field, value):
    path = Path(PROBE.os.environ["GITHUB_EVENT_PATH"])
    event = json.loads(path.read_text())
    event[field] = value
    path.write_text(json.dumps(event))
    with pytest.raises(SystemExit, match="single reviewed"):
        PROBE.main()
    assert setup[1] == []
