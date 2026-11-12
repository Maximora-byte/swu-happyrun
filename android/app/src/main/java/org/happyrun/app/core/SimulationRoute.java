package org.happyrun.app.core;

/** A synthetic 20 metre square, never geographic/device location data. */
public final class SimulationRoute {
    public static final double TOTAL_METRES = 20.0;
    public static final double SPEED_METRES_PER_SECOND = 2.5;
    private double elapsed;
    public double advance(double seconds) {
        if (!Double.isFinite(seconds) || seconds < elapsed) throw new IllegalArgumentException("invalid_elapsed");
        elapsed = seconds;
        return Math.min(TOTAL_METRES, elapsed * SPEED_METRES_PER_SECOND);
    }
    public double[] position() {
        double d = Math.min(TOTAL_METRES, elapsed * SPEED_METRES_PER_SECOND);
        if (d <= 5) return new double[]{d,0};
        if (d <= 10) return new double[]{5,d-5};
        if (d <= 15) return new double[]{15-d,5};
        return new double[]{0,20-d};
    }
}
