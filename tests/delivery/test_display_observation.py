"""Compile the same fail-closed gate used by the Android instrumentation entry."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "android/app/src/androidTest/java/org/happyrun/app/DisplayObservationGate.java"


def test_observation_gate_rejects_every_ambiguous_snapshot_without_writes(tmp_path):
    assert GATE.exists(), "The MuMu observation gate is not implemented"
    harness = tmp_path / "GateCheck.java"
    harness.write_text("""package org.happyrun.app;
public final class GateCheck {
    public static void main(String[] args) {
        DisplayObservationGate.Snapshot s = new DisplayObservationGate.Snapshot();
        s.observationId = "fresh"; s.packageName = "org.happyrun.app";
        s.activity = "org.happyrun.app.MainActivity"; s.signature = "abc";
        s.display = 7; s.task = 42; s.taskCount = 1; s.window = true;
        s.controls = true; s.started = 100; s.captured = 101; s.finished = 102;
        for (int scenario = 0; scenario < 12; scenario++) {
            s.display = 7; s.task = 42; s.taskCount = 1; s.window = true;
            s.observationId = "fresh"; s.dumpExit = 0; s.finished = 102;
            s.controls = true; s.signature = "abc"; s.packageName = "org.happyrun.app";
            s.captured = 101;
            switch (scenario) {
                case 0: s.display = 0; break;
                case 1: s.observationId = "stale"; break;
                case 2: s.dumpExit = 139; break;
                case 3: s.taskCount = 2; break;
                case 4: s.window = false; break;
                case 5: s.finished = 501; break;
                case 6: s.task = 9; break;
                case 7: s.controls = false; break;
                case 8: s.signature = "other"; break;
                case 9: s.packageName = "other.app"; break;
                case 10: s.captured = 99; break;
                default: break;
            }
            boolean accepted = DisplayObservationGate.accepts(s, "fresh", 7, 42, "abc", 200);
            int writes = 0;
            if (accepted) writes++;
            if (accepted != (scenario == 11) || (scenario != 11 && writes != 0))
                throw new AssertionError("scenario=" + scenario + " writes=" + writes);
        }
        System.out.println("11 rejected snapshots: writes=0; fresh display accepted");
    }
}""")
    result = subprocess.run(
        ["java", "com.sun.tools.javac.Main", "-d", str(tmp_path), str(GATE), str(harness)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run(
        ["java", "-cp", str(tmp_path), "org.happyrun.app.GateCheck"], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_host_observation_requires_current_bound_result():
    import importlib.util

    script = ROOT / "scripts/check_mumu_observation.py"
    assert script.exists(), "Bounded MuMu observation host entry is missing"
    spec = importlib.util.spec_from_file_location("mumu_observation", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    good = "\n".join(
        [
            "INSTRUMENTATION_STATUS: state=observed",
            "INSTRUMENTATION_STATUS: observation_id=fresh",
            "INSTRUMENTATION_STATUS: display_id=7",
            "INSTRUMENTATION_STATUS: task_id=42",
            "INSTRUMENTATION_STATUS: signature_sha256=abc",
            "INSTRUMENTATION_STATUS: activity=org.happyrun.app.MainActivity",
            "INSTRUMENTATION_STATUS: writes=0",
            "INSTRUMENTATION_STATUS: visible_controls=app_scroll,framework_probe,wizard_refresh",
            "INSTRUMENTATION_STATUS_CODE: 0",
            "OK (1 test)",
            "INSTRUMENTATION_CODE: -1",
        ]
    )
    assert module.accepted(good, 0, "fresh", 7, 42, "abc")
    for text, code in [
        (good, 139),
        (good.replace("fresh", "stale"), 0),
        (good.replace("display_id=7", "display_id=0"), 0),
        (good.replace("writes=0", "writes=1"), 0),
        (good + "\nINSTRUMENTATION_FAILED", 0),
        (good.replace("OK (1 test)", ""), 0),
        (good.replace("task_id=42", "task_id=43"), 0),
        (good.replace("signature_sha256=abc", "signature_sha256=bad"), 0),
        (good.replace("INSTRUMENTATION_STATUS_CODE: 0", ""), 0),
    ]:
        assert not module.accepted(text, code, "fresh", 7, 42, "abc")


def test_host_timeout_fails_with_zero_test_writes(monkeypatch, tmp_path):
    import importlib.util
    import json

    spec = importlib.util.spec_from_file_location(
        "mumu_timeout", ROOT / "scripts/check_mumu_observation.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = tmp_path / "result.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "observe",
            "--serial",
            "selected-instance",
            "--display",
            "7",
            "--task",
            "42",
            "--signature-sha256",
            "a" * 64,
            "--isolated-no-personal-data",
            "--output",
            str(output),
        ],
    )
    commands = []

    def timeout(command, **kwargs):
        commands.append(command)
        assert kwargs["timeout"] == 30
        raise subprocess.TimeoutExpired(command, 30)

    monkeypatch.setattr(module.subprocess, "run", timeout)
    assert module.main() == 1
    report = json.loads(output.read_text())
    assert report["result"] == "failed"
    assert report["writes"] == 0
    assert report["reason"] == "host_timeout_device_runner_may_still_be_active"
    assert len(commands) == 1
    assert commands[0][:7] == ["adb", "-s", "selected-instance", "shell", "am", "instrument", "-w"]
    assert not {"clear", "uninstall", "input", "tap", "su", "force-stop"} & set(commands[0])


def test_visible_control_contract_requires_viewport_intersection():
    source = (
        ROOT / "android/app/src/androidTest/java/org/happyrun/app/DisplayObservationTest.java"
    ).read_text()
    assert "getGlobalVisibleRect" in source, "isShown alone accepts offscreen ScrollView children"
    assert 'shown(observed, "framework_probe")' in source
    assert 'shown(observed, "wizard_refresh")' in source
    assert 'shown(observed, "start_simulation")' not in source
