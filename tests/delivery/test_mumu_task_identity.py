"""Run the exact adapter task-check block with synthetic snapshots, never a device."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (
    ROOT
    / "android/app/src/remoteQaAndroidTest/java/org/happyrun/app/remoteqa"
    / "RemoteMumuHttpsAcceptanceTest.java"
)


@pytest.fixture(scope="module")
def task_harness(tmp_path_factory):
    source = SOURCE.read_text(encoding="utf-8")
    start = source.index('        assertEquals("Own task must be unambiguous"')
    end = source.index("        // No UI action", start)
    block = source[start:end]
    java = shutil.which("java")
    if java is None:
        pytest.skip("JVM unavailable; no Android validation claimed")
    directory = tmp_path_factory.mktemp("task-identity-jvm")
    harness = r"""
import java.util.*;
public class TaskHarness {
    static final String PACKAGE = "org.happyrun.app";
    static class ComponentName {
        String name;
        String className = PACKAGE + ".MainActivity";
        String getClassName() { return className; }
        ComponentName(String value) { name = value; }
        String getPackageName() { return name; }
    }
    static class Intent {
        ComponentName component;
        Intent(String value) { component = value == null ? null : new ComponentName(value); }
        ComponentName getComponent() { return component; }
    }
    static class ApplicationInfo { int uid = 123; }
    static class ActivityInfo {
        String packageName = PACKAGE, name = PACKAGE + ".MainActivity";
        ApplicationInfo applicationInfo = new ApplicationInfo();
    }
    static class PackageManager {
        ActivityInfo info = new ActivityInfo();
        ActivityInfo getActivityInfo(ComponentName component, int flags) throws Exception {
            if (component.className.equals("missing.Activity")) throw new NameNotFoundException();
            return info;
        }
    }
    static class NameNotFoundException extends Exception { }
    static class Context {
        PackageManager pm = new PackageManager();
        PackageManager getPackageManager() { return pm; }
        ApplicationInfo getApplicationInfo() { return new ApplicationInfo(); }
    }
    static Context context = new Context();
    static class ActivityManager {
        static class RecentTaskInfo {
            int taskId = 7, numActivities;
            boolean isRunning;
            ComponentName baseActivity, topActivity;
            Intent baseIntent = new Intent(PACKAGE);
        }
        static class AppTask {
            RecentTaskInfo info;
            AppTask(RecentTaskInfo value) { info = value; }
            RecentTaskInfo getTaskInfo() { return info; }
        }
    }
    static void assertTrue(String message, boolean value) {
        if (!value) throw new AssertionError(message);
    }
    static void assertNotNull(Object value) { assertNotNull("null", value); }
    static void assertNotNull(String message, Object value) {
        if (value == null) throw new AssertionError(message);
    }
    static void assertNull(String message, Object value) {
        if (value != null) throw new AssertionError(message);
    }
    static void assertFalse(String message, boolean value) { assertTrue(message, !value); }
    static void assertEquals(Object expected, Object actual) {
        assertEquals("mismatch", expected, actual);
    }
    static void assertEquals(String message, Object expected, Object actual) {
        if (!Objects.equals(expected, actual)) throw new AssertionError(message);
    }
    static void check(List<ActivityManager.AppTask> tasks, int taskId) throws Exception {
BLOCK
    }
    public static void main(String[] args) throws Exception {
        String mode = args[0];
        ActivityManager.RecentTaskInfo task = new ActivityManager.RecentTaskInfo();
        boolean active = mode.startsWith("active");
        if (active) {
            task.isRunning = true; task.numActivities = 1;
            task.baseActivity = new ComponentName(PACKAGE);
            task.topActivity = new ComponentName(PACKAGE);
        }
        switch (mode) {
            case "active_missing_class": task.baseIntent.component.className = "missing.Activity";
                break;
            case "active_resolved_foreign_package": context.pm.info.packageName = "foreign.app";
                break;
            case "active_resolved_wrong_class": context.pm.info.name = "other.Activity"; break;
            case "active_resolved_foreign_uid": context.pm.info.applicationInfo.uid = 456; break;
            case "active_resolved_null_application": context.pm.info.applicationInfo = null; break;
            case "active_resolved_null_info": context.pm.info = null; break;
            case "wrong_task": task.taskId = 8; break;
            case "null_intent": case "active_null_intent": task.baseIntent = null; break;
            case "implicit_intent": case "active_implicit_intent":
                task.baseIntent = new Intent(null);
                break;
            case "foreign_intent": case "active_foreign_intent":
                task.baseIntent = new Intent("foreign.app");
                break;
            case "empty_intent": task.baseIntent = new Intent(""); break;
            case "active_foreign_base": task.baseActivity = new ComponentName("foreign.app"); break;
            case "active_foreign_top": task.topActivity = new ComponentName("foreign.app"); break;
            case "active_null_base": task.baseActivity = null; break;
            case "active_null_top": task.topActivity = null; break;
            case "active_empty_base": task.baseActivity = new ComponentName(""); break;
            case "active_empty_top": task.topActivity = new ComponentName(""); break;
            case "active_zero_count": task.numActivities = 0; break;
            case "active_negative_count": task.numActivities = -1; break;
            case "stopped_running": task.isRunning = true; break;
            case "stopped_count": task.numActivities = 1; break;
            case "stopped_negative_count": task.numActivities = -1; break;
            case "stopped_base": task.baseActivity = new ComponentName(PACKAGE); break;
            case "stopped_top": task.topActivity = new ComponentName(PACKAGE); break;
            case "stopped_foreign_base": task.baseActivity = new ComponentName("foreign.app");
                break;
            case "stopped_foreign_top": task.topActivity = new ComponentName("foreign.app"); break;
        }
        List<ActivityManager.AppTask> tasks = new ArrayList<>();
        if (!mode.equals("no_task")) tasks.add(new ActivityManager.AppTask(task));
        if (mode.equals("two_tasks")) tasks.add(new ActivityManager.AppTask(task));
        if (mode.equals("null_snapshot")) tasks.set(0, new ActivityManager.AppTask(null));
        boolean rejected = false;
        try { check(tasks, 7); }
        catch (AssertionError | NameNotFoundException expected) { rejected = true; }
        boolean valid = mode.equals("stopped") || mode.equals("active");
        if (rejected == valid) throw new AssertionError("incorrect task decision: " + mode);
        System.out.println("task-identity-" + mode + "-passed");
    }
}
""".replace("BLOCK", block)
    path = directory / "TaskHarness.java"
    path.write_text(harness, encoding="utf-8")
    command = [java, "-Xmx128m", "-XX:ActiveProcessorCount=2"]
    compiled = subprocess.run(
        [*command, "com.sun.tools.javac.Main", "-source", "17", "-target", "17", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=45,
    )
    if "Could not find" in compiled.stderr and "com.sun.tools.javac.Main" in compiled.stderr:
        pytest.skip("JDK compiler unavailable")
    assert compiled.returncode == 0, compiled.stderr

    def run(mode):
        result = subprocess.run(
            [*command, "-cp", str(directory), "TaskHarness", mode],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == f"task-identity-{mode}-passed"

    return run


@pytest.mark.parametrize(
    "mode",
    [
        "active_missing_class",
        "active_resolved_foreign_package",
        "active_resolved_wrong_class",
        "active_resolved_foreign_uid",
        "active_resolved_null_application",
        "active_resolved_null_info",
        "stopped",
        "active",
        "wrong_task",
        "null_intent",
        "implicit_intent",
        "foreign_intent",
        "empty_intent",
        "active_null_intent",
        "active_implicit_intent",
        "active_foreign_intent",
        "active_foreign_base",
        "active_foreign_top",
        "active_null_base",
        "active_null_top",
        "active_empty_base",
        "active_empty_top",
        "active_zero_count",
        "active_negative_count",
        "stopped_running",
        "stopped_count",
        "stopped_negative_count",
        "stopped_base",
        "stopped_top",
        "stopped_foreign_base",
        "stopped_foreign_top",
        "no_task",
        "two_tasks",
        "null_snapshot",
    ],
)
def test_actual_task_guard_handles_only_consistent_own_snapshots(task_harness, mode):
    task_harness(mode)
