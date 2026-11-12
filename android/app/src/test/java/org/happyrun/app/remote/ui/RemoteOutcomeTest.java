package org.happyrun.app.remote.ui;
import org.junit.Test;
import static org.junit.Assert.*;
public final class RemoteOutcomeTest {
 @Test public void onlyIdleMeansEmptyQueue() {
  assertEquals(RemoteOutcome.EMPTY,RemoteOutcome.classify("idle",false));
  assertEquals(RemoteOutcome.UNCONFIRMED,RemoteOutcome.classify("claim_unconfirmed",false));
 }
 @Test public void staleRunningViewIsNeverConfirmation() {
  assertEquals(RemoteOutcome.UNCONFIRMED,RemoteOutcome.classify("attention_unconfirmed",true));
  assertEquals(RemoteOutcome.UNCONFIRMED,RemoteOutcome.classify("execution_stopped",true));
  assertEquals(RemoteOutcome.UNCONFIRMED,RemoteOutcome.classify("running",true));
 }
 @Test public void storageOverridesAnyView() {
  assertEquals(RemoteOutcome.STORAGE_BLOCKED,RemoteOutcome.classify("storage_failed_not_persisted",true));
 }
 @Test public void confirmedStateStillRequiresAView() {
  assertEquals(RemoteOutcome.CONFIRMED,RemoteOutcome.classify("completed",true));
  assertEquals(RemoteOutcome.UNCONFIRMED,RemoteOutcome.classify("completed",false));
 }
}
