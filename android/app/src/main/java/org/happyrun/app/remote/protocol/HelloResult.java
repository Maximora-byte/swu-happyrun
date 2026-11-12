package org.happyrun.app.remote.protocol;
import java.time.Instant;
public final class HelloResult {
    public final String agentId;
    public final int heartbeatSeconds;
    public final int leaseSeconds;
    public HelloResult(String agentId, int heartbeatSeconds, int leaseSeconds) {
        Checks.uuid(agentId);if(heartbeatSeconds!=10||leaseSeconds!=30)throw Checks.invalid();
        this.agentId = agentId;
        this.heartbeatSeconds = heartbeatSeconds;
        this.leaseSeconds = leaseSeconds;
    }
    @Override public boolean equals(Object value) {if (!(value instanceof HelloResult)) return false; HelloResult other=(HelloResult)value; return java.util.Objects.equals(this.agentId, other.agentId) && this.heartbeatSeconds == other.heartbeatSeconds && this.leaseSeconds == other.leaseSeconds;}
    @Override public int hashCode() {return java.util.Objects.hash(agentId,heartbeatSeconds,leaseSeconds);}
    @Override public String toString() {return "HelloResult[redacted]";}
}
