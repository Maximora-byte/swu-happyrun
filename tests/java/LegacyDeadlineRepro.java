final class LegacyDeadlineRepro {
 static long time;
 static class SystemClock { static long elapsedRealtime(){return time;} static void sleep(long ms){time+=ms;} }
 static class AccessibilityNodeInfo { boolean isEnabled(){return true;} }
 AccessibilityNodeInfo waitId(String id,long timeout){time+=timeout; throw new AssertionError("Missing native view");}
 void fail(String message){throw new AssertionError(message);}
    private AccessibilityNodeInfo waitEnabled(String id, boolean enabled) {
        long deadline = SystemClock.elapsedRealtime() + 5000;
        do {
            AccessibilityNodeInfo node = waitId(id, 1000);
            if (node.isEnabled() == enabled) return node;
            SystemClock.sleep(50);
        } while (SystemClock.elapsedRealtime() < deadline);
        fail("Expected enabled=" + enabled + " for " + id);
        return null;
    }

 public static void main(String[] args){try{new LegacyDeadlineRepro().waitEnabled("start_simulation",true);}catch(AssertionError e){if(time!=1000)throw new AssertionError();System.out.println("RED reproduced: requested 5000 ms budget failed at "+time+" ms before target appearance at 1500 ms");return;}throw new AssertionError();}
}
