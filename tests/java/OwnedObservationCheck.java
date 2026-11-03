package org.happyrun.app.observation;
public final class OwnedObservationCheck {
    private static void check(boolean value) { if (!value) throw new AssertionError(); }
    public static void main(String[] args) throws Exception {
        ObservationWindow w = new ObservationWindow(100, 1000, 2);
        check(w.offer("location", 101, 102, new double[]{1,2}, 3));
        check(!w.offer("location", 101, 103, new double[]{1,2}, 3));
        check(!w.offer("gravity", 99, 103, new double[]{1,2,3}, 3));
        check(!w.offer("gravity", 104, 103, new double[]{1,2,3}, 3));
        check(!w.offer("gravity", 103, 103, new double[]{Double.NaN,2,3}, 3));
        check(w.offer("gravity", 104, 104, new double[]{1,2,3}, 3));
        check(!w.offer("gravity", 105, 105, new double[]{1,2,3}, 3));
        check(w.snapshot().size()==2);
        ObservationWindow invalids=new ObservationWindow(100,1000,10);
        check(!invalids.offer("location",101,101,new double[]{91,0},1));
        check(!invalids.offer("location",101,101,new double[]{1,2},-1));
        check(!invalids.offer("unknown",101,101,new double[]{1,2},1));
        check(!invalids.offer("gravity",101,101,new double[]{1,2},1));
        check(!invalids.offer("gravity",101,101,new double[]{1,2,3},Double.POSITIVE_INFINITY));
        check(invalids.snapshot().isEmpty());
        double[] v=w.snapshot().get(0).values();v[0]=90;
        check(w.snapshot().get(0).values()[0]==1);
        w.close();w.close();
        check(!w.offer("location", 106, 106, new double[]{1,2}, 3));
        ObservationWindow deadline = new ObservationWindow(100, 1000, 10);
        check(!deadline.offer("location", 1100, 1100, new double[]{1,2}, 3));
        ObservationWindow race=new ObservationWindow(0, 1000000, 128);
        Thread t=new Thread(()->{for(int i=1;i<500;i++)race.offer("gravity",i,i,new double[]{1,2,3},3);});
        t.start();race.close();int count=race.snapshot().size();t.join();check(count==race.snapshot().size());
        check(!race.offer("gravity",900,900,new double[]{1,2,3},3));
        boolean invalid=false;try{new ObservationWindow(0,0,1);}catch(IllegalArgumentException e){invalid=true;}check(invalid);
        ObservationSession s = new ObservationSession(new ObservationWindow(0,1000,10));
        final int[] removed={0};
        s.register(() -> { removed[0]++; throw new IllegalStateException("first cleanup failed"); });
        s.register(() -> removed[0]++);
        check(!s.stopObserving());check(removed[0]==2);
        check(!s.stopObserving());check(removed[0]==2);
        check(!s.window.offer("gravity",1,1,new double[]{1,2,3},3));
        boolean late=false;try{s.register(()->{});}catch(IllegalStateException e){late=true;}check(late);
        System.out.println("owned-observation: passed");
    }
}
