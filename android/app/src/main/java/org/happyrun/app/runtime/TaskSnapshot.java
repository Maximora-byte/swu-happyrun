package org.happyrun.app.runtime;

/** Local-only persisted simulation DTO. This is not a server JobView or lease. */
public final class TaskSnapshot {
    public final String id, state, mode, reason;
    public final double distanceM, totalDistanceM;
    public final long startedAtMs, updatedAtMs;
    public final boolean recordVerified = false;
    public final boolean persisted;
    public TaskSnapshot(String id, String state, String reason, double distanceM,
                        double totalDistanceM, long startedAtMs, long updatedAtMs) {
        this(id,state,reason,distanceM,totalDistanceM,startedAtMs,updatedAtMs,true);
    }
    public TaskSnapshot(String id, String state, String reason, double distanceM,
                        double totalDistanceM, long startedAtMs, long updatedAtMs, boolean persisted) {
        this.persisted=persisted;
        if (id == null || id.isEmpty() || reason == null ||
            !("ready".equals(state) || "running".equals(state) || "completed".equals(state) ||
              "cancelled".equals(state) || "needs_attention".equals(state)) ||
            !Double.isFinite(distanceM) || !Double.isFinite(totalDistanceM) ||
            distanceM < 0 || totalDistanceM <= 0 || distanceM > totalDistanceM ||
            ("completed".equals(state) && distanceM != totalDistanceM) ||
            startedAtMs < 0 || updatedAtMs < 0) throw new IllegalArgumentException("invalid_local_task");
        this.id=id; this.state=state; this.reason=reason; this.mode="simulation_local";
        this.distanceM=distanceM; this.totalDistanceM=totalDistanceM;
        this.startedAtMs=startedAtMs; this.updatedAtMs=updatedAtMs;
    }
}
