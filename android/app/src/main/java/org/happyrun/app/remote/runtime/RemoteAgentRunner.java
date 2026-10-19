package org.happyrun.app.remote.runtime;

import java.time.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;
import org.happyrun.app.remote.protocol.*;
import org.happyrun.app.remote.transport.AgentClient;
import org.happyrun.app.remote.journal.RemoteJournal;
import org.happyrun.app.remote.simulation.*;

/** One explicit simulation lease. No automatic claim/reconnect/restart or physical adapter. */
public final class RemoteAgentRunner {
 private final AgentClient client;private final RemoteJournal journal;private final RemoteFakeDriver driver;
 private final RemoteClock clock;private final String agentId,deviceId;private final double budget;
 private final AtomicBoolean stop=new AtomicBoolean(),used=new AtomicBoolean();
 private volatile JobView job;private volatile String status="idle";
 private AgentHello observation;private double heartbeatAt;
 private LeaseCommand lease;private double leaseDeadline,jobDeadline,jobNotBefore;
 private static final Set<String> SETTLED=new HashSet<>(Arrays.asList("completed","cancelled","failed","needs_attention"));
 public RemoteAgentRunner(AgentClient client,RemoteJournal journal,RemoteFakeDriver driver,RemoteClock clock,String agentId,String deviceId,double runSeconds){
  if(client==null||journal==null||driver==null||clock==null||agentId==null||deviceId==null||!Double.isFinite(runSeconds)||runSeconds<=0||runSeconds>30)throw new IllegalArgumentException("invalid_runner_configuration");
  this.client=client;this.journal=journal;this.driver=driver;this.clock=clock;this.agentId=agentId;this.deviceId=deviceId;budget=runSeconds;
 }
 public void setHeartbeatObservation(AgentHello hello){if(used.get()||hello==null||!agentId.equals(hello.agentId)||!deviceId.equals(hello.deviceId))throw new IllegalArgumentException("invalid_observation");observation=hello;}
 public void requestStop(){stop.set(true);driver.stop();}
 public JobView currentJob(){return job;}
 public String localStatus(){return status;}
 private boolean recovery(){return job!=null&&(Objects.equals(job.recoveryAction,"verify_only")||Objects.equals(job.recoveryAction,"stop_only"));}
 private void checkLease(){if(clock.monotonicSeconds()>=leaseDeadline)throw new IllegalStateException("lease_expired");}
 private void check(){checkLease();if(stop.get()||Thread.currentThread().isInterrupted())throw new IllegalStateException("local_stop_requested");if("cancel".equals(job.desiredState))throw new Cancellation();if(!recovery()&&(clock.monotonicSeconds()<jobNotBefore||clock.monotonicSeconds()>=jobDeadline))throw new IllegalStateException("execution_window_expired");}
 private void guard(){check();if(Math.min(leaseDeadline,jobDeadline)-clock.monotonicSeconds()<=5.1)throw new IllegalStateException("insufficient_action_budget");}
 private void expiry(Instant expires,double before,Instant wall){double seconds=Duration.between(wall,expires).toNanos()/1e9;leaseDeadline=before+Math.min(30,seconds);}
 private void accept(JobView v){if(v==null||!v.jobId.equals(job.jobId)||!v.spec.equals(job.spec)||v.fence!=lease.fence||!Objects.equals(v.runSessionId,job.runSessionId)||!Objects.equals(v.agentId,agentId))throw new IllegalStateException("response_identity_changed");job=v;}
 private void renew(){check();if(observation!=null&&clock.monotonicSeconds()-heartbeatAt>=10){client.heartbeat(observation);check();heartbeatAt=clock.monotonicSeconds();}double before=clock.monotonicSeconds();Instant wall=clock.utcNow();RenewResult r=client.renew(job.jobId,lease);check();expiry(r.expiresAt,before,wall);if("cancel".equals(r.desiredState))throw new Cancellation();check();}
 private void event(String state,String reason,String phase){if(state.equals("needs_attention"))checkLease();else check();JobEvent e=new JobEvent(UUID.randomUUID().toString(),job.revision,state,reason,phase);JobView updated=client.events(job.jobId,lease,e);requireTransitionReply(updated,state,e.expectedRevision);accept(updated);if(state.equals("needs_attention"))checkLease();else check();}
 private static void requireTransitionReply(JobView view,String state,long previousRevision){if(view==null||!state.equals(view.state)||previousRevision==Long.MAX_VALUE||view.revision!=previousRevision+1)throw new IllegalStateException("unexpected_transition_response");}
 private void attention(String reason){
  if(job==null||lease==null||SETTLED.contains(job.state))return;
  try{checkLease();accept(client.getJob(job.jobId));checkLease();if(SETTLED.contains(job.state))return;
   String phase=recovery()&&job.resumePhase!=null?job.resumePhase:job.state;
   event("needs_attention",reason,phase);
  }catch(RuntimeException ignored){status="attention_unconfirmed";}
 }
 private void stopped(boolean finished)throws java.io.IOException {driver.stop();journal.stopped(job.jobId,job.runSessionId,lease.fence,finished);}
 private void cancel()throws java.io.IOException {
  stopped(false);checkLease();accept(client.getJob(job.jobId));checkLease();
  if(!job.state.equals("cancelling")){
   JobEvent e=new JobEvent(UUID.randomUUID().toString(),job.revision,"cancelling",null,null);JobView updated=client.events(job.jobId,lease,e);requireTransitionReply(updated,"cancelling",e.expectedRevision);accept(updated);
  }
  checkLease();long revision=job.revision;String id=journal.stopAckId(job.jobId,job.runSessionId,lease.fence,revision);
  JobView updated=client.stopAck(job.jobId,lease,id,revision);requireTransitionReply(updated,"cancelled",revision);accept(updated);
 }
 public JobView runOnce(){
  if(!used.compareAndSet(false,true))throw new IllegalStateException("runner_already_used");
  if(stop.get()||Thread.currentThread().isInterrupted()){status="stopped";return null;}
  status="claiming";heartbeatAt=clock.monotonicSeconds();
  try {
   double before=clock.monotonicSeconds();Instant wall=clock.utcNow();LeaseGrant grant=client.claim(deviceId);
   if(grant==null){status="idle";return null;}
   job=grant.job;
   if(!"leased".equals(job.state)||job.fence<1||!deviceId.equals(job.spec.deviceId)||!agentId.equals(job.agentId)||!"simulation".equals(job.spec.mode)||job.spec.expectedAppVersion!=null)throw new IllegalStateException("claim_identity_invalid");
   lease=new LeaseCommand(grant.leaseToken,grant.fence);expiry(grant.expiresAt,before,wall);
   journal.bind(job.jobId,job.runSessionId,lease.fence,specDigest(job.spec));
   jobNotBefore=before+Duration.between(wall,job.spec.notBefore).toNanos()/1e9;
   jobDeadline=before+Duration.between(wall,job.spec.deadline).toNanos()/1e9;
   if("stop_only".equals(job.recoveryAction)||"cancel".equals(job.desiredState)){cancel();status="cancelled";return job;}
   renew();
   if("verify_only".equals(job.recoveryAction)){
    // Deliberately conservative parity with Python: never reconstruct/replay motion.
    driver.stop();event("verifying",null,null);attention("verification_pending");return job;
   }
   if(journal.hasStart(job.jobId))throw new IllegalStateException("start_already_attempted");
   event("preflight",null,null);
   try{BundledSimulationProfiles.require(job.spec.profileId,job.spec.profileRevision,job.spec.routeId,job.spec.routeRevision);}
   catch(IllegalArgumentException unsupported){driver.stop();attention("unsupported_simulation_profile");return job;}
   catch(java.io.IOException unavailable){driver.stop();attention("simulation_profile_unavailable");return job;}
   renew();event("ready",null,null);event("running",null,null);
   journal.startIntent(job.jobId,job.runSessionId,lease.fence);renew();guard();driver.start(this::guard);status="running";
   double started=clock.monotonicSeconds();
   while(clock.monotonicSeconds()-started<budget){
    renew();guard();driver.tick(Math.min(budget,clock.monotonicSeconds()-started),this::guard);check();
    if(driver.finished())break;
    clock.sleepMillis(Math.max(1,(long)(Math.min(.1,Math.max(0,budget-(clock.monotonicSeconds()-started)))*1000)));
   }
   renew();if(!driver.finished()){guard();driver.tick(Math.min(budget,clock.monotonicSeconds()-started),this::guard);check();}
   if(!driver.finished()){stopped(false);attention("simulation_incomplete");return job;}
   event("finishing",null,null);stopped(true);event("verifying",null,null);renew();
   if(!journal.finished(job.jobId,job.runSessionId)||!driver.stopped())throw new IllegalStateException("verification_pending");
   event("completed",null,null);status="completed";
  }catch(Cancellation e){try{cancel();status="cancelled";}catch(Exception failure){driver.stop();attention("stop_unconfirmed");}}
  catch(Exception failure){driver.stop();status=journal.healthyState()?(job==null?"claim_unconfirmed":"execution_stopped"):"storage_failed_not_persisted";attention("execution_uncertain");}
  finally{driver.stop();if(!journal.healthyState())status="storage_failed_not_persisted";else if(job!=null&&job.state.equals("needs_attention"))status="needs_attention";}
  return job;
 }
 private static String specDigest(JobSpec s){
  // Local binding only, not profile canonicalization and never a wire field.
  try {java.io.ByteArrayOutputStream b=new java.io.ByteArrayOutputStream();java.io.DataOutputStream out=new java.io.DataOutputStream(b);
   for(String v:new String[]{Integer.toString(s.protocolVersion),s.mode,s.profileId,s.profileRevision,s.routeId,s.routeRevision,s.deviceId,s.notBefore.toString(),s.deadline.toString(),s.expectedAppVersion==null?"":s.expectedAppVersion})out.writeUTF(v);
   StringBuilder hex=new StringBuilder();for(byte v:java.security.MessageDigest.getInstance("SHA-256").digest(b.toByteArray()))hex.append(String.format(java.util.Locale.ROOT,"%02x",v&255));return hex.toString();
  }catch(Exception e){throw new IllegalStateException("invalid_binding");}
 }
 private static final class Cancellation extends RuntimeException {private static final long serialVersionUID=1L;}
}
