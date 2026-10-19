package org.happyrun.app.remote.simulation;
import org.junit.Test;
import static org.junit.Assert.*;
public final class RemoteFakeObservationTest {
 @Test public void successfulTicksRemainObservableAfterDistanceSaturates() {
  RemoteFakeDriver d=new RemoteFakeDriver();assertEquals(0,d.tickCount());d.start(()->{});
  d.tick(1,()->{});double endpoint=d.distanceM();assertEquals(1,d.tickCount());
  d.tick(2,()->{});assertEquals(endpoint,d.distanceM(),0);assertEquals(2,d.tickCount());
  d.stop();try{d.tick(3,()->{});fail();}catch(IllegalStateException expected){}
  assertEquals(2,d.tickCount());assertEquals(3,d.tickAttemptCount());
 }
 @Test public void rejectedOrGuardedTicksDoNotCountAsEffects() {
  RemoteFakeDriver d=new RemoteFakeDriver();
  try{d.tick(0,()->{});fail();}catch(IllegalStateException expected){}
  d.start(()->{});
  try{d.tick(1,()->{throw new IllegalStateException("lease_lost");});fail();}catch(IllegalStateException expected){}
  try{d.tick(Double.NaN,()->{});fail();}catch(IllegalStateException expected){}
  assertEquals(0,d.tickCount());assertEquals(3,d.tickAttemptCount());assertEquals(0,d.distanceM(),0);
 }
}
