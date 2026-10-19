package org.happyrun.app;

/** Fail-closed, read-only predicate. No UI/input/runtime references or side effects. */
final class DisplayObservationGate {
    static boolean canRestoreOnDefaultDisplay(int expectedDisplay, int systemDefaultDisplay) {
        return expectedDisplay >= 0 && systemDefaultDisplay >= 0
            && expectedDisplay == systemDefaultDisplay;
    }
    /** A missing display during attach is pending, never a successful binding. */
    static boolean shouldAwaitViewport(Snapshot s, int display, int task, long deadline) {
        return s.task == task && s.taskCount == 1 && s.finished < deadline
            && (s.display == -1 || s.display == display)
            && !(s.display == display && s.window && s.controls);
    }
    static final class Snapshot {
        String observationId, packageName, activity, signature;
        int display = -1, task = -1, taskCount, dumpExit;
        boolean window, controls;
        long started, captured, finished;
    }
    /** Persistent task identity remains available when instrumentation stops the live Activity. */
    static boolean taskComponentsMatch(String intentPackage, String intentClass,
                                       String basePackage, String baseClass) {
        if (!"org.happyrun.app".equals(intentPackage)
            || !"org.happyrun.app.MainActivity".equals(intentClass)) return false;
        // A missing live component is permitted only after exact persistent component proof.
        // Any non-null live component must independently match; no alias/other Activity fallback.
        return (basePackage == null && baseClass == null)
            || ("org.happyrun.app".equals(basePackage)
                && "org.happyrun.app.MainActivity".equals(baseClass));
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
