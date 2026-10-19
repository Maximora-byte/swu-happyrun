"""Static delivery boundaries; these do not claim an APK was built or run."""

import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_android_manifest_has_no_privileged_permissions():
    manifest = ET.parse(ROOT / "android/app/src/main/AndroidManifest.xml").getroot()
    assert not manifest.findall("uses-permission")
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
    assert len(activities) == 1
    assert activities[0].attrib[android + "name"] == ".MainActivity"


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
