"""Only fixed enums and bounded numeric/boolean context may leave instrumentation output."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "display_diagnostics", ROOT / "scripts/check_mumu_observation.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_assertion_survives_without_raw_stack_or_private_text():
    assert hasattr(MODULE, "diagnostics"), "Failed observation discards its assertion diagnostics"
    raw = """INSTRUMENTATION_STATUS: observation_phase=tasks
INSTRUMENTATION_STATUS: observed_task_count=0
INSTRUMENTATION_STATUS_CODE: 2
ASSERTION_LINE
secret@example.com private-token
INSTRUMENTATION_STATUS_CODE: -2
INSTRUMENTATION_CODE: -1
"""
    raw = raw.replace(
        "ASSERTION_LINE",
        "INSTRUMENTATION_STATUS: stack="
        "junit.framework.AssertionFailedError: Do not guess among same-package tasks "
        "expected:<1> but was:<0>",
    )
    result = MODULE.diagnostics(raw, 0)
    assert result["last_phase"] == "tasks"
    assert result["assertion_code"] == "task_count_mismatch"
    assert result["observed_task_count"] == 0
    assert result["status_codes"] == [2, -2]
    assert "secret" not in str(result) and "private-token" not in str(result)
    assert "stack" not in result


def test_unknown_or_malformed_diagnostic_values_are_discarded():
    assert hasattr(MODULE, "diagnostics")
    raw = """INSTRUMENTATION_STATUS: observation_phase=private-token
INSTRUMENTATION_STATUS: observed_task_count=secret@example.com
INSTRUMENTATION_STATUS: observed_task_id=999999999999999999999999999
INSTRUMENTATION_STATUS: visible_controls=true private-token
INSTRUMENTATION_STATUS_CODE: 99999
"""
    result = MODULE.diagnostics(raw, 139)
    assert result["last_phase"] == "unknown"
    assert result["assertion_code"] == "unclassified"
    assert result["adb_exit"] == 139
    assert result["status_codes"] == []
    assert "observed_task_count" not in result and "observed_task_id" not in result
    assert "private-token" not in str(result)


def test_current_success_parser_result_is_not_relaxed_by_diagnostics():
    assert hasattr(MODULE, "diagnostics")
    raw = "INSTRUMENTATION_STATUS: observation_phase=success\nOK (1 test)\nINSTRUMENTATION_CODE: -1"
    assert not MODULE.accepted(raw, 0, "fresh", 0, 12, "abc")
    assert MODULE.diagnostics(raw, 0)["ok_one_test"]


def test_only_installed_identity_digest_and_version_are_retained():
    raw = (
        "INSTRUMENTATION_STATUS: installed_signature_sha256=" + "a" * 64 + "\n"
        "INSTRUMENTATION_STATUS: installed_version_code=1\n"
        "INSTRUMENTATION_STATUS: installed_package=org.happyrun.app\n"
        "INSTRUMENTATION_STATUS: installed_version_name=secret-token\n"
    )
    result = MODULE.diagnostics(raw, 0)
    assert result["installed_signature_sha256"] == "a" * 64
    assert result["installed_version_code"] == 1
    assert result["installed_package"] == "org.happyrun.app"
    assert "secret-token" not in str(result)
    assert "installed_signature_sha256" not in MODULE.diagnostics(
        raw.replace("a" * 64, "private"), 0
    )


def test_phase_status_bundles_do_not_weaken_or_break_bound_success():
    phase = (
        "INSTRUMENTATION_STATUS: observation_phase=signature\n"
        "INSTRUMENTATION_STATUS: signature_matches=1\n"
        "INSTRUMENTATION_STATUS_CODE: 2\n"
    )
    fields = {
        "state": "observed",
        "observation_id": "fresh",
        "display_id": "7",
        "task_id": "42",
        "signature_sha256": "abc",
        "writes": "0",
        "activity": "org.happyrun.app.MainActivity",
        "visible_controls": "app_scroll,framework_probe,wizard_refresh",
    }
    lines = ["INSTRUMENTATION_STATUS: " + key + "=" + value for key, value in fields.items()]
    good = phase + "\n".join(lines) + "\nINSTRUMENTATION_STATUS_CODE: 0\n" + phase
    good += "OK (1 test)\nINSTRUMENTATION_CODE: -1\n"
    assert MODULE.accepted(good, 0, "fresh", 7, 42, "abc")
    spliced = good.replace(
        "INSTRUMENTATION_STATUS: task_id=42",
        "INSTRUMENTATION_STATUS_CODE: 2\nINSTRUMENTATION_STATUS: task_id=42",
    )
    assert not MODULE.accepted(spliced, 0, "fresh", 7, 42, "abc")
    assert not MODULE.accepted(
        good.replace("display_id=7", "display_id=0"), 0, "fresh", 7, 42, "abc"
    )
