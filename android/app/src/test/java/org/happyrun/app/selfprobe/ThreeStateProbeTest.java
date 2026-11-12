package org.happyrun.app.selfprobe;
import org.junit.Test;
import static org.junit.Assert.*;
public class ThreeStateProbeTest {
    @Test public void missingHookIsInactiveButMalformedReceiptUnknown() {
        String c="0123456789abcdef0123456789abcdef";
        assertEquals("inactive",SelfProbe.inspect().status);
        assertEquals("inactive",SelfProbe.evaluate(c,null).status);
        assertEquals("unknown",SelfProbe.evaluate(c,"bad").status);
        assertEquals("unknown",SelfProbe.evaluate(c,"self-v1|"+c+"|0").status);
        ProbeReport active=SelfProbe.evaluate(c,"self-v1|"+c+"|93");
        assertEquals("active",active.status);assertTrue(active.active);
        assertEquals(Integer.valueOf(93),active.bridgeApiVersion);
    }
}
