package org.happyrun.app;

/** Test-only shared budget. Observation reveals a target before reading accessibility. */
final class NativeViewDeadline<T> {
    interface Port<T> {
        long now();
        void pause(long millis);
        T revealAndObserve(String id);
        boolean enabled(T node);
        void failure(String id, Boolean enabled);
    }
    private final Port<T> port;
    NativeViewDeadline(Port<T> port) { this.port = port; }
    T await(String id, Boolean enabled, long timeout) {
        final long deadline = port.now() + timeout;
        while (port.now() < deadline) {
            T node = port.revealAndObserve(id);
            if (port.now() >= deadline) break;
            if (node != null && (enabled == null || port.enabled(node) == enabled)) return node;
            long remaining = deadline - port.now();
            if (remaining > 0) port.pause(Math.min(50, remaining));
        }
        port.failure(id, enabled);
        throw new AssertionError("Native navigation deadline exceeded");
    }
}
