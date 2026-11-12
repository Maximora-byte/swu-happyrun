package org.happyrun.app.diagnostics;
import android.content.Context;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.hardware.Sensor;
import android.hardware.SensorManager;
import android.os.Build;
import java.io.File;
import java.util.ArrayList;
import java.util.List;
public final class CapabilityDiagnostics {
    private CapabilityDiagnostics() {}
    public static List<CheckItem> inspect(Context context) {
        List<CheckItem> result=new ArrayList<>();
        result.add(new CheckItem("Android","observed","API "+Build.VERSION.SDK_INT+" / "+Build.VERSION.RELEASE+" / "+Build.MODEL));
        SensorManager manager=(SensorManager)context.getSystemService(Context.SENSOR_SERVICE);
        Sensor sensor=manager==null?null:manager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER);
        result.add(new CheckItem("加速度传感器",sensor==null?"unavailable":"observed",sensor==null?"未发现传感器":"已枚举传感器；未验证数据质量或写入能力"));
        try {
            PackageInfo info=context.getPackageManager().getPackageInfo("com.lptiyu.tanke",0);
            long code=Build.VERSION.SDK_INT>=28 ? info.getLongVersionCode() : info.versionCode;
            result.add(new CheckItem("乐跑版本","observed",String.valueOf(info.versionName)+" ("+code+")；仅观察安装版本，执行适配未验证"));
        } catch(PackageManager.NameNotFoundException absent) {
            result.add(new CheckItem("乐跑版本","unavailable","未发现可见安装包 com.lptiyu.tanke；执行适配未验证"));
        } catch(RuntimeException unavailable) {
            result.add(new CheckItem("乐跑版本","unknown","无法读取安装版本；执行适配未验证"));
        }
        boolean rootHint=new File("/system/bin/su").exists() || new File("/system/xbin/su").exists();
        result.add(new CheckItem("Root",rootHint?"unverified":"unknown",rootHint?"发现 su 路径迹象；未执行、未申请授权":"未发现公开路径迹象；不能证明未 Root"));
        result.add(new CheckItem("LSPosed","unknown","未获得框架版本、模块激活或作用域证据；不会执行 su 或安装模块"));
        result.add(new CheckItem("真实定位/传感器写入","unsupported","尚无经验证的设备适配器；普通读取权限不等于注入权限"));
        result.add(new CheckItem("学校记录","unsupported","本地模拟不会操作第三方应用或生成学校有效记录"));
        return result;
    }
}
