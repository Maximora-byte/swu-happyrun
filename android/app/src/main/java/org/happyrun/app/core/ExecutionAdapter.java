package org.happyrun.app.core;
/** Extension boundary: presence/version detection never grants execution authority. */
public interface ExecutionAdapter {
    String id();
    boolean verified();
    void start();
    final class Unsupported implements ExecutionAdapter {
        private final String name;
        public Unsupported(String name) { this.name=name; }
        public String id() {return name;}
        public boolean verified() {return false;}
        public void start() {throw new UnsupportedOperationException("adapter_not_verified");}
    }
}
