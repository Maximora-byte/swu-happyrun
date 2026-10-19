"""Compile the exact task component guard used before the own AppTask launch."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "android/app/src/androidTest/java/org/happyrun/app/DisplayObservationGate.java"


def test_persisted_task_identity_survives_absent_live_activity_and_rejects_ambiguity(tmp_path):
    assert "taskComponentsMatch" in GATE.read_text(encoding="utf-8"), (
        "Prelaunch gate rejects the observed stopped task without a live baseActivity"
    )
    harness = tmp_path / "TaskCheck.java"
    harness.write_text(
        """package org.happyrun.app;
public final class TaskCheck {
    public static void main(String[] args) {
        String pkg = "org.happyrun.app", main = pkg + ".MainActivity";
        String[][] cases = {
            {pkg, main, null, null},
            {pkg, main, pkg, main},
            {null, null, null, null},
            {"other.app", main, null, null},
            {pkg, pkg + ".RemoteAgentActivity", null, null},
            {pkg, main, "other.app", main},
            {pkg, main, pkg, pkg + ".RemoteAgentActivity"},
            {null, null, pkg, main},
            {pkg, main, pkg, null},
            {pkg, main, null, main},
            {pkg, ".MainActivity", null, null}
        };
        for (int n = 0; n < cases.length; n++) {
            String[] c = cases[n];
            boolean allowed = DisplayObservationGate.taskComponentsMatch(c[0], c[1], c[2], c[3]);
            if (allowed != (n < 2)) throw new AssertionError("case=" + n);
            int writes = allowed ? 1 : 0;
            if (n >= 2 && writes != 0) throw new AssertionError("unexpected authorized write");
        }
        // Component proof only permits own task launch, never bypasses final observed identity.
        DisplayObservationGate.Snapshot s = new DisplayObservationGate.Snapshot();
        s.observationId="fresh"; s.packageName=pkg; s.activity=main; s.signature="cert";
        s.display=7; s.task=42; s.taskCount=1; s.window=true; s.controls=true;
        s.started=100; s.captured=101; s.finished=102;
        if (!DisplayObservationGate.accepts(s,"fresh",7,42,"cert",200)) throw new AssertionError();
        if (DisplayObservationGate.accepts(s,"fresh",0,42,"cert",200)) throw new AssertionError();
        if (DisplayObservationGate.accepts(s,"fresh",7,41,"cert",200)) throw new AssertionError();
        if (DisplayObservationGate.accepts(s,"fresh",7,42,"wrong",200)) throw new AssertionError();
        if (DisplayObservationGate.accepts(s,"old",7,42,"cert",200)) throw new AssertionError();
        System.out.println("11 component cases and final identity rejection checks passed");
    }
}""",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["java", "com.sun.tools.javac.Main", "-d", str(tmp_path), str(GATE), str(harness)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run(
        ["java", "-cp", str(tmp_path), "org.happyrun.app.TaskCheck"], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
