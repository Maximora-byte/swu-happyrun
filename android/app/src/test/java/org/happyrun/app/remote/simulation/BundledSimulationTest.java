package org.happyrun.app.remote.simulation;
import org.junit.Test;
import static org.junit.Assert.*;
public class BundledSimulationTest {
 @Test public void packagedCanonicalBytesMatchPythonRevisions() throws Exception {BundledSimulationProfiles.verifyAssets();assertTrue(BundledSimulationProfiles.DISTANCE_M>1.5);assertTrue(BundledSimulationProfiles.DISTANCE_M<1.6);}
 @Test public void motionStopsAtActualEndpoint() {RemoteFakeDriver d=new RemoteFakeDriver();d.start(()->{});d.tick(.2,()->{});assertFalse(d.finished());d.tick(1,()->{});assertTrue(d.finished());assertEquals(.20001,d.latitude(),0);d.stop();assertTrue(d.stopped());}
 @Test public void guardPreventsProgressAndStartCannotRepeat() {RemoteFakeDriver d=new RemoteFakeDriver();try{d.start(()->{throw new IllegalStateException();});fail();}catch(IllegalStateException e){}assertEquals(0,d.startCount());d.start(()->{});try{d.start(()->{});fail();}catch(IllegalStateException e){}double before=d.latitude();try{d.tick(1,()->{throw new IllegalStateException();});fail();}catch(IllegalStateException e){}assertEquals(before,d.latitude(),0);}
}
