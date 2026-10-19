"""Regression guard for the dedicated compiler job; no device/runtime grant."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/mumu-adapter-build-only.yml"


def check_build_only(text):
    forbidden = (
        "upload-artifact",
        "pull_request_target",
        "workflow_dispatch",
        "sudo ",
        "chmod ",
        "chown ",
        "/dev/kvm",
        "emulator",
        "platform-tools",
        "adb ",
        "connectedAndroidTest",
        "android_emulator_test",
        "android_remote_https_test",
        "check_ci_kvm",
        "--licenses",
        "continue-on-error",
        "secrets.",
    )
    if any(word in text for word in forbidden):
        raise ValueError("runtime_or_secret_boundary_expanded")
    required = (
        "contents: read",
        "persist-credentials: false",
        "timeout-minutes: 20",
        "github.repository == 'Maximora-byte/swu-happyrun'",
        "dot/mumu-own-https-runner",
        "head.repo.full_name == github.repository",
        "'platforms;android-35' 'build-tools;35.0.0' </dev/null",
        "JAVA_HOME_17_X64",
        "trap cleanup EXIT",
        'rm -rf -- "$private"',
        "-PremoteQaInstrumentation assembleRemoteQa assembleRemoteQaAndroidTest",
        "11d5960a326750d5838078e36cf38b85af677262",
    )
    if not all(word in text for word in required):
        raise ValueError("missing_build_only_boundary")


def test_dedicated_workflow_has_no_runtime_or_private_artifact():
    check_build_only(WORKFLOW.read_text())


@pytest.mark.parametrize(
    "addition",
    [
        "adb shell",
        "sudo chmod",
        "upload-artifact",
        "--licenses",
        "pull_request_target",
        "emulator",
        "secrets.TOKEN",
    ],
)
def test_runtime_and_private_upload_mutations_are_rejected(addition):
    with pytest.raises(ValueError):
        check_build_only(WORKFLOW.read_text() + "\n" + addition)


@pytest.mark.parametrize(
    "removed",
    [
        "trap cleanup EXIT",
        "contents: read",
        "head.repo.full_name == github.repository",
        "'platforms;android-35' 'build-tools;35.0.0' </dev/null",
    ],
)
def test_missing_identity_cleanup_or_sdk_boundary_rejected(removed):
    with pytest.raises(ValueError):
        check_build_only(WORKFLOW.read_text().replace(removed, ""))
