package org.happyrun.app.remote.ui;
import org.junit.Test;
import static org.junit.Assert.*;
public final class RemoteSessionPresentationTest {
 @Test public void waitingIsOnlineButNeverClaimsSimulation() {
  assertEquals(RemoteSessionPresentation.WAITING,RemoteSessionPresentation.classify("waiting",null,true));
  assertEquals(RemoteSessionPresentation.CLAIMING,RemoteSessionPresentation.classify("executing_or_claiming",null,true));
  assertEquals(RemoteSessionPresentation.RUNNING,RemoteSessionPresentation.classify("executing_or_claiming","running",true));
 }
 @Test public void finishedTaskKeepsSessionWaiting() {
  assertEquals(RemoteSessionPresentation.WAITING,RemoteSessionPresentation.classify("task_finished","completed",true));
 }
 @Test public void disconnectNeverReportsCancellationFromStaleView() {
  assertEquals(RemoteSessionPresentation.UNCONFIRMED,RemoteSessionPresentation.classify("disconnected_unconfirmed","running",false));
  assertEquals(RemoteSessionPresentation.UNCONFIRMED,RemoteSessionPresentation.classify("waiting",null,false));
 }
 @Test public void attentionAndStorageAreSeparateBlockedOutcomes() {
  assertEquals(RemoteSessionPresentation.ATTENTION,RemoteSessionPresentation.classify("needs_attention","needs_attention",false));
  assertEquals(RemoteSessionPresentation.STORAGE,RemoteSessionPresentation.classify("storage_failed_not_persisted","completed",false));
  assertEquals(RemoteSessionPresentation.UNCONFIRMED,RemoteSessionPresentation.classify("attention_unconfirmed","running",false));
 }
}
