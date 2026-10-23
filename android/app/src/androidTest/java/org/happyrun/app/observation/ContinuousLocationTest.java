package org.happyrun.app.observation;

import android.Manifest;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.os.Bundle;
import android.os.Looper;
import android.os.SystemClock;
import android.test.InstrumentationTestCase;
import android.test.InstrumentationTestRunner;
import java.io.FileInputStream;
import java.nio.charset.StandardCharsets;
import org.happyrun.app.BuildConfig;

/** Explicit selfProbe-only GPS observer. It cannot grant permissions or inject location. */
public final class ContinuousLocationTest extends InstrumentationTestCase {
    private static final String SERVICE="org.happyrun.app.selfprobe.ProbeLocationService";
    private static boolean serviceActive(Context target,String nonce) throws Exception {
        // Reflection keeps this optional class out of the ordinary APK/test compilation.
        return Boolean.TRUE.equals(Class.forName(SERVICE,true,target.getClassLoader())
                .getMethod("isActive",String.class).invoke(null,nonce));
    }
    public void testObserveWhenRequested() {
        Bundle args=((InstrumentationTestRunner)getInstrumentation()).getArguments();
        String nonce=args.getString("continuousNonce");
        if(nonce==null) return;
        if(!"selfProbe".equals(BuildConfig.BUILD_TYPE)) { status("error","self_probe_required");return; }
        int duration=ContinuousLocationReport.duration(nonce,args.getString("continuousDurationMs"));
        if(duration<0) { status("error","request_invalid");return; }
        Context target=getInstrumentation().getTargetContext();
        if(!"org.happyrun.app".equals(target.getPackageName())) { status("error","own_target_required");return; }
        String boot;
        try(FileInputStream stream=new FileInputStream("/proc/sys/kernel/random/boot_id")) {
            byte[] bytes=new byte[129];int length=stream.read(bytes);
            boot=length>0 && length<=128?new String(bytes,0,length,StandardCharsets.US_ASCII).trim():"";
            if(!boot.matches("[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}"))throw new IllegalStateException();
        } catch(Exception unavailable) { status("error","boot_unavailable");return; }
        long start=SystemClock.elapsedRealtimeNanos();
        ContinuousLocationReport report=new ContinuousLocationReport(nonce,boot,start);
        ContinuousLocationFile file;
        try { file=new ContinuousLocationFile(target.getFilesDir(),nonce); }
        catch(Exception unavailable) { status("error","private_file_unavailable");return; }
        Reader reader=new Reader(target,report,file,start+duration*1000000L);
        boolean[] removed={false};
        Activity[] ownActivity={null};
        boolean[] activityFinished={true};
        boolean serviceRequested=false;
        boolean serviceStopped=true;
        try {
            file.write(report,SystemClock::elapsedRealtimeNanos);
            try {
                // Starting instrumentation stops the previously running target process. Keep an
                // own Activity alive inside this instrumentation for while-in-use GPS permission.
                Intent intent=new Intent().setClassName("org.happyrun.app","org.happyrun.app.MainActivity")
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                ownActivity[0]=getInstrumentation().startActivitySync(intent);
                if(ownActivity[0]==null || ownActivity[0].isFinishing()) {
                    report.error("own_activity_start_failed");return;
                }
            } catch(RuntimeException failure) { report.error("own_activity_start_failed");return; }
            serviceRequested=true;
            serviceStopped=false;
            Intent service=new Intent().setClassName("org.happyrun.app",SERVICE)
                    .putExtra("nonce",nonce).putExtra("durationMs",duration);
            try {
                target.startForegroundService(service);
                long serviceDeadline=SystemClock.elapsedRealtime()+4000;
                while(!serviceActive(target,nonce) && SystemClock.elapsedRealtime()<serviceDeadline)
                    Thread.sleep(50);
                if(!serviceActive(target,nonce)) { report.error("foreground_service_start_failed");return; }
            } catch(Exception failure) { report.error("foreground_service_start_failed");return; }
            getInstrumentation().runOnMainSync(reader::start);
            status(report.state(),report.errorCode());
            while("observing".equals(report.state()) && !file.stop.exists()) {
                long remaining=reader.deadline-SystemClock.elapsedRealtimeNanos();
                if(remaining<=0)break;
                Thread.sleep(Math.max(1,Math.min(200,(remaining+999999)/1000000)));
                if(target.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)!=PackageManager.PERMISSION_GRANTED)
                    report.error("permission_required");
                if(!serviceActive(target,nonce))report.error("foreground_service_ended");
                file.write(report,SystemClock::elapsedRealtimeNanos);
            }
        } catch(InterruptedException interrupted) {
            report.error("observation_interrupted");Thread.currentThread().interrupt();
        } catch(Exception failure) { report.error("private_write_failed"); }
        finally {
            try { getInstrumentation().runOnMainSync(()->removed[0]=reader.remove()); }
            catch(RuntimeException failure) { removed[0]=false; }
            if(serviceRequested) {
                try {
                    target.stopService(new Intent().setClassName("org.happyrun.app",SERVICE));
                    long stopDeadline=SystemClock.elapsedRealtime()+2000;
                    while(serviceActive(target,nonce) && SystemClock.elapsedRealtime()<stopDeadline)
                        Thread.sleep(25);
                    serviceStopped=!serviceActive(target,nonce);
                } catch(Exception failure) { serviceStopped=false; }
            }
            if(ownActivity[0]!=null) {
                activityFinished[0]=false;
                try {
                    getInstrumentation().runOnMainSync(()->{
                        ownActivity[0].finish();
                        activityFinished[0]=ownActivity[0].isFinishing();
                    });
                } catch(RuntimeException failure) { activityFinished[0]=false; }
            }
            report.finish(removed[0] && activityFinished[0] && serviceStopped);
            try { file.write(report,SystemClock::elapsedRealtimeNanos); }
            catch(Exception failure) { report.error("private_write_failed"); }
            status(report.state(),report.errorCode());
        }
    }
    private void status(String state,String code) {
        Bundle values=new Bundle();values.putString("continuous_state",state);
        if(code!=null)values.putString("continuous_error_code",code);
        getInstrumentation().sendStatus(0,values);
    }
    private static final class Reader implements LocationListener {
        private final Context context;
        private final ContinuousLocationReport report;
        private final ContinuousLocationFile file;
        final long deadline;
        private LocationManager manager;
        private boolean registrationAttempted;
        Reader(Context context,ContinuousLocationReport report,ContinuousLocationFile file,long deadline) {
            this.context=context;this.report=report;this.file=file;this.deadline=deadline;
        }
        void start() {
            try {
                if(context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)!=PackageManager.PERMISSION_GRANTED) {
                    report.error("permission_required");return;
                }
                manager=(LocationManager)context.getSystemService(Context.LOCATION_SERVICE);
                if(manager==null || !manager.getAllProviders().contains(LocationManager.GPS_PROVIDER)) {
                    report.error("gps_unsupported");return;
                }
                if(!manager.isProviderEnabled(LocationManager.GPS_PROVIDER)) { report.error("gps_disabled");return; }
                registrationAttempted=true;
                manager.requestLocationUpdates(LocationManager.GPS_PROVIDER,0,0,this,Looper.getMainLooper());
                report.observing();
                file.write(report,SystemClock::elapsedRealtimeNanos);
            } catch(SecurityException denied) { report.error("permission_required"); }
            catch(Exception unavailable) { report.error("gps_registration_failed"); }
        }
        @Override public void onLocationChanged(Location value) {
            long now=SystemClock.elapsedRealtimeNanos();
            if(now>=deadline || !value.hasAccuracy() || !LocationManager.GPS_PROVIDER.equals(value.getProvider()))return;
            if(report.offer(value.getLatitude(),value.getLongitude(),value.getAccuracy(),value.getElapsedRealtimeNanos(),now)) {
                try { file.write(report,SystemClock::elapsedRealtimeNanos); }
                catch(Exception unavailable) { report.error("private_write_failed"); }
            }
        }
        @Override public void onProviderDisabled(String provider) {
            if(LocationManager.GPS_PROVIDER.equals(provider))report.error("gps_disabled");
        }
        @Override public void onProviderEnabled(String provider) {}
        @Override public void onStatusChanged(String provider,int status,Bundle extras) {}
        boolean remove() {
            if(!registrationAttempted)return true;
            try { manager.removeUpdates(this);registrationAttempted=false;return true; }
            catch(RuntimeException unavailable) { return false; }
        }
    }
}
