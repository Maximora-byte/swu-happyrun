package org.happyrun.app.remote.ui;
import org.junit.Test;
import static org.junit.Assert.*;
public final class RemoteSessionGateTest {
 @Test public void requiresForegroundAndExplicitBegin() {
  RemoteSessionGate gate=new RemoteSessionGate();
  assertFalse(gate.begin()); gate.enter(); assertFalse(gate.busy());
  assertTrue(gate.begin()); assertFalse(gate.begin()); gate.finish(); assertFalse(gate.busy());
 }
 @Test public void leaveStopsAttachedRunnerWithoutPretendingServerAck() {
  RemoteSessionGate gate=new RemoteSessionGate(); int[] stops={0};
  gate.enter();assertTrue(gate.begin());gate.attach(()->stops[0]++);gate.leave();
  assertEquals(1,stops[0]);assertTrue(gate.busy());assertTrue(gate.stopping());
  gate.enter();assertFalse(gate.begin());gate.finish();assertTrue(gate.begin());
 }
 @Test public void leaveBeforeWorkerAttachStillStopsAndDoesNotRestart() {
  RemoteSessionGate gate=new RemoteSessionGate(); int[] stops={0};
  gate.enter();assertTrue(gate.begin());gate.leave();gate.attach(()->stops[0]++);
  assertEquals(1,stops[0]);gate.finish();assertFalse(gate.begin());
 }
 @Test public void storageFailureBlocksNewSession() {
  RemoteSessionGate gate=new RemoteSessionGate();gate.enter();gate.begin();gate.block();gate.finish();
  assertFalse(gate.begin());gate.leave();gate.enter();assertFalse(gate.begin());
 }
 @Test public void repeatedStopIsIdempotent() {
  RemoteSessionGate gate=new RemoteSessionGate();int[] stops={0};gate.enter();gate.begin();
  gate.attach(()->stops[0]++);gate.stop();gate.stop();gate.leave();assertEquals(1,stops[0]);
 }
}
