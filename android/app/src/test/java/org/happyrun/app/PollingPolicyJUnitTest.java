package org.happyrun.app;
import org.junit.Test;
public final class PollingPolicyJUnitTest {
    @Test public void pollsOnlyLiveHealthyTasksAndRendersChanges() {
        PollingPolicyTest.main(new String[0]);
    }
}
