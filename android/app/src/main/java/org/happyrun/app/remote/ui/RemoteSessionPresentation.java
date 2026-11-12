package org.happyrun.app.remote.ui;

/** A task ending is not a connection ending; stale views never acknowledge a stop. */
public enum RemoteSessionPresentation {
    CONNECTING, WAITING, CLAIMING, RUNNING, ATTENTION, STORAGE, UNCONFIRMED;
    public static RemoteSessionPresentation classify(String state, String jobState, boolean active) {
        if ("storage_failed_not_persisted".equals(state)) return STORAGE;
        if ("needs_attention".equals(state) && "needs_attention".equals(jobState)) return ATTENTION;
        if (!active) return UNCONFIRMED;
        if ("connecting".equals(state)) return CONNECTING;
        if ("waiting".equals(state) || "task_finished".equals(state)) return WAITING;
        if ("executing_or_claiming".equals(state))
            return "running".equals(jobState) ? RUNNING : CLAIMING;
        return UNCONFIRMED;
    }
}
