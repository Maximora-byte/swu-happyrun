package org.happyrun.app.remote.protocol;
import org.junit.Test;
import static org.junit.Assert.*;
import java.time.Instant;
import java.util.Map;
public class ProtocolCodecTest {
 public static final String ID="00000000-0000-0000-0000-000000000001";
 public static JobSpec spec() {return new JobSpec(1,"simulation",ID,"a".repeat(64),ID,"b".repeat(64),ID,Instant.parse("2026-10-19T00:00:00Z"),Instant.parse("2026-10-19T01:00:00Z"),null);}
 public static JobView job() {return new JobView(ID,spec(),"leased",1,"run",1,ID,null,null,null,ID);}
 @Test public void exactRoundTripAndNullFields() {JobView j=job();assertEquals(j,ProtocolCodec.decodeJob(StrictJson.write(ProtocolCodec.job(j))));}
 @Test public void rejectUnknownMissingCoercedAndDevice() {
  for(Object value:new Object[]{true,1.0,"1",-1L}) {
   Map<String,Object> m=ProtocolCodec.spec(spec());m.put("protocol_version",value);reject(()->ProtocolCodec.spec(m));
  }
  Map<String,Object> missing=ProtocolCodec.job(job());missing.remove("reason_code");reject(()->ProtocolCodec.job(missing));
  Map<String,Object> bad=ProtocolCodec.job(job());bad.put("unexpected",null);reject(()->ProtocolCodec.job(bad));
  reject(()->new JobSpec(1,"device",ID,"a".repeat(64),ID,"b".repeat(64),ID,Instant.now(),Instant.now().plusSeconds(3),"app"));
 }
 @Test public void strictStatesTimeAndFences() {
  reject(()->new JobView(ID,spec(),"succeeded",1,"run",1,ID,null,null,null,ID));
  reject(()->new JobView(ID,spec(),"needs_attention",1,"run",1,ID,null,null,null,ID));
  reject(()->new LeaseGrant(job(),"synthetic",2,Instant.parse("2026-10-19T00:00:30Z")));
  for(String t:new String[]{"0000-01-01T00:00:00Z","2026-02-30T00:00:00Z","2026-10-19T00:00:00+00:00","2026-10-19T00:00:00.1234567Z","2026-10-19T00:00:60Z"})reject(()->Checks.time(t));
 }
 @Test public void noCredentialInDiagnosticRepresentation() {assertFalse(new LeaseCommand("synthetic-secret",1).toString().contains("synthetic-secret"));}
 private static void reject(Runnable r) {try{r.run();fail("invalid protocol accepted");}catch(IllegalArgumentException expected){}}
}
