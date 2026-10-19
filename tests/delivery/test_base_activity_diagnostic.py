"""Classify both strict baseActivity assertions without publishing arbitrary component names."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "base_diagnostic", ROOT / "scripts/check_mumu_observation.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_null_base_activity_is_identified_without_relaxing_success():
    raw = (
        "INSTRUMENTATION_STATUS: base_activity_present=0\n"
        "INSTRUMENTATION_STATUS: base_activity_is_expected=0\n"
        "junit.framework.AssertionFailedError: Base activity must be present\n"
    )
    result = MODULE.diagnostics(raw, 0)
    assert result.get("base_activity_present") == 0
    assert result.get("base_activity_is_expected") == 0
    assert result["assertion_code"] == "base_activity_missing"
    assert not MODULE.accepted(raw, 0, "fresh", 0, 12, "abc")


def test_wrong_base_class_is_classified_without_echoing_it():
    raw = (
        "INSTRUMENTATION_STATUS: base_activity_present=1\n"
        "INSTRUMENTATION_STATUS: base_activity_is_expected=0\n"
        "junit.framework.ComparisonFailure: Base activity must match MainActivity "
        "expected:<org.happyrun.app.MainActivity> but was:<private.other.Activity>\n"
    )
    result = MODULE.diagnostics(raw, 0)
    assert result.get("base_activity_present") == 1
    assert result["assertion_code"] == "base_activity_mismatch"
    assert "private.other" not in str(result)
    assert not MODULE.accepted(raw, 0, "fresh", 0, 12, "abc")


def test_both_strict_instrumentation_assertions_remain():
    source = (
        ROOT / "android/app/src/androidTest/java/org/happyrun/app/DisplayObservationTest.java"
    ).read_text(encoding="utf-8")
    assert 'assertNotNull("Base activity must be present", baseActivity)' in source
    assert (
        'assertEquals("Base activity must match MainActivity", MainActivity.class.getName(),'
        in source
    )
    assert '"base_activity_present"' in source
    assert '"base_activity_is_expected"' in source
    assert "baseIntent" not in source
