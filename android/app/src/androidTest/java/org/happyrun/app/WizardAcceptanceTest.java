package org.happyrun.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.test.InstrumentationTestCase;
import android.os.SystemClock;
import android.view.View;
import android.widget.TextView;
import java.lang.reflect.Field;
import java.lang.reflect.Method;

/** Independent wizard UI suite. Never presses the Root confirmation's positive action. */
public final class WizardAcceptanceTest extends InstrumentationTestCase {
    private Activity activity;
    @Override protected void setUp() throws Exception {
        super.setUp();
        Intent intent = new Intent(getInstrumentation().getTargetContext(), MainActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
        activity = getInstrumentation().startActivitySync(intent);
        awaitRefresh();
    }
    @Override protected void tearDown() throws Exception {
        if (activity != null) getInstrumentation().runOnMainSync(() -> activity.finish());
        super.tearDown();
    }
    public void testVariantAndNoFrameworkEvidenceAreConservative() {
        getInstrumentation().runOnMainSync(() -> {
            String text = text(targetId("framework_probe"));
            assertTrue(text.contains("inactive") || text.contains("unknown"));
            assertFalse(text.contains("已收到本应用 hook 回执"));
            assertTrue(text.contains(installedTargetIncludesModule() ? "包含可选" : "不含可选"));
            assertFalse(activity.findViewById(targetId("actual_run_blocked")).isEnabled());
            assertTrue(text(targetId("root_evidence")).contains("尚未主动检查"));
        });
    }
    public void testRootConfirmationCancelAndDuplicateEntryNeverStartCheck() {
        getInstrumentation().runOnMainSync(() -> {
            View entry = activity.findViewById(targetId("root_check"));
            entry.performClick();
            AlertDialog first = (AlertDialog) field("confirmation");
            assertNotNull(first);
            assertTrue(first.isShowing());
            assertEquals("开始一次检查", first.getButton(AlertDialog.BUTTON_POSITIVE).getText().toString());
            TextView message = first.findViewById(android.R.id.message);
            assertTrue(message.getText().toString().contains("su -c id"));
            assertTrue(message.getText().toString().contains("30 秒"));
            assertTrue(message.getText().toString().contains("不会自动重试"));
            entry.performClick();
            assertSame(first, field("confirmation"));
            first.getButton(AlertDialog.BUTTON_NEGATIVE).performClick();
        });
        getInstrumentation().waitForIdleSync();
        getInstrumentation().runOnMainSync(() -> {
            assertNull(field("confirmation"));
            assertEquals("not_checked", field("rootStatus"));
            assertEquals(Boolean.FALSE, field("rootPending"));
            assertTrue(text(targetId("root_evidence")).contains("尚未主动检查"));
            assertEquals(View.GONE, activity.findViewById(targetId("root_cancel")).getVisibility());
            assertFalse(activity.findViewById(targetId("actual_run_blocked")).isEnabled());
        });
    }
    public void testReturnAndRefreshDoNotAuthorizeRootOrRealExecution() {
        getInstrumentation().runOnMainSync(() -> activity.findViewById(targetId("wizard_next")).performClick());
        getInstrumentation().runOnMainSync(() -> {
            AlertDialog instructions = (AlertDialog) field("auxiliaryDialog");
            assertNotNull(instructions);
            assertTrue(instructions.isShowing());
            instructions.dismiss();
        });
        getInstrumentation().waitForIdleSync();
        getInstrumentation().runOnMainSync(() -> activity.findViewById(targetId("wizard_refresh")).performClick());
        awaitRefresh();
        getInstrumentation().runOnMainSync(() -> {
            assertEquals("not_checked", field("rootStatus"));
            assertFalse(activity.findViewById(targetId("actual_run_blocked")).isEnabled());
            assertFalse(text(targetId("framework_probe")).contains("已收到本应用 hook 回执"));
        });
    }
    public void testInjectedPresentationStatesCannotUnlockRealExecution() {
        // Presentation-only fixture, not a hook receipt or Root result. Never touches RootDiagnostic.
        getInstrumentation().runOnMainSync(() -> {
            for (String status : new String[]{"inactive", "unknown", "active"}) {
                setField("probeStatus", status);
                setField("probeApi", "active".equals(status) ? Integer.valueOf(82) : null);
                invoke("renderWizard");
                assertTrue(text(targetId("framework_probe")).contains(status));
                assertFalse(activity.findViewById(targetId("actual_run_blocked")).isEnabled());
            }
            setField("rootPending", true);
            invoke("updateButtons");
            assertFalse(activity.findViewById(targetId("root_check")).isEnabled());
            activity.findViewById(targetId("root_check")).performClick();
            assertNull(field("confirmation"));
            setField("rootPending", false);
            invoke("updateButtons");
        });
    }
    private void awaitRefresh() {
        long deadline = SystemClock.elapsedRealtime() + 5000;
        boolean[] ready = {false};
        do {
            getInstrumentation().runOnMainSync(() -> ready[0] = !Boolean.TRUE.equals(field("reading"))
                && activity.findViewById(targetId("wizard_refresh")).isEnabled());
            if (ready[0]) return;
            SystemClock.sleep(50);
        } while (SystemClock.elapsedRealtime() < deadline);
        fail("Wizard refresh did not complete");
    }
    private boolean installedTargetIncludesModule() {
        try {
            ClassLoader targetLoader = getInstrumentation().getTargetContext().getClassLoader();
            Class<?> targetConfig = targetLoader.loadClass("org.happyrun.app.BuildConfig");
            return targetConfig.getField("SELF_PROBE_ENABLED").getBoolean(null);
        } catch (ReflectiveOperationException error) {
            throw new AssertionError("Cannot verify installed target variant", error);
        }
    }
    private int targetId(String name) {
        android.content.Context target = getInstrumentation().getTargetContext();
        int id = target.getResources().getIdentifier(name, "id", target.getPackageName());
        assertTrue("Missing installed-target view ID: " + name, id != 0);
        return id;
    }
    private String text(int id) { return ((TextView) activity.findViewById(id)).getText().toString(); }
    private Object field(String name) {
        try { Field f = MainActivity.class.getDeclaredField(name); f.setAccessible(true); return f.get(activity); }
        catch (ReflectiveOperationException error) { throw new AssertionError(error); }
    }
    private void setField(String name, Object value) {
        try { Field f = MainActivity.class.getDeclaredField(name); f.setAccessible(true); f.set(activity, value); }
        catch (ReflectiveOperationException error) { throw new AssertionError(error); }
    }
    private void invoke(String name) {
        try { Method m = MainActivity.class.getDeclaredMethod(name); m.setAccessible(true); m.invoke(activity); }
        catch (ReflectiveOperationException error) { throw new AssertionError(error); }
    }
}
