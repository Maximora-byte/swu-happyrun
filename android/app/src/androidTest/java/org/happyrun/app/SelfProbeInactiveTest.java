package org.happyrun.app;

import android.test.InstrumentationTestCase;
import org.happyrun.app.selfprobe.ProbeReport;
import org.happyrun.app.selfprobe.SelfProbe;

/** Runs on a disposable official AVD without a framework, for both APK variants. */
public final class SelfProbeInactiveTest extends InstrumentationTestCase {
    public void testNoFrameworkReturnsInactive() throws Exception {
        String expected = ((android.test.InstrumentationTestRunner) getInstrumentation())
                .getArguments().getString("expectedProbeVariant");
        assertTrue("Explicit expected variant required",
                "debug".equals(expected) || "optional".equals(expected));
        // Reflection through target loader avoids javac inlining the test build's constant.
        Class<?> targetConfig = getInstrumentation().getTargetContext().getClassLoader()
                .loadClass("org.happyrun.app.BuildConfig");
        boolean packaged = targetConfig.getField("SELF_PROBE_ENABLED").getBoolean(null);
        assertEquals("Installed target variant", "optional".equals(expected), packaged);
        for (int i = 0; i < 10; i++) {
            ProbeReport report = SelfProbe.inspect();
            assertFalse(report.active);
            assertNull(report.bridgeApiVersion);
        }
    }
}
