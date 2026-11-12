package org.happyrun.app.selfprobe;
import org.junit.Test;
import static org.junit.Assert.*;
public class SelfProbeTest {
    @Test public void scopeIsOnlyOurMainProcess() {
        assertTrue(SelfScope.accepts("org.happyrun.app","org.happyrun.app"));
        assertFalse(SelfScope.accepts("com.lptiyu.tanke","com.lptiyu.tanke"));
        assertFalse(SelfScope.accepts("org.happyrun.app","org.happyrun.app:remote"));
        assertFalse(SelfScope.accepts("android","android"));
        assertFalse(SelfScope.accepts(null,null));
    }
    @Test public void noFrameworkIsInactive() {
        assertFalse(SelfProbe.inspect().active);
        assertNull(SelfProbe.inspect().bridgeApiVersion);
    }
    @Test public void challengeMustMatchAndVersionMustBePositive() {
        String c="0123456789abcdef0123456789abcdef";
        ProbeReport report=SelfProbe.evaluate(c,"self-v1|"+c+"|93");
        assertTrue(report.active);assertEquals(Integer.valueOf(93),report.bridgeApiVersion);
        for(String response:new String[]{"self-v1|wrong|93","self-v1|"+c+"|0","self-v1|"+c+"|-1","self-v1|"+c+"|abc","self-v1|"+c+"|93|extra","active",null}) {
            assertFalse(SelfProbe.evaluate(c,response).active);
        }
    }
}
