"""Synthetic dumpsys and subprocess regressions for the disposable-AVD display entry."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def module():
    path = ROOT / "scripts/check_android_display_ci.py"
    assert path.exists(), "Actual AVD display suite helper is missing"
    spec = importlib.util.spec_from_file_location("display_ci", path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


GOOD = """ACTIVITY MANAGER ACTIVITIES (dumpsys activity activities)
Display #7 (activities from top to bottom):
  * Task{abc #42 type=standard A=10123:org.happyrun.app U=0 visible=true}
    topResumedActivity=ActivityRecord{abc u0 org.happyrun.app/.MainActivity t42}
    * Hist #0: ActivityRecord{abc u0 org.happyrun.app/.MainActivity t42}
Display #0 (activities from top to bottom):
  * Task{other #1 type=home A=999:other.app}
    topResumedActivity=ActivityRecord{other u0 other.app/.Home t1}
"""


def test_extracts_unique_nondefault_display_and_task():
    assert module().identity(GOOD) == (7, 42)
    api31 = GOOD.replace("topResumedActivity=", "mResumedActivity: ")
    assert module().identity(api31) == (7, 42)


@pytest.mark.parametrize(
    "text",
    [
        "",
        GOOD.replace("Display #7", "unknown display"),
        GOOD.replace("topResumedActivity=", "paused="),
        GOOD + "Display #9 (activities from top to bottom):\n"
        "  * Task{def #55 A=10123:org.happyrun.app}\n",
        GOOD.replace("t42", "t43"),
        GOOD.replace(".MainActivity", ".OtherActivity"),
        GOOD.replace("org.happyrun.app", "org.happyrun.app.other"),
    ],
)
def test_ambiguous_or_unresumed_identity_rejected(text):
    with pytest.raises(ValueError):
        module().identity(text)


def test_instrumentation_failure_markers_and_exact_count():
    checker = module()
    assert checker.case_passed("OK (1 test)\nINSTRUMENTATION_CODE: -1\n", 0)
    for text, code in [
        ("OK (1 test)", 139),
        ("OK (2 tests)", 0),
        ("OK (1 test)\nINSTRUMENTATION_FAILED", 0),
        ("OK (1 test)\nINSTRUMENTATION_STATUS_CODE: -2", 0),
    ]:
        assert not checker.case_passed(text, code)


@pytest.mark.parametrize("failure", ["", "dump", "case", "timeout"])
def test_ci_runs_only_bound_observation_and_six_selected_cases(monkeypatch, tmp_path, failure):
    import json
    import subprocess

    helper = module()
    delivery = tmp_path / "delivery.json"
    delivery.write_text(
        json.dumps(
            {
                "certificate_sha256": "a" * 64,
                "app_package": "org.happyrun.app",
                "test_package": "org.happyrun.app.test",
                "instrumentation_runner": "android.test.InstrumentationTestRunner",
            }
        )
    )
    output = tmp_path / "out"
    monkeypatch.setenv("ANDROID_SERIAL", "emulator-5556")
    monkeypatch.setenv("HAPPYRUN_DISPOSABLE_EMULATOR", "1")
    monkeypatch.setattr(
        "sys.argv", ["display", "--delivery", str(delivery), "--output", str(output)]
    )
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        assert kwargs["timeout"] <= 45
        joined = " ".join(command)
        code, text = 0, ""
        if "getprop" in command:
            text = "1\n"
        elif "start" in command:
            text = "Status: ok\n"
        elif "dumpsys" in command:
            code, text = (139 if failure == "dump" else 0), GOOD
        elif "check_mumu_observation.py" in joined:
            if failure == "timeout":
                raise subprocess.TimeoutExpired(command, 40)
            assert command[command.index("--display") + 1] == "7"
            assert command[command.index("--task") + 1] == "42"
            (output / "observation.json").write_text(
                json.dumps({"result": "observed", "writes": 0})
            )
        elif "instrument" in command:
            text = "OK (1 test)\nINSTRUMENTATION_CODE: -1\n"
            if failure == "case":
                text += "INSTRUMENTATION_STATUS_CODE: -2\n"
        else:
            raise AssertionError(command)
        return subprocess.CompletedProcess(command, code, text, "")

    monkeypatch.setattr(helper.subprocess, "run", run)
    assert helper.main() == (1 if failure else 0)
    report = json.loads((output / "report.json").read_text())
    assert report["writes"] == 0
    assert not report["mumu_verified"]
    if not failure:
        assert report["tests"] == 7
        assert len(commands) == 10
        assert report["cases"][1:] == list(helper.METHODS)
    else:
        assert report["result"] == "failed"
        assert report["tests"] < 7
    assert not {"clear", "uninstall", "input", "tap", "su", "force-stop"} & {
        value for command in commands for value in command
    }
