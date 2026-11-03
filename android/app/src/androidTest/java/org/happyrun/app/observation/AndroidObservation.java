package org.happyrun.app.observation;

import android.Manifest;
import android.content.Context;
import android.content.pm.PackageManager;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;

/** Test-APK-only independent reader. No injector, mock provider, framework or network calls. */
public final class AndroidObservation {
    public final ObservationSession session;
    private final Handler handler;
    private final Runnable deadline;
    private AndroidObservation(long durationMillis) {
        handler=new Handler(Looper.getMainLooper());
        session=new ObservationSession(new ObservationWindow(
                SystemClock.elapsedRealtimeNanos(),durationMillis*1000000L,128));
        deadline=()->session.stopObserving();
    }
    /** Invoke on the main thread after the user has explicitly granted any requested permission. */
    public static AndroidObservation start(Context ownTarget, String channel, long durationMillis) {
        if(Looper.myLooper()!=Looper.getMainLooper())throw new IllegalStateException("main_thread_required");
        if(!"org.happyrun.app".equals(ownTarget.getPackageName()))
            throw new IllegalArgumentException("own_target_required");
        if(durationMillis<1 || durationMillis>5000)throw new IllegalArgumentException("observation_budget_invalid");
        if(!"location".equals(channel) && !"gravity".equals(channel))
            throw new IllegalArgumentException("channel_unsupported");
        if("location".equals(channel) && ownTarget.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)
                !=PackageManager.PERMISSION_GRANTED)throw new IllegalStateException("permission_required");
        AndroidObservation reader=new AndroidObservation(durationMillis);
        try {
            if("location".equals(channel))reader.location(ownTarget);else reader.gravity(ownTarget);
            if(!reader.handler.postDelayed(reader.deadline,durationMillis))
                throw new IllegalStateException("deadline_schedule_failed");
            return reader;
        } catch(RuntimeException failure) {
            if(!reader.stopObserving())throw new IllegalStateException("observation_cleanup_unconfirmed",failure);
            throw failure;
        }
    }
    private void location(Context context) {
        LocationManager manager=(LocationManager)context.getSystemService(Context.LOCATION_SERVICE);
        if(manager==null || !manager.isProviderEnabled(LocationManager.GPS_PROVIDER))
            throw new IllegalStateException("location_provider_unsupported");
        LocationListener listener=new LocationListener() {
            @Override public void onLocationChanged(Location value) {
                if(value.hasAccuracy())session.window.offer("location",value.getElapsedRealtimeNanos(),
                        SystemClock.elapsedRealtimeNanos(),new double[]{value.getLatitude(),value.getLongitude()},
                        value.getAccuracy());
            }
            @Override public void onStatusChanged(String provider,int status,Bundle extras) {}
            @Override public void onProviderEnabled(String provider) {}
            @Override public void onProviderDisabled(String provider) { stopObserving(); }
        };
        session.register(()->manager.removeUpdates(listener));
        manager.requestLocationUpdates(LocationManager.GPS_PROVIDER,0,0,listener,Looper.getMainLooper());
    }
    private void gravity(Context context) {
        SensorManager manager=(SensorManager)context.getSystemService(Context.SENSOR_SERVICE);
        Sensor sensor=manager==null?null:manager.getDefaultSensor(Sensor.TYPE_GRAVITY);
        if(sensor==null)throw new IllegalStateException("gravity_sensor_unsupported");
        SensorEventListener listener=new SensorEventListener() {
            @Override public void onSensorChanged(SensorEvent value) {
                if(value.sensor.getType()==Sensor.TYPE_GRAVITY && value.values.length>=3)
                    session.window.offer("gravity",value.timestamp,SystemClock.elapsedRealtimeNanos(),
                            new double[]{value.values[0],value.values[1],value.values[2]},value.accuracy);
            }
            @Override public void onAccuracyChanged(Sensor sensor,int accuracy) {}
        };
        session.register(()->manager.unregisterListener(listener));
        if(!manager.registerListener(listener,sensor,SensorManager.SENSOR_DELAY_NORMAL,handler))
            throw new IllegalStateException("gravity_registration_failed");
    }
    /** True means our listeners were removed, never a MuMu stop or queue-empty acknowledgment. */
    public boolean stopObserving() {
        handler.removeCallbacks(deadline);
        return session.stopObserving();
    }
}
