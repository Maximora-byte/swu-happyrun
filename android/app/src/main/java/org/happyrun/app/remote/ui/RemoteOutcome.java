package org.happyrun.app.remote.ui;

/** Presentation only: no inference of server acknowledgment from a local stop. */
public enum RemoteOutcome {
    EMPTY, CONFIRMED, UNCONFIRMED, STORAGE_BLOCKED;
    public static RemoteOutcome classify(String localStatus, boolean hasView) {
        if ("storage_failed_not_persisted".equals(localStatus)) return STORAGE_BLOCKED;
        if ("idle".equals(localStatus) && !hasView) return EMPTY;
        if (hasView && ("completed".equals(localStatus) || "cancelled".equals(localStatus)
                || "needs_attention".equals(localStatus))) return CONFIRMED;
        return UNCONFIRMED;
    }
}
