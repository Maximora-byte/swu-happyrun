package org.happyrun.app.selfprobe;
/** Independent of manager-selected scope: reject every other package/process. */
final class SelfScope {
    static boolean accepts(String packageName,String processName) {
        return "org.happyrun.app".equals(packageName) && "org.happyrun.app".equals(processName);
    }
}
