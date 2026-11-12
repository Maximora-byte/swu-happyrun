package org.happyrun.app.runtime;
import org.junit.Test;
import static org.junit.Assert.*;
public class TaskSnapshotTest {
    @Test public void localOnlyNeverClaimsRecord() {
        TaskSnapshot s=new TaskSnapshot("id","completed","simulation_only",20,20,0,8000);
        assertFalse(s.recordVerified);assertEquals("simulation_local",s.mode);
    }
    @Test public void unsavedSafetyProjectionIsExplicit() {
        TaskSnapshot stored=new TaskSnapshot("id","running","simulation_only",5,20,0,2000);
        TaskSnapshot projection=new TaskSnapshot(stored.id,"needs_attention","storage_write_failed_not_persisted",stored.distanceM,stored.totalDistanceM,stored.startedAtMs,stored.updatedAtMs,false);
        assertTrue(stored.persisted);assertFalse(projection.persisted);
        assertEquals("running",stored.state);assertEquals("needs_attention",projection.state);
        assertFalse(projection.recordVerified);
    }
    @Test public void corruptValuesFailClosed() {
        for(String state:new String[]{"succeeded","valid","unknown",""}) {
            try {new TaskSnapshot("id",state,"reason",0,20,0,0);fail();}
            catch(IllegalArgumentException expected){}
        }
        for(double distance:new double[]{-1,21,Double.NaN,Double.POSITIVE_INFINITY}) {
            try {new TaskSnapshot("id","running","reason",distance,20,0,0);fail();}
            catch(IllegalArgumentException expected){}
        }
        try {new TaskSnapshot("id","completed","reason",1,20,0,0);fail();}
        catch(IllegalArgumentException expected){}
    }
}
