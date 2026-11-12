package org.happyrun.app.remote.journal;
import org.junit.Test;
import static org.junit.Assert.*;
import java.nio.file.*;
public class RemoteJournalTest {
 private final String job="00000000-0000-0000-0000-000000000001", session="00000000-0000-0000-0000-000000000002";
 @Test public void startIntentSurvivesReopenAndCannotRepeat() throws Exception {
  Path dir=Files.createTempDirectory("remote-journal");
  try(RemoteJournal j=new RemoteJournal(dir)){j.bind(job,session,1,"a".repeat(64));j.startIntent(job,session,1);assertTrue(j.hasStart(job));}
  try(RemoteJournal j=new RemoteJournal(dir)){assertTrue(j.hasStart(job));try{j.startIntent(job,session,2);fail();}catch(IllegalStateException expected){}}
 }
 @Test public void exclusiveLockPreventsSecondRunner() throws Exception {
  Path dir=Files.createTempDirectory("remote-journal");
  try(RemoteJournal j=new RemoteJournal(dir)){try(RemoteJournal other=new RemoteJournal(dir)){fail();}catch(java.io.IOException expected){}}
 }
 @Test public void truncatedJournalFailsClosed() throws Exception {
  Path dir=Files.createTempDirectory("remote-journal");
  try(RemoteJournal j=new RemoteJournal(dir)){j.bind(job,session,1,"a".repeat(64));j.startIntent(job,session,1);}
  Files.write(dir.resolve("journal.bin"),new byte[]{1},StandardOpenOption.APPEND);
  try(RemoteJournal j=new RemoteJournal(dir)){fail();}catch(java.io.IOException expected){}
 }
 @Test public void stopAckIdentityStableAndCompletionRequiresStopped() throws Exception {
  Path dir=Files.createTempDirectory("remote-journal");String id;
  try(RemoteJournal j=new RemoteJournal(dir)){j.bind(job,session,1,"a".repeat(64));j.startIntent(job,session,1);id=j.stopAckId(job,session,1,7);assertEquals(id,j.stopAckId(job,session,1,7));j.stopped(job,session,1,false);assertFalse(j.finished(job,session));}
  try(RemoteJournal j=new RemoteJournal(dir)){assertEquals(id,j.stopAckId(job,session,1,7));assertFalse(j.finished(job,session));}
 }
 @Test public void bindingRejectsChangedSessionSpecAndOldFence()throws Exception {
  Path dir=Files.createTempDirectory("remote-journal");
  try(RemoteJournal j=new RemoteJournal(dir)){j.bind(job,session,4,"a".repeat(64));}
  try(RemoteJournal j=new RemoteJournal(dir)){
   try{j.bind(job,session,3,"a".repeat(64));fail();}catch(IllegalStateException expected){}
   try{j.bind(job,session,5,"b".repeat(64));fail();}catch(IllegalStateException expected){}
   j.bind(job,session,5,"a".repeat(64));
  }
 }
 @Test public void realClosedChannelWriteFailureLatchesAndDoesNotConfirmIntent()throws Exception {
  Path dir=Files.createTempDirectory("remote-journal");
  try(RemoteJournal j=new RemoteJournal(dir)){
   j.bind(job,session,1,"a".repeat(64));
   java.lang.reflect.Field f=RemoteJournal.class.getDeclaredField("data");f.setAccessible(true);((java.nio.channels.FileChannel)f.get(j)).close();
   try{j.startIntent(job,session,1);fail();}catch(java.io.IOException expected){}
   assertFalse(j.healthyState());try{j.hasStart(job);fail();}catch(IllegalStateException expected){}
  }
  try(RemoteJournal j=new RemoteJournal(dir)){assertFalse(j.hasStart(job));}
 }
 @Test public void fileNeverContainsCredentialFields()throws Exception {
  Path dir=Files.createTempDirectory("remote-journal");
  try(RemoteJournal j=new RemoteJournal(dir)){j.bind(job,session,1,"a".repeat(64));j.startIntent(job,session,1);j.stopAckId(job,session,1,2);}
  String raw=new String(Files.readAllBytes(dir.resolve("journal.bin")),java.nio.charset.StandardCharsets.ISO_8859_1);
  assertFalse(raw.contains("token"));assertFalse(raw.contains("Authorization"));
 }
 @Test public void anotherJobCannotReuseDeviceFenceEvenAfterReopen()throws Exception {
  Path dir=Files.createTempDirectory("remote-journal");
  try(RemoteJournal j=new RemoteJournal(dir)){j.bind(job,session,4,"a".repeat(64));}
  try(RemoteJournal j=new RemoteJournal(dir)){
   try{j.bind("99999999-9999-4999-8999-999999999999",session,4,"a".repeat(64));fail("second job reused device fence");}catch(IllegalStateException expected){}
  }
 }
 @Test public void completedProofSurvivesReopenWithExactBindingAndFreshFence()throws Exception {
  Path dir=Files.createTempDirectory("proof");try(RemoteJournal j=new RemoteJournal(dir)){j.bind(job,session,1,"a".repeat(64));j.startIntent(job,session,1);j.stopped(job,session,1,true);assertFalse(j.completedForRecovery(job,session,1,"a".repeat(64)));}
  try(RemoteJournal j=new RemoteJournal(dir)){j.bind(job,session,2,"a".repeat(64));assertTrue(j.completedForRecovery(job,session,2,"a".repeat(64)));assertFalse(j.completedForRecovery(job,session,2,"b".repeat(64)));try{j.completedForRecovery(job,session,1,"a".repeat(64));fail();}catch(IllegalStateException expected){}try{j.completedForRecovery(job,"99999999-9999-4999-8999-999999999999",2,"a".repeat(64));fail();}catch(IllegalStateException expected){}}
 }
 @Test public void startIntentAloneDoesNotProveCompletion()throws Exception {
  Path dir=Files.createTempDirectory("proof");try(RemoteJournal j=new RemoteJournal(dir)){j.bind(job,session,1,"a".repeat(64));j.startIntent(job,session,1);}
  try(RemoteJournal j=new RemoteJournal(dir)){j.bind(job,session,2,"a".repeat(64));assertFalse(j.completedForRecovery(job,session,2,"a".repeat(64)));}
 }
 @Test public void recoveryCannotInventFinishedStopUnderNewFence()throws Exception {
  try(RemoteJournal j=new RemoteJournal(Files.createTempDirectory("proof"))){j.bind(job,session,1,"a".repeat(64));j.startIntent(job,session,1);j.bind(job,session,2,"a".repeat(64));try{j.stopped(job,session,2,true);fail();}catch(IllegalStateException expected){}assertFalse(j.completedForRecovery(job,session,2,"a".repeat(64)));}
 }
 @Test public void incompleteStopClearsPriorCompletion()throws Exception {
  Path dir=Files.createTempDirectory("proof");try(RemoteJournal j=new RemoteJournal(dir)){j.bind(job,session,1,"a".repeat(64));j.startIntent(job,session,1);j.stopped(job,session,1,true);j.bind(job,session,2,"a".repeat(64));j.stopped(job,session,2,false);}
  try(RemoteJournal j=new RemoteJournal(dir)){assertFalse(j.completedForRecovery(job,session,2,"a".repeat(64)));}
 }
 private static void appendRecord(Path dir,String record)throws Exception {byte[] b=record.getBytes(java.nio.charset.StandardCharsets.US_ASCII);java.nio.ByteBuffer out=java.nio.ByteBuffer.allocate(b.length+36).putInt(b.length).put(b).put(java.security.MessageDigest.getInstance("SHA-256").digest(b));Files.write(dir.resolve("journal.bin"),out.array(),StandardOpenOption.APPEND);}
 @Test public void replayRejectsValidChecksumWithoutBinding()throws Exception {
  Path dir=Files.createTempDirectory("proof");try(RemoteJournal j=new RemoteJournal(dir)){}appendRecord(dir,"start|"+job+"|"+session+"|1|0|intent");try(RemoteJournal j=new RemoteJournal(dir)){fail();}catch(java.io.IOException expected){}
 }
 @Test public void replayRejectsCompletionFromDifferentFence()throws Exception {
  Path dir=Files.createTempDirectory("proof");try(RemoteJournal j=new RemoteJournal(dir)){j.bind(job,session,1,"a".repeat(64));j.startIntent(job,session,1);j.bind(job,session,2,"a".repeat(64));}appendRecord(dir,"stop|"+job+"|"+session+"|2|0|finished");try(RemoteJournal j=new RemoteJournal(dir)){fail();}catch(java.io.IOException expected){}
 }
 @Test public void staleWritesCannotAddCompletionAfterRebind()throws Exception {
  try(RemoteJournal j=new RemoteJournal(Files.createTempDirectory("proof"))){j.bind(job,session,1,"a".repeat(64));j.startIntent(job,session,1);j.bind(job,session,2,"a".repeat(64));try{j.stopped(job,session,1,true);fail();}catch(IllegalStateException expected){}assertFalse(j.completedForRecovery(job,session,2,"a".repeat(64)));}
 }

}
