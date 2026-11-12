package org.happyrun.app.remote.protocol;
import org.junit.Test;
import static org.junit.Assert.*;
import java.util.Map;
public class StrictJsonTest {
 @Test public void parsesWithoutNumericCoercion() {
  Map<?,?> value=(Map<?,?>)StrictJson.parse("{\"n\":1,\"v\":null,\"a\":[true,\"中文\"]}");
  assertNotNull(value); assertEquals(Long.valueOf(1),value.get("n"));
  assertEquals(value,StrictJson.parse(StrictJson.write(value)));
 }
 @Test public void rejectsAmbiguousAndUnboundedInputs() {
  for(String invalid:new String[]{"{\"x\":1,\"x\":2}","{\"x\":1,}","[01]","[NaN]","[1e999]","\"bad\ntext\"","{} trailing","[","\"\\ud800\""}) {
   try {StrictJson.parse(invalid);fail("accepted invalid JSON");}catch(IllegalArgumentException expected){}
  }
 }
}
