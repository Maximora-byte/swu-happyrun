package org.happyrun.app;

import android.app.Activity;
import android.app.ActivityManager;
import android.app.Instrumentation;
import android.content.Context;
import android.content.ComponentName;
import android.content.pm.PackageManager;
import android.content.pm.PackageInfo;
import android.content.pm.Signature;
import android.hardware.display.DisplayManager;
import android.graphics.Rect;
import android.os.Build;
import android.os.Bundle;
import android.os.SystemClock;
import android.test.InstrumentationTestCase;
import android.test.InstrumentationTestRunner;
import android.view.View;
import android.view.Display;
import java.security.MessageDigest;
import java.util.List;
import java.util.UUID;

/** Opt-in isolated-instance observation. Never touches other apps or calls simulation controls. */
public final class DisplayObservationTest extends InstrumentationTestCase {
    private DisplayObservationGate.Snapshot fixture() {
        DisplayObservationGate.Snapshot s = new DisplayObservationGate.Snapshot();
        s.observationId = "fresh"; s.packageName = "org.happyrun.app";
        s.activity = MainActivity.class.getName(); s.signature = "synthetic";
        s.display = 7; s.task = 42; s.taskCount = 1; s.window = true; s.controls = true;
        s.started = 100; s.captured = 101; s.finished = 102;
        return s;
    }
    private void rejected(DisplayObservationGate.Snapshot s) {
        int writes = 0;
        boolean accepted = DisplayObservationGate.accepts(s, "fresh", 7, 42, "synthetic", 200);
        if (accepted) writes++;
        assertFalse("An ambiguous observation must not authorize an action", accepted);
        assertEquals(0, writes);
    }
    public void testWrongDisplayNeverClicks() { DisplayObservationGate.Snapshot s = fixture(); s.display = 0; rejected(s); }
    public void testStaleObservationNeverCompletes() { DisplayObservationGate.Snapshot s = fixture(); s.observationId = "old"; rejected(s); }
    public void testFailedDumpNeverUsesOldXml() { DisplayObservationGate.Snapshot s = fixture(); s.dumpExit = 139; rejected(s); }
    public void testMultipleTasksNeverClicks() { DisplayObservationGate.Snapshot s = fixture(); s.taskCount = 2; rejected(s); }
    public void testMissingWindowNeverClicks() { DisplayObservationGate.Snapshot s = fixture(); s.window = false; rejected(s); }
    public void testTimeoutNeverCompletes() { DisplayObservationGate.Snapshot s = fixture(); s.finished = 200; rejected(s); }

    /** Select this method explicitly; the default acceptance script must not run it. */
    public void testObserveOwnActivity() throws Exception {
        phase("arguments");
        Bundle args = ((InstrumentationTestRunner) getInstrumentation()).getArguments();
        assertEquals("Requires a disposable instance with no personal data", "yes", args.getString("isolated"));
        assertTrue("API29+ is required for explicit task/display binding", Build.VERSION.SDK_INT >= 29);
        String id = args.getString("observationId");
        assertNotNull(id);
        assertEquals("Use a fresh UUID for each invocation", id, UUID.fromString(id).toString());
        int display = Integer.parseInt(args.getString("displayId", "-1"));
        int task = Integer.parseInt(args.getString("taskId", "-1"));
        String expectedSignature = args.getString("signatureSha256", "");
        assertTrue(expectedSignature.matches("[0-9a-f]{64}"));
        Context context = getInstrumentation().getTargetContext();
        phase("package");
        assertEquals("org.happyrun.app", context.getPackageName());
        phase("signing_info");
        PackageInfo installed = context.getPackageManager().getPackageInfo(context.getPackageName(),
            PackageManager.GET_SIGNING_CERTIFICATES);
        phase("signing_info", "installed_version_code", installed.versionCode);
        Signature[] signatures = installed.signingInfo.getApkContentsSigners();
        phase("signing_info", "signer_count", signatures.length);
        assertEquals(1, signatures.length);
        StringBuilder signature = new StringBuilder();
        for (byte b : MessageDigest.getInstance("SHA-256").digest(signatures[0].toByteArray()))
            signature.append(String.format(java.util.Locale.ROOT, "%02x", b & 255));
        Bundle identity = new Bundle();
        identity.putString("observation_phase", "signature");
        identity.putString("installed_package", context.getPackageName());
        identity.putString("installed_signature_sha256", signature.toString());
        getInstrumentation().sendStatus(2, identity);
        phase("signature", "signature_matches", expectedSignature.equals(signature.toString()) ? 1 : 0);
        assertEquals("Installed signing identity must match the verified paired artifact", expectedSignature, signature.toString());
        phase("display");
        assertNotNull("No such display", ((DisplayManager) context.getSystemService(Context.DISPLAY_SERVICE)).getDisplay(display));
        ActivityManager manager = (ActivityManager) context.getSystemService(Context.ACTIVITY_SERVICE);
        List<ActivityManager.AppTask> tasks = manager.getAppTasks();
        phase("tasks", "observed_task_count", tasks.size());
        assertEquals("Do not guess among same-package tasks", 1, tasks.size());
        ActivityManager.RecentTaskInfo taskInfo = tasks.get(0).getTaskInfo();
        phase("task_id", "observed_task_id", taskInfo.taskId);
        assertEquals("Task must be selected by independent observation", task, taskInfo.taskId);
        ComponentName baseActivity = taskInfo.baseActivity;
        ComponentName baseIntentComponent = taskInfo.baseIntent == null ? null
            : taskInfo.baseIntent.getComponent();
        phase("base_activity", "base_activity_present", baseActivity != null ? 1 : 0);
        phase("base_activity", "base_activity_is_expected", baseActivity != null
            && MainActivity.class.getName().equals(baseActivity.getClassName()) ? 1 : 0);
        phase("task_identity", "base_intent_present", baseIntentComponent != null ? 1 : 0);
        phase("task_identity", "base_intent_is_expected", baseIntentComponent != null
            && context.getPackageName().equals(baseIntentComponent.getPackageName())
            && MainActivity.class.getName().equals(baseIntentComponent.getClassName()) ? 1 : 0);
        assertTrue("Task components must match own MainActivity", DisplayObservationGate.taskComponentsMatch(
            baseIntentComponent == null ? null : baseIntentComponent.getPackageName(),
            baseIntentComponent == null ? null : baseIntentComponent.getClassName(),
            baseActivity == null ? null : baseActivity.getPackageName(),
            baseActivity == null ? null : baseActivity.getClassName()));
        // Recent-task restoration without launch options can fall back to the system default display.
        // Refuse other displays before restoring; never move a task to satisfy an expectation.
        Display defaultDisplay = ((DisplayManager) context.getSystemService(Context.DISPLAY_SERVICE))
            .getDisplay(Display.DEFAULT_DISPLAY);
        assertTrue("Task restore is unsupported on a non-default display",
            DisplayObservationGate.canRestoreOnDefaultDisplay(display,
                defaultDisplay == null ? -1 : defaultDisplay.getDisplayId()));
        long started = SystemClock.elapsedRealtime();
        Instrumentation.ActivityMonitor monitor = getInstrumentation().addMonitor(MainActivity.class.getName(), null, false);
        Activity activity = null;
        try {
            // No CLEAR_TASK, reset, coordinates, shell input or simulated movement.
            // Preserve the observed task/display; never move it to make an expectation pass.
            phase("launch");
            tasks.get(0).moveToFront();
            phase("activity");
            activity = monitor.waitForActivityWithTimeout(5000);
            assertNotNull("Own Activity not observed within the bounded window", activity);
            Activity observed = activity;
            DisplayObservationGate.Snapshot s = new DisplayObservationGate.Snapshot();
            s.started = started; s.observationId = id; s.signature = signature.toString();
            phase("viewport");
            do {
                getInstrumentation().runOnMainSync(() -> {
                    s.packageName = observed.getPackageName(); s.activity = observed.getClass().getName();
                    s.task = observed.getTaskId();
                    s.display = observed.getWindow().getDecorView().getDisplay() == null ? -1
                        : observed.getWindow().getDecorView().getDisplay().getDisplayId();
                    s.window = observed.hasWindowFocus() && observed.getWindow().getDecorView().isShown();
                    s.controls = shown(observed, "app_scroll") && shown(observed, "framework_probe") && shown(observed, "wizard_refresh");
                    s.captured = SystemClock.elapsedRealtime();
                });
                s.taskCount = manager.getAppTasks().size(); s.finished = SystemClock.elapsedRealtime();
                if (s.task != task || s.display != display || s.taskCount != 1
                    || (s.window && s.controls) || s.finished >= started + 10000) break;
                // ActivityMonitor may return before layout/focus. Wait read-only, never click.
                SystemClock.sleep(50);
            } while (true);
            phase("binding", "observed_task_count", s.taskCount);
            phase("binding", "observed_task_id", s.task);
            phase("binding", "observed_display_id", s.display);
            phase("binding", "window_visible", s.window ? 1 : 0);
            phase("binding", "controls_visible", s.controls ? 1 : 0);
            assertTrue("Observation rejected; writes=0", DisplayObservationGate.accepts(s, id, display, task, expectedSignature, started + 10000));
            phase("success");
            Bundle result = new Bundle();
            result.putString("observation_id", id); result.putInt("display_id", s.display);
            result.putInt("task_id", s.task); result.putString("activity", s.activity);
            result.putString("signature_sha256", s.signature); result.putString("state", "observed");
            result.putString("visible_controls", "app_scroll,framework_probe,wizard_refresh");
            result.putInt("writes", 0); getInstrumentation().sendStatus(0, result);
        } finally {
            getInstrumentation().removeMonitor(monitor);
            // Leave the observed task and its data intact; no finish(), clear or reset.
        }
    }
    private void phase(String name) {
        Bundle status = new Bundle();
        status.putString("observation_phase", name);
        getInstrumentation().sendStatus(2, status);
    }
    private void phase(String name, String metric, int value) {
        Bundle status = new Bundle();
        status.putString("observation_phase", name);
        status.putInt(metric, value);
        getInstrumentation().sendStatus(2, status);
    }
    private boolean shown(Activity activity, String name) {
        View view = activity.findViewById(activity.getResources().getIdentifier(name, "id", activity.getPackageName()));
        Rect visible = new Rect();
        return view != null && view.isShown() && view.getWidth() > 0 && view.getHeight() > 0
            && view.getGlobalVisibleRect(visible) && visible.width() > 0 && visible.height() > 0;
    }
}
