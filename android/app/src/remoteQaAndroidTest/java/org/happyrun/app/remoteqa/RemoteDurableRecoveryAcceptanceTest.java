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
import org.happyrun.app.remote.transport.HttpsAgentClient;
import org.happyrun.app.remote.runtime.RemoteClock;
import org.happyrun.app.remote.runtime.RemoteAgentRunner;
import org.happyrun.app.remote.journal.RemoteJournal;
import org.happyrun.app.remote.simulation.RemoteFakeDriver;

/** Two actual app processes and the real HTTPS runner. No fabricated journal evidence. */
@SuppressWarnings("deprecation")
public final class RemoteDurableRecoveryAcceptanceTest extends InstrumentationTestCase {
    private String arg(String name) {
        String value=((InstrumentationTestRunner)getInstrumentation()).getArguments().getString(name);
        assertNotNull("Missing disposable fixture argument",value);return value;
    }
    private void marker(String text) {
        Bundle result=new Bundle();result.putString("stream","\nDURABLE_RECOVERY "+text+"\n");getInstrumentation().sendStatus(0,result);
    }
    public void testStage()throws Exception {
        String stage=arg("stage"),agent=arg("agent"),device=arg("device");
        assertTrue("Unknown stage",stage.equals("prepare")||stage.equals("recover"));
        Path directory=getInstrumentation().getTargetContext().getFilesDir().toPath().resolve("durable-recovery-qa");
        RemoteClock clock=new RemoteClock() {
            public double monotonicSeconds(){return SystemClock.elapsedRealtimeNanos()/1e9;}
            public Instant utcNow(){return Instant.now().truncatedTo(ChronoUnit.MICROS);}
            public void sleepMillis(long milliseconds)throws InterruptedException{Thread.sleep(milliseconds);}
        };
        try(HttpsAgentClient client=new HttpsAgentClient(arg("origin"),arg("token"));RemoteJournal journal=new RemoteJournal(directory)) {
            AgentHello hello=new AgentHello(agent,device,UUID.randomUUID().toString(),clock.utcNow());client.hello(hello);
            RemoteFakeDriver driver=new RemoteFakeDriver();
            RemoteAgentRunner runner=new RemoteAgentRunner(client,journal,driver,clock,agent,device,2);
            runner.setHeartbeatObservation(hello);
            if(stage.equals("prepare")) {
                AtomicReference<Throwable> failure=new AtomicReference<>();
                Thread worker=new Thread(()->{try{runner.runOnce();}catch(Throwable error){failure.set(error);}},"durable-recovery-prepare");worker.start();
                try {
                    long deadline=SystemClock.elapsedRealtime()+12000;boolean proven=false;
                    while(worker.isAlive()&&SystemClock.elapsedRealtime()<deadline) {
                        JobView job=runner.currentJob();
                        if(job!=null&&driver.finished()&&driver.startCount()==1&&driver.stopped()&&journal.finished(job.jobId,job.runSessionId)) {
                            proven=true;marker("READY starts=1 stopped=true persisted_finished=true");break;
                        }
                        SystemClock.sleep(2);
                    }
                    assertTrue("Real durable finished-stop boundary was not observed",proven);
                    assertNull("Prepare worker failed before interruption",failure.get());
                    // Host performs a real am force-stop while verifying is held before commit.
                    SystemClock.sleep(60000);fail("Host never interrupted the first app process");
                }finally{runner.requestStop();client.close();worker.join(7000);}
                return;
            }
            JobView result=runner.runOnce();
            assertNotNull("No recovery grant",result);assertEquals("completed",result.state);
            assertEquals("Recovery replayed a start",0,driver.startCount());
            assertEquals("Recovery advanced synthetic distance",0.0,driver.distanceM(),0.0);
            assertFalse("Recovery reconstructed a finished moving driver",driver.finished());
            assertTrue("Recovery did not stop the local driver",driver.stopped());
            assertTrue("Original start journal evidence disappeared",journal.hasStart(result.jobId));
            marker("PASS state=completed starts=0 distance=0 stopped=true");
        }
    }
}
