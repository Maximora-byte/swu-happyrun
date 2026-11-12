package org.happyrun.app;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.os.SystemClock;
import android.test.InstrumentationTestCase;
import android.view.View;
import android.widget.TextView;
import org.happyrun.app.runtime.LocalRuntime;
import org.happyrun.app.runtime.TaskSnapshot;

/** Real SQLite faults. Run each method in a fresh, empty disposable app process. */
public final class StorageFailureTest extends InstrumentationTestCase {
    private static final String FAULT = "storage_write_failed_not_persisted";
    private LocalRuntime runtime;
    private SQLiteDatabase database;
    private Activity activity;

    @Override protected void setUp() throws Exception {
        super.setUp();
        Context context = getInstrumentation().getTargetContext();
        runtime = LocalRuntime.get(context);
        assertNull("Host must clear fixture data before each storage case", runtime.currentTask());
        database = SQLiteDatabase.openDatabase(context.getDatabasePath("happyrun-local-simulation.db").getPath(),
            null, SQLiteDatabase.OPEN_READWRITE);
    }

    @Override protected void tearDown() throws Exception {
        try {
            if (database != null) {
                database.execSQL("DROP TRIGGER IF EXISTS qa_write_failure");
                database.close();
            }
        } finally {
            if (activity != null) getInstrumentation().runOnMainSync(() -> activity.finish());
            super.tearDown();
        }
    }

    public void testFirstIntentFailureIsVisibleWithoutTask() throws Exception {
        installFault();
        expectRejected(() -> runtime.startSimulation());
        assertEquals(FAULT, runtime.health());
        assertNotNull(runtime.healthTaskId());
        assertNull(runtime.currentTask());
        assertEquals(0, rowCount());
        expectRejected(() -> runtime.startSimulation());
        assertEquals(0, rowCount());
        assertFailureUi();
    }

    public void testNewIntentFailurePreservesPreviousCompletion() throws Exception {
        TaskSnapshot started = runtime.startSimulation();
        long deadline = SystemClock.elapsedRealtime() + 15000;
        while (!"completed".equals(runtime.currentTask().state) && SystemClock.elapsedRealtime() < deadline) {
            SystemClock.sleep(50);
        }
        TaskSnapshot completed = runtime.currentTask();
        assertEquals("completed", completed.state);
        assertEquals(started.id, completed.id);
        installFault();
        expectRejected(() -> runtime.startSimulation());
        assertEquals(FAULT, runtime.health());
        assertNotNull(runtime.healthTaskId());
        assertFalse(completed.id.equals(runtime.healthTaskId()));
        TaskSnapshot unchanged = runtime.currentTask();
        assertEquals(completed.id, unchanged.id);
        assertEquals("completed", unchanged.state);
        assertTrue(unchanged.persisted);
        assertTrue(runtime.getTask(completed.id).persisted);
        assertEquals("completed", runtime.history().get(0).state);
        assertEquals("completed", durableState(completed.id));
        assertEquals(1, rowCount());
        expectRejected(() -> runtime.startSimulation());
        expectRejected(() -> runtime.stop(completed.id));
        assertFailureUi();
    }

    public void testTickAndAttentionWriteFailureNeverClaimsSavedOrStopped() throws Exception {
        TaskSnapshot started = runtime.startSimulation();
        installFault();
        long deadline = SystemClock.elapsedRealtime() + 5000;
        while ("ok".equals(runtime.health()) && SystemClock.elapsedRealtime() < deadline) SystemClock.sleep(25);
        assertEquals(FAULT, runtime.health());
        assertEquals(started.id, runtime.healthTaskId());
        assertEquals("running", durableState(started.id)); // physical row remains stale
        TaskSnapshot projected = runtime.currentTask();
        assertEquals(started.id, projected.id);
        assertEquals("needs_attention", projected.state);
        assertEquals(FAULT, projected.reason);
        assertFalse(projected.persisted);
        assertFalse(projected.recordVerified);
        assertFalse(runtime.getTask(started.id).persisted);
        assertEquals("needs_attention", runtime.history().get(0).state);
        expectRejected(() -> runtime.startSimulation());
        expectRejected(() -> runtime.stop(started.id));
        assertFailureUi();
        database.execSQL("DROP TRIGGER qa_write_failure");
        SystemClock.sleep(1200); // restored storage must not silently restart stopped motion
        assertEquals(FAULT, runtime.health());
        assertEquals("running", durableState(started.id));
        assertEquals(projected.distanceM, runtime.currentTask().distanceM, 0.001);
        assertFalse(runtime.currentTask().persisted);
        expectRejected(() -> runtime.stop(started.id));
    }

    private void installFault() {
        database.execSQL("CREATE TRIGGER qa_write_failure BEFORE INSERT ON runs BEGIN SELECT RAISE(FAIL, 'qa_write_failure'); END");
    }
    private int rowCount() {
        try (Cursor rows = database.rawQuery("SELECT COUNT(*) FROM runs", null)) {
            assertTrue(rows.moveToFirst()); return rows.getInt(0);
        }
    }
    private String durableState(String id) {
        try (Cursor rows = database.rawQuery("SELECT state FROM runs WHERE id=?", new String[]{id})) {
            assertTrue(rows.moveToFirst()); return rows.getString(0);
        }
    }
    private void expectRejected(Runnable operation) {
        try { operation.run(); fail("Storage failure must reject mutation"); }
        catch (RuntimeException expected) { /* Assert persisted state separately, not only the exception. */ }
    }
    private void assertFailureUi() throws Exception {
        Intent intent = new Intent(getInstrumentation().getTargetContext(), MainActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
        activity = getInstrumentation().startActivitySync(intent);
        long deadline = SystemClock.elapsedRealtime() + 5000;
        boolean[] ready = {false};
        do {
            getInstrumentation().runOnMainSync(() -> {
                TextView notice = activity.findViewById(R.id.operation_notice);
                ready[0] = notice.getVisibility() == View.VISIBLE && notice.getText().toString().contains("未保存");
            });
            if (ready[0]) break;
            SystemClock.sleep(50);
        } while (SystemClock.elapsedRealtime() < deadline);
        assertTrue("Storage health must visibly explain 未保存 even without an affected current task", ready[0]);
        getInstrumentation().runOnMainSync(() -> {
            assertFalse(activity.findViewById(R.id.start_simulation).isEnabled());
            assertFalse(activity.findViewById(R.id.stop_simulation).isEnabled());
        });
    }
}
