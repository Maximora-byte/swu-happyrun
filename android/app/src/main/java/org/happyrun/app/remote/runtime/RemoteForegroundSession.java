package org.happyrun.app.remote.runtime;

import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;
import org.happyrun.app.remote.protocol.*;
import org.happyrun.app.remote.transport.AgentClient;
import org.happyrun.app.remote.journal.RemoteJournal;
import org.happyrun.app.remote.simulation.RemoteFakeDriver;

/** Explicit foreground session. Never reconnects after a fault or starts in the background. */
public final class RemoteForegroundSession {
 private final AgentClient client;
 private final RemoteJournal journal;
 private final RemoteClock clock;
 private final String agentId,deviceId;
 private final double runSeconds;
 private final AtomicBoolean stopping=new AtomicBoolean(),used=new AtomicBoolean();
 private final Object ownerLock=new Object();
 private final AtomicBoolean clientClosed=new AtomicBoolean();
 private Thread ownerThread;
 private volatile RemoteAgentRunner active;
 private volatile JobView latest;
 private volatile String state="disconnected";
 private AgentHello observation;
 private double heartbeatAt;
 public RemoteForegroundSession(AgentClient client,RemoteJournal journal,RemoteClock clock,String agentId,String deviceId,double runSeconds){
  if(client==null||journal==null||clock==null||!Double.isFinite(runSeconds)||runSeconds<=0||runSeconds>30)throw new IllegalArgumentException("invalid_session");
  // Schema constructors validate identity without any network request.
  new AgentHello(agentId,deviceId,UUID.randomUUID().toString(),clock.utcNow());
  this.client=client;this.journal=journal;this.clock=clock;this.agentId=agentId;this.deviceId=deviceId;this.runSeconds=runSeconds;
 }
 public String status(){return state;}
 public JobView currentJob(){RemoteAgentRunner runner=active;return runner!=null&&runner.currentJob()!=null?runner.currentJob():latest;}
 public void requestStop(){
  stopping.set(true);RemoteAgentRunner runner=active;if(runner!=null)runner.requestStop();
  closeClient();
  // Serialize with finally so a recycled executor thread is never interrupted.
  synchronized(ownerLock){if(ownerThread!=null&&ownerThread!=Thread.currentThread())ownerThread.interrupt();}
 }
 private void closeClient(){if(clientClosed.compareAndSet(false,true))client.close();}
 private void check(){if(stopping.get()||Thread.currentThread().isInterrupted())throw new StopRequested();if(!journal.healthyState())throw new IllegalStateException("storage_failed_not_persisted");}
 private void pulse(){check();if(observation!=null&&clock.monotonicSeconds()-heartbeatAt>=10){client.heartbeat(observation);check();heartbeatAt=clock.monotonicSeconds();}}
 private void hello(){
  check();observation=new AgentHello(agentId,deviceId,UUID.randomUUID().toString(),clock.utcNow());
  HelloResult reply=client.hello(observation);check();
  if(reply==null||!agentId.equals(reply.agentId)||reply.heartbeatSeconds!=10||reply.leaseSeconds!=30)throw new IllegalStateException("invalid_hello");
 }
 private void waitIdle(double seconds)throws InterruptedException {
  double until=clock.monotonicSeconds()+seconds;
  state="waiting";
  while(clock.monotonicSeconds()<until){check();pulse();double remaining=until-clock.monotonicSeconds();if(remaining>0)clock.sleepMillis(Math.max(1,(long)(Math.min(.1,remaining)*1000)));}
  pulse();
 }
 /** Blocking caller-owned worker; finally closes the in-memory client, not the caller-owned journal. */
 public void run(){
  if(!used.compareAndSet(false,true))throw new IllegalStateException("session_already_used");
  synchronized(ownerLock){ownerThread=Thread.currentThread();}
  double backoff=1;
  try{
   check();state="connecting";hello();heartbeatAt=clock.monotonicSeconds();
   boolean first=true;
   while(true){
    check();pulse();if(!first)hello();first=false;check();pulse();
    RemoteAgentRunner runner=new RemoteAgentRunner(client,journal,new RemoteFakeDriver(),clock,agentId,deviceId,runSeconds);
    runner.setHeartbeatObservation(observation,heartbeatAt);
    active=runner;
    if(stopping.get())runner.requestStop();
    state="executing_or_claiming";
    JobView result=runner.runOnce();latest=result;
    heartbeatAt=runner.lastHeartbeatSeconds();String outcome=runner.localStatus();active=null;
    if(stopping.get()||Thread.currentThread().isInterrupted()){state="disconnected_unconfirmed";break;}
    if(!journal.healthyState()){state="storage_failed_not_persisted";break;}
    if(result==null&&"idle".equals(outcome)){waitIdle(backoff);backoff=Math.min(8,backoff*2);continue;}
    if(result!=null&&(("completed".equals(result.state)&&"completed".equals(outcome))||("cancelled".equals(result.state)&&"cancelled".equals(outcome)))){
     backoff=1;state="task_finished";continue;
    }
    // Attention, unknown profile, uncertain claim/stop, lease/auth/network failure all latch.
    state=outcome;break;
   }
  }catch(StopRequested stopped){state="disconnected_unconfirmed";}
  catch(InterruptedException interrupted){Thread.currentThread().interrupt();state="disconnected_unconfirmed";}
  catch(RuntimeException failure){state=journal.healthyState()?(stopping.get()?"disconnected_unconfirmed":"connection_failed"):"storage_failed_not_persisted";}
  finally{
   stopping.set(true);RemoteAgentRunner runner=active;if(runner!=null){runner.requestStop();latest=runner.currentJob();}active=null;
   try{closeClient();if(!journal.healthyState())state="storage_failed_not_persisted";}finally{synchronized(ownerLock){ownerThread=null;}}
  }
 }
 private static final class StopRequested extends RuntimeException {private static final long serialVersionUID=1L;}
}
