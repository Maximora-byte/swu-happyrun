package org.happyrun.app.selfprobe;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import org.happyrun.app.BuildConfig;
import org.happyrun.app.MainActivity;

/** Own, optional, bounded foreground location lifetime. No location injection or IPC. */
public final class ProbeLocationService extends Service {
    private static volatile ProbeLocationService active;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private String nonce;

    public static boolean isActive(String expectedNonce) {
        ProbeLocationService value = active;
        return value != null && expectedNonce != null && expectedNonce.equals(value.nonce);
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (active != null) return START_NOT_STICKY;
        String requested = intent == null ? null : intent.getStringExtra("nonce");
        int duration = intent == null ? -1 : intent.getIntExtra("durationMs", -1);
        if (!"selfProbe".equals(BuildConfig.BUILD_TYPE) || requested == null
                || !requested.matches("[a-f0-9]{32}") || duration < 5000 || duration > 1800000
                || checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)
                    != PackageManager.PERMISSION_GRANTED) {
            stopSelf(startId);
            return START_NOT_STICKY;
        }
        try {
            NotificationManager manager = getSystemService(NotificationManager.class);
            manager.createNotificationChannel(new NotificationChannel(
                    "happyrun_location", "HappyRun 位置读回", NotificationManager.IMPORTANCE_LOW));
            PendingIntent open = PendingIntent.getActivity(this, 0,
                    new Intent(this, MainActivity.class), PendingIntent.FLAG_IMMUTABLE);
            Notification notification = new Notification.Builder(this, "happyrun_location")
                    .setSmallIcon(android.R.drawable.ic_menu_mylocation)
                    .setContentTitle("HappyRun 位置读回")
                    .setContentText("正在观察 MuMu GPS，可切换到跑步应用")
                    .setOngoing(true).setContentIntent(open).build();
            if (Build.VERSION.SDK_INT >= 29)
                startForeground(7123, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION);
            else startForeground(7123, notification);
            nonce = requested;
            active = this;
            // Cleanup allowance after the observer's deadline; never restart after process death.
            handler.postDelayed(this::stopSelf, (long) duration + 5000);
        } catch (RuntimeException unavailable) {
            stopSelf(startId);
        }
        return START_NOT_STICKY;
    }

    @Override public void onDestroy() {
        handler.removeCallbacksAndMessages(null);
        if (active == this) active = null;
        stopForeground(STOP_FOREGROUND_REMOVE);
        super.onDestroy();
    }

    @Override public IBinder onBind(Intent intent) { return null; }
}
