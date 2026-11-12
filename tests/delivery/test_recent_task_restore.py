"""Restore only the observed own task on the system default display."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JAVA = ROOT / "android/app/src/androidTest/java/org/happyrun/app"


def test_default_display_restore_guard_is_dynamic_and_fail_closed(tmp_path):
    gate = JAVA / "DisplayObservationGate.java"
    assert "canRestoreOnDefaultDisplay" in gate.read_text(encoding="utf-8")
    harness = tmp_path / "RestoreCheck.java"
    harness.write_text(
        """package org.happyrun.app;
public final class RestoreCheck {
    public static void main(String[] args) {
        int[][] cases = {{7,7},{0,7},{7,0},{-1,-1},{-1,0},{0,-1},{0,0}};
        for (int n=0; n<cases.length; n++) {
            boolean allowed=DisplayObservationGate.canRestoreOnDefaultDisplay(
                cases[n][0],cases[n][1]);
            if (allowed != (n==0 || n==6)) throw new AssertionError("case="+n);
        }
    }
}""",
        encoding="utf-8",
    )
    compiled = subprocess.run(
        ["java", "com.sun.tools.javac.Main", "-d", str(tmp_path), str(gate), str(harness)],
        capture_output=True,
        text=True,
    )
    assert compiled.returncode == 0, compiled.stderr
    run = subprocess.run(
        ["java", "-cp", str(tmp_path), "org.happyrun.app.RestoreCheck"],
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr


def test_restore_uses_same_guarded_app_task_without_new_task_or_display_move():
    source = (JAVA / "DisplayObservationTest.java").read_text(encoding="utf-8")
    restore = source.index("tasks.get(0).moveToFront();")
    assert source.index("DisplayObservationGate.canRestoreOnDefaultDisplay(") < restore
    assert source.index("DisplayObservationGate.taskComponentsMatch(") < restore
    assert "getDisplay(Display.DEFAULT_DISPLAY)" in source
    assert "defaultDisplay.getDisplayId()" in source
    assert "tasks.get(0).startActivity(" not in source
    assert "setLaunchDisplayId" not in source
    assert "FLAG_ACTIVITY_" not in source
    assert source.index("DisplayObservationGate.accepts(", restore) > restore
