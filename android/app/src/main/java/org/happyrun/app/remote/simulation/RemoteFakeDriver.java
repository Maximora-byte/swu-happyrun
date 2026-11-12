package org.happyrun.app.remote.simulation;
/** In-memory synthetic motion only. New process never reconstructs active movement. */
public final class RemoteFakeDriver {
 private boolean started,stopped;private double elapsed,distance;private int starts,stops,ticks,tickAttempts;
 public synchronized void start(Runnable guard){if(started||stopped)throw new IllegalStateException("start_already_attempted");guard.run();started=true;starts++;}
 public synchronized void tick(double seconds,Runnable guard){tickAttempts++;if(!started||stopped||!Double.isFinite(seconds)||seconds<elapsed)throw new IllegalStateException("invalid_tick");guard.run();elapsed=seconds;distance=Math.min(BundledSimulationProfiles.DISTANCE_M,seconds*BundledSimulationProfiles.SPEED_MPS);ticks++;}
 public synchronized void stop(){if(!stopped){stopped=true;stops++;}}
 public synchronized boolean finished(){return started&&distance>=BundledSimulationProfiles.DISTANCE_M;}
 public synchronized boolean stopped(){return stopped;}
 public synchronized double distanceM(){return distance;}
 public synchronized double latitude(){return finished() ? .20001 : .2+.00001*(distance/BundledSimulationProfiles.DISTANCE_M);}
 public synchronized double longitude(){return latitude();}
 public synchronized int startCount(){return starts;}
 public synchronized int tickCount(){return ticks;}
 public synchronized int tickAttemptCount(){return tickAttempts;}
 public synchronized int stopCount(){return stops;}
}
