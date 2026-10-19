package org.happyrun.app;

import android.test.InstrumentationTestCase;
import java.lang.reflect.Method;
import java.nio.file.Files;
import java.nio.file.Path;
import org.happyrun.app.remote.journal.RemoteJournal;

/** Local journal only. No endpoint contact, token, Activity launch or root action. */
@SuppressWarnings("deprecation")
public final class RemoteNamespaceProofTest extends InstrumentationTestCase {
    private static final String ORIGIN = "https://example.invalid";
    private static final String AGENT = "00000000-0000-4000-8000-000000000001";
    private static final String DEVICE = "00000000-0000-4000-8000-000000000002";
    private static final String JOB = "00000000-0000-4000-8000-000000000003";
    private static final String SESSION = "00000000-0000-4000-8000-000000000004";
    private static final String OTHER = "00000000-0000-4000-8000-000000000099";
    private static final String DIGEST = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

    private String namespace(String origin, String agent, String device) throws Exception {
        Method method = RemoteAgentActivity.class.getDeclaredMethod(
                "namespace", String.class, String.class, String.class);
        method.setAccessible(true);
        return (String) method.invoke(null, origin, agent, device);
    }

    private void assertIsolated(String origin, String agent, String device) throws Exception {
        Path root = Files.createTempDirectory(
                getInstrumentation().getTargetContext().getCacheDir().toPath(), "namespace-proof-");
        String oldName = namespace(ORIGIN, AGENT, DEVICE);
        String newName = namespace(origin, agent, device);
        assertFalse(oldName.equals(newName));
        Path original = root.resolve(oldName);
        try (RemoteJournal journal = new RemoteJournal(original)) {
            journal.bind(JOB, SESSION, 1, DIGEST);
            journal.startIntent(JOB, SESSION, 1);
            journal.stopped(JOB, SESSION, 1, true);
        }
        // Identical job/session/spec and a newer authorized fence deliberately
        // maximize the chance of a namespace collision consuming old proof.
        try (RemoteJournal isolated = new RemoteJournal(root.resolve(newName))) {
            isolated.bind(JOB, SESSION, 2, DIGEST);
            assertFalse(isolated.hasStart(JOB));
            assertFalse(isolated.completedForRecovery(JOB, SESSION, 2, DIGEST));
        }
        // The other namespace has not consumed, erased or rebound the proof.
        try (RemoteJournal originalJournal = new RemoteJournal(original)) {
            originalJournal.bind(JOB, SESSION, 2, DIGEST);
            assertTrue(originalJournal.completedForRecovery(JOB, SESSION, 2, DIGEST));
        }
    }

    public void testChangedOriginCannotConsumeProof() throws Exception {
        assertIsolated("https://other.invalid", AGENT, DEVICE);
    }
    public void testChangedAgentCannotConsumeProof() throws Exception {
        assertIsolated(ORIGIN, OTHER, DEVICE);
    }
    public void testChangedDeviceCannotConsumeProof() throws Exception {
        assertIsolated(ORIGIN, AGENT, OTHER);
    }
}
