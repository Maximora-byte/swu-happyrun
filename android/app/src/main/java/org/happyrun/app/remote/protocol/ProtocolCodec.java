package org.happyrun.app.remote.protocol;

import java.time.Instant;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.HashSet;
import java.util.Map;

/** Exact v1 wire keys. This client deliberately accepts only the simulation subset. */
public final class ProtocolCodec {
    private ProtocolCodec() {}
    public static Map<String,Object> object(Object value,String... fields) {
        if (!(value instanceof Map)) throw Checks.invalid();
        Map<?,?> map=(Map<?,?>)value;
        if (!map.keySet().equals(new HashSet<>(Arrays.asList(fields)))) throw Checks.invalid();
        Map<String,Object> copy=new LinkedHashMap<>();
        for(String field:fields)copy.put(field,map.get(field));return copy;
    }
    private static String string(Object v) {if(!(v instanceof String))throw Checks.invalid();return (String)v;}
    private static String nullable(Object v) {return v==null?null:string(v);}
    private static long counter(Object v) {if(!(v instanceof Long))throw Checks.invalid();return Checks.counter((Long)v);}
    private static Instant time(Object v) {return Checks.time(string(v));}
    public static Map<String,Object> map(Object... values) {
        Map<String,Object> map=new LinkedHashMap<>();for(int i=0;i<values.length;i+=2)map.put((String)values[i],values[i+1]);return map;
    }
    public static JobSpec spec(Object input) {
        Map<String,Object> m=object(input,"protocol_version","mode","profile_id","profile_revision","route_id","route_revision","device_id","not_before","deadline","expected_app_version");
        if(!Long.valueOf(1).equals(m.get("protocol_version")))throw Checks.invalid();
        return new JobSpec(1,string(m.get("mode")),string(m.get("profile_id")),string(m.get("profile_revision")),string(m.get("route_id")),string(m.get("route_revision")),string(m.get("device_id")),time(m.get("not_before")),time(m.get("deadline")),nullable(m.get("expected_app_version")));
    }
    public static JobView job(Object input) {
        Map<String,Object> m=object(input,"job_id","spec","state","revision","desired_state","fence","agent_id","reason_code","resume_phase","recovery_action","run_session_id");
        return new JobView(string(m.get("job_id")),spec(m.get("spec")),string(m.get("state")),counter(m.get("revision")),string(m.get("desired_state")),counter(m.get("fence")),nullable(m.get("agent_id")),nullable(m.get("reason_code")),nullable(m.get("resume_phase")),nullable(m.get("recovery_action")),nullable(m.get("run_session_id")));
    }
    public static JobView decodeJob(String json) {return job(StrictJson.parse(json));}
    public static LeaseGrant decodeGrant(String json) {
        Map<String,Object> m=object(StrictJson.parse(json),"job","lease_token","fence","expires_at");
        return new LeaseGrant(job(m.get("job")),string(m.get("lease_token")),counter(m.get("fence")),time(m.get("expires_at")));
    }
    public static RenewResult decodeRenew(String json) {
        Map<String,Object> m=object(StrictJson.parse(json),"expires_at","desired_state");return new RenewResult(time(m.get("expires_at")),string(m.get("desired_state")));
    }
    public static HelloResult decodeHello(String json) {
        Map<String,Object> m=object(StrictJson.parse(json),"agent_id","heartbeat_seconds","lease_seconds");
        long heartbeat=counter(m.get("heartbeat_seconds")),lease=counter(m.get("lease_seconds"));
        if(heartbeat!=10||lease!=30)throw Checks.invalid();return new HelloResult(string(m.get("agent_id")),10,30);
    }
    public static Instant decodeHeartbeat(String json) {return time(object(StrictJson.parse(json),"server_time").get("server_time"));}
    public static Map<String,Object> lease(LeaseCommand command) {return map("lease_token",command.leaseToken,"fence",command.fence);}
    public static Map<String,Object> event(JobEvent event) {return map("event_id",event.eventId,"expected_revision",event.expectedRevision,"state",event.state,"reason_code",event.reasonCode,"evidence",Collections.emptyList(),"resume_phase",event.resumePhase);}
    public static Map<String,Object> hello(AgentHello hello) {
        return map("protocol_version",1L,"agent_id",hello.agentId,"devices",Collections.singletonList(map("device_id",hello.deviceId,"backend","fake","app_version",null,"capabilities",Collections.emptyList(),"observed_at",hello.observedAt.toString(),"probe_id",hello.probeId)));
    }
    public static Map<String,Object> spec(JobSpec s) {return map("protocol_version",1L,"mode",s.mode,"profile_id",s.profileId,"profile_revision",s.profileRevision,"route_id",s.routeId,"route_revision",s.routeRevision,"device_id",s.deviceId,"not_before",s.notBefore.toString(),"deadline",s.deadline.toString(),"expected_app_version",s.expectedAppVersion);}
    public static Map<String,Object> job(JobView j) {return map("job_id",j.jobId,"spec",spec(j.spec),"state",j.state,"revision",j.revision,"desired_state",j.desiredState,"fence",j.fence,"agent_id",j.agentId,"reason_code",j.reasonCode,"resume_phase",j.resumePhase,"recovery_action",j.recoveryAction,"run_session_id",j.runSessionId);}
}
