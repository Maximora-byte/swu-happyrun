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
        "GITHUB_REF": "refs/heads/dot/android-foreground-agent",
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
                "before": "481098f124f0fb5ea054180d1ecb845008348003",
                "after": "a" * 40,
                "ref": "refs/heads/dot/android-foreground-agent",
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
        [str(Path("/synthetic-sdk") / "emulator/emulator"), "-accel-check"],
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
    workflow = (ROOT / ".github/workflows/checks.yml").read_text(encoding="utf-8")
    assert "github.event.before == '481098f124f0fb5ea054180d1ecb845008348003'" in workflow
    assert "github.ref == 'refs/heads/dot/android-foreground-agent'" in workflow
    assert "github.event_name == 'push'" in workflow
    assert "workflow_dispatch:" not in workflow
    assert "sudo chmod" not in workflow


@pytest.mark.parametrize(
    "field,value",
    [
        ("before", "b" * 40),
        ("before", "e5b3b973f9e055fc8bcb4a9e3261cf6320568787"),
        ("before", "77494e21756e514f53e51b3a2c72f22555f0aae6"),
        ("before", "491019d0b68802fdcf0c67fbe4bd3b846a9eae82"),
        ("before", "6427e91b7099cdf2233983ff55a5bcf9718e6b61"),
        ("before", None),
        ("ref", "refs/heads/main"),
        ("after", "c" * 40),
        ("repository", {"full_name": "other/repo"}),
    ],
)
def test_future_or_wrong_event_never_grants(setup, monkeypatch, field, value):
    path = Path(PROBE.os.environ["GITHUB_EVENT_PATH"])
    event = json.loads(path.read_text(encoding="utf-8"))
    event[field] = value
    path.write_text(json.dumps(event))
    with pytest.raises(SystemExit, match="single reviewed"):
        PROBE.main()
    assert setup[1] == []


def synchronize_event(monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_REF", "refs/pull/33/merge")
    path = Path(PROBE.os.environ["GITHUB_EVENT_PATH"])
    event = json.loads(path.read_text(encoding="utf-8"))
    event.update(
        {
            "action": "synchronize",
            "number": 33,
            "pull_request": {
                "head": {
                    "sha": "a" * 40,
                    "ref": "dot/android-foreground-agent",
                    "repo": {"full_name": "Maximora-byte/swu-happyrun"},
                },
                "base": {"repo": {"full_name": "Maximora-byte/swu-happyrun"}},
            },
        }
    )
    path.write_text(json.dumps(event), encoding="utf-8")
    return path, event


def test_pull_requests_are_not_this_reviewed_push(setup, monkeypatch):
    synchronize_event(monkeypatch)
    with pytest.raises(SystemExit):
        PROBE.main()
    assert setup[1] == []


@pytest.mark.parametrize(
    "change",
    [
        "missing_before",
        "missing_after",
        "opened",
        "wrong_pr",
        "fork",
        "wrong_head",
        "wrong_after",
        "wrong_base_repo",
        "wrong_ref",
    ],
)
def test_untrusted_or_incomplete_pr_payload_never_grants(setup, monkeypatch, change):
    path, event = synchronize_event(monkeypatch)
    if change.startswith("missing_"):
        event.pop(change.removeprefix("missing_"))
    elif change == "opened":
        event["action"] = "opened"
    elif change == "wrong_pr":
        event["number"] = 34
    elif change == "fork":
        event["pull_request"]["head"]["repo"]["full_name"] = "other/swu-happyrun"
    elif change == "wrong_head":
        event["pull_request"]["head"]["ref"] = "main"
    elif change == "wrong_after":
        event["after"] = "b" * 40
    elif change == "wrong_base_repo":
        event["pull_request"]["base"]["repo"]["full_name"] = "other/repo"
    else:
        monkeypatch.setenv("GITHUB_REF", "refs/pull/34/merge")
    path.write_text(json.dumps(event), encoding="utf-8")
    with pytest.raises(SystemExit):
        PROBE.main()
    assert setup[1] == []


def test_previous_288_transition_cannot_reuse_acl(setup, monkeypatch):
    import os

    path = Path(os.environ["GITHUB_EVENT_PATH"])
    event = json.loads(path.read_text())
    event["before"] = "28871b2d599a8ec8335570effb3207d2564639ab"
    path.write_text(json.dumps(event))
    with pytest.raises(SystemExit):
        PROBE.main()
    assert setup[1] == []
