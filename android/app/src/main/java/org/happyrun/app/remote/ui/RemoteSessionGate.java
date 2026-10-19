package org.happyrun.app.remote.ui;

/** UI lifecycle latch only. A local stop never implies a server acknowledgment. */
public final class RemoteSessionGate {
    public interface Stop { void requestStop(); }
    private boolean foreground;
    private boolean blocked;
    private boolean busy;
    private boolean stopping;
    private Stop active;
    public synchronized void block() { blocked = true; stop(); }
    public synchronized boolean blocked() { return blocked; }
    public synchronized void enter() { foreground = true; }
    public synchronized boolean begin() {
        if (!foreground || busy || blocked) return false;
        busy = true;
        stopping = false;
        return true;
    }
    public synchronized void attach(Stop runner) {
        if (!busy || active != null) throw new IllegalStateException("invalid_session_lifecycle");
        active = runner;
        if (stopping) active.requestStop();
    }
    public synchronized void stop() {
        if (!busy || stopping) return;
        stopping = true;
        if (active != null) active.requestStop();
    }
    public synchronized void leave() { foreground = false; stop(); }
    public synchronized void finish() { active = null; busy = false; }
    public synchronized boolean busy() { return busy; }
    public synchronized boolean stopping() { return stopping; }
}
