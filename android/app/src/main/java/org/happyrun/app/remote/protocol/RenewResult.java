package org.happyrun.app.remote.protocol;
import java.time.Instant;
public final class RenewResult {
    public final Instant expiresAt;
    public final String desiredState;
    public RenewResult(Instant expiresAt, String desiredState) {
        Checks.instant(expiresAt);Checks.one(desiredState,"run cancel");
        this.expiresAt = expiresAt;
        this.desiredState = desiredState;
    }
    @Override public boolean equals(Object value) {if (!(value instanceof RenewResult)) return false; RenewResult other=(RenewResult)value; return java.util.Objects.equals(this.expiresAt, other.expiresAt) && java.util.Objects.equals(this.desiredState, other.desiredState);}
    @Override public int hashCode() {return java.util.Objects.hash(expiresAt,desiredState);}
    @Override public String toString() {return "RenewResult[redacted]";}
}
