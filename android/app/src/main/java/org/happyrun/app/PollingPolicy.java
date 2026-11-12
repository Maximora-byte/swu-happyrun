package org.happyrun.app;

import java.util.Arrays;
import java.util.Collections;
import java.util.List;

/** UI refresh policy only; never drives execution or changes a task's state. */
public final class PollingPolicy {
    private PollingPolicy() { }

    public static boolean shouldPoll(String state, boolean foreground, boolean uncertain,
            boolean pending, boolean reading, String health, boolean persisted) {
        return foreground && !uncertain && !pending && !reading && persisted
                && "ok".equals(health) && ("ready".equals(state) || "running".equals(state));
    }

    public static List<Object> key(Object... fields) {
        return Collections.unmodifiableList(Arrays.asList(fields.clone()));
    }
}
