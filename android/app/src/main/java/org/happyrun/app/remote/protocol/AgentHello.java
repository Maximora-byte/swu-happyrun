package org.happyrun.app.remote.protocol;
import java.time.Instant;
public final class AgentHello {
    public final String agentId;
    public final String deviceId;
    public final String probeId;
    public final Instant observedAt;
    public AgentHello(String agentId, String deviceId, String probeId, Instant observedAt) {
        Checks.uuid(agentId);Checks.uuid(deviceId);Checks.uuid(probeId);Checks.instant(observedAt);
        this.agentId = agentId;
        this.deviceId = deviceId;
        this.probeId = probeId;
        this.observedAt = observedAt;
    }
    @Override public boolean equals(Object value) {if (!(value instanceof AgentHello)) return false; AgentHello other=(AgentHello)value; return java.util.Objects.equals(this.agentId, other.agentId) && java.util.Objects.equals(this.deviceId, other.deviceId) && java.util.Objects.equals(this.probeId, other.probeId) && java.util.Objects.equals(this.observedAt, other.observedAt);}
    @Override public int hashCode() {return java.util.Objects.hash(agentId,deviceId,probeId,observedAt);}
    @Override public String toString() {return "AgentHello[redacted]";}
}
