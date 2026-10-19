package org.happyrun.app.remoteqa;

import android.app.ActivityManager;
import android.content.Context;
import android.content.pm.ActivityInfo;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.hardware.display.DisplayManager;
import android.os.Build;
import android.os.Bundle;
import android.os.SystemClock;
import android.test.InstrumentationTestCase;
import android.test.InstrumentationTestRunner;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Collections;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;
import org.happyrun.app.remote.protocol.AgentHello;
import org.happyrun.app.remote.protocol.JobView;
import org.happyrun.app.remote.transport.HttpsAgentClient;
import org.happyrun.app.remote.journal.RemoteJournal;
import org.happyrun.app.remote.runtime.RemoteAgentRunner;
import org.happyrun.app.remote.runtime.RemoteClock;
import org.happyrun.app.remote.runtime.RemoteForegroundSession;
import org.happyrun.app.remote.simulation.RemoteFakeDriver;

/** Opt-in own-package simulation only. No Activity lifecycle, sensor, location or other app action. */
@SuppressWarnings("deprecation")
public final class RemoteMumuHttpsAcceptanceTest extends InstrumentationTestCase {
    private static final String PACKAGE = "org.happyrun.app";
    private String arg(String name) {
        String value = ((InstrumentationTestRunner)getInstrumentation()).getArguments().getString(name);
        assertNotNull("Required guarded adapter argument missing", value);
        return value;
    }
    private void marker(String value) {
        Bundle bundle = new Bundle();
        bundle.putString("stream", "\nMUMU_HTTPS " + value + "\n");
        getInstrumentation().sendStatus(0, bundle);
    }
    private void failureMarker(String phase, Throwable failure) {
        String kind = failure.getClass().getSimpleName();
        if (!java.util.Arrays.asList("AssertionFailedError", "AssertionError", "IOException",
                "IllegalStateException", "ControlException", "InterruptedException").contains(kind)) kind = "other";
        try { marker("FAILURE phase=" + phase + " kind=" + kind); }
        catch (RuntimeException unavailable) { /* Diagnostics cannot replace the primary failure. */ }
    }
    private String digest(byte[] value) throws Exception {
        StringBuilder result = new StringBuilder();
        for (byte b : MessageDigest.getInstance("SHA-256").digest(value))
            result.append(String.format(java.util.Locale.ROOT, "%02x", b & 255));
        return result.toString();
    }
    private void checkSigner(Context context, String name, String expected) throws Exception {
        PackageInfo info = context.getPackageManager().getPackageInfo(name, PackageManager.GET_SIGNING_CERTIFICATES);
        assertNotNull("Missing signing identity", info.signingInfo);
        Signature[] signers = info.signingInfo.getApkContentsSigners();
        assertEquals("Exactly one current signer required", 1, signers.length);
        assertEquals("Paired installed signer mismatch", expected, digest(signers[0].toByteArray()));
    }
    private void guard() throws Exception {
        assertEquals("Explicit own simulation approval required", "yes", arg("allowOwnSimulation"));
        assertEquals("Isolated instance required", "yes", arg("isolated"));
        assertTrue("API29+ required", Build.VERSION.SDK_INT >= 29);
        Context context = getInstrumentation().getTargetContext();
        assertEquals(PACKAGE, context.getPackageName());
        String signature = arg("signatureSha256");
        assertTrue(signature.matches("[0-9a-f]{64}"));
        checkSigner(context, PACKAGE, signature);
        checkSigner(context, PACKAGE + ".test", signature);
        String bootId = new String(Files.readAllBytes(java.nio.file.Paths.get("/proc/sys/kernel/random/boot_id")), StandardCharsets.US_ASCII).trim();
        assertEquals("Device changed since host observation", arg("bootId"), bootId);
        int taskId = Integer.parseInt(arg("taskId"));
        int displayId = Integer.parseInt(arg("displayId"));
        assertTrue(taskId >= 0 && displayId >= 0);
        assertNotNull("Observed display disappeared", ((DisplayManager)context.getSystemService(Context.DISPLAY_SERVICE)).getDisplay(displayId));
        List<ActivityManager.AppTask> tasks = ((ActivityManager)context.getSystemService(Context.ACTIVITY_SERVICE)).getAppTasks();
        assertEquals("Own task must be unambiguous", 1, tasks.size());
        ActivityManager.RecentTaskInfo task = tasks.get(0).getTaskInfo();
        assertNotNull("Own task snapshot missing", task);
        assertEquals("Own task changed", taskId, task.taskId);
        assertNotNull("Own task base intent missing", task.baseIntent);
        assertNotNull("Own task must have an explicit component", task.baseIntent.getComponent());
        assertEquals(PACKAGE, task.baseIntent.getComponent().getPackageName());
        ActivityInfo activity = context.getPackageManager().getActivityInfo(
            task.baseIntent.getComponent(), 0);
        assertNotNull("Own task activity not registered", activity);
        assertEquals(PACKAGE, activity.packageName);
        assertEquals(task.baseIntent.getComponent().getClassName(), activity.name);
        assertNotNull("Own task application identity missing", activity.applicationInfo);
        assertEquals("Own task UID mismatch", context.getApplicationInfo().uid, activity.applicationInfo.uid);
        // AOSP API35 retains the recent task/baseIntent after its Activity records are removed.
        // This is a task-ownership check, not a claim that a stopped task is visible or focused.
        if (task.baseActivity == null) {
            assertFalse("Missing base activity on a running task", task.isRunning);
            assertEquals("Stopped task still has activities", 0, task.numActivities);
            assertNull("Stopped task still has a top activity", task.topActivity);
        } else {
            assertTrue("Activity present on a non-running task", task.isRunning);
            assertTrue("Running task must contain activities", task.numActivities > 0);
            assertEquals(PACKAGE, task.baseActivity.getPackageName());
            assertNotNull("Running task top activity missing", task.topActivity);
            assertEquals(PACKAGE, task.topActivity.getPackageName());
        }
        // No UI action is made: a display existing is not reported as viewport/UI validation.
    }
    private Path directory(String scenario, boolean recover) throws Exception {
        String run = arg("runId");
        assertEquals(run, UUID.fromString(run).toString());
        Path files = getInstrumentation().getTargetContext().getFilesDir().toPath();
        String owner = scenario + "\n" + arg("agent") + "\n" + arg("device") + "\n"
            + arg("bootId") + "\n" + arg("signatureSha256") + "\n" + arg("origin") + "\n";
        return ownedDirectory(files, run, owner.getBytes(StandardCharsets.UTF_8), recover);
    }
    // BEGIN HOST_TESTABLE_NAMESPACE
    private static Path ownedDirectory(Path files, String run, byte[] owner, boolean recover) throws Exception {
        if (!UUID.fromString(run).toString().equals(run)) throw new IllegalArgumentException("invalid_run_id");
        if (!Files.isDirectory(files, LinkOption.NOFOLLOW_LINKS) || Files.isSymbolicLink(files))
            throw new IllegalStateException("unsafe_files_directory");
        Path root = files.resolve("mumu-https-qa");
        if (!recover && !Files.exists(root, LinkOption.NOFOLLOW_LINKS)) Files.createDirectory(root);
        if (!Files.isDirectory(root, LinkOption.NOFOLLOW_LINKS) || Files.isSymbolicLink(root))
            throw new IllegalStateException("unsafe_namespace_root");
        Path runDirectory = root.resolve(run);
        if (!recover) {
            Files.createDirectory(runDirectory);
            Files.write(runDirectory.resolve("owner"), owner, StandardOpenOption.CREATE_NEW);
            Files.createDirectory(runDirectory.resolve("journal"));
        }
        if (!Files.isDirectory(runDirectory, LinkOption.NOFOLLOW_LINKS) || Files.isSymbolicLink(runDirectory))
            throw new IllegalStateException("unsafe_run_directory");
        Path ownerPath = runDirectory.resolve("owner");
        if (!Files.isRegularFile(ownerPath, LinkOption.NOFOLLOW_LINKS))
            throw new IllegalStateException("unsafe_owner_file");
        try (java.nio.channels.SeekableByteChannel channel = Files.newByteChannel(ownerPath,
                StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)) {
            if (channel.size() > 4096) throw new IllegalStateException("owner_limit");
            java.nio.ByteBuffer bytes = java.nio.ByteBuffer.allocate(4097);
            while (bytes.hasRemaining() && channel.read(bytes) != -1) { }
            byte[] actual = java.util.Arrays.copyOf(bytes.array(), bytes.position());
            if (!java.util.Arrays.equals(owner, actual)) throw new IllegalStateException("owner_mismatch");
        }
        Path journal = runDirectory.resolve("journal");
        if (!Files.isDirectory(journal, LinkOption.NOFOLLOW_LINKS) || Files.isSymbolicLink(journal))
            throw new IllegalStateException("unsafe_journal_directory");
        for (String name : new String[]{"runner.lock", "journal.bin"}) {
            Path file = journal.resolve(name);
            if (Files.exists(file, LinkOption.NOFOLLOW_LINKS)
                    && !Files.isRegularFile(file, LinkOption.NOFOLLOW_LINKS))
                throw new IllegalStateException("unsafe_journal_file");
        }
        return journal;
    }
    // END HOST_TESTABLE_NAMESPACE
    private RemoteClock clock() {
        return new RemoteClock() {
            public double monotonicSeconds() { return SystemClock.elapsedRealtimeNanos() / 1e9; }
            public Instant utcNow() { return Instant.now().truncatedTo(ChronoUnit.MICROS); }
            public void sleepMillis(long value) throws InterruptedException { Thread.sleep(value); }
        };
    }
    public void testScenario() throws Exception {
        guard();
        String scenario = arg("scenario"), stage = arg("stage");
        assertTrue(java.util.Arrays.asList("completed", "two_jobs", "disconnect_running", "lost_renew", "cancel", "restart").contains(scenario));
        assertTrue(stage.equals("run") || scenario.equals("restart") && stage.equals("recover"));
        boolean recover = stage.equals("recover");
        Path directory = directory(scenario, recover);
        try (HttpsAgentClient client = new HttpsAgentClient(arg("origin"), arg("token")); RemoteJournal journal = new RemoteJournal(directory)) {
            if (scenario.equals("two_jobs")) {
                session(client, journal);
            } else {
                single(client, journal, scenario, recover);
            }
        }
    }
    private void single(HttpsAgentClient client, RemoteJournal journal, String scenario, boolean recover) throws Exception {
        RemoteFakeDriver driver = new RemoteFakeDriver();
        RemoteAgentRunner runner = new RemoteAgentRunner(client, journal, driver, clock(), arg("agent"), arg("device"), 2);
        AgentHello hello = new AgentHello(arg("agent"), arg("device"), UUID.randomUUID().toString(), clock().utcNow());
        client.hello(hello);
        runner.setHeartbeatObservation(hello);
        AtomicReference<Throwable> failure = new AtomicReference<>();
        Thread worker = new Thread(() -> { try { runner.runOnce(); } catch (Throwable error) { failure.set(error); } }, "mumu-own-simulation");
        worker.start();
        Throwable primary = null;
        try {
            if (scenario.equals("disconnect_running") || scenario.equals("restart") && !recover) {
                long end = SystemClock.elapsedRealtime() + 12000;
                while (driver.startCount() == 0 && worker.isAlive() && SystemClock.elapsedRealtime() < end) SystemClock.sleep(5);
                assertEquals(1, driver.startCount());
                assertNotNull(runner.currentJob());
                assertTrue(journal.hasStart(runner.currentJob().jobId));
                if (scenario.equals("restart")) {
                    marker("READY restart starts=1 persisted_start=true");
                    SystemClock.sleep(60000);
                    fail("Host did not interrupt own process");
                }
                runner.requestStop();
                client.close();
            }
            worker.join(20000);
            assertFalse("Worker did not stop within its budget", worker.isAlive());
            assertNull("Worker failed", failure.get());
            assertTrue("Driver must stop before result", driver.stopped());
            JobView view = runner.currentJob();
            assertNotNull(view);
            if (scenario.equals("completed")) assertEquals("completed", view.state);
            else if (scenario.equals("cancel")) assertEquals("cancelled", view.state);
            else if (recover) {
                assertEquals("needs_attention", view.state);
                assertTrue(journal.hasStart(view.jobId));
                assertEquals(0.0, driver.distanceM(), 0.0);
            } else assertFalse("Uncertain execution cannot complete", "completed".equals(view.state));
            assertEquals(recover ? 0 : 1, driver.startCount());
            if (scenario.equals("lost_renew")) assertEquals("attention_unconfirmed", runner.localStatus());
            double distance = driver.distanceM();
            SystemClock.sleep(200);
            assertEquals(distance, driver.distanceM(), 0.0);
            marker("PASS case=" + scenario + " starts=" + driver.startCount() + " stopped=true");
        } catch (Exception | AssertionError bodyFailure) {
            primary = bodyFailure; failureMarker("body", bodyFailure); throw bodyFailure;
        } finally {
            try {
                runner.requestStop(); client.close(); worker.join(7000);
                assertFalse("Owned worker survived cleanup", worker.isAlive());
            } catch (Exception | AssertionError cleanup) {
                failureMarker("cleanup", cleanup);
                if (primary != null) primary.addSuppressed(new AssertionError("owned_worker_cleanup_failed"));
                else throw cleanup;
            }
        }
    }
    private Object field(Object object, String name) throws Exception {
        java.lang.reflect.Field field = object.getClass().getDeclaredField(name);
        field.setAccessible(true);
        return field.get(object);
    }
    private void session(HttpsAgentClient client, RemoteJournal journal) throws Exception {
        RemoteForegroundSession session = new RemoteForegroundSession(client, journal, clock(), arg("agent"), arg("device"), 2);
        Set<RemoteFakeDriver> drivers = Collections.newSetFromMap(new IdentityHashMap<>());
        Set<String> completed = new java.util.HashSet<>();
        AtomicReference<Throwable> failure = new AtomicReference<>();
        Thread worker = new Thread(() -> { try { session.run(); } catch (Throwable error) { failure.set(error); } }, "mumu-own-session");
        worker.start();
        Throwable primary = null;
        try {
            long end = SystemClock.elapsedRealtime() + 30000;
            while (completed.size() < 2 && worker.isAlive() && SystemClock.elapsedRealtime() < end) {
                RemoteAgentRunner active = (RemoteAgentRunner)field(session, "active");
                if (active != null) drivers.add((RemoteFakeDriver)field(active, "driver"));
                JobView job = session.currentJob();
                if (job != null && "completed".equals(job.state)) completed.add(job.jobId);
                SystemClock.sleep(2);
            }
            assertEquals("Two distinct jobs must complete in one session", 2, completed.size());
            session.requestStop();
            worker.join(7000);
            assertFalse(worker.isAlive());
            assertNull(failure.get());
            int starts = 0;
            for (RemoteFakeDriver driver : drivers) { starts += driver.startCount(); assertTrue(driver.stopped()); }
            assertEquals("Exactly two starts across session drivers", 2, starts);
            marker("PASS case=two_jobs starts=2 stopped=true");
        } catch (Exception | AssertionError bodyFailure) {
            primary = bodyFailure; failureMarker("body", bodyFailure); throw bodyFailure;
        } finally {
            try {
                session.requestStop(); client.close(); worker.join(7000);
                assertFalse("Owned session survived cleanup", worker.isAlive());
            } catch (Exception | AssertionError cleanup) {
                failureMarker("cleanup", cleanup);
                if (primary != null) primary.addSuppressed(new AssertionError("owned_session_cleanup_failed"));
                else throw cleanup;
            }
        }
    }
}
