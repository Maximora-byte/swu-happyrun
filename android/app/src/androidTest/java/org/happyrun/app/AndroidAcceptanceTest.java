package org.happyrun.app;

import android.app.Activity;
import android.app.Instrumentation;
import android.graphics.Rect;
import android.view.View;
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
    private Instrumentation.ActivityMonitor mainMonitor;
    private String navigationObservation = "not_observed";

    @Override protected void setUp() throws Exception {
        super.setUp();
        AccessibilityServiceInfo info = getInstrumentation().getUiAutomation().getServiceInfo();
        info.flags |= AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS;
        getInstrumentation().getUiAutomation().setServiceInfo(info);
        mainMonitor = getInstrumentation().addMonitor(MainActivity.class.getName(), null, false);
        Intent intent = new Intent(getInstrumentation().getTargetContext(), MainActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
        activity = getInstrumentation().startActivitySync(intent);
        getInstrumentation().waitForIdleSync();
        runtime = LocalRuntime.get(getInstrumentation().getTargetContext());
        TaskSnapshot old = runtime.currentTask();
        if (old != null && "running".equals(old.state)) runtime.stop(old.id);
    }

    @Override protected void tearDown() throws Exception {
        if (activity != null) getInstrumentation().runOnMainSync(() -> {
            Activity current = currentMain();
            if (current != null && !current.isDestroyed()) current.finish();
        });
        if (mainMonitor != null) getInstrumentation().removeMonitor(mainMonitor);
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

    private Activity currentMain() {
        Activity latest = mainMonitor == null ? null : mainMonitor.getLastActivity();
        return latest == null ? activity : latest;
    }

    /** Reveal only the real target View; clicks still use visible accessibility nodes. */
    private AccessibilityNodeInfo revealAndObserve(String id) {
        final boolean[] focused = {false};
        final boolean[] targetReady = {false};
        getInstrumentation().runOnMainSync(() -> {
            Activity current = currentMain();
            if (current == null || current.isDestroyed() || current.isFinishing()) {
                navigationObservation = "activity_missing_or_destroyed";
                return;
            }
            int resource = current.getResources().getIdentifier(id, "id", current.getPackageName());
            View target = resource == 0 ? null : current.findViewById(resource);
            View container = current.findViewById(current.getResources().getIdentifier(
                    "app_scroll", "id", current.getPackageName()));
            focused[0] = current.hasWindowFocus();
            if (target == null) {
                navigationObservation = "resource=" + resource + " target=false focus=" + focused[0];
                return;
            }
            targetReady[0] = target.isAttachedToWindow() && target.isShown();
            Rect bounds = new Rect();
            boolean visible = target.getGlobalVisibleRect(bounds);
            boolean reveal = false;
            if (focused[0] && target.isAttachedToWindow() && target.isShown()
                    && (!visible || bounds.height() < target.getHeight())) {
                Rect local = new Rect();
                target.getDrawingRect(local);
                reveal = target.requestRectangleOnScreen(local, true);
            }
            target.getGlobalVisibleRect(bounds);
            navigationObservation = "resource=" + resource + " target=true attached="
                    + target.isAttachedToWindow() + " shown=" + target.isShown()
                    + " focus=" + focused[0] + " rect=" + bounds.toShortString()
                    + " scrollY=" + (container == null ? -1 : container.getScrollY())
                    + " reveal=" + reveal;
        });
        AccessibilityNodeInfo root = getInstrumentation().getUiAutomation().getRootInActiveWindow();
        String windowPackage = root == null ? "null" : String.valueOf(root.getPackageName());
        navigationObservation += " windowPackage=" + windowPackage;
        if (!focused[0] || !targetReady[0] || root == null || !"org.happyrun.app".equals(windowPackage)) return null;
        List<AccessibilityNodeInfo> nodes = root.findAccessibilityNodeInfosByViewId(
                "org.happyrun.app:id/" + id);
        for (AccessibilityNodeInfo node : nodes) {
            Rect bounds = new Rect();
            node.getBoundsInScreen(bounds);
            Rect window = new Rect();
            root.getBoundsInScreen(window);
            if ("org.happyrun.app".equals(String.valueOf(node.getPackageName()))
                    && node.isVisibleToUser() && !bounds.isEmpty()
                    && Rect.intersects(bounds, window)) return node;
        }
        return null;
    }

    private AccessibilityNodeInfo awaitNative(String id, Boolean enabled, long timeout) {
        return new NativeViewDeadline<AccessibilityNodeInfo>(
                new NativeViewDeadline.Port<AccessibilityNodeInfo>() {
            public long now() { return SystemClock.elapsedRealtime(); }
            public void pause(long millis) { SystemClock.sleep(millis); }
            public AccessibilityNodeInfo revealAndObserve(String target) {
                return AndroidAcceptanceTest.this.revealAndObserve(target);
            }
            public boolean enabled(AccessibilityNodeInfo node) { return node.isEnabled(); }
            public void failure(String target, Boolean expected) {
                // Own local MainActivity geometry only: no UI text, tokens or remote-page dump.
                System.out.println("NATIVE_NAV_FAIL target=" + target + " enabled=" + expected
                        + " " + navigationObservation);
                fail("Native view unavailable or wrong enabled state: " + target);
            }
        }).await(id, enabled, timeout);
    }

    private AccessibilityNodeInfo waitId(String id, long timeout) {
        return awaitNative(id, null, timeout);
    }

    private AccessibilityNodeInfo waitEnabled(String id, boolean enabled) {
        return awaitNative(id, enabled, 5000);
    }

    private void showId(String id) {
        assertTrue(waitId(id, 5000).isVisibleToUser());
        getInstrumentation().waitForIdleSync();
    }

    private void clickId(String id) {
        AccessibilityNodeInfo node = waitEnabled(id, true);
        assertTrue("Target is not visible: " + id, node.isVisibleToUser());
        assertTrue("Target is not clickable: " + id, node.isClickable());
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
