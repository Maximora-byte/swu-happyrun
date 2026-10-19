package org.happyrun.app;

/** Fail-closed, read-only predicate. No UI/input/runtime references or side effects. */
final class DisplayObservationGate {
    static final class Snapshot {
        String observationId, packageName, activity, signature;
        int display = -1, task = -1, taskCount, dumpExit;
        boolean window, controls;
        long started, captured, finished;
    }
    static boolean accepts(Snapshot s, String id, int display, int task,
                           String signature, long deadline) {
        return s != null && id != null && !id.isEmpty() && id.equals(s.observationId)
            && display >= 0 && task >= 0 && s.display == display && s.task == task
            && s.taskCount == 1 && "org.happyrun.app".equals(s.packageName)
            && "org.happyrun.app.MainActivity".equals(s.activity)
            && signature != null && !signature.isEmpty() && signature.equals(s.signature)
            && s.window && s.controls && s.dumpExit == 0
            && s.started >= 0 && s.captured >= s.started && s.finished >= s.captured
            && s.finished < deadline;
    }
}
