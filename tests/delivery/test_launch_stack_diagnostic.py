"""Keep only allowlisted launch stack structure, never exception messages."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "launch_diag", ROOT / "scripts/check_mumu_observation.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_launch_stack_reports_only_allowed_structural_frames():
    raw = """java.lang.NullPointerException: token=secret user=data
    at android.app.Instrumentation.execStartActivityFromAppTask(Instrumentation.java:2042)
    at android.app.ActivityManager$AppTask.startActivity(ActivityManager.java:4726)
  at org.happyrun.app.DisplayObservationTest.testObserveOwnActivity(DisplayObservationTest.java:112)
    at private.user.Component.token(Component.java:99)
    at android.app.SecretToken.secret(SecretToken.java:1)
    at android.app.Instrumentation.execStartActivityFromAppTask(secret.java:42)
    at android.app.Instrumentation.execStartActivityFromAppTask(Instrumentation.java:42) secret
"""
    result = MODULE.diagnostics(raw, 0)
    assert result.get("launch_frames") == [
        {"frame": "instrumentation_app_task", "line": 2042},
        {"frame": "app_task_start", "line": 4726},
        {"frame": "own_observation", "line": 112},
    ]
    assert "secret" not in str(result) and "private" not in str(result)
    assert not MODULE.accepted(raw, 0, "fresh", 0, 12, "abc")


def test_launch_stack_is_bounded_and_missing_frames_stay_unknown():
    raw = "\n".join(
        "at android.app.ActivityManager$AppTask.startActivity(ActivityManager.java:" + str(n) + ")"
        for n in range(30)
    )
    assert len(MODULE.diagnostics(raw, 0).get("launch_frames", [])) == 12
    assert (
        MODULE.diagnostics("java.lang.NullPointerException: private", 0).get("launch_frames") == []
    )


def test_binder_exception_frames_remain_distinguishable_without_message():
    raw = """INSTRUMENTATION_STATUS: stack=java.lang.NullPointerException: private
    at android.os.Parcel.createExceptionOrNull(Parcel.java:2431)
    at android.os.Parcel.readException(Parcel.java:2399)
    at android.app.IAppTask$Stub$Proxy.startActivity(IAppTask.java:232)
"""
    assert MODULE.diagnostics(raw, 0)["launch_frames"] == [
        {"frame": "parcel_create_exception_or_null", "line": 2431},
        {"frame": "parcel_read_exception", "line": 2399},
        {"frame": "app_task_binder_proxy", "line": 232},
    ]
