"""Static delivery boundaries; these do not claim an APK was built or run."""

import os
import shutil
import subprocess
import time
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_android_manifest_has_no_privileged_permissions():
    manifest = ET.parse(ROOT / "android/app/src/main/AndroidManifest.xml").getroot()
    assert [
        node.attrib["{http://schemas.android.com/apk/res/android}name"]
        for node in manifest.findall("uses-permission")
    ] == ["android.permission.INTERNET"]
    assert not manifest.findall("uses-permission-sdk-23")
    queries = manifest.findall("queries/package")
    assert [q.attrib["{http://schemas.android.com/apk/res/android}name"] for q in queries] == [
        "com.lptiyu.tanke"
    ]
    application = manifest.find("application")
    android = "{http://schemas.android.com/apk/res/android}"
    assert application is not None
    assert application.attrib[android + "allowBackup"] == "false"
    assert application.attrib[android + "usesCleartextTraffic"] == "false"
    activities = application.findall("activity")
    assert {node.attrib[android + "name"] for node in activities} == {
        ".MainActivity",
        ".RemoteAgentActivity",
    }
    remote = next(
        node for node in activities if node.attrib[android + "name"] == ".RemoteAgentActivity"
    )
    assert remote.attrib[android + "exported"] == "false"


def test_android_local_state_excluded_from_source_distribution():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    excludes = config["tool"]["hatch"]["build"]["targets"]["sdist"]["exclude"]
    for pattern in (
        "**/local.properties",
        "**/*.keystore",
        "**/*.jks",
        "**/.gradle/**",
        "**/.kotlin/**",
        "**/build/**",
        "**/*.apk",
    ):
        assert pattern in excludes
    assert "android/**" not in excludes
    assert "portable-build" not in config["project"]["optional-dependencies"]


def test_android_bootstrap_is_pinned_and_does_not_accept_licenses():
    bootstrap = (ROOT / "scripts/android_gradle.sh").read_text()
    assert "https://services.gradle.org/distributions/gradle-8.9-bin.zip" in bootstrap
    assert "d725d707bfabd4dfdc958c624003b3c80accc03f7037b5122c4b1d0ef15cecab" in bootstrap
    assert "sha256sum -c -" in bootstrap
    workflow = (ROOT / ".github/workflows/checks.yml").read_text()
    assert "lintDebug testDebugUnitTest assembleDebug assembleDebugAndroidTest" in workflow
    assert "sdkmanager --licenses" not in workflow
    assert "sudo chmod" not in workflow
    assert "contents: read" in workflow
    assert "api: [31, 35]" in workflow
    assert "android-debug-candidate-api${{ matrix.api }}" in workflow


def test_emulator_selects_stable_api31_image_without_license_acceptance():
    script = (ROOT / "scripts/android_emulator_test.sh").read_text()
    assert "31) image_tag=default ;;" in script
    assert "35) image_tag=google_apis ;;" in script
    assert 'system_image="system-images;android-$api;$image_tag;x86_64"' in script
    assert '"$sdk/system-images/android-$api/$image_tag/x86_64"' in script
    assert 'sdkmanager "$system_image" </dev/null' in script
    assert "sdkmanager --licenses" not in script
    assert "yes |" not in script


@pytest.mark.skipif(
    os.name != "posix" or shutil.which("bash") is None, reason="POSIX shell harness"
)
@pytest.mark.parametrize(
    "failure, expected",
    [
        ("sdk", "Official SDK installation failed"),
        ("ini", "AVD metadata missing after creation"),
        ("list", "Created AVD not visible to emulator"),
        ("exit", "Emulator exited before readiness"),
    ],
)
def test_emulator_bootstrap_failures_are_bounded(tmp_path, failure, expected):
    sdk = tmp_path / "sdk"
    tools = sdk / "cmdline-tools/latest/bin"
    tools.mkdir(parents=True)
    programs = {
        "sdkmanager": "exit 0\n",
        "avdmanager": 'touch "$ANDROID_AVD_HOME/happyrun-ci-api35.ini"\n',
        "emulator": 'if [ "$1" = -list-avds ]; then echo happyrun-ci-api35; exit 0; fi\n'
        "echo SYNTHETIC_EMULATOR_EXIT >&2\nexit 9\n",
        "adb": "exit 1\n",
    }
    if failure == "sdk":
        programs["sdkmanager"] = "exit 77\n"
    elif failure == "ini":
        programs["avdmanager"] = "exit 0\n"
    elif failure == "list":
        programs["emulator"] = "exit 0\n"
    for name, body in programs.items():
        path = tools / name
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)
    (sdk / "system-images/android-35/google_apis/x86_64").mkdir(parents=True)
    # Run a copied script so generated QA output cannot enter the source tree.
    copied = tmp_path / "project/scripts/android_emulator_test.sh"
    copied.parent.mkdir(parents=True)
    copied.write_bytes((ROOT / "scripts/android_emulator_test.sh").read_bytes())
    started = time.monotonic()
    result = subprocess.run(
        ["bash", str(copied)],
        env=dict(
            os.environ, ANDROID_HOME=str(sdk), RUNNER_TEMP=str(tmp_path), HAPPYRUN_ANDROID_API="35"
        ),
        capture_output=True,
        text=True,
        timeout=8,
    )
    assert result.returncode != 0
    assert time.monotonic() - started < 8
    assert expected in result.stderr
    if failure == "exit":
        assert "SYNTHETIC_EMULATOR_EXIT" in result.stderr
