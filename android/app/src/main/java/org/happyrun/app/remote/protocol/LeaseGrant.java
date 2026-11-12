package org.happyrun.app.remote.protocol;
import java.time.Instant;
public final class LeaseGrant {
    public final JobView job;
    public final String leaseToken;
    public final long fence;
    public final Instant expiresAt;
    public LeaseGrant(JobView job, String leaseToken, long fence, Instant expiresAt) {
        if(job==null||job.fence!=fence)throw Checks.invalid();Checks.text(leaseToken);Checks.counter(fence);Checks.instant(expiresAt);
        this.job = job;
        this.leaseToken = leaseToken;
        this.fence = fence;
        this.expiresAt = expiresAt;
    }
    @Override public String toString() {return "LeaseGrant[redacted]";}
}
