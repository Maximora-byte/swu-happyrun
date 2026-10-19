"""Host assertions only. These checks do not claim Android execution."""

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/check_foreground_activity_https.py"
JAVA = (
    ROOT
    / "android/app/src/remoteQaAndroidTest/java/org/happyrun/app/remoteqa"
    / "RemoteForegroundActivityAcceptanceTest.java"
)


def validator():
    tree = ast.parse(SCRIPT.read_text())
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "require_instrumentation_success"
    )
    namespace = {"re": re}
    exec(  # noqa: S102 -- compile only the reviewed local assertion function, no external input
        compile(ast.Module(body=[function], type_ignores=[]), str(SCRIPT), "exec"),
        namespace,
    )
    return namespace[function.name]


def test_exact_instrumentation_success():
    validator()(0, ["OK (1 test)", "FOREGROUND_QA PASS starts=2 stopped=true"], 2)


@pytest.mark.parametrize(
    "returncode,lines",
    [
        (1, ["OK (1 test)", "FOREGROUND_QA PASS starts=2 stopped=true"]),
        (0, ["OK (0 tests)", "FOREGROUND_QA PASS starts=2 stopped=true"]),
        (0, ["OK (1 test)", "FOREGROUND_QA PASS starts=1 stopped=true"]),
        (0, ["OK (1 test)", "FOREGROUND_QA PASS starts=2 stopped=false"]),
        (0, ["OK (1 test)", "FOREGROUND_QA PASS starts=2 stopped=true", "FAILURES"]),
        (
            0,
            [
                "OK (1 test)",
                "FOREGROUND_QA PASS starts=2 stopped=true",
                "INSTRUMENTATION_ABORTED",
            ],
        ),
        (
            0,
            [
                "OK (1 test)",
                "FOREGROUND_QA PASS starts=2 stopped=true",
                "shortMsg=crash",
            ],
        ),
        (0, ["OK (1 test)", "FOREGROUND_QA PASS starts=2 stopped=true", "Exception"]),
        (
            0,
            [
                "OK (1 test)",
                "FOREGROUND_QA PASS starts=2 stopped=true",
                "FOREGROUND_QA PASS starts=2 stopped=true",
            ],
        ),
    ],
)
def test_rejects_partial_failed_or_ambiguous_output(returncode, lines):
    with pytest.raises(AssertionError):
        validator()(returncode, lines, 2)


def test_exact_fourteen_cases_and_no_original_runner_write():
    tree = ast.parse(SCRIPT.read_text())
    cases = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "CASES" for target in node.targets)
    )
    assert len(cases) == len(set(cases)) == 14
    assert {
        "two_jobs",
        "rapid_toggle",
        "auth_latch",
        "attention_latch",
        "transport_latch",
        "storage_latch",
    } <= set(cases)
    for action in ("disconnect", "back", "home", "rotate"):
        assert {action + "_idle", action + "_running"} <= set(cases)


def test_ui_uses_actual_platform_navigation_and_real_client_owner():
    source = JAVA.read_text()
    for forbidden in (
        "callActivityOnStop",
        "callActivityOnStart",
        "callActivityOnDestroy",
        ".recreate()",
        "FakeAgentClient",
        "setAccessible(true);f.set(",
    ):
        assert forbidden not in source
    for required in (
        "MainActivity.class",
        '"remote_entry"',
        '"remote_connect"',
        "KEYCODE_BACK",
        'executeShellCommand("input keyevent 3")',
        "setRequestedOrientation",
        "waitForActivityWithTimeout",
        '"session"',
        '"driver"',
        "noStoredCredential",
        "FLAG_SECURE",
    ):
        assert required in source
    assert "takeScreenshot" not in source
    assert "getUiAutomation().takeScreenshot" not in source
