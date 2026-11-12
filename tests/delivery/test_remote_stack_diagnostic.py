"""Remote stack structure stays bounded, fixed-vocabulary and fail closed."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "remote_diag", ROOT / "scripts/check_mumu_observation.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_remote_frames_are_distinguished_and_deduplicated():
    raw = """java.lang.NullPointerException: private
 at android.os.Parcel.readException(Parcel.java:2393)
Caused by: android.os.RemoteException: Remote stack trace:
 at com.android.server.wm.ActivityStarter.startActivityInner(ActivityStarter.java:1730)
 at com.android.server.wm.AppTaskImpl.startActivity(AppTaskImpl.java:153)
 at com.android.server.wm.PrivateUserToken.secret(PrivateUserToken.java:1)
 at com.android.server.wm.ActivityStarter.secret(ActivityStarter.java:1730)
 at com.android.server.wm.ActivityStarter.startActivityInner(private.java:1730)
"""
    result = MODULE.diagnostics(raw + raw, 0)
    assert result.get("remote_stack_marker") is True
    assert result["launch_frames"] == [
        {"frame": "parcel_read_exception", "line": 2393},
        {"frame": "server_starter_inner", "line": 1730},
        {"frame": "server_app_task_start", "line": 153},
    ]
    assert "private" not in str(result).lower() and "secret" not in str(result)
    assert not MODULE.accepted(raw, 0, "fresh", 0, 12, "abc")


def test_no_remote_marker_is_explicit_and_unknown_frames_are_not_disclosed():
    result = MODULE.diagnostics("java.lang.NullPointerException: private", 0)
    assert result.get("remote_stack_marker") is False
    assert result["launch_frames"] == []


def test_each_explicit_server_mapping_preserves_only_its_fixed_label_and_line():
    for (class_name, method, filename), label in MODULE.LAUNCH_FRAMES.items():
        if not class_name.startswith("com.android.server.wm."):
            continue
        raw = f" at {class_name}.{method}({filename}:123)"
        assert MODULE.diagnostics(raw, 0)["launch_frames"] == [{"frame": label, "line": 123}]
