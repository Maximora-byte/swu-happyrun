package org.happyrun.app.rootprobe;
import org.junit.Test;
import static org.junit.Assert.*;
import java.io.*;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicBoolean;
public class RootDiagnosticTest {
    static final class FakeProcess extends Process {
        final InputStream output; final int exit; boolean alive; boolean destroyed;
        FakeProcess(String output,int exit,boolean alive) {this.output=new ByteArrayInputStream(output.getBytes(java.nio.charset.StandardCharsets.UTF_8));this.exit=exit;this.alive=alive;}
        public OutputStream getOutputStream(){return new ByteArrayOutputStream();}
        public InputStream getInputStream(){return output;}
        public InputStream getErrorStream(){return new ByteArrayInputStream(new byte[0]);}
        public int waitFor(){alive=false;return exit;}
        public int exitValue(){if(alive)throw new IllegalThreadStateException();return exit;}
        public boolean isAlive(){return alive;}
        public void destroy(){destroyed=true;alive=false;}
        public Process destroyForcibly(){destroy();return this;}
    }
    RootReport inspect(FakeProcess p) {
        AtomicLong now=new AtomicLong();
        return RootDiagnostic.run(command->{assertArrayEquals(new String[]{"su","-c","id"},command);return p;},()->false,now::get,ms->now.addAndGet(ms*1_000_000L));
    }
    @Test public void onlySuccessfulExactUidZeroIsObserved() {
        RootReport yes=inspect(new FakeProcess("uid=0(root) gid=0(root) groups=0(root)\n",0,false));
        assertTrue(yes.uidZeroObserved);assertEquals("uid_zero_observed",yes.status);
        assertFalse(inspect(new FakeProcess("uid=1000(shell) gid=1000\n",0,false)).uidZeroObserved);
        assertEquals("invalid_response",inspect(new FakeProcess("warning uid=0(root)",0,false)).status);
        assertEquals("nonzero_exit",inspect(new FakeProcess("uid=0(root)",1,false)).status);
    }
    @Test public void boundedOutputAndDeadlineCleanUp() {
        FakeProcess huge=new FakeProcess("x".repeat(4097),0,true);
        assertEquals("output_limit",inspect(huge).status);assertTrue(huge.destroyed);
        FakeProcess stuck=new FakeProcess("",0,true);
        assertEquals("timeout",inspect(stuck).status);assertTrue(stuck.destroyed);
    }
    @Test public void cancellationDoesNotLaunchAndDoesNotRetry() {
        AtomicLong calls=new AtomicLong();
        RootReport r=RootDiagnostic.run(command->{calls.incrementAndGet();throw new IOException();},()->true,System::nanoTime,Thread::sleep);
        assertEquals("cancelled",r.status);assertEquals(0,calls.get());
        r=RootDiagnostic.run(command->{calls.incrementAndGet();throw new IOException();},()->false,System::nanoTime,Thread::sleep);
        assertEquals("launch_failed",r.status);assertEquals(1,calls.get());
    }
    @Test public void cancellationAfterLaunchDestroysChild() {
        FakeProcess p=new FakeProcess("",0,true);AtomicBoolean cancel=new AtomicBoolean();
        RootReport r=RootDiagnostic.run(command->p,cancel::get,System::nanoTime,ms->cancel.set(true));
        assertEquals("cancelled",r.status);assertTrue(p.destroyed);
    }
    @Test public void threadInterruptionCleansUpWithoutSuccess() {
        FakeProcess p=new FakeProcess("",0,true);
        RootReport r=RootDiagnostic.run(command->p,()->false,System::nanoTime,ms->{throw new InterruptedException();});
        assertEquals("interrupted",r.status);assertTrue(p.destroyed);
        assertTrue(Thread.interrupted());
    }
    @Test public void refusalIsNotMistakenForMissingSu() {
        assertEquals("nonzero_exit",inspect(new FakeProcess("Permission denied\n",1,false)).status);
        assertEquals("invalid_response",inspect(new FakeProcess("",0,false)).status);
        assertEquals("invalid_response",inspect(new FakeProcess("uid=0(root)\nuid=1000(shell)",0,false)).status);
    }
    @Test public void alreadyInterruptedNeverLaunches() {
        AtomicLong calls=new AtomicLong();Thread.currentThread().interrupt();
        try {
            RootReport report=RootDiagnostic.run(command->{calls.incrementAndGet();return new FakeProcess("",0,true);},()->false,System::nanoTime,Thread::sleep);
            assertEquals("interrupted",report.status);assertEquals(0,calls.get());
        } finally {Thread.interrupted();}
    }
}
