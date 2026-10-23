package org.happyrun.app.observation;

/** Bounded latest-value envelope, shared by the instrumentation listener and writer. */
final class ContinuousLocationReport {
    private final String nonce,boot;
    private final long start;
    private String state="starting",error;
    private long sequence,sampleNs;
    private double latitude,longitude,accuracy;

    static int duration(String nonce,String value) {
        if(nonce==null || !nonce.matches("[a-f0-9]{32}")
                || value==null || !value.matches("[0-9]{4,7}"))return -1;
        try {
            int duration=Integer.parseInt(value);
            return duration>=5000 && duration<=1800000?duration:-1;
        } catch(NumberFormatException invalid) { return -1; }
    }
    ContinuousLocationReport(String nonce,String boot,long start) {
        if(nonce==null || !nonce.matches("[a-f0-9]{32}") || boot==null
                || !boot.matches("[a-zA-Z0-9-]{1,128}") || start<=0)
            throw new IllegalArgumentException("report_identity_invalid");
        this.nonce=nonce;this.boot=boot;this.start=start;
    }
    synchronized void observing() { if("starting".equals(state))state="observing"; }
    synchronized boolean offer(double latitude,double longitude,double accuracy,long sampleNs,long now) {
        if(!"observing".equals(state) || sampleNs<=0 || sampleNs<start || sampleNs<=this.sampleNs
                || sampleNs>now || !Double.isFinite(latitude) || latitude< -90 || latitude>90
                || !Double.isFinite(longitude) || longitude< -180 || longitude>180
                || !Double.isFinite(accuracy) || accuracy<0)return false;
        this.latitude=latitude;this.longitude=longitude;this.accuracy=accuracy;
        this.sampleNs=sampleNs;sequence++;return true;
    }
    synchronized String encode(long now) {
        return "{\"schema\":1,\"nonce\":\""+nonce+"\",\"boot_id\":\""+boot
                +"\",\"sequence\":"+sequence+",\"state\":\""+state+"\",\"error_code\":"
                +(error==null?"null":"\""+error+"\"")+",\"window_start_ns\":"+start
                +",\"reported_at_ns\":"+now+",\"sample\":"+(sampleNs==0?"null":
                    "{\"latitude\":"+latitude+",\"longitude\":"+longitude+",\"accuracy\":"+accuracy
                    +",\"elapsed_realtime_ns\":"+sampleNs+"}")+"}";
    }
    synchronized void finish(boolean removed) {
        if(!removed)error("cleanup_unconfirmed");
        else if(error==null)state="stopped";
    }
    synchronized void error(String code) {
        if(code==null || !code.matches("[a-z_]{1,64}"))throw new IllegalArgumentException("invalid_error_code");
        error=code;state="error";
    }
    synchronized String state() { return state; }
    synchronized String errorCode() { return error; }
}
