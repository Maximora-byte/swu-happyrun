package org.happyrun.app.remote.protocol;
import java.time.Instant;
public final class JobSpec {
    public final int protocolVersion;
    public final String mode;
    public final String profileId;
    public final String profileRevision;
    public final String routeId;
    public final String routeRevision;
    public final String deviceId;
    public final Instant notBefore;
    public final Instant deadline;
    public final String expectedAppVersion;
    public JobSpec(int protocolVersion, String mode, String profileId, String profileRevision, String routeId, String routeRevision, String deviceId, Instant notBefore, Instant deadline, String expectedAppVersion) {
        if(protocolVersion!=1||!"simulation".equals(mode)||expectedAppVersion!=null)throw Checks.invalid();
        Checks.uuid(profileId);Checks.digest(profileRevision);Checks.uuid(routeId);Checks.digest(routeRevision);Checks.uuid(deviceId);
        Checks.instant(notBefore);Checks.instant(deadline);if(!deadline.isAfter(notBefore))throw Checks.invalid();
        this.protocolVersion = protocolVersion;
        this.mode = mode;
        this.profileId = profileId;
        this.profileRevision = profileRevision;
        this.routeId = routeId;
        this.routeRevision = routeRevision;
        this.deviceId = deviceId;
        this.notBefore = notBefore;
        this.deadline = deadline;
        this.expectedAppVersion = expectedAppVersion;
    }
    @Override public boolean equals(Object value) {if (!(value instanceof JobSpec)) return false; JobSpec other=(JobSpec)value; return this.protocolVersion == other.protocolVersion && java.util.Objects.equals(this.mode, other.mode) && java.util.Objects.equals(this.profileId, other.profileId) && java.util.Objects.equals(this.profileRevision, other.profileRevision) && java.util.Objects.equals(this.routeId, other.routeId) && java.util.Objects.equals(this.routeRevision, other.routeRevision) && java.util.Objects.equals(this.deviceId, other.deviceId) && java.util.Objects.equals(this.notBefore, other.notBefore) && java.util.Objects.equals(this.deadline, other.deadline) && java.util.Objects.equals(this.expectedAppVersion, other.expectedAppVersion);}
    @Override public int hashCode() {return java.util.Objects.hash(protocolVersion,mode,profileId,profileRevision,routeId,routeRevision,deviceId,notBefore,deadline,expectedAppVersion);}
    @Override public String toString() {return "JobSpec[redacted]";}
}
