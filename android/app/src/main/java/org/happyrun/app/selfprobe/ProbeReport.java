package org.happyrun.app.selfprobe;
/** A local live-method observation, not a security attestation. */
public final class ProbeReport {
    public final String status;
    public final boolean active;
    public final Integer bridgeApiVersion;
    ProbeReport(String status,Integer version) {
        this.status=status;this.active="active".equals(status);this.bridgeApiVersion=active?version:null;
    }
}
