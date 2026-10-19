package org.happyrun.app;
public final class PollingPolicyTest {
    public static void main(String[] args) {
        for (String state : new String[] {null, "completed", "cancelled", "needs_attention", "unknown"}) {
            check(!PollingPolicy.shouldPoll(state, true, false, false, false, "ok", true));
        }
        for (String state : new String[] {"ready", "running"}) {
            check(PollingPolicy.shouldPoll(state, true, false, false, false, "ok", true));
            check(!PollingPolicy.shouldPoll(state, false, false, false, false, "ok", true));
            check(!PollingPolicy.shouldPoll(state, true, true, false, false, "ok", true));
            check(!PollingPolicy.shouldPoll(state, true, false, true, false, "ok", true));
            check(!PollingPolicy.shouldPoll(state, true, false, false, true, "ok", true));
            check(!PollingPolicy.shouldPoll(state, true, false, false, false, "storage_failure", true));
            check(!PollingPolicy.shouldPoll(state, true, false, false, false, "ok", false));
        }
        check(PollingPolicy.key("id", "running", "ok", true).equals(PollingPolicy.key("id", "running", "ok", true)));
        Object[] fields = {"id", "running", "reason", 1d, 20d, 10L, 11L, true, "ok", null};
        for (int i = 0; i < fields.length; i++) {
            Object[] changed = fields.clone();
            changed[i] = "changed";
            check(!PollingPolicy.key(fields).equals(PollingPolicy.key(changed)));
        }
        System.out.println("PASS: bounded foreground polling and display equality");
    }
    private static void check(boolean value) { if (!value) throw new AssertionError(); }
}
