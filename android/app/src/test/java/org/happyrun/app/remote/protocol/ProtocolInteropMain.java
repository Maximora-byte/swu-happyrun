package org.happyrun.app.remote.protocol;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
/** Test-only JSONL bridge; never opens a network connection. */
public final class ProtocolInteropMain {
 public static void main(String[] args)throws Exception {
  if(args.length==1 && args[0].equals("emit")) {
   System.out.println(StrictJson.write(ProtocolCodec.job(ProtocolCodecTest.job())));
   System.out.println(StrictJson.write(ProtocolCodec.hello(new AgentHello(ProtocolCodecTest.ID,ProtocolCodecTest.ID,ProtocolCodecTest.ID,Instant.parse("2026-10-19T00:00:00Z")))));
   System.out.println(StrictJson.write(ProtocolCodec.event(new JobEvent(ProtocolCodecTest.ID,2,"completed",null,null))));return;
  }
  BufferedReader input=new BufferedReader(new InputStreamReader(System.in,StandardCharsets.UTF_8));String line;
  while((line=input.readLine())!=null){try{ProtocolCodec.decodeJob(line);System.out.println("accept");}catch(IllegalArgumentException rejected){System.out.println("reject");}}
 }
}
