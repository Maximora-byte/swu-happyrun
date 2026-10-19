package org.happyrun.app.observation;

import java.util.List;

/** Private protocol only. Never put this result in instrumentation status or logs. */
public final class ObservationReport {
    private ObservationReport() {}
    public static String encode(String nonce, String binding, String boot, String channel,
            int durationMillis, ObservationWindow window, boolean cleanup, String status) {
        if(nonce==null || !nonce.matches("[a-f0-9]{32}") || binding==null || !binding.matches("[a-f0-9]{64}")
                || boot==null || !boot.matches("[A-Za-z0-9-]{1,128}")
                || !("location".equals(channel)||"gravity".equals(channel))
                || durationMillis<1 || durationMillis>5000 || status==null
                || !status.matches("[a-z_]{1,64}"))throw new IllegalArgumentException("private_request_invalid");
        long start=window==null?0:window.startNanos();
        StringBuilder out=new StringBuilder("{\"schema\":1,\"nonce\":\"").append(nonce)
                .append("\",\"binding_digest\":\"").append(binding).append("\",\"boot_id\":\"").append(boot)
                .append("\",\"channel\":\"").append(channel).append("\",\"duration_ms\":").append(durationMillis)
                .append(",\"window_start_ns\":").append(start).append(",\"window_end_ns\":")
                .append(start+durationMillis*1000000L).append(",\"cleanup_confirmed\":").append(cleanup)
                .append(",\"status\":\"").append(status).append("\",\"samples\":[");
        if(window!=null && cleanup && "samples_observed".equals(status)) {
            List<ObservationWindow.Sample> samples=window.snapshot();
            for(int i=0;i<samples.size();i++) {
                ObservationWindow.Sample sample=samples.get(i);
                if(!channel.equals(sample.channel))throw new IllegalArgumentException("channel_mismatch");
                if(i>0)out.append(',');
                out.append("{\"channel\":\"").append(channel).append("\",\"elapsed_realtime_ns\":")
                        .append(sample.elapsedRealtimeNanos).append(",\"values\":[");
                double[] values=sample.values();
                for(int j=0;j<values.length;j++) { if(j>0)out.append(',');out.append(values[j]); }
                out.append("],\"accuracy\":");
                if("gravity".equals(channel))out.append((int)sample.accuracy);else out.append(sample.accuracy);
                out.append('}');
            }
        }
        return out.append("]}").toString();
    }
}
