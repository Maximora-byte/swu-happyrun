package org.happyrun.app.core;
import org.junit.Test;
import static org.junit.Assert.*;
public class SimulationRouteTest {
    @Test public void progressesToExactClosedEndpoint() {
        SimulationRoute r=new SimulationRoute();assertEquals(0,r.advance(0),0);
        assertEquals(5,r.advance(2),0);assertArrayEquals(new double[]{5,0},r.position(),0);
        assertEquals(10,r.advance(4),0);assertArrayEquals(new double[]{5,5},r.position(),0);
        assertEquals(20,r.advance(8),0);assertArrayEquals(new double[]{0,0},r.position(),0);
        assertEquals(20,r.advance(100),0);
    }
    @Test public void rejectsInvalidAndBackwardsClock() {
        for(double invalid:new double[]{-1,Double.NaN,Double.POSITIVE_INFINITY}) {
            try {new SimulationRoute().advance(invalid);fail();}catch(IllegalArgumentException expected){}
        }
        SimulationRoute r=new SimulationRoute();r.advance(2);
        try {r.advance(1);fail();}catch(IllegalArgumentException expected){}
    }
    @Test public void unverifiedAdaptersNeverStart() {
        for(String name:new String[]{"android","root","lsposed","mumu"}) {
            ExecutionAdapter a=new ExecutionAdapter.Unsupported(name);assertFalse(a.verified());
            try {a.start();fail();}catch(UnsupportedOperationException expected){}
        }
    }
}
