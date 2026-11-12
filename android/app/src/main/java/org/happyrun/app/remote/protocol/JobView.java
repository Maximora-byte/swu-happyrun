package org.happyrun.app.remote.protocol;
import java.time.Instant;
public final class JobView {
    public final String jobId;
    public final JobSpec spec;
    public final String state;
    public final long revision;
    public final String desiredState;
    public final long fence;
    public final String agentId;
    public final String reasonCode;
    public final String resumePhase;
    public final String recoveryAction;
    public final String runSessionId;
    public JobView(String jobId, JobSpec spec, String state, long revision, String desiredState, long fence, String agentId, String reasonCode, String resumePhase, String recoveryAction, String runSessionId) {
        Checks.uuid(jobId);if(spec==null)throw Checks.invalid();Checks.state(state);Checks.counter(revision);Checks.one(desiredState,"run cancel");Checks.counter(fence);
        if(agentId!=null)Checks.uuid(agentId);if(reasonCode!=null)Checks.text(reasonCode);Checks.phase(resumePhase);Checks.optional(recoveryAction,"retry_preflight verify_only stop_only");if(runSessionId!=null)Checks.uuid(runSessionId);
        if((fence>0)!=(runSessionId!=null)||(agentId!=null&&runSessionId==null)||("needs_attention".equals(state)&&resumePhase==null))throw Checks.invalid();
        if("retry_preflight".equals(recoveryAction)&&java.util.Arrays.asList("running","finishing","verifying","cancelling").contains(resumePhase))throw Checks.invalid();
        if("cancel".equals(desiredState)&&("queued".equals(state)||(recoveryAction!=null&&!"stop_only".equals(recoveryAction))))throw Checks.invalid();
        this.jobId = jobId;
        this.spec = spec;
        this.state = state;
        this.revision = revision;
        this.desiredState = desiredState;
        this.fence = fence;
        this.agentId = agentId;
        this.reasonCode = reasonCode;
        this.resumePhase = resumePhase;
        this.recoveryAction = recoveryAction;
        this.runSessionId = runSessionId;
    }
    @Override public boolean equals(Object value) {if (!(value instanceof JobView)) return false; JobView other=(JobView)value; return java.util.Objects.equals(this.jobId, other.jobId) && java.util.Objects.equals(this.spec, other.spec) && java.util.Objects.equals(this.state, other.state) && this.revision == other.revision && java.util.Objects.equals(this.desiredState, other.desiredState) && this.fence == other.fence && java.util.Objects.equals(this.agentId, other.agentId) && java.util.Objects.equals(this.reasonCode, other.reasonCode) && java.util.Objects.equals(this.resumePhase, other.resumePhase) && java.util.Objects.equals(this.recoveryAction, other.recoveryAction) && java.util.Objects.equals(this.runSessionId, other.runSessionId);}
    @Override public int hashCode() {return java.util.Objects.hash(jobId,spec,state,revision,desiredState,fence,agentId,reasonCode,resumePhase,recoveryAction,runSessionId);}
    @Override public String toString() {return "JobView[redacted]";}
}
