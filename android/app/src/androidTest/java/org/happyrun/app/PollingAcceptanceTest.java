package org.happyrun.app;

import android.app.Activity;
import android.content.Intent;
import android.database.sqlite.SQLiteDatabase;
import android.os.SystemClock;
import android.test.InstrumentationTestCase;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.KeyEvent;
import android.widget.TextView;
import java.lang.reflect.Field;
import java.util.concurrent.atomic.AtomicInteger;
import org.happyrun.app.runtime.LocalRuntime;
import org.happyrun.app.runtime.TaskSnapshot;

/** Each method runs in its own cleared disposable app process; never performs Root checks. */
public final class PollingAcceptanceTest extends InstrumentationTestCase {
    private Activity activity;
    private LocalRuntime runtime;
    private SQLiteDatabase database;
    @Override protected void setUp() throws Exception {
        super.setUp();
        runtime = LocalRuntime.get(getInstrumentation().getTargetContext());
        assertNull("Each polling case requires clean fixture data", runtime.currentTask());
        Intent intent = new Intent(getInstrumentation().getTargetContext(), MainActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
        activity = getInstrumentation().startActivitySync(intent);
        awaitIdle();
    }
    @Override protected void tearDown() throws Exception {
        try {
            if (database != null) {
                database.execSQL("DROP TRIGGER IF EXISTS qa_poll_failure");
                database.close();
            }
        } finally {
            if (activity != null) getInstrumentation().runOnMainSync(() -> activity.finish());
            super.tearDown();
        }
    }
    public void testEmptyUiStaysIdle() {
        assertIdleAndStable();
        refresh();
        assertIdleAndStable();
    }
    public void testTerminalUiStaysIdle() {
        TaskSnapshot task = runtime.startSimulation();
        long deadline = SystemClock.elapsedRealtime() + 15000;
        while (!"completed".equals(runtime.currentTask().state) && SystemClock.elapsedRealtime() < deadline) SystemClock.sleep(50);
        refresh();
        assertEquals("completed", runtime.currentTask().state);
        assertIdleAndStable();
    }
    public void testActiveProgressBackgroundReturnAndStop() {
        TaskSnapshot task = runtime.startSimulation();
        refresh();
        double first = runtime.currentTask().distanceM;
        long deadline = SystemClock.elapsedRealtime() + 4000;
        while (runtime.currentTask().distanceM <= first && SystemClock.elapsedRealtime() < deadline) SystemClock.sleep(50);
        assertTrue(runtime.currentTask().distanceM > first);
        // During genuine background polling, neither refresh control should flash disabled.
        for (int i = 0; i < 20; i++) {
            getInstrumentation().runOnMainSync(() -> {
                assertTrue(activity.findViewById(id("refresh_checks")).isEnabled());
                assertTrue(activity.findViewById(id("wizard_refresh")).isEnabled());
            });
            SystemClock.sleep(40);
        }
        TaskSnapshot[] displayed = {null};
        getInstrumentation().runOnMainSync(() -> displayed[0] = (TaskSnapshot) field("task"));
        assertNotNull(displayed[0]);
        assertTrue("Real engine progress must reach the Activity", displayed[0].distanceM > first);
        synchronized (runtime) {
            getInstrumentation().runOnMainSync(() -> {
                try {
                    java.lang.reflect.Method read = MainActivity.class.getDeclaredMethod("readState", boolean.class);
                    read.setAccessible(true); read.invoke(activity, false);
                } catch (ReflectiveOperationException failure) { throw new AssertionError(failure); }
                assertEquals(Boolean.TRUE, field("reading"));
                assertTrue(activity.findViewById(id("wizard_refresh")).isEnabled());
                activity.findViewById(id("wizard_refresh")).performClick();
                assertEquals("Explicit refresh must queue behind real blocked read", Boolean.TRUE, field("refreshQueued"));
            });
        }
        awaitIdle();
        getInstrumentation().runOnMainSync(() -> assertEquals(Boolean.FALSE, field("refreshQueued")));
        getInstrumentation().sendKeyDownUpSync(KeyEvent.KEYCODE_HOME);
        awaitForeground(false);
        awaitIdle();
        long backgroundSerial = serial();
        SystemClock.sleep(1100);
        assertEquals(backgroundSerial, serial());
        Intent intent = new Intent(getInstrumentation().getTargetContext(), MainActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_REORDER_TO_FRONT);
        getInstrumentation().getTargetContext().startActivity(intent);
        awaitForeground(true);
        awaitIdle();
        assertTrue(serial() > backgroundSerial);
        assertEquals(task.id, runtime.currentTask().id);
        runtime.stop(task.id);
        refresh();
        assertEquals("cancelled", runtime.currentTask().state);
        assertIdleAndStable();
    }
    public void testStorageLatchRemainsVisibleAndIdle() {
        TaskSnapshot task = runtime.startSimulation();
        refresh();
        database = SQLiteDatabase.openDatabase(getInstrumentation().getTargetContext()
            .getDatabasePath("happyrun-local-simulation.db").getPath(), null, SQLiteDatabase.OPEN_READWRITE);
        database.execSQL("CREATE TRIGGER qa_poll_failure BEFORE INSERT ON runs BEGIN SELECT RAISE(FAIL, 'qa_poll_failure'); END");
        long deadline = SystemClock.elapsedRealtime() + 5000;
        boolean[] shown = {false};
        do {
            getInstrumentation().runOnMainSync(() -> shown[0] = ((TextView) activity.findViewById(id("operation_notice")))
                .getText().toString().contains("未保存"));
            if (shown[0]) break;
            SystemClock.sleep(50);
        } while (SystemClock.elapsedRealtime() < deadline);
        assertTrue("Background polling must surface real SQLite failure", shown[0]);
        assertEquals(task.id, runtime.currentTask().id);
        assertFalse(runtime.currentTask().persisted);
        getInstrumentation().runOnMainSync(() -> {
            assertFalse(activity.findViewById(id("start_simulation")).isEnabled());
            assertFalse(activity.findViewById(id("stop_simulation")).isEnabled());
        });
        assertIdleAndStable();
    }
    private void assertIdleAndStable() {
        awaitIdle();
        AtomicInteger changes = new AtomicInteger();
        TextWatcher watcher = new TextWatcher() {
            public void beforeTextChanged(CharSequence s, int start, int count, int after) { }
            public void onTextChanged(CharSequence s, int start, int before, int count) { changes.incrementAndGet(); }
            public void afterTextChanged(Editable s) { }
        };
        getInstrumentation().runOnMainSync(() -> {
            ((TextView) activity.findViewById(id("task_state"))).addTextChangedListener(watcher);
            ((TextView) activity.findViewById(id("task_summary"))).addTextChangedListener(watcher);
        });
        long reads = serial();
        try {
            for (int i = 0; i < 28; i++) {
                getInstrumentation().runOnMainSync(() -> {
                    assertTrue(activity.findViewById(id("refresh_checks")).isEnabled());
                    assertTrue(activity.findViewById(id("wizard_refresh")).isEnabled());
                });
                SystemClock.sleep(50);
            }
            assertEquals("Idle states must not keep scheduling reads", reads, serial());
            assertEquals("Unchanged task text must not be rewritten", 0, changes.get());
        } finally {
            getInstrumentation().runOnMainSync(() -> {
                ((TextView) activity.findViewById(id("task_state"))).removeTextChangedListener(watcher);
                ((TextView) activity.findViewById(id("task_summary"))).removeTextChangedListener(watcher);
            });
        }
    }
    private void refresh() {
        getInstrumentation().runOnMainSync(() -> activity.findViewById(id("wizard_refresh")).performClick());
        awaitIdle();
    }
    private void awaitIdle() { awaitFlag("reading", false); }
    private void awaitForeground(boolean value) { awaitFlag("foreground", value); }
    private void awaitFlag(String name, boolean expected) {
        long deadline = SystemClock.elapsedRealtime() + 5000;
        boolean[] matches = {false};
        do {
            getInstrumentation().runOnMainSync(() -> matches[0] = Boolean.valueOf(expected).equals(field(name)));
            if (matches[0]) return;
            SystemClock.sleep(25);
        } while (SystemClock.elapsedRealtime() < deadline);
        fail("Timed out waiting for " + name + "=" + expected);
    }
    private long serial() {
        long[] value = {0};
        getInstrumentation().runOnMainSync(() -> value[0] = (Long) field("serial"));
        return value[0];
    }
    private Object field(String name) {
        try { Field f = MainActivity.class.getDeclaredField(name); f.setAccessible(true); return f.get(activity); }
        catch (ReflectiveOperationException failure) { throw new AssertionError(failure); }
    }
    private int id(String name) {
        android.content.Context target = getInstrumentation().getTargetContext();
        int value = target.getResources().getIdentifier(name, "id", target.getPackageName());
        assertTrue("Missing target resource " + name, value != 0); return value;
    }
}
