package org.happyrun.app.remote.protocol;
import java.time.Instant;
public final class JobEvent {
    public final String eventId;
    public final long expectedRevision;
    public final String state;
    public final String reasonCode;
    public final String resumePhase;
    public JobEvent(String eventId, long expectedRevision, String state, String reasonCode, String resumePhase) {
        Checks.uuid(eventId);Checks.counter(expectedRevision);Checks.state(state);if(reasonCode!=null)Checks.text(reasonCode);Checks.phase(resumePhase);
        if("needs_attention".equals(state)&&resumePhase==null)throw Checks.invalid();
        this.eventId = eventId;
        this.expectedRevision = expectedRevision;
        this.state = state;
        this.reasonCode = reasonCode;
        this.resumePhase = resumePhase;
    }
    @Override public boolean equals(Object value) {if (!(value instanceof JobEvent)) return false; JobEvent other=(JobEvent)value; return java.util.Objects.equals(this.eventId, other.eventId) && this.expectedRevision == other.expectedRevision && java.util.Objects.equals(this.state, other.state) && java.util.Objects.equals(this.reasonCode, other.reasonCode) && java.util.Objects.equals(this.resumePhase, other.resumePhase);}
    @Override public int hashCode() {return java.util.Objects.hash(eventId,expectedRevision,state,reasonCode,resumePhase);}
    @Override public String toString() {return "JobEvent[redacted]";}
}
