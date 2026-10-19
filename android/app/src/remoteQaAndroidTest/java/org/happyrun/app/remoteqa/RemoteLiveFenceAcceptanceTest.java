package org.happyrun.app.remoteqa;

import android.os.Bundle;
import android.os.Process;
import android.os.SystemClock;
import android.test.InstrumentationTestCase;
import android.test.InstrumentationTestRunner;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.UUID;
import org.happyrun.app.remote.journal.RemoteJournal;
import org.happyrun.app.remote.protocol.AgentHello;
import org.happyrun.app.remote.protocol.JobView;
import org.happyrun.app.remote.runtime.RemoteAgentRunner;
import org.happyrun.app.remote.runtime.RemoteClock;
import org.happyrun.app.remote.simulation.RemoteFakeDriver;
import org.happyrun.app.remote.transport.HttpsAgentClient;

/** The old instrumented process remains alive after transport loss and a newer real grant. */
@SuppressWarnings("deprecation")
public final class RemoteLiveFenceAcceptanceTest extends InstrumentationTestCase {
    private String arg(String key) {
        String value = ((InstrumentationTestRunner)getInstrumentation()).getArguments().getString(key);
        assertNotNull("Missing synthetic argument", value); return value;
    }
    private void marker(String value) {
        Bundle bundle = new Bundle(); bundle.putString("stream", "\nLIVE_FENCE " + value + "\n");
        getInstrumentation().sendStatus(0, bundle);
    }
    public void testOldProcessStopsAcrossNewFence() throws Exception {
        String origin=arg("origin"), token=arg("token"), agent=arg("agent"), device=arg("device");
        RemoteClock clock=new RemoteClock() {
            boolean delayed;
            public double monotonicSeconds(){return SystemClock.elapsedRealtimeNanos()/1e9;}
            public Instant utcNow(){return Instant.now().truncatedTo(ChronoUnit.MICROS);}
            public void sleepMillis(long millis)throws InterruptedException {
                // A real scheduling delay after the first successful tick makes the next
                // ordinary maintain() renew due, before the short route can finish.
                if(!delayed){delayed=true;Thread.sleep(5200);}else Thread.sleep(millis);
            }
        };
        RemoteFakeDriver driver=new RemoteFakeDriver();
        try(RemoteJournal journal=new RemoteJournal(getInstrumentation().getTargetContext()
                .getFilesDir().toPath().resolve("live-fence-qa"));
            HttpsAgentClient client=new HttpsAgentClient(origin,token)) {
            AgentHello hello=new AgentHello(agent,device,UUID.randomUUID().toString(),clock.utcNow());
            client.hello(hello);
            RemoteAgentRunner runner=new RemoteAgentRunner(client,journal,driver,clock,agent,device,20);
            runner.setHeartbeatObservation(hello);
            long started=SystemClock.elapsedRealtime(); JobView original=runner.runOnce();
            assertTrue("Run did not terminate within the transport budget",SystemClock.elapsedRealtime()-started<18000);
            assertNotNull(original); assertEquals("running",original.state);
            assertEquals("attention_unconfirmed",runner.localStatus());
            assertEquals(1,driver.startCount()); assertTrue(driver.tickCount()>0);
            assertFalse("Route must still be incomplete at link loss",driver.finished());
            assertTrue(driver.stopped());
            int starts=driver.startCount(),ticks=driver.tickCount(),attempts=driver.tickAttemptCount();
            marker("STOPPED pid="+Process.myPid()+" starts="+starts+" ticks="+ticks+" attempts="+attempts);
            // Separate read-only connection observes the actual new server grant. The
            // failed runner/client are never restarted or replaced for execution.
            try(HttpsAgentClient observer=new HttpsAgentClient(origin,token)) {
                long deadline=SystemClock.elapsedRealtime()+65000; JobView newer=null;
                while(SystemClock.elapsedRealtime()<deadline) {
                    JobView view=observer.getJob(original.jobId);
                    assertEquals(original.runSessionId,view.runSessionId);
                    if(view.fence>original.fence){newer=view;break;}
                    Thread.sleep(200);
                }
                assertNotNull("No real higher fence observed",newer);
                for(int i=0;i<10;i++) {
                    assertEquals(starts,driver.startCount());assertEquals(ticks,driver.tickCount());
                    assertEquals(attempts,driver.tickAttemptCount());assertTrue(driver.stopped());
                    Thread.sleep(200);
                }
                marker("PASS pid="+Process.myPid()+" starts="+starts+" ticks="+ticks+" attempts="+attempts);
            }
        }
    }
}
