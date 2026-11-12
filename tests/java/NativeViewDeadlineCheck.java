package org.happyrun.app;

public final class NativeViewDeadlineCheck {
    static class Port implements NativeViewDeadline.Port<String> {
        long time, appears, enableAt;
        boolean reveal, fail;
        int observations;
        public long now() { return time; }
        public void pause(long ms) { time += ms; }
        public String revealAndObserve(String id) {
            reveal=true; observations++;
            return time >= appears ? id : null;
        }
        public boolean enabled(String node) { return time >= enableAt; }
        public void failure(String id, Boolean enabled) { fail=true; }
    }
    static void check(boolean ok) { if (!ok) throw new AssertionError(); }
    public static void main(String[] args) {
        Port later = new Port(); later.appears=1500; later.enableAt=2500;
        check(new NativeViewDeadline<>(later).await("start", true, 5000).equals("start"));
        check(later.time==2500 && !later.fail && later.reveal);
        Port missing = new Port(); missing.appears=Long.MAX_VALUE;
        try { new NativeViewDeadline<>(missing).await("missing",null,5000); throw new AssertionError(); }
        catch (AssertionError expected) { check(missing.fail && missing.time==5000); }
        Port disabled = new Port(); disabled.enableAt=Long.MAX_VALUE;
        try { new NativeViewDeadline<>(disabled).await("disabled",true,5000); throw new AssertionError(); }
        catch (AssertionError expected) { check(disabled.fail && disabled.time==5000); }
        Port blocked = new Port(); blocked.enableAt=Long.MAX_VALUE;
        check(new NativeViewDeadline<>(blocked).await("blocked",false,5000).equals("blocked"));
        Port late = new Port() { public String revealAndObserve(String id) { time=5001; return id; } };
        try { new NativeViewDeadline<>(late).await("late",null,5000); throw new AssertionError(); }
        catch (AssertionError expected) { check(late.fail); }
        System.out.println("PASS 5 shared-deadline checks");
    }
}
