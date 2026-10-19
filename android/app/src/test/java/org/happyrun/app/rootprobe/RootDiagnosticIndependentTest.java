package org.happyrun.app.rootprobe;

import org.junit.Test;
import static org.junit.Assert.*;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

/** All launches are injected memory-only Process objects. Never calls production process discovery. */
public final class RootDiagnosticIndependentTest {
    @Test public void timeoutUsesOneFixedCommandAndAlwaysDestroysFakeChild() {
        AtomicInteger launches = new AtomicInteger();
        AtomicLong time = new AtomicLong();
        MemoryProcess child = new MemoryProcess("", 0, true);
        RootReport result = RootDiagnostic.run(command -> {
            launches.incrementAndGet();
            assertArrayEquals(new String[]{"su", "-c", "id"}, command);
            return child;
        }, () -> false, time::get, ms -> time.addAndGet(ms * 1_000_000L));
        assertEquals("timeout", result.status);
        assertFalse(result.uidZeroObserved);
        assertEquals(1, launches.get());
        assertTrue(child.destroyed);
    }
    @Test public void successfulUidZeroNeedsBothExitSuccessAndExactIdentity() {
        String[] outputs = {"uid=0(root) gid=0(root)\n", "uid=1000(shell)\n", "Permission denied uid=0\n"};
        for (String output : outputs) {
            for (int exit : new int[]{0, 1}) {
                MemoryProcess child = new MemoryProcess(output, exit, false);
                AtomicInteger launches = new AtomicInteger();
                RootReport result = RootDiagnostic.run(command -> {
                    launches.incrementAndGet(); return child;
                }, () -> false, () -> 0L, ms -> { throw new AssertionError("Exited fake process must not wait"); });
                assertEquals(exit == 0 && output.startsWith("uid=0(root)"), result.uidZeroObserved);
                assertEquals(1, launches.get());
                assertTrue(child.destroyed);
            }
        }
    }
    @Test public void alreadyCancelledCannotInvokeEvenInjectedFactory() {
        RootReport result = RootDiagnostic.run(command -> { throw new AssertionError("No launch allowed"); },
            () -> true, () -> 0L, ms -> { throw new AssertionError("No wait allowed"); });
        assertEquals("cancelled", result.status);
        assertFalse(result.uidZeroObserved);
    }
    private static final class MemoryProcess extends Process {
        private final InputStream output;
        private final int exit;
        private boolean alive;
        private boolean destroyed;
        MemoryProcess(String text, int exit, boolean alive) {
            this.output = new ByteArrayInputStream(text.getBytes(java.nio.charset.StandardCharsets.UTF_8));
            this.exit = exit; this.alive = alive;
        }
        @Override public OutputStream getOutputStream() { return new ByteArrayOutputStream(); }
        @Override public InputStream getInputStream() { return output; }
        @Override public InputStream getErrorStream() { return new ByteArrayInputStream(new byte[0]); }
        @Override public int waitFor() { throw new AssertionError("Unbounded waiting forbidden"); }
        @Override public int exitValue() { if (alive) throw new IllegalThreadStateException(); return exit; }
        @Override public boolean isAlive() { return alive; }
        @Override public void destroy() { destroyed = true; alive = false; }
        @Override public Process destroyForcibly() { destroy(); return this; }
    }
}
