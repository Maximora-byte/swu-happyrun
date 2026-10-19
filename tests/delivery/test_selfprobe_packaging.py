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
    xml = (ROOT / "android/app/src/main/AndroidManifest.xml").read_text()
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
    settings = (ROOT / "android/settings.gradle").read_text()
    gradle = (ROOT / "android/app/build.gradle").read_text()
    pin = json.loads((ROOT / "android/dependency-pins/xposed-api-82.json").read_text())
    assert "exclusiveContent" in settings
    assert "https://api.xposed.info/" in settings
    assert "selfProbeCompileOnly('de.robv.android.xposed:api:82') { transitive = false }" in gradle
    assert pin["sha256"] in gradle
    assert "preSelfProbeBuild" in gradle and "dependsOn verifySelfProbeApi" in gradle
    assert "Xposed API must never be a runtime dependency" in gradle


def test_same_id_same_job_signing_is_not_parallel_installation():
    gradle = (ROOT / "android/app/build.gradle").read_text()
    assert "applicationIdSuffix" not in gradle
    assert "signingConfig signingConfigs.debug" in gradle
    script = (ROOT / "scripts/android_selfprobe_acceptance.sh").read_text()
    assert "run_inactive debug" in script and "run_inactive optional" in script
    assert "uninstall" not in script
    assert "su " not in script


def test_optional_scope_metadata_cannot_point_to_a_different_array():
    xml = (ROOT / "android/app/src/selfProbe/AndroidManifest.xml").read_text()
    xml = xml.replace("<manifest ", '<manifest package="org.happyrun.app" ')
    checker.verify_manifest(xml, True)
    with pytest.raises(AssertionError):
        checker.verify_manifest(
            xml.replace("@array/happyrun_self_probe_scope", "@array/foreign"), True
        )


def test_variant_identity_does_not_infer_framework_activation():
    gradle = (ROOT / "android/app/build.gradle").read_text()
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
    script = (ROOT / "scripts/android_selfprobe_acceptance.sh").read_text()
    workflow = (ROOT / ".github/workflows/checks.yml").read_text()
    assert "run_wizard debug" in script and "run_wizard optional" in script
    assert "org.happyrun.app.WizardAcceptanceTest" in script
    assert r"OK \(4 tests\)" in script
    assert "wizard-report.json" in script
    for filename in ("wizard-debug.txt", "wizard-optional.txt", "wizard-report.json"):
        assert f"qa/android/{filename}" in workflow
    assert 'root_command_executed":false' in script


def test_optional_emulator_overrides_retain_private_avd_guards():
    script = (ROOT / "scripts/android_emulator_test.sh").read_text()
    for marker in (
        "HAPPYRUN_ANDROID_TEST_APK",
        "HAPPYRUN_ANDROID_ACCEPTANCE_SCRIPT",
        "ANDROID_AVD_HOME",
        'emulator -list-avds | grep -Fx "$avd"',
        'kill -0 "$pid"',
        "31) image_tag=default ;;",
    ):
        assert marker in script
