package org.happyrun.app.observation;

import java.util.ArrayList;
import java.util.List;

/** Observation lifecycle only: no device transport or control-plane acknowledgment. */
public final class ObservationSession {
    public final ObservationWindow window;
    private final List<Runnable> removals = new ArrayList<>();
    private boolean closed, removed;
    public ObservationSession(ObservationWindow window) { this.window=window; }
    public synchronized void register(Runnable removal) {
        if(closed)throw new IllegalStateException("observation_already_closed");
        if(removal==null)throw new IllegalArgumentException("removal_required");
        removals.add(removal);
    }
    public synchronized boolean stopObserving() {
        if(closed)return removed;
        closed=true;window.close();removed=true;
        for(Runnable removal:removals) {
            try { removal.run(); } catch(RuntimeException failure) { removed=false; }
        }
        removals.clear();
        return removed;
    }
}
