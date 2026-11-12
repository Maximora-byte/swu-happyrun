package org.happyrun.app.runtime;

import android.content.Context;
import android.os.SystemClock;
import org.happyrun.app.core.SimulationRoute;
import org.happyrun.app.diagnostics.CheckItem;
import org.happyrun.app.diagnostics.CapabilityDiagnostics;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/** In-process local simulator. Process death never grants permission to resume. */
public final class LocalRuntime implements AutoCloseable {
    private static LocalRuntime instance;
    public static synchronized LocalRuntime get(Context context) {
        if(instance==null) instance=new LocalRuntime(context.getApplicationContext());
        return instance;
    }
    private final Context context;
    private final LocalStore store;
    private final ScheduledExecutorService executor=Executors.newSingleThreadScheduledExecutor();
    private SimulationRoute route;
    private long startNanos;
    private boolean closed;
    private boolean storageFailure;
    private String storageFailureTaskId;
    private LocalRuntime(Context context) {
        this.context=context;store=new LocalStore(context);store.recover();
        executor.scheduleWithFixedDelay(this::tickSafely,100,100,TimeUnit.MILLISECONDS);
    }
    public synchronized String health() { return storageFailure ? "storage_write_failed_not_persisted" : "ok"; }
    public synchronized String healthTaskId() { return storageFailureTaskId; }
    public synchronized TaskSnapshot currentTask() {
        return project(store.latest());
    }
    private TaskSnapshot project(TaskSnapshot s) {
        if(!storageFailure || s==null || !s.id.equals(storageFailureTaskId))return s;
        return new TaskSnapshot(s.id,"needs_attention","storage_write_failed_not_persisted",s.distanceM,
            s.totalDistanceM,s.startedAtMs,s.updatedAtMs,false);
    }
    private void requireHealthy() {
        if(storageFailure)throw new IllegalStateException("storage_write_failed_not_persisted");
    }
    private void saveRequired(TaskSnapshot s) {
        try {store.save(s);} catch(RuntimeException failure) {
            route=null;storageFailure=true;storageFailureTaskId=s.id;throw failure;
        }
    }
    public synchronized TaskSnapshot getTask(String id) { return project(store.get(id)); }
    public synchronized List<TaskSnapshot> history() {
        List<TaskSnapshot> rows=store.history();
        for(int i=0;i<rows.size();i++)rows.set(i,project(rows.get(i)));
        return rows;
    }
    public synchronized TaskSnapshot startSimulation() {
        if(closed) throw new IllegalStateException("runtime_closed");
        requireHealthy();
        TaskSnapshot old=store.latest();
        if(old!=null && ("running".equals(old.state) || "ready".equals(old.state) ||
            "needs_attention".equals(old.state))) return old;
        long now=System.currentTimeMillis();String id=UUID.randomUUID().toString();
        // Commit intent before initializing motion. A crash here recovers to attention.
        saveRequired(new TaskSnapshot(id,"ready","start_intent",0,SimulationRoute.TOTAL_METRES,now,now));
        route=new SimulationRoute();startNanos=SystemClock.elapsedRealtimeNanos();
        TaskSnapshot active=new TaskSnapshot(id,"running","simulation_only",0,SimulationRoute.TOTAL_METRES,now,now);
        saveRequired(active);return active;
    }
    public synchronized TaskSnapshot stop(String id) {
        requireHealthy();
        TaskSnapshot s=store.latest();
        if(s==null || !s.id.equals(id)) throw new IllegalArgumentException("task_not_current");
        if("running".equals(s.state) || "ready".equals(s.state) || "needs_attention".equals(s.state)) {
            route=null;
            String reason="needs_attention".equals(s.state) ? "local_simulation_stopped_after_attention" : "local_simulation_stopped";
            s=update(s,"cancelled",reason,s.distanceM);saveRequired(s);
        }
        return s;
    }
    public List<CheckItem> diagnostics() { return CapabilityDiagnostics.inspect(context); }
    private synchronized void tickSafely() {
        if(closed || route==null) return;
        String affectedId=null;
        try {
            TaskSnapshot s=store.latest();
            affectedId=s==null ? null : s.id;
            if(s==null || !"running".equals(s.state)) {route=null;return;}
            double distance=route.advance((SystemClock.elapsedRealtimeNanos()-startNanos)/1_000_000_000.0);
            boolean done=distance>=s.totalDistanceM;
            store.save(update(s,done?"completed":"running","simulation_only",distance));
            if(done) route=null;
        } catch(RuntimeException failure) {
            route=null;
            try {TaskSnapshot s=store.latest();if(s!=null)store.save(update(s,"needs_attention","local_runtime_error",s.distanceM));}
            catch(RuntimeException storageUnavailable) { storageFailure=true;storageFailureTaskId=affectedId; /* DB retains prior intent; UI is explicitly unpersisted. */ }
        }
    }
    private TaskSnapshot update(TaskSnapshot s,String state,String reason,double distance) {
        return new TaskSnapshot(s.id,state,reason,distance,s.totalDistanceM,s.startedAtMs,System.currentTimeMillis());
    }
    @Override public synchronized void close() {
        if(closed)return;closed=true;route=null;executor.shutdownNow();
        TaskSnapshot s=store.latest();
        if(s!=null && "running".equals(s.state))saveRequired(update(s,"needs_attention","runtime_stopped",s.distanceM));
        // Keep database handle alive for final read; singleton is intentionally not restartable.
    }
}
