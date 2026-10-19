"""Exercise the actual Java viewport loop policy before allowing any final observation."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JAVA = ROOT / "android/app/src/androidTest/java/org/happyrun/app"


def test_transient_unattached_window_waits_but_never_passes(tmp_path):
    gate = JAVA / "DisplayObservationGate.java"
    assert "shouldAwaitViewport" in gate.read_text(encoding="utf-8")
    harness = tmp_path / "WaitCheck.java"
    harness.write_text(
        """package org.happyrun.app;
public final class WaitCheck {
    public static void main(String[] args) {
        DisplayObservationGate.Snapshot s=new DisplayObservationGate.Snapshot();
        s.task=12; s.taskCount=1; s.finished=100; s.display=-1;
        s.observationId="fresh"; s.packageName="org.happyrun.app";
        s.activity="org.happyrun.app.MainActivity"; s.signature="cert";
        s.started=90; s.captured=100;
        check(DisplayObservationGate.shouldAwaitViewport(s,7,12,200), "unattached must wait");
        check(!DisplayObservationGate.accepts(s,"fresh",7,12,"cert",200), "unknown cannot pass");
        s.display=7; s.finished=110; s.captured=110;
        check(DisplayObservationGate.shouldAwaitViewport(s,7,12,200), "layout still waits");
        s.window=true; s.controls=true;
        check(!DisplayObservationGate.shouldAwaitViewport(s,7,12,200), "ready ends wait");
        check(DisplayObservationGate.accepts(s,"fresh",7,12,"cert",200), "exact ready passes");
        s.display=0;
        check(!DisplayObservationGate.shouldAwaitViewport(s,7,12,200), "wrong display stops");
        check(!DisplayObservationGate.accepts(s,"fresh",7,12,"cert",200), "wrong never passes");
        s.display=-1; s.window=false; s.controls=false;
        for (long t=120;t<200;t+=10) {
            s.finished=t;
            check(DisplayObservationGate.shouldAwaitViewport(s,7,12,200), "bounded wait");
        }
        s.finished=200;
        check(!DisplayObservationGate.shouldAwaitViewport(s,7,12,200), "deadline stops");
        check(!DisplayObservationGate.accepts(s,"fresh",7,12,"cert",200), "timeout fails");
        s.finished=100; s.task=13;
        check(!DisplayObservationGate.shouldAwaitViewport(s,7,12,200), "wrong task stops");
        s.task=12; s.taskCount=2;
        check(!DisplayObservationGate.shouldAwaitViewport(s,7,12,200), "multiple tasks stops");
        s.taskCount=1; s.display=-2;
        check(!DisplayObservationGate.shouldAwaitViewport(s,7,12,200), "invalid sentinel stops");
    }
    static void check(boolean value,String label) { if(!value) throw new AssertionError(label); }
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
        ["java", "-cp", str(tmp_path), "org.happyrun.app.WaitCheck"], capture_output=True, text=True
    )
    assert run.returncode == 0, run.stderr


def test_android_loop_uses_wait_policy_and_preserves_strict_final_gate():
    source = (JAVA / "DisplayObservationTest.java").read_text(encoding="utf-8")
    assert (
        "if (!DisplayObservationGate.shouldAwaitViewport(s, display, task, started + 10000))"
        in source
    )
    assert "s.task != task || s.display != display" not in source
    assert "SystemClock.sleep(50)" in source
    assert "DisplayObservationGate.accepts(s, id, display, task, expectedSignature" in source
