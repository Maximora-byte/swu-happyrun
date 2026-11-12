package org.happyrun.app.observation;

import android.os.Bundle;
import org.happyrun.app.BuildConfig;
import java.io.FileInputStream;
import java.nio.charset.StandardCharsets;
import android.test.InstrumentationTestCase;
import android.test.InstrumentationTestRunner;

/** Explicit opt-in field reader; default CI never registers physical listeners. */
public final class AndroidObservationTest extends InstrumentationTestCase {
    public void testReadOwnChannelOnlyWhenRequested() throws Exception {
        Bundle args=((InstrumentationTestRunner)getInstrumentation()).getArguments();
        String channel=args.getString("ownedObservationChannel");
        if(channel==null) {
            Bundle status=new Bundle();status.putString("owned_observation","not_run_opt_in_required");
            getInstrumentation().sendStatus(0,status);return;
        }
        assertTrue("Only location/gravity accepted", "location".equals(channel)||"gravity".equals(channel));
        AndroidObservation[] reader={null};RuntimeException[] failure={null};
        try {
            getInstrumentation().runOnMainSync(()->{
                try { reader[0]=AndroidObservation.start(getInstrumentation().getTargetContext(),channel,1000); }
                catch(RuntimeException error) { failure[0]=error; }
            });
            if(failure[0]!=null)throw failure[0];
            Thread.sleep(1100);
        } finally {
            if(reader[0]!=null) {
                boolean[] removed={false};
                getInstrumentation().runOnMainSync(()->removed[0]=reader[0].stopObserving());
                assertTrue("observation_cleanup_unconfirmed",removed[0]);
            }
        }
        int count=reader[0].session.window.snapshot().size();
        Bundle status=new Bundle();status.putString("owned_observation",count>0?"samples_observed":"no_samples");
        status.putInt("sample_count",count);
        status.putString("injection_status","unsupported");
        status.putString("injection_stop","unconfirmed");
        getInstrumentation().sendStatus(0,status);
        assertTrue("No fresh independent samples; not readback acceptance",count>0);
    }

    /** Explicit host request only; all values stay in the own app's private sandbox. */
    public void testPrivateReadbackWhenRequested() throws Exception {
        Bundle args=((InstrumentationTestRunner)getInstrumentation()).getArguments();
        String nonce=args.getString("ownedObservationNonce");
        if(nonce==null)return;
        if(!"selfProbe".equals(BuildConfig.BUILD_TYPE)) {
            reportStatus("self_probe_required");return;
        }
        String binding=args.getString("ownedObservationBinding");
        String channel=args.getString("ownedObservationChannel");
        int duration;
        try {
            duration=Integer.parseInt(args.getString("ownedObservationDurationMs","0"));
            if(!nonce.matches("[a-f0-9]{32}") || binding==null || !binding.matches("[a-f0-9]{64}")
                    || !("location".equals(channel)||"gravity".equals(channel))
                    || duration<1 || duration>5000)throw new IllegalArgumentException();
        } catch(RuntimeException invalid) { reportStatus("private_request_invalid");return; }
        String boot;
        try(FileInputStream stream=new FileInputStream("/proc/sys/kernel/random/boot_id")) {
            byte[] bytes=new byte[129];int length=stream.read(bytes);
            if(length<1 || length>128)throw new IllegalStateException();
            boot=new String(bytes,0,length,StandardCharsets.US_ASCII).trim();
            if(!boot.matches("[A-Za-z0-9-]{1,128}"))throw new IllegalStateException();
        } catch(Exception unavailable) { reportStatus("boot_unavailable");return; }
        AndroidObservation[] reader={null};RuntimeException[] failure={null};
        boolean[] removed={true};String status="observation_failed";
        final int budget=duration;
        try {
            getInstrumentation().runOnMainSync(()->{
                try { reader[0]=AndroidObservation.start(getInstrumentation().getTargetContext(),channel,budget); }
                catch(RuntimeException error) { failure[0]=error; }
            });
            if(failure[0]!=null) {
                String code=failure[0].getMessage();
                if("permission_required".equals(code) || "location_provider_unsupported".equals(code)
                        || "gravity_sensor_unsupported".equals(code) || "gravity_registration_failed".equals(code)
                        || "observation_cleanup_unconfirmed".equals(code))status=code;
            } else {
                Thread.sleep(duration+100L);
                status=reader[0].session.window.snapshot().isEmpty()?"no_samples":"samples_observed";
            }
        } finally {
            if(reader[0]!=null)getInstrumentation().runOnMainSync(()->removed[0]=reader[0].stopObserving());
        }
        if(!removed[0])status="observation_cleanup_unconfirmed";
        String report=ObservationReport.encode(nonce,binding,boot,channel,duration,
                reader[0]==null?null:reader[0].session.window,removed[0],status);
        try {
            ObservationPrivateFile.write(getInstrumentation().getTargetContext().getFilesDir(),nonce,report);
        } catch(Exception unavailable) { reportStatus("private_write_failed");return; }
        reportStatus(status);
    }
    private void reportStatus(String status) {
        Bundle bundle=new Bundle();bundle.putString("owned_observation",status);
        getInstrumentation().sendStatus(0,bundle);
    }
}
