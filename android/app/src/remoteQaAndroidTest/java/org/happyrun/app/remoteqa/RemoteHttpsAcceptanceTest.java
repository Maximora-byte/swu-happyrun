package org.happyrun.app.remoteqa;

import android.os.Bundle;
import android.os.SystemClock;
import android.test.InstrumentationTestCase;
import android.test.InstrumentationTestRunner;
import java.nio.file.Path;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;
import org.happyrun.app.remote.protocol.AgentHello;
import org.happyrun.app.remote.protocol.JobView;
import org.happyrun.app.remote.protocol.LeaseGrant;
import org.happyrun.app.remote.protocol.LeaseCommand;
import org.happyrun.app.remote.transport.HttpsAgentClient;
import org.happyrun.app.remote.transport.ControlException;
import org.happyrun.app.remote.journal.RemoteJournal;
import org.happyrun.app.remote.runtime.RemoteAgentRunner;
import org.happyrun.app.remote.runtime.RemoteClock;
import org.happyrun.app.remote.simulation.RemoteFakeDriver;

/** Real HTTPS only. No fake AgentClient, connection injection or manual lifecycle calls. */
@SuppressWarnings("deprecation")
public final class RemoteHttpsAcceptanceTest extends InstrumentationTestCase {
    private String arg(String name) {
        String value = ((InstrumentationTestRunner) getInstrumentation()).getArguments().getString(name);
        assertNotNull("Missing synthetic test argument: " + name, value);
        return value;
    }
    private void report(String state, int starts, boolean stopped) {
        Bundle result = new Bundle();
        result.putString("stream", "\nREMOTE_QA_STATE state=" + state + " starts=" + starts + " stopped=" + stopped + "\n");
        getInstrumentation().sendStatus(0, result);
    }
    private String diagnosticPhase = "arguments";
    private void diagnostic(String value) {
        try {
            Bundle result = new Bundle();
            result.putString("stream", "\nREMOTE_QA " + value + "\n");
            getInstrumentation().sendStatus(0, result);
        } catch (RuntimeException unavailable) { /* Never replace a primary failure. */ }
    }
    private void phase(String value) { diagnosticPhase = value; diagnostic("PHASE " + value); }
    private void diagnosticError(Throwable failure, String phase) {
        String kind = failure.getClass().getSimpleName();
        if (!java.util.Arrays.asList("AssertionFailedError", "AssertionError", "SecurityException",
                "IOException", "IllegalStateException", "RuntimeException", "NullPointerException",
                "ControlException", "InterruptedException").contains(kind)) kind = "other";
        diagnostic("ERROR kind=" + kind + " phase=" + phase);
    }
    public void testScenario() throws Exception {
        try { exercise(); }
        catch (Exception | AssertionError failure) {
            diagnosticError(failure, diagnosticPhase);
            throw failure;
        }
    }
    private void exercise() throws Exception {
        phase("arguments");
        String scenario = arg("scenario"), origin = arg("origin"), agent = arg("agent"), device = arg("device");
        if (scenario.equals("plaintext")) {
            try { new HttpsAgentClient(origin.replace("https:", "http:"), arg("token")); fail("HTTP origin accepted"); }
            catch (IllegalArgumentException expected) { report("http_rejected", 0, true); }
            return;
        }
        AgentHello hello = new AgentHello(agent, device, UUID.randomUUID().toString(), Instant.now().truncatedTo(ChronoUnit.MICROS));
        phase("client_open");
        try (HttpsAgentClient client = new HttpsAgentClient(origin, arg("token"))) {
            if (scenario.equals("bad_ca") || scenario.equals("bad_san") || scenario.equals("bad_token") || scenario.equals("redirect")) {
                boolean failed = false;
                try { client.hello(hello); } catch (ControlException expected) {
                    failed = true;
                    if (scenario.equals("redirect")) assertEquals("Redirect must be rejected without following", 307, expected.httpStatus);
                    if (scenario.equals("bad_token")) assertEquals("Real auth rejection required", 401, expected.httpStatus);
                }
                assertTrue("Unsafe/rejected connection unexpectedly succeeded", failed);
                report("connection_rejected", 0, true);
                return;
            }
            phase("hello_begin");client.hello(hello);phase("hello_return");
            if (scenario.equals("expired")) {
                LeaseGrant grant = client.claim(device);
                assertNotNull(grant);
                phase("expired_wait");SystemClock.sleep(31500);phase("expired_renew");
                boolean failed = false;
                try { client.renew(grant.job.jobId, new LeaseCommand(grant.leaseToken, grant.fence)); }
                catch (ControlException expected) { failed = true; assertEquals("Real expired lease conflict required", 409, expected.httpStatus); }
                assertTrue("Expired lease was renewed", failed);
                report("expired_lease_rejected", 0, true);
                return;
            }
            Path directory = getInstrumentation().getTargetContext().getFilesDir().toPath().resolve("remote-https-qa");
            phase("journal_open");
            try (RemoteJournal journal = new RemoteJournal(directory)) {
                RemoteFakeDriver driver = new RemoteFakeDriver();
                RemoteClock clock = new RemoteClock() {
                    public double monotonicSeconds() { return SystemClock.elapsedRealtimeNanos() / 1e9; }
                    public Instant utcNow() { return Instant.now().truncatedTo(ChronoUnit.MICROS); }
                    public void sleepMillis(long milliseconds) throws InterruptedException { Thread.sleep(milliseconds); }
                };
                RemoteAgentRunner runner = new RemoteAgentRunner(client, journal, driver, clock, agent, device, 2.0);
                runner.setHeartbeatObservation(hello);
                AtomicReference<Throwable> error = new AtomicReference<>();
                Thread worker = new Thread(() -> { try { runner.runOnce(); } catch (Throwable failure) { error.set(failure); diagnosticError(failure, "runner"); } }, "remote-qa-runner");
                phase("worker_start");worker.start();
                if (scenario.equals("local_stop") || scenario.equals("restart_prepare")) {
                    phase("wait_durable_start");
                    long deadline = SystemClock.elapsedRealtime() + 10000;
                    while (driver.startCount() == 0 && worker.isAlive() && SystemClock.elapsedRealtime() < deadline) SystemClock.sleep(10);
                    assertEquals("Real driver did not reach its durable start", 1, driver.startCount());
                    if (scenario.equals("restart_prepare")) {
                        assertNotNull(runner.currentJob());
                        assertTrue(journal.hasStart(runner.currentJob().jobId));
                        report("ready_for_process_kill", 1, driver.stopped());
                        // Host must actually force-stop this process, then reopen the same journal.
                        phase("process_kill_wait");SystemClock.sleep(60000);
                        fail("Host did not perform the required process interruption");
                    }
                    runner.requestStop();
                }
                phase("worker_join_begin");worker.join(15000);phase("worker_join_return");
                boolean fallbackStop = worker.isAlive();
                if (fallbackStop) { phase("fallback_begin");runner.requestStop(); client.close(); worker.join(7000);phase("fallback_return"); }
                diagnostic("SNAPSHOT starts=" + driver.startCount() + " stopped=" + driver.stopped()
                        + " worker_alive=" + worker.isAlive() + " runner_error=" + (error.get()!=null)
                        + " local=" + runner.localStatus());
                phase("assert_worker");
                assertFalse("Acceptance must not rely on emergency fallback stop", fallbackStop);
                assertFalse("Worker exceeded bounded shutdown", worker.isAlive());
                assertNull("Runner leaked an exception", error.get());
                phase("assert_job");
                JobView view = runner.currentJob();
                assertNotNull("No real server job claimed", view);
                assertTrue("Driver must be stopped before reporting", driver.stopped());
                phase("assert_outcome");
                if (scenario.equals("completed")) { assertEquals("completed", view.state); assertEquals(1, driver.startCount()); }
                else if (scenario.equals("cancel") || scenario.equals("stop_only")) { assertEquals("cancelled", view.state); assertEquals(scenario.equals("stop_only") ? 0 : 1, driver.startCount()); }
                else if (scenario.equals("verify_only") || scenario.equals("restart_recover")) { assertEquals("needs_attention", view.state); assertEquals(0, driver.startCount()); assertTrue(journal.hasStart(view.jobId)); }
                else if (scenario.equals("bad_profile")) { assertEquals("needs_attention", view.state); assertEquals(0, driver.startCount()); }
                else { assertFalse("Uncertain execution claimed completion", "completed".equals(view.state)); assertEquals(1, driver.startCount()); }
                if (scenario.equals("lost_renew") || scenario.equals("lost_event")) {
                    phase("assert_uncertain");
                    assertEquals("Timed-out client cannot confirm attention", "attention_unconfirmed", runner.localStatus());
                    phase("assert_stopped_distance");
                    double distance = driver.distanceM();
                    SystemClock.sleep(200);
                    assertEquals("Stopped driver must not keep moving", distance, driver.distanceM(), 0.0);
                }
                phase("report");
                report(view.state, driver.startCount(), driver.stopped());
            }
        }
        phase("resources_closed");
    }
}
