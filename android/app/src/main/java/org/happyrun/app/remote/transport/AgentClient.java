package org.happyrun.app.remote.transport;
import java.time.Instant;
import org.happyrun.app.remote.protocol.*;
/** Blocking explicit calls only; no scheduling, retries or constructor network. */
public interface AgentClient extends AutoCloseable {
    HelloResult hello(AgentHello hello);
    Instant heartbeat(AgentHello hello);
    LeaseGrant claim(String deviceId);
    JobView getJob(String jobId);
    RenewResult renew(String jobId, LeaseCommand lease);
    JobView events(String jobId, LeaseCommand lease, JobEvent event);
    JobView stopAck(String jobId, LeaseCommand lease, String eventId, long expectedRevision);
    @Override void close();
}
