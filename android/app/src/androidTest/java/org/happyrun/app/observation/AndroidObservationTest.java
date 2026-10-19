package org.happyrun.app.observation;

import android.os.Bundle;
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
}
