"""Deterministic launch-probe fixtures; no Android execution claim."""

import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "launch_probe", ROOT / "scripts/check_android_launch.py"
)
assert SPEC and SPEC.loader
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)
ACTIVITY = "mResumedActivity: ActivityRecord{abc u0 org.happyrun.app/.MainActivity t2}"
XML = (
    "<hierarchy>"
    + "".join(
        f'<node package="org.happyrun.app" resource-id="org.happyrun.app:id/{name}" '
        'bounds="[0,0][100,100]" />'
        for name in ("app_scroll", "task_state", "start_simulation")
    )
    + "</hierarchy>"
)


@pytest.mark.parametrize(
    "status,activity,xml,log,expected",
    [
        ("timeout", ACTIVITY, XML, "", 0),
        ("ok", ACTIVITY, XML, "", 0),
        ("timeout", ACTIVITY, "<hierarchy/>", "", 1),
        ("timeout", ACTIVITY, XML.replace('package="org.happyrun.app"', 'package="other"'), "", 1),
        ("timeout", "other resumed", XML, "", 1),
        ("timeout", ACTIVITY, XML, "ANR in org.happyrun.app", 1),
        ("ok", ACTIVITY, XML, "FATAL EXCEPTION: main\nProcess: org.happyrun.app, PID: 123", 1),
        ("error", ACTIVITY, XML, "", 1),
        ("dump_failed", ACTIVITY, XML, "", 1),
        ("rm_failed", ACTIVITY, XML, "", 1),
        ("late_timeout", ACTIVITY, XML, "", 1),
        ("timeout", "ADB_COMMAND_FAILED\n" + ACTIVITY, XML, "", 1),
        ("timeout", ACTIVITY.replace("MainActivity", "MainActivityOther"), XML, "", 1),
        ("ok", ACTIVITY, XML, "HOST_COMMAND_TIMEOUT", 1),
    ],
)
@pytest.mark.parametrize("profile", ["core", "wizard"])
def test_single_launch_requires_visible_resumed_app_without_crash(
    monkeypatch, tmp_path, status, activity, xml, log, expected, profile
):
    monkeypatch.setenv("ANDROID_SERIAL", "emulator-5554")
    monkeypatch.setenv("HAPPYRUN_DISPOSABLE_EMULATOR", "1")
    monkeypatch.setenv("HAPPYRUN_ANDROID_LAUNCH_PROFILE", profile)
    if profile == "wizard":
        xml = xml.replace("task_state", "framework_probe").replace(
            "start_simulation", "wizard_refresh"
        )
    monkeypatch.setattr(PROBE.sys, "argv", ["probe", str(tmp_path)])
    clock = [0]
    monkeypatch.setattr(PROBE.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(PROBE.time, "sleep", lambda _: clock.__setitem__(0, clock[0] + 61))
    commands = []
    launch_status = "ok" if status in ("dump_failed", "rm_failed") else status.removeprefix("late_")

    def run(cmd, **kwargs):
        commands.append(cmd)
        joined = " ".join(cmd)
        value = ""
        if "ro.kernel.qemu" in joined:
            value = "1\n"
        elif "pm path" in joined:
            value = "package:/data/app/app.apk"
        elif "am start" in joined:
            value = f"Status: {launch_status}\n"
        elif "dumpsys activity" in joined:
            value = activity
        elif "logcat" in joined:
            value = log
        elif "uiautomator dump" in joined:
            value = "UI hierchary dumped to: /sdcard/happyrun-launch.xml"
        elif "shell cat" in joined:
            value = xml
            if status == "late_timeout":
                clock[0] = 121
        elif "pidof" in joined:
            value = "123"
        return subprocess.CompletedProcess(
            cmd,
            139
            if (status == "dump_failed" and "uiautomator dump" in joined)
            or (status == "rm_failed" and "shell rm" in joined)
            else 0,
            value.encode(),
            b"",
        )

    monkeypatch.setattr(PROBE.subprocess, "run", run)
    assert PROBE.main() == expected
    assert sum("am" in cmd and "start" in cmd for cmd in commands) == 1
    assert (tmp_path / "launch.txt").read_text() == f"Status: {launch_status}\n"
    for name in (
        "activity.txt",
        "window.txt",
        "logcat.txt",
        "pid.txt",
        "ui.xml",
        "screen.png",
        "verification.txt",
    ):
        assert (tmp_path / ("launch-" + name)).exists()


def test_probe_refuses_unmarked_or_real_device(monkeypatch, tmp_path):
    monkeypatch.delenv("HAPPYRUN_DISPOSABLE_EMULATOR", raising=False)
    monkeypatch.setenv("ANDROID_SERIAL", "physical-device")
    with pytest.raises(SystemExit, match="disposable"):
        PROBE.main()


def test_empty_bounds_and_malformed_ui_never_count_as_visible():
    assert not PROBE.visible(ACTIVITY, XML.replace("[0,0][100,100]", "[0,0][0,100]"))
    assert not PROBE.visible(ACTIVITY, "not XML")


def test_wizard_profile_requires_its_own_visible_first_screen():
    wizard = XML.replace("task_state", "framework_probe").replace(
        "start_simulation", "wizard_refresh"
    )
    assert PROBE.visible(ACTIVITY, wizard, "wizard")
    assert not PROBE.visible(ACTIVITY, XML, "wizard")
    assert not PROBE.visible(ACTIVITY, wizard, "core")
    assert not PROBE.visible(ACTIVITY, "<hierarchy/>", "wizard")
    assert not PROBE.visible("other resumed", wizard, "wizard")
    assert not PROBE.visible(
        ACTIVITY, wizard.replace('package="org.happyrun.app"', 'package="other"'), "wizard"
    )
    assert not PROBE.visible(ACTIVITY, wizard, "unknown")


def test_unknown_profile_rejected_before_adb(monkeypatch, tmp_path):
    monkeypatch.setenv("ANDROID_SERIAL", "emulator-5554")
    monkeypatch.setenv("HAPPYRUN_DISPOSABLE_EMULATOR", "1")
    monkeypatch.setenv("HAPPYRUN_ANDROID_LAUNCH_PROFILE", "anything")
    monkeypatch.setattr(PROBE.sys, "argv", ["probe", str(tmp_path)])
    monkeypatch.setattr(PROBE.subprocess, "run", lambda *a, **kw: pytest.fail("ADB called"))
    with pytest.raises(SystemExit, match="profile"):
        PROBE.main()
