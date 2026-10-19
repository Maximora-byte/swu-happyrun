package org.happyrun.app.remote.journal;

import java.io.*;
import java.nio.ByteBuffer;
import java.nio.channels.*;
import java.nio.file.*;
import java.security.*;
import java.util.*;

/** Private token-free append journal. A partial write latches failure; never truncate/replay. */
public final class RemoteJournal implements AutoCloseable {
 private final FileChannel lockChannel;
 private FileLock lock;
 private FileChannel data;
 private boolean failed,closed;
 private long highestFence;private String highestFenceJob;
 private final Map<String,String> bindings=new HashMap<>();
 private final Map<String,Long> bindingFences=new HashMap<>(),startFences=new HashMap<>(),stopFences=new HashMap<>();
 private final Map<String,String> starts=new HashMap<>(),stops=new HashMap<>(),acks=new HashMap<>();
 public RemoteJournal(Path directory) throws IOException {
  Files.createDirectories(directory);
  if(Files.isSymbolicLink(directory))throw new IOException("unsafe_journal_path");
  Path lp=directory.resolve("runner.lock"),dp=directory.resolve("journal.bin");
  if(Files.isSymbolicLink(lp)||Files.isSymbolicLink(dp))throw new IOException("unsafe_journal_path");
  lockChannel=FileChannel.open(lp,StandardOpenOption.CREATE,StandardOpenOption.WRITE);
  try {
   try{lock=lockChannel.tryLock();}catch(OverlappingFileLockException e){throw new IOException("agent_already_running");}
   if(lock==null)throw new IOException("agent_already_running");
   data=FileChannel.open(dp,StandardOpenOption.CREATE,StandardOpenOption.READ,StandardOpenOption.WRITE);
   if(data.size()>4_000_000)throw new IOException("journal_limit");
   while(data.position()<data.size()) {
    ByteBuffer size=ByteBuffer.allocate(4);readFully(size);size.flip();int n=size.getInt();
    if(n<1||n>1024)throw new IOException("journal_corrupt");
    ByteBuffer bytes=ByteBuffer.allocate(n),hash=ByteBuffer.allocate(32);readFully(bytes);readFully(hash);
    if(!MessageDigest.isEqual(digest(bytes.array()),hash.array()))throw new IOException("journal_corrupt");
    apply(new String(bytes.array(),java.nio.charset.StandardCharsets.US_ASCII));
   }
  }catch(Exception e){if(data!=null)data.close();if(lock!=null)lock.release();lockChannel.close();throw new IOException("journal_unavailable_or_corrupt",e);}
 }
 private void readFully(ByteBuffer b)throws IOException {while(b.hasRemaining())if(data.read(b)<0)throw new IOException("journal_truncated");}
 private static byte[] digest(byte[] bytes){try{return MessageDigest.getInstance("SHA-256").digest(bytes);}catch(NoSuchAlgorithmException e){throw new AssertionError(e);}}
 private static void uuid(String s){if(s==null||!s.matches("[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}"))throw new IllegalArgumentException("invalid_id");}
 private void healthy(){if(failed||closed)throw new IllegalStateException("journal_unavailable");}
 public synchronized boolean healthyState(){return !failed&&!closed;}
 public synchronized void bind(String job,String session,long fence,String specDigest)throws IOException {
  healthy();uuid(job);uuid(session);
  if(specDigest==null||!specDigest.matches("[0-9a-f]{64}")||fence<1)throw new IllegalArgumentException("invalid_binding");
  if(fence<highestFence||(fence==highestFence&&!job.equals(highestFenceJob)))throw new IllegalStateException("stale_fence");
  String expected=session+"|"+specDigest;
  if(bindings.containsKey(job)&&!bindings.get(job).equals(expected))throw new IllegalStateException("session_or_spec_changed");
  append("bind|"+job+"|"+session+"|"+fence+"|0|"+specDigest);
 }
 private void requireBinding(String job,String session,long fence){
  String binding=bindings.get(job);
  if(binding==null||!binding.startsWith(session+"|")||!Objects.equals(bindingFences.get(job),fence)||fence!=highestFence||!job.equals(highestFenceJob))throw new IllegalStateException("invalid_record_binding");
 }
 public synchronized boolean completedForRecovery(String job,String session,long fence,String specDigest){
  healthy();uuid(job);uuid(session);requireBinding(job,session,fence);
  if(!Objects.equals(bindings.get(job),session+"|"+specDigest))return false;
  Long started=startFences.get(job),finished=stopFences.get(job);
  return session.equals(starts.get(job))&&(session+"|finished").equals(stops.get(job))
      &&started!=null&&started.equals(finished)&&finished<fence;
 }
 public synchronized boolean hasStart(String job){healthy();uuid(job);return starts.containsKey(job);}
 public synchronized void startIntent(String job,String session,long fence)throws IOException {
  healthy();uuid(job);uuid(session);if(fence<1)throw new IllegalArgumentException("invalid_fence");
  requireBinding(job,session,fence);
  if(starts.containsKey(job))throw new IllegalStateException("start_already_attempted");
  append("start|"+job+"|"+session+"|"+fence+"|0|intent");
 }
 public synchronized void stopped(String job,String session,long fence,boolean finished)throws IOException {
  healthy();uuid(job);uuid(session);if(fence<1)throw new IllegalArgumentException("invalid_fence");
  requireBinding(job,session,fence);
  if(finished&&(!session.equals(starts.get(job))||!Objects.equals(startFences.get(job),fence)))throw new IllegalStateException("missing_start_intent");
  append("stop|"+job+"|"+session+"|"+fence+"|0|"+(finished?"finished":"incomplete"));
 }
 public synchronized boolean finished(String job,String session){healthy();return (session+"|finished").equals(stops.get(job));}
 public synchronized String stopAckId(String job,String session,long fence,long revision)throws IOException {
  healthy();uuid(job);uuid(session);if(fence<1||revision<0)throw new IllegalArgumentException("invalid_revision");
  String key=job+"|"+session+"|"+fence+"|"+revision;
  if(!acks.containsKey(key))append("ack|"+key+"|"+UUID.randomUUID());
  return acks.get(key);
 }
 private void append(String record)throws IOException {
  byte[] bytes=record.getBytes(java.nio.charset.StandardCharsets.US_ASCII);
  try {
   if(data.size()+bytes.length+36>4_000_000)throw new IOException("journal_limit");
   ByteBuffer out=ByteBuffer.allocate(bytes.length+36).putInt(bytes.length).put(bytes).put(digest(bytes));out.flip();
   while(out.hasRemaining())data.write(out);data.force(true);apply(record);
  }catch(Exception e){failed=true;throw new IOException("journal_write_failed",e);}
 }
 private void apply(String s)throws IOException {
  try {
   String[] v=s.split("\\|",-1);if(v.length!=6)throw new IllegalArgumentException();uuid(v[1]);uuid(v[2]);
   if(Long.parseLong(v[3])<1||Long.parseLong(v[4])<0)throw new IllegalArgumentException();
   switch(v[0]) {
    case "bind": if(!v[5].matches("[0-9a-f]{64}")||(Long.parseLong(v[3])<highestFence||(Long.parseLong(v[3])==highestFence&&!v[1].equals(highestFenceJob))))throw new IllegalArgumentException();String binding=v[2]+"|"+v[5];if(bindings.containsKey(v[1])&&!bindings.get(v[1]).equals(binding))throw new IllegalArgumentException();bindings.put(v[1],binding);bindingFences.put(v[1],Long.parseLong(v[3]));highestFence=Long.parseLong(v[3]);highestFenceJob=v[1];break;
    case "start": requireBinding(v[1],v[2],Long.parseLong(v[3]));if(!v[5].equals("intent")||starts.putIfAbsent(v[1],v[2])!=null)throw new IllegalArgumentException();startFences.put(v[1],Long.parseLong(v[3]));break;
    case "stop": requireBinding(v[1],v[2],Long.parseLong(v[3]));if(!v[5].equals("finished")&&!v[5].equals("incomplete"))throw new IllegalArgumentException();if(v[5].equals("finished")&&(!v[2].equals(starts.get(v[1]))||!Objects.equals(startFences.get(v[1]),Long.parseLong(v[3]))))throw new IllegalArgumentException();stops.put(v[1],v[2]+"|"+v[5]);stopFences.put(v[1],Long.parseLong(v[3]));break;
    case "ack": uuid(v[5]);String key=String.join("|",Arrays.copyOfRange(v,1,5));if(acks.putIfAbsent(key,v[5])!=null)throw new IllegalArgumentException();break;
    default: throw new IllegalArgumentException();
   }
  }catch(RuntimeException e){throw new IOException("journal_corrupt");}
 }
 public synchronized void close()throws IOException {closed=true;try{if(data!=null)data.close();}finally{try{if(lock!=null)lock.release();}finally{lockChannel.close();}}}
}
