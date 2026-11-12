package org.happyrun.app.selfprobe;
import de.robv.android.xposed.IXposedHookLoadPackage;
import de.robv.android.xposed.XC_MethodHook;
import de.robv.android.xposed.XposedBridge;
import de.robv.android.xposed.callbacks.XC_LoadPackage;
import java.lang.reflect.Method;
/** Optional legacy Xposed entrypoint; never loaded by normal application code. */
public final class SelfDiagnosticModule implements IXposedHookLoadPackage {
    @Override public void handleLoadPackage(XC_LoadPackage.LoadPackageParam param) throws Throwable {
        if(param==null || !SelfScope.accepts(param.packageName,param.processName) || param.classLoader==null)return;
        Class<?> probe=param.classLoader.loadClass("org.happyrun.app.selfprobe.SelfProbe");
        Method response=probe.getDeclaredMethod("response",String.class);
        final int bridgeVersion=XposedBridge.getXposedVersion();
        if(bridgeVersion<=0)return;
        XposedBridge.hookMethod(response,new XC_MethodHook() {
            @Override protected void beforeHookedMethod(MethodHookParam call) {
                if(call.args.length!=1 || !(call.args[0] instanceof String))return;
                String challenge=(String)call.args[0];
                if(!challenge.matches("[0-9a-f]{32}"))return;
                call.setResult("self-v1|"+challenge+"|"+bridgeVersion);
            }
        });
    }
}
