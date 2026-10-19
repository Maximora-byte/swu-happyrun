package org.happyrun.app;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Bitmap;
import android.test.InstrumentationTestCase;
import android.view.accessibility.AccessibilityNodeInfo;
import android.accessibilityservice.AccessibilityServiceInfo;
import android.os.SystemClock;
import java.io.File;
import java.io.FileOutputStream;
import java.util.List;
import org.happyrun.app.runtime.LocalRuntime;
import org.happyrun.app.runtime.TaskSnapshot;
import org.happyrun.app.diagnostics.CheckItem;

/** Runs against the real Activity, clock, engine and SQLite; no mocked task results. */
public final class AndroidAcceptanceTest extends InstrumentationTestCase {
    private Activity activity;
    private LocalRuntime runtime;

    @Override protected void setUp() throws Exception {
        super.setUp();
        AccessibilityServiceInfo info = getInstrumentation().getUiAutomation().getServiceInfo();
        info.flags |= AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS;
        getInstrumentation().getUiAutomation().setServiceInfo(info);
        Intent intent = new Intent(getInstrumentation().getTargetContext(), MainActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
        activity = getInstrumentation().startActivitySync(intent);
        getInstrumentation().waitForIdleSync();
        runtime = LocalRuntime.get(getInstrumentation().getTargetContext());
        TaskSnapshot old = runtime.currentTask();
        if (old != null && "running".equals(old.state)) runtime.stop(old.id);
    }

    @Override protected void tearDown() throws Exception {
        if (activity != null) getInstrumentation().runOnMainSync(() -> activity.finish());
        super.tearDown();
    }

    public void testDeniedLocationDoesNotEnableRealExecution() throws Exception {
        assertEquals(android.content.pm.PackageManager.PERMISSION_DENIED,
            getInstrumentation().getTargetContext().checkSelfPermission(android.Manifest.permission.ACCESS_FINE_LOCATION));
        assertEquals(android.content.pm.PackageManager.PERMISSION_DENIED,
            getInstrumentation().getTargetContext().checkSelfPermission(android.Manifest.permission.ACCESS_COARSE_LOCATION));
        clickId("refresh_checks");
        assertFalse(waitId("actual_run_blocked", 5000).isEnabled());
        assertNotNull(waitId("capability_list", 5000));
    }

    public void testChineseLaunchAndRealExecutionBlocked() throws Exception {
        AccessibilityNodeInfo start = waitId("start_simulation", 5000);
        assertTrue(start.getText().toString().contains("模拟"));
        assertFalse(waitId("actual_run_blocked", 5000).isEnabled());
        clickId("refresh_checks");
        assertFalse(waitId("actual_run_blocked", 5000).isEnabled());
        boolean rootSeen = false, frameworkSeen = false;
        for (CheckItem item : runtime.diagnostics()) {
            if ("Root".equals(item.name)) {
                rootSeen = true;
                assertTrue("Root hints cannot establish access", "unknown".equals(item.status) || "unverified".equals(item.status));
            }
            if ("LSPosed".equals(item.name)) {
                frameworkSeen = true;
                assertEquals("unknown", item.status);
            }
        }
        assertTrue(rootSeen);
        assertTrue(frameworkSeen);
        showId("start_simulation");
        screenshot("android-onboarding.png");
    }

    public void testRealSimulationCompletesAndSurvivesActivityRecreation() throws Exception {
        clickId("start_simulation");
        clickText("开始模拟");
        TaskSnapshot started = awaitState("running", 4000);
        assertEquals("simulation_local", started.mode);
        assertFalse(started.recordVerified);
        runtime.startSimulation(); // a second caller must reuse the running intent
        assertEquals(started.id, runtime.currentTask().id);
        waitEnabled("start_simulation", false);
        TaskSnapshot done = awaitState("completed", 15000);
        assertEquals(started.id, done.id);
        assertTrue(done.totalDistanceM > 0);
        assertEquals(done.totalDistanceM, done.distanceM, 0.001);
        assertFalse(done.recordVerified);
        getInstrumentation().runOnMainSync(() -> activity.recreate());
        SystemClock.sleep(800);
        assertEquals(done.id, runtime.currentTask().id);
        assertEquals("completed", runtime.currentTask().state);
        assertFalse(waitId("actual_run_blocked", 3000).isEnabled());
        showId("task_state");
        screenshot("android-completed.png");
    }

    public void testCancelUsesRealEngineAndDoesNotRestart() throws Exception {
        clickId("start_simulation");
        clickText("开始模拟");
        TaskSnapshot started = awaitState("running", 4000);
        clickId("stop_simulation");
        clickText("确认停止");
        TaskSnapshot stopped = awaitState("cancelled", 4000);
        assertEquals(started.id, stopped.id);
        assertFalse(stopped.recordVerified);
        double distance = stopped.distanceM;
        SystemClock.sleep(1500);
        assertEquals("cancelled", runtime.currentTask().state);
        assertEquals(distance, runtime.currentTask().distanceM, 0.001);
    }

    private TaskSnapshot awaitState(String state, long timeout) throws Exception {
        long deadline = SystemClock.elapsedRealtime() + timeout;
        do {
            TaskSnapshot task = runtime.currentTask();
            if (task != null && state.equals(task.state)) return task;
            SystemClock.sleep(50);
        } while (SystemClock.elapsedRealtime() < deadline);
        TaskSnapshot task = runtime.currentTask();
        fail("Expected " + state + ", actual " + (task == null ? "null" : task.state));
        return null;
    }

    private AccessibilityNodeInfo waitId(String id, long timeout) {
        boolean forward = false;
        long deadline = SystemClock.elapsedRealtime() + timeout;
        do {
            AccessibilityNodeInfo root = getInstrumentation().getUiAutomation().getRootInActiveWindow();
            if (root != null) {
                List<AccessibilityNodeInfo> nodes = root.findAccessibilityNodeInfosByViewId("org.happyrun.app:id/" + id);
                if (!nodes.isEmpty()) return nodes.get(0);
                List<AccessibilityNodeInfo> scrolls = root.findAccessibilityNodeInfosByViewId("org.happyrun.app:id/app_scroll");
                if (!scrolls.isEmpty()) {
                    AccessibilityNodeInfo scroll = scrolls.get(0);
                    int direction = forward ? AccessibilityNodeInfo.ACTION_SCROLL_FORWARD : AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD;
                    if (!scroll.performAction(direction)) forward = !forward;
                }
            }
            SystemClock.sleep(50);
        } while (SystemClock.elapsedRealtime() < deadline);
        fail("Missing native view: " + id);
        return null;
    }

    private AccessibilityNodeInfo waitEnabled(String id, boolean enabled) {
        long deadline = SystemClock.elapsedRealtime() + 5000;
        do {
            AccessibilityNodeInfo node = waitId(id, 1000);
            if (node.isEnabled() == enabled) return node;
            SystemClock.sleep(50);
        } while (SystemClock.elapsedRealtime() < deadline);
        fail("Expected enabled=" + enabled + " for " + id);
        return null;
    }

    private void showId(String id) {
        waitId(id, 5000).performAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_SHOW_ON_SCREEN.getId());
        getInstrumentation().waitForIdleSync();
        SystemClock.sleep(250);
    }

    private void clickId(String id) {
        AccessibilityNodeInfo node = waitEnabled(id, true);
        node.performAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_SHOW_ON_SCREEN.getId());
        getInstrumentation().waitForIdleSync();
        node = waitId(id, 5000);
        assertTrue("Click failed: " + id, node.performAction(AccessibilityNodeInfo.ACTION_CLICK));
        getInstrumentation().waitForIdleSync();
    }

    private void clickText(String text) {
        long deadline = SystemClock.elapsedRealtime() + 5000;
        do {
            AccessibilityNodeInfo root = getInstrumentation().getUiAutomation().getRootInActiveWindow();
            if (root != null) for (AccessibilityNodeInfo node : root.findAccessibilityNodeInfosByText(text)) {
                if (text.contentEquals(node.getText()) && node.isClickable()) {
                    assertTrue(node.performAction(AccessibilityNodeInfo.ACTION_CLICK));
                    getInstrumentation().waitForIdleSync();
                    return;
                }
            }
            SystemClock.sleep(50);
        } while (SystemClock.elapsedRealtime() < deadline);
        fail("Missing dialog action: " + text);
    }

    private void screenshot(String name) throws Exception {
        Bitmap bitmap = getInstrumentation().getUiAutomation().takeScreenshot();
        assertNotNull(bitmap);
        File dir = new File(getInstrumentation().getTargetContext().getExternalFilesDir(null), "qa");
        assertTrue(dir.isDirectory() || dir.mkdirs());
        try (FileOutputStream out = new FileOutputStream(new File(dir, name))) {
            assertTrue(bitmap.compress(Bitmap.CompressFormat.PNG, 100, out));
        } finally { bitmap.recycle(); }
    }
}
