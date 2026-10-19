package org.happyrun.app.remoteqa;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Intent;
import android.content.pm.ActivityInfo;
import android.content.res.Configuration;
import android.os.Bundle;
import android.os.SystemClock;
import android.test.InstrumentationTestCase;
import android.test.InstrumentationTestRunner;
import android.view.KeyEvent;
import android.view.WindowManager;
import android.widget.EditText;
import android.widget.TextView;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.Collections;
import java.util.IdentityHashMap;
import java.util.Set;
import java.util.concurrent.atomic.AtomicReference;
import org.happyrun.app.MainActivity;
import org.happyrun.app.RemoteAgentActivity;
import org.happyrun.app.remote.runtime.RemoteForegroundSession;
import org.happyrun.app.remote.ui.RemoteSessionGate;
import org.happyrun.app.remote.runtime.RemoteAgentRunner;
import org.happyrun.app.remote.simulation.RemoteFakeDriver;

/** Actual UI and HTTPS. Reads real driver state; no fake client or lifecycle callbacks. */
@SuppressWarnings("deprecation")
public final class RemoteForegroundActivityAcceptanceTest extends InstrumentationTestCase {
    private RemoteAgentActivity page;
    private final Set<RemoteFakeDriver> drivers=Collections.newSetFromMap(new IdentityHashMap<>());
    private final Set<RemoteForegroundSession> sessions=Collections.newSetFromMap(new IdentityHashMap<>());
    private String secret;
    private String arg(String name) {
        String value=((InstrumentationTestRunner)getInstrumentation()).getArguments().getString(name);
        assertNotNull("Missing synthetic argument",value);return value;
    }
    private int id(Activity activity,String name) {return activity.getResources().getIdentifier(name,"id",activity.getPackageName());}
    private void ui(Runnable action) {getInstrumentation().runOnMainSync(action);}
    private Object field(Object owner,String name)throws Exception {java.lang.reflect.Field f=owner.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(owner);}
    private void observe()throws Exception {
        if(page==null)return;
        RemoteForegroundSession session=(RemoteForegroundSession)field(page,"session");
        if(session!=null){sessions.add(session);RemoteAgentRunner runner=(RemoteAgentRunner)field(session,"active");if(runner!=null)drivers.add((RemoteFakeDriver)field(runner,"driver"));}
    }
    private int starts(){return drivers.stream().mapToInt(RemoteFakeDriver::startCount).sum();}
    private interface Condition {boolean ready()throws Exception;}
    private void await(String label,Condition condition,long millis)throws Exception {
        long end=SystemClock.elapsedRealtime()+millis;
        while(SystemClock.elapsedRealtime()<end){observe();if(condition.ready())return;SystemClock.sleep(5);}
        fail("Timed out: "+label);
    }
    private boolean enabled(String name) {AtomicReference<Boolean> value=new AtomicReference<>();ui(()->value.set(page.findViewById(id(page,name)).isEnabled()));return value.get();}
    private String text(String name) {AtomicReference<String> value=new AtomicReference<>();ui(()->value.set(((TextView)page.findViewById(id(page,name))).getText().toString()));return value.get();}
    private boolean foreground()throws Exception{return (Boolean)field(page,"foreground");}
    private void marker(String value) {Bundle b=new Bundle();b.putString("stream","\nFOREGROUND_QA "+value+"\n");getInstrumentation().sendStatus(0,b);}
    private RemoteAgentActivity openFromMain()throws Exception {
        Intent intent=new Intent(getInstrumentation().getTargetContext(),MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK|Intent.FLAG_ACTIVITY_CLEAR_TASK);
        MainActivity main=(MainActivity)getInstrumentation().startActivitySync(intent);
        Instrumentation.ActivityMonitor monitor=getInstrumentation().addMonitor(RemoteAgentActivity.class.getName(),null,false);
        try {
            ui(()->{assertTrue(main.findViewById(id(main,"remote_entry")).performClick());});
            Activity opened=monitor.waitForActivityWithTimeout(5000);assertNotNull("Main entry did not open remote page",opened);
            return (RemoteAgentActivity)opened;
        }finally{getInstrumentation().removeMonitor(monitor);}
    }
    private void connect(boolean rapid)throws Exception {
        assertTrue("Credential field is not empty",text("remote_token").isEmpty());assertFalse(enabled("remote_stop"));
        ui(()->{
            ((EditText)page.findViewById(id(page,"remote_endpoint"))).setText(arg("origin"));
            ((EditText)page.findViewById(id(page,"remote_agent_id"))).setText(arg("agent"));
            ((EditText)page.findViewById(id(page,"remote_device_id"))).setText(arg("device"));
            ((EditText)page.findViewById(id(page,"remote_token"))).setText(secret);
            assertTrue(page.findViewById(id(page,"remote_connect")).performClick());
            if(rapid){page.findViewById(id(page,"remote_connect")).performClick();page.findViewById(id(page,"remote_stop")).performClick();}
        });
        assertTrue("Credential field is not empty",text("remote_token").isEmpty());
        assertTrue((page.getWindow().getAttributes().flags&WindowManager.LayoutParams.FLAG_SECURE)!=0);
    }
    private void noStoredCredential()throws Exception {
        assertTrue("Credential field is not empty",text("remote_token").isEmpty());
        assertFalse(((EditText)page.findViewById(id(page,"remote_token"))).isSaveEnabled());
        scan(new File(getInstrumentation().getTargetContext().getApplicationInfo().dataDir,"shared_prefs"));
        scan(getInstrumentation().getTargetContext().getFilesDir());
    }
    private void scan(File file)throws Exception {
        if(!file.exists())return;
        if(file.isDirectory()){File[] children=file.listFiles();if(children!=null)for(File child:children)scan(child);return;}
        if(file.length()>2_000_000)fail("Unexpectedly large private QA file");
        assertFalse("Credential persisted in app private data",new String(Files.readAllBytes(file.toPath()),StandardCharsets.UTF_8).contains(secret));
    }
    private void storageFault()throws Exception {
        String value=arg("origin")+"\n"+arg("agent")+"\n"+arg("device");StringBuilder digest=new StringBuilder();
        for(byte b:MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)))digest.append(String.format(java.util.Locale.ROOT,"%02x",b&255));
        File directory=new File(getInstrumentation().getTargetContext().getFilesDir(),"remote-agent");assertTrue(directory.mkdirs()||directory.isDirectory());
        // Real filesystem failure: a file where RemoteJournal requires its directory.
        assertTrue(new File(directory,digest.toString()).createNewFile());
    }
    public void testScenario()throws Exception {
        String scenario=arg("scenario");secret=arg("token");page=openFromMain();
        try {
            assertFalse("Page connected automatically",enabled("remote_stop"));
            if(scenario.equals("storage_latch"))storageFault();
            connect(scenario.equals("rapid_toggle"));
            if(scenario.equals("two_jobs")) {
                await("visible waiting",()->text("remote_status").contains("在线等待"),10000);marker("WAITING");
                await("two actual driver starts",()->starts()==2,40000);
                await("two completed jobs and waiting UI",()->text("remote_status").contains("在线等待")&&drivers.stream().allMatch(RemoteFakeDriver::stopped),15000);
                marker("TWO_DONE");ui(()->page.findViewById(id(page,"remote_stop")).performClick());
            } else if(scenario.equals("rapid_toggle")) {
                await("first rapid session exits",()->field(page,"session")==null&&!((RemoteSessionGate)field(page,"gate")).busy(),10000);
                assertEquals(0,starts());connect(false);
                await("explicit reconnect waiting",()->text("remote_status").contains("在线等待"),10000);marker("RECONNECTED");
                await("new executor work really starts",()->starts()==1,15000);
                await("new work completes visibly",()->text("remote_status").contains("在线等待")&&drivers.stream().allMatch(RemoteFakeDriver::stopped),10000);
                marker("RAPID_DONE");ui(()->page.findViewById(id(page,"remote_stop")).performClick());
            } else if(scenario.endsWith("_latch")) {
                await("session closes",()->field(page,"session")==null&&!((RemoteSessionGate)field(page,"gate")).busy()&&!enabled("remote_stop"),18000);
                if(scenario.equals("auth_latch")||scenario.equals("transport_latch")){assertTrue(text("remote_status").contains("会话已结束"));assertTrue(enabled("remote_connect"));}
                if(scenario.equals("attention_latch"))assertTrue(text("remote_status").contains("管理员"));
                if(scenario.equals("storage_latch")){assertFalse(enabled("remote_connect"));assertTrue(text("remote_status").contains("存储"));}
                if(scenario.equals("transport_latch"))assertEquals(1,starts());
                if(scenario.equals("auth_latch")||scenario.equals("attention_latch")||scenario.equals("storage_latch"))assertEquals(0,starts());
                marker("LATCHED");
            } else {
                boolean running=scenario.endsWith("_running");
                if(running)await("real driver started",()->starts()==1,15000);
                else await("visible idle wait",()->text("remote_status").contains("在线等待"),10000);
                marker(running?"RUNNING":"WAITING");
                if(scenario.startsWith("disconnect"))ui(()->page.findViewById(id(page,"remote_stop")).performClick());
                else if(scenario.startsWith("back")) {
                    getInstrumentation().sendKeyDownUpSync(KeyEvent.KEYCODE_BACK);
                    await("Back stopped old Activity",()->!foreground(),5000);
                } else if(scenario.startsWith("home")) {
                    try(android.os.ParcelFileDescriptor command=getInstrumentation().getUiAutomation().executeShellCommand("input keyevent 3")){
                        try(java.io.InputStream output=new android.os.ParcelFileDescriptor.AutoCloseInputStream(command)){while(output.read()!=-1){}}
                    }
                    await("Home really backgrounded Activity",()->!foreground()&&!page.hasWindowFocus(),5000);
                } else if(scenario.startsWith("rotate")) {
                    RemoteAgentActivity old=page;
                    Instrumentation.ActivityMonitor monitor=getInstrumentation().addMonitor(RemoteAgentActivity.class.getName(),null,false);
                    try {
                        ui(()->old.setRequestedOrientation(old.getResources().getConfiguration().orientation==Configuration.ORIENTATION_LANDSCAPE?ActivityInfo.SCREEN_ORIENTATION_PORTRAIT:ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE));
                        Activity created=monitor.waitForActivityWithTimeout(8000);assertNotNull("Rotation did not recreate Activity",created);assertNotSame(old,created);
                        await("old rotated worker exits",()->field(old,"session")==null&&!((RemoteSessionGate)field(old,"gate")).busy(),8000);page=(RemoteAgentActivity)created;
                    }finally{getInstrumentation().removeMonitor(monitor);}
                }
            }
            await("worker session reference released",()->field(page,"session")==null&&!((RemoteSessionGate)field(page,"gate")).busy(),8000);
            assertTrue("Driver not stopped",drivers.stream().allMatch(RemoteFakeDriver::stopped));
            if(scenario.startsWith("home")) {
                RemoteAgentActivity old=page;
                ui(()->old.startActivity(new Intent(old,RemoteAgentActivity.class).addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT)));
                await("foreground return",()->foreground()&&page.hasWindowFocus(),5000);
            } else if(scenario.startsWith("back"))page=openFromMain();
            assertFalse("Automatic reconnect after leave",enabled("remote_stop"));
            noStoredCredential();marker("STOPPED starts="+starts());
            // Host creates another queued task after this marker. No UI action may reconnect.
            SystemClock.sleep(3200);observe();assertFalse(enabled("remote_stop"));assertNull(field(page,"session"));noStoredCredential();
            marker("PASS starts="+starts()+" stopped=true");
        } finally {
            if(page!=null)ui(()->page.finish());
        }
    }
}
