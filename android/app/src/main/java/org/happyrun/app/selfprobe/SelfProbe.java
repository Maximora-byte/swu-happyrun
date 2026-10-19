package org.happyrun.app.selfprobe;
import java.util.UUID;
/** Local live-method diagnostic only; not security attestation or device permission. */
public final class SelfProbe {
    private SelfProbe() {}
    // The optional module hooks only this method. Base APK always returns null.
    public static String response(String challenge) { return null; }
    public static ProbeReport inspect() {
        String challenge=UUID.randomUUID().toString().replace("-","");
        try {
            Object response=SelfProbe.class.getDeclaredMethod("response",String.class).invoke(null,challenge);
            return evaluate(challenge,response instanceof String ? (String)response : null);
        } catch(ReflectiveOperationException | RuntimeException failure) {
            return new ProbeReport("unknown",null);
        }
    }
    static ProbeReport evaluate(String challenge,String response) {
        if(response==null)return new ProbeReport("inactive",null);
        if(challenge==null || !challenge.matches("[0-9a-f]{32}") || response.length()>100)
            return new ProbeReport("unknown",null);
        String[] parts=response.split("\\|",-1);
        if(parts.length!=3 || !"self-v1".equals(parts[0]) || !challenge.equals(parts[1]))return new ProbeReport("unknown",null);
        try {
            int version=Integer.parseInt(parts[2]);
            return version>0 ? new ProbeReport("active",version) : new ProbeReport("unknown",null);
        } catch(NumberFormatException invalid) {return new ProbeReport("unknown",null);}
    }
}
