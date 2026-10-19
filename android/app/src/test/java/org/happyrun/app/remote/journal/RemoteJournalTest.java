package org.happyrun.app.remote.journal;
import org.junit.Test;
import static org.junit.Assert.*;
import java.nio.file.*;
public class RemoteJournalTest {
 private final String job="00000000-0000-0000-0000-000000000001", session="00000000-0000-0000-0000-000000000002";
 @Test public void startIntentSurvivesReopenAndCannotRepeat() throws Exception {
  Path dir=Files.createTempDirectory("remote-journal");
  try(RemoteJournal j=new RemoteJournal(dir)){j.startIntent(job,session,1);assertTrue(j.hasStart(job));}
  try(RemoteJournal j=new RemoteJournal(dir)){assertTrue(j.hasStart(job));try{j.startIntent(job,session,2);fail();}catch(IllegalStateException expected){}}
 }
 @Test public void exclusiveLockPreventsSecondRunner() throws Exception {
  Path dir=Files.createTempDirectory("remote-journal");
  try(RemoteJournal j=new RemoteJournal(dir)){try(RemoteJournal other=new RemoteJournal(dir)){fail();}catch(java.io.IOException expected){}}
 }
 @Test public void truncatedJournalFailsClosed() throws Exception {
  Path dir=Files.createTempDirectory("remote-journal");
  try(RemoteJournal j=new RemoteJournal(dir)){j.startIntent(job,session,1);}
  Files.write(dir.resolve("journal.bin"),new byte[]{1},StandardOpenOption.APPEND);
  try(RemoteJournal j=new RemoteJournal(dir)){fail();}catch(java.io.IOException expected){}
 }
 @Test public void stopAckIdentityStableAndCompletionRequiresStopped() throws Exception {
  Path dir=Files.createTempDirectory("remote-journal");String id;
  try(RemoteJournal j=new RemoteJournal(dir)){j.startIntent(job,session,1);id=j.stopAckId(job,session,1,7);assertEquals(id,j.stopAckId(job,session,1,7));j.stopped(job,session,1,false);assertFalse(j.finished(job,session));}
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
   java.lang.reflect.Field f=RemoteJournal.class.getDeclaredField("data");f.setAccessible(true);((java.nio.channels.FileChannel)f.get(j)).close();
   try{j.startIntent(job,session,1);fail();}catch(java.io.IOException expected){}
   assertFalse(j.healthyState());try{j.hasStart(job);fail();}catch(IllegalStateException expected){}
  }
  try(RemoteJournal j=new RemoteJournal(dir)){assertFalse(j.hasStart(job));}
 }
 @Test public void fileNeverContainsCredentialFields()throws Exception {
  Path dir=Files.createTempDirectory("remote-journal");
  try(RemoteJournal j=new RemoteJournal(dir)){j.startIntent(job,session,1);j.stopAckId(job,session,1,2);}
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
}
