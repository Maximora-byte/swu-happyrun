package org.happyrun.app;

import org.junit.Test;

/** Runs the same dependency-free presentation assertions in Gradle's JUnit task. */
public final class TaskPresentationJUnitTest {
    @Test public void presentationKeepsSimulationAndEvidenceSeparate() {
        TaskPresentationTest.main(new String[0]);
    }
}
