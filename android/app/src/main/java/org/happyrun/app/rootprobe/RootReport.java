package org.happyrun.app.rootprobe;
public final class RootReport {
    public final String status;
    public final boolean uidZeroObserved;
    RootReport(String status) {this.status=status;this.uidZeroObserved="uid_zero_observed".equals(status);}
}
