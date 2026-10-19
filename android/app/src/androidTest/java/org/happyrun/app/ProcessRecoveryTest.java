package org.happyrun.app;

import android.content.Context;
import android.os.SystemClock;
import android.test.InstrumentationTestCase;
import org.happyrun.app.runtime.LocalRuntime;
import org.happyrun.app.runtime.TaskSnapshot;

/** Each method is launched separately by android_acceptance.sh, with real process death between. */
public final class ProcessRecoveryTest extends InstrumentationTestCase {
    public void testPrepareCompletedTask() {
        Context context = getInstrumentation().getTargetContext();
        LocalRuntime runtime = LocalRuntime.get(context);
        runtime.startSimulation();
        long deadline = SystemClock.elapsedRealtime() + 15000;
        while (!"completed".equals(runtime.currentTask().state) && SystemClock.elapsedRealtime() < deadline) {
            SystemClock.sleep(50);
        }
        TaskSnapshot task = runtime.currentTask();
        assertEquals("completed", task.state);
        assertEquals(task.totalDistanceM, task.distanceM, 0.001);
        assertTrue(context.getSharedPreferences("qa-recovery-marker", 0).edit()
            .putString("completed_id", task.id).commit());
    }

    public void testCompletedTaskSurvivesProcessRestart() {
        Context context = getInstrumentation().getTargetContext();
        String expected = context.getSharedPreferences("qa-recovery-marker", 0).getString("completed_id", null);
        assertNotNull(expected);
        TaskSnapshot task = LocalRuntime.get(context).currentTask();
        assertNotNull(task);
        assertEquals(expected, task.id);
        assertEquals("completed", task.state);
        assertEquals(task.totalDistanceM, task.distanceM, 0.001);
        assertFalse(task.recordVerified);
    }

    public void testPrepareRunningIntent() {
        Context context = getInstrumentation().getTargetContext();
        LocalRuntime runtime = LocalRuntime.get(context);
        runtime.startSimulation();
        TaskSnapshot task = runtime.currentTask();
        assertNotNull(task);
        assertEquals("running", task.state);
        assertTrue(context.getSharedPreferences("qa-recovery-marker", 0).edit()
            .putString("id", task.id).putLong("started", task.startedAtMs).commit());
        // Return while a genuine engine task is active; the host then force-stops this package.
        assertEquals("running", runtime.currentTask().state);
    }

    public void testRecoverWithoutReplay() {
        Context context = getInstrumentation().getTargetContext();
        String expected = context.getSharedPreferences("qa-recovery-marker", 0).getString("id", null);
        assertNotNull("prepare stage must have persisted its marker", expected);
        LocalRuntime runtime = LocalRuntime.get(context);
        TaskSnapshot recovered = runtime.currentTask();
        assertNotNull(recovered);
        assertEquals(expected, recovered.id);
        assertEquals("needs_attention", recovered.state);
        assertEquals("restart_uncertain", recovered.reason);
        assertFalse(recovered.recordVerified);
        assertEquals(expected, runtime.startSimulation().id);
        assertEquals("needs_attention", runtime.currentTask().state);
        double distance = recovered.distanceM;
        long started = recovered.startedAtMs;
        SystemClock.sleep(9500); // longer than a complete simulation; no automatic replay
        TaskSnapshot later = runtime.currentTask();
        assertEquals(expected, later.id);
        assertEquals("needs_attention", later.state);
        assertEquals(started, later.startedAtMs);
        assertEquals(distance, later.distanceM, 0.001);
        assertFalse(later.recordVerified);
        runtime.stop(expected); // explicit user-equivalent acknowledgement, never implicit restart
        assertEquals("cancelled", runtime.getTask(expected).state);
        TaskSnapshot next = runtime.startSimulation();
        assertFalse(expected.equals(next.id));
        assertEquals("cancelled", runtime.getTask(expected).state);
        runtime.stop(next.id);
    }
}
