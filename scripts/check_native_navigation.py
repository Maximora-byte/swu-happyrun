"""Compile exact test helper methods against controlled UI/clock ports, not Android ART."""

import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "android/app/src/androidTest/java/org/happyrun/app/AndroidAcceptanceTest.java"
source = SOURCE.read_text()
methods = source[
    source.index("    private Activity currentMain()") : source.index(
        "    private AccessibilityNodeInfo awaitNative"
    )
]
stubs = r"""
import java.util.*;
final class NavigationAdapterCheck {
    static String actions="";
    static class Rect {
        int top=0,bottom=0;
        int height(){return bottom-top;} boolean isEmpty(){return height()<=0;}
        String toShortString(){return "[0,"+top+"][100,"+bottom+"]";}
        static boolean intersects(Rect a,Rect b){return a.top<b.bottom&&b.top<a.bottom;}
    }
    static class View {
        boolean shown=true,attached=true,visible=false; int y=200;
        boolean isAttachedToWindow(){return attached;} boolean isShown(){return shown;}
        boolean getGlobalVisibleRect(Rect r){r.top=y;r.bottom=y+20;return visible;}
        int getHeight(){return 20;} int getScrollY(){return y;}
        void getDrawingRect(Rect r){r.top=0;r.bottom=20;}
        boolean requestRectangleOnScreen(Rect r,boolean immediate){
            check(immediate);actions+="reveal>";visible=true;y=20;return true;
        }
    }
    static class Resources {
        int getIdentifier(String id,String type,String pkg){return id.equals("app_scroll")?2:1;}
    }
    static class Activity {
        View target=new View();boolean destroyed,finishing,focused=true;
        boolean isDestroyed(){return destroyed;} boolean isFinishing(){return finishing;}
        boolean hasWindowFocus(){return focused;} Resources getResources(){return new Resources();}
        String getPackageName(){return "org.happyrun.app";}
        View findViewById(int id){return target;}
    }
    static class Monitor {Activity latest;Activity getLastActivity(){return latest;}}
    static class AccessibilityNodeInfo {
        String pkg="org.happyrun.app"; boolean root;
        View view;
        CharSequence getPackageName(){return pkg;}
        boolean isVisibleToUser(){return view.visible;}
        void getBoundsInScreen(Rect r){r.top=root?0:view.y;r.bottom=root?100:view.y+20;}
        List<AccessibilityNodeInfo> findAccessibilityNodeInfosByViewId(String id){
            AccessibilityNodeInfo n=new AccessibilityNodeInfo();n.view=view;n.pkg=nodePackage;
            return Arrays.asList(n);
        }
    }
    static String windowPackage="org.happyrun.app",nodePackage="org.happyrun.app";
    final class Automation {
        AccessibilityNodeInfo getRootInActiveWindow(){
            actions+="observe>";AccessibilityNodeInfo n=new AccessibilityNodeInfo();
            n.root=true;n.view=currentMain().target;n.pkg=windowPackage;return n;
        }
    }
    final class Instrumentation {
        void runOnMainSync(Runnable r){r.run();}
        Automation getUiAutomation(){return new Automation();}
    }
    Instrumentation getInstrumentation(){return new Instrumentation();}
    Activity activity=new Activity();Monitor mainMonitor=new Monitor();
    String navigationObservation="";
    static void check(boolean pass){if(!pass)throw new AssertionError();}
"""
checks = r"""
    public static void main(String[] args){
        NavigationAdapterCheck c=new NavigationAdapterCheck();
        check(c.revealAndObserve("start_simulation")!=null);
        check(actions.equals("reveal>observe>"));
        c.activity.destroyed=true;c.mainMonitor.latest=new Activity();
        check(c.revealAndObserve("refresh_checks")!=null);
        check(c.mainMonitor.latest.target.visible);
        windowPackage="android";check(c.revealAndObserve("start") == null);
        windowPackage="org.happyrun.app";nodePackage="another.app";
        check(c.revealAndObserve("start") == null);nodePackage="org.happyrun.app";
        c.mainMonitor.latest.target.shown=false;check(c.revealAndObserve("start") == null);
        c.mainMonitor.latest.target.shown=true;c.mainMonitor.latest.focused=false;
        check(c.revealAndObserve("start") == null);
        c.mainMonitor.latest.focused=true;c.mainMonitor.latest.target.attached=false;
        check(c.revealAndObserve("start") == null);
        c.mainMonitor.latest.target.attached=true;c.mainMonitor.latest.target.y=200;
        c.mainMonitor.latest.target.visible=true;check(c.revealAndObserve("start") == null);
        System.out.println("PASS 8 extracted-adapter checks (controlled ports, not ART)");
    }
}
"""
with tempfile.TemporaryDirectory(prefix="happyrun-navigation-check-") as directory:
    temporary = Path(directory)
    extracted = temporary / "NavigationAdapterCheck.java"
    extracted.write_text(stubs + methods + checks)
    sources = [
        extracted,
        ROOT / "tests/java/LegacyDeadlineRepro.java",
        ROOT / "tests/java/NativeViewDeadlineCheck.java",
        ROOT / "android/app/src/androidTest/java/org/happyrun/app/NativeViewDeadline.java",
    ]
    subprocess.run(
        [
            "java",
            "com.sun.tools.javac.Main",
            "-source",
            "17",
            "-target",
            "17",
            "-d",
            str(temporary),
            *map(str, sources),
        ],
        check=True,
    )
    for main in (
        "LegacyDeadlineRepro",
        "org.happyrun.app.NativeViewDeadlineCheck",
        "NavigationAdapterCheck",
    ):
        subprocess.run(["java", "-cp", str(temporary), main], check=True)
