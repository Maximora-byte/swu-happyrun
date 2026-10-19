"""Negative fixtures for optional variant packaging; no actual framework execution."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("apk_check", ROOT / "scripts/check_selfprobe_apks.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def test_default_manifest_has_no_module():
    xml = (ROOT / "android/app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
    # AGP writes namespace into the compiled manifest; mimic that in this text fixture.
    checker.verify_manifest(
        xml.replace("<manifest ", '<manifest package="org.happyrun.app" '), False
    )


def test_class_check_distinguishes_reference_from_packaged_implementation():
    ordinary = "C d 1 1 85 org.happyrun.app.MainActivity\n"
    checker.verify_classes(ordinary + "C r 0 1 40 de.robv.android.xposed.XposedBridge\n", False)
    with pytest.raises(AssertionError):
        checker.verify_classes(ordinary + "C d 1 1 40 de.robv.android.xposed.XposedBridge\n", False)


def test_optional_entry_must_not_leak_into_ordinary_apk():
    output = "C d 1 1 85 " + checker.ENTRY
    with pytest.raises(AssertionError):
        checker.verify_classes(output, False)
    checker.verify_classes(output, True)


def test_dependency_is_exclusive_compile_only_and_verified():
    settings = (ROOT / "android/settings.gradle").read_text(encoding="utf-8")
    gradle = (ROOT / "android/app/build.gradle").read_text(encoding="utf-8")
    pin = json.loads(
        (ROOT / "android/dependency-pins/xposed-api-82.json").read_text(encoding="utf-8")
    )
    assert "exclusiveContent" in settings
    assert "https://api.xposed.info/" in settings
    assert "selfProbeCompileOnly('de.robv.android.xposed:api:82') { transitive = false }" in gradle
    assert pin["sha256"] in gradle
    assert "preSelfProbeBuild" in gradle and "dependsOn verifySelfProbeApi" in gradle
    assert "Xposed API must never be a runtime dependency" in gradle


def test_same_id_same_job_signing_is_not_parallel_installation():
    gradle = (ROOT / "android/app/build.gradle").read_text(encoding="utf-8")
    assert "applicationIdSuffix" not in gradle
    assert "signingConfig signingConfigs.debug" in gradle
    script = (ROOT / "scripts/android_selfprobe_acceptance.sh").read_text(encoding="utf-8")
    assert "run_inactive debug" in script and "run_inactive optional" in script
    assert "uninstall" not in script
    assert "su " not in script


def test_optional_scope_metadata_cannot_point_to_a_different_array():
    xml = (ROOT / "android/app/src/selfProbe/AndroidManifest.xml").read_text(encoding="utf-8")
    xml = xml.replace("<manifest ", '<manifest package="org.happyrun.app" ')
    checker.verify_manifest(xml, True)
    with pytest.raises(AssertionError):
        checker.verify_manifest(
            xml.replace("@array/happyrun_self_probe_scope", "@array/foreign"), True
        )


def test_variant_identity_does_not_infer_framework_activation():
    gradle = (ROOT / "android/app/build.gradle").read_text(encoding="utf-8")
    assert "buildFeatures { buildConfig true }" in gradle
    defaults, variants = gradle.split("    buildTypes {", 1)
    assert "buildConfigField 'boolean', 'SELF_PROBE_ENABLED', 'false'" in defaults
    assert "buildConfigField 'boolean', 'SELF_PROBE_ENABLED', 'true'" in variants


@pytest.mark.parametrize(
    "value",
    [
        '["org.happy", "run.app"]',
        '["org.happyrun.app", "foreign.package"]',
        '["org.happyrun.app", "org.happyrun.app"]',
        "['org.happyrun.app']",
    ],
)
def test_scope_rendering_never_concatenates_multiple_entries(value):
    with pytest.raises(AssertionError):
        checker.verify_scope_value(value)


@pytest.mark.parametrize("value", ["org.happyrun.app", '[ "org.happyrun.app" ]'])
def test_scope_rendering_accepts_exact_single_entry(value):
    checker.verify_scope_value(value)


def test_wizard_evidence_is_separate_and_runs_on_both_variants():
    script = (ROOT / "scripts/android_selfprobe_acceptance.sh").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/checks.yml").read_text(encoding="utf-8")
    assert "run_wizard debug" in script and "run_wizard optional" in script
    assert "org.happyrun.app.WizardAcceptanceTest" in script
    assert r"OK \(4 tests\)" in script
    assert "wizard-report.json" in script
    for filename in ("wizard-debug.txt", "wizard-optional.txt", "wizard-report.json"):
        assert f"qa/android/{filename}" in workflow
    assert 'root_command_executed":false' in script


def test_optional_emulator_overrides_retain_private_avd_guards():
    script = (ROOT / "scripts/android_emulator_test.sh").read_text(encoding="utf-8")
    for marker in (
        "HAPPYRUN_ANDROID_TEST_APK",
        "HAPPYRUN_ANDROID_ACCEPTANCE_SCRIPT",
        "ANDROID_AVD_HOME",
        'emulator -list-avds | grep -Fx "$avd"',
        'kill -0 "$pid"',
        "31) image_tag=default ;;",
    ):
        assert marker in script


def test_manifest_fixture_does_not_depend_on_windows_locale(monkeypatch):
    original = Path.read_text

    def cp1252_default(path, encoding=None, errors=None):
        return original(path, encoding=encoding or "cp1252", errors=errors)

    monkeypatch.setattr(Path, "read_text", cp1252_default)
    test_optional_scope_metadata_cannot_point_to_a_different_array()


# Exact array block observed with official aapt2 on the real 6427 CI APK.
RESOURCE_TABLE = """Binary APK
Package name=org.happyrun.app id=7f
  type array id=01 entryCount=1
    resource 0x7f010000 array/happyrun_self_probe_scope
      () (array) size=1
        ["org.happyrun.app"]
"""


@pytest.mark.parametrize("reference", ["@0x7f010000", "@ref/0x7f010000", "@7f010000"])
def test_compiled_numeric_scope_must_bind_to_exact_table_entry(reference):
    scope_id = checker.verify_resource_table(RESOURCE_TABLE)
    xml = (ROOT / "android/app/src/selfProbe/AndroidManifest.xml").read_text(encoding="utf-8")
    xml = xml.replace("<manifest ", '<manifest package="org.happyrun.app" ')
    xml = xml.replace("@array/happyrun_self_probe_scope", reference)
    checker.verify_manifest(xml, True, scope_id)
    with pytest.raises(AssertionError):
        checker.verify_manifest(xml, True, scope_id + 1)
    with pytest.raises(AssertionError):
        checker.verify_manifest(xml, True)


@pytest.mark.parametrize(
    "table",
    [
        RESOURCE_TABLE.replace("array/happyrun_self_probe_scope", "array/foreign"),
        RESOURCE_TABLE.replace('["org.happyrun.app"]', '["org.happy", "run.app"]'),
        RESOURCE_TABLE.replace("size=1", "size=2"),
        RESOURCE_TABLE.replace("Package name=org.happyrun.app", "Package name=foreign"),
        RESOURCE_TABLE.replace("() (array)", "(en) (array)"),
        RESOURCE_TABLE + '      (en) (array) size=1\n        ["foreign"]\n',
        RESOURCE_TABLE + '    resource 0x7f010000 string/foreign\n      () "foreign"\n',
    ],
)
def test_compiled_scope_table_rejects_misbinding_or_extra_values(table):
    with pytest.raises(AssertionError):
        checker.verify_resource_table(table)


def test_each_variant_uses_matching_instrumentation_and_full_native_suite():
    script = (ROOT / "scripts/android_selfprobe_acceptance.sh").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/checks.yml").read_text(encoding="utf-8")
    native = (ROOT / "scripts/android_acceptance.sh").read_text(encoding="utf-8")
    assert "assembleDebug assembleDebugAndroidTest assembleSelfProbe" in workflow
    assert "HAPPYRUN_ANDROID_TEST_APK:" not in workflow
    assert "androidTest/selfProbe/app-selfProbe-androidTest.apk" in script
    for variant in ("native-debug", "native-optional"):
        assert f'"$root/qa/android/{variant}"' in script
        assert f"qa/android/{variant}/report.json" in workflow
    assert '"tests":15' in native
    for method in (
        "EmptyUiStaysIdle",
        "TerminalUiStaysIdle",
        "ActiveProgressBackgroundReturnAndStop",
        "StorageLatchRemainsVisibleAndIdle",
    ):
        assert method in native
        for directory in ("qa/android", "qa/android/native-debug", "qa/android/native-optional"):
            assert f"{directory}/polling_{method}.txt" in workflow


def test_optional_observer_permissions_are_exact_and_never_allowed_in_debug():
    xml = (ROOT / "android/app/src/selfProbe/AndroidManifest.xml").read_text(encoding="utf-8")
    xml = xml.replace("<manifest ", '<manifest package="org.happyrun.app" ')
    checker.verify_manifest(xml, True)
    merged = xml.replace(
        "<application>",
        '<uses-permission android:name="android.permission.INTERNET"/><application>',
    )
    checker.verify_manifest(merged, True)
    for name in ("CAMERA", "ACCESS_BACKGROUND_LOCATION", "ACTIVITY_RECOGNITION"):
        with pytest.raises(AssertionError):
            checker.verify_manifest(
                merged.replace(
                    "<application>",
                    f'<uses-permission android:name="android.permission.{name}"/><application>',
                ),
                True,
            )
    with pytest.raises(AssertionError):
        checker.verify_manifest(merged, False)
    with pytest.raises(AssertionError):
        checker.verify_manifest(
            merged.replace("ACCESS_FINE_LOCATION", "ACCESS_COARSE_LOCATION"), True
        )
    with pytest.raises(AssertionError):
        checker.verify_manifest(
            merged.replace(
                '    <uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" />\n',
                "",
            ),
            True,
        )


def test_ordinary_manifest_rejects_location_without_module_metadata():
    xml = (ROOT / "android/app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
    xml = xml.replace("<manifest ", '<manifest package="org.happyrun.app" ')
    xml = xml.replace(
        "<application ",
        '<uses-permission android:name="android.permission.ACCESS_COARSE_LOCATION"/>'
        '<uses-permission android:name="android.permission.ACCESS_FINE_LOCATION"/>'
        "<application ",
    )
    with pytest.raises(AssertionError):
        checker.verify_manifest(xml, False)
