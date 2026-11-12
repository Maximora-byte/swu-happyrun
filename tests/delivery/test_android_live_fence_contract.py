"""Source boundaries for the real-device scenario; these do not claim Android execution."""

import ast
from pathlib import Path

ROOT = Path(__file__).parents[2]
HOST = ROOT / "scripts/check_android_live_fence.py"
JAVA = ROOT / (
    "android/app/src/remoteQaAndroidTest/java/org/happyrun/app/remoteqa/"
    "RemoteLiveFenceAcceptanceTest.java"
)


def test_host_requires_real_expiry_claim_and_old_pid():
    text = HOST.read_text()
    ast.parse(text)
    for check in (
        'scenario="lost_renew"',
        'reason_code"] == "lease_expired"',
        '"/api/v1/leases/claim"',
        'grant["fence"] > original["fence"]',
        "rejected.status_code == 409",
        'adb("shell", "pidof", PACKAGE)',
        "renew_count == 4",
        "fault_used",
        "process.poll() is None",
    ):
        assert check in text


def test_instrumentation_observes_counts_without_restart():
    text = JAVA.read_text()
    assert text.count("runner.runOnce()") == 1
    assert "driver.tickCount()>0" in text
    assert "assertEquals(ticks,driver.tickCount())" in text
    assert "assertEquals(attempts,driver.tickAttemptCount())" in text
    assert "view.fence>original.fence" in text
    assert "observer.getJob(original.jobId)" in text
    assert "Thread.sleep(5200)" in text  # Real delayed scheduling, no clock offset.
    assert "requestStop(" not in text
    assert "driver.tick(" not in text
    assert "driver.stop(" not in text
