package org.happyrun.app.remote.protocol;
import java.time.Instant;
public final class LeaseCommand {
    public final String leaseToken;
    public final long fence;
    public LeaseCommand(String leaseToken, long fence) {
        Checks.text(leaseToken);Checks.counter(fence);
        this.leaseToken = leaseToken;
        this.fence = fence;
    }
    @Override public String toString() {return "LeaseCommand[redacted]";}
}
