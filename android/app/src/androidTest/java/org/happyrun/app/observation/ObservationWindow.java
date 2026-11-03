package org.happyrun.app.observation;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** Private, bounded callback buffer. Closing this buffer never stops an injector. */
public final class ObservationWindow {
    public static final class Sample {
        public final String channel;
        public final long elapsedRealtimeNanos;
        public final double accuracy;
        private final double[] data;
        Sample(String channel, long timestamp, double[] values, double accuracy) {
            this.channel=channel; this.elapsedRealtimeNanos=timestamp;
            this.data=values.clone(); this.accuracy=accuracy;
        }
        public double[] values() { return data.clone(); }
    }
    private final long start, duration;
    private final int limit;
    private boolean closed;
    private final List<Sample> samples = new ArrayList<>();
    private final Map<String,Long> last = new HashMap<>();
    public ObservationWindow(long start, long durationNanos, int limit) {
        if(start<0 || durationNanos<=0 || durationNanos>30000000000L || limit<1 || limit>128)
            throw new IllegalArgumentException("observation_budget_invalid");
        this.start=start; this.duration=durationNanos; this.limit=limit;
    }
    public synchronized boolean offer(String channel, long timestamp, long now,
                                      double[] values, double accuracy) {
        if(closed)return false;
        if(now<start || now-start>=duration) { closed=true; return false; }
        int size="location".equals(channel)?2:("gravity".equals(channel)?3:0);
        if(size==0 || values==null || values.length!=size || timestamp<start || timestamp>now
                || timestamp<=last.getOrDefault(channel,-1L) || !Double.isFinite(accuracy))return false;
        for(double v:values)if(!Double.isFinite(v))return false;
        if("location".equals(channel) && (Math.abs(values[0])>90 || Math.abs(values[1])>180 || accuracy<0))return false;
        if(samples.size()>=limit) { closed=true; return false; }
        samples.add(new Sample(channel,timestamp,values,accuracy));last.put(channel,timestamp);
        return true;
    }
    public synchronized void close() { closed=true; }
    public synchronized List<Sample> snapshot() { return new ArrayList<>(samples); }
}
