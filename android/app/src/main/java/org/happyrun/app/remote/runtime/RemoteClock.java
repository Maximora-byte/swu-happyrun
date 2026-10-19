package org.happyrun.app.remote.runtime;
import java.time.Instant;
/** Android implementations must use elapsedRealtimeNanos (including device suspend). */
public interface RemoteClock {
 double monotonicSeconds();Instant utcNow();void sleepMillis(long milliseconds)throws InterruptedException;
}
