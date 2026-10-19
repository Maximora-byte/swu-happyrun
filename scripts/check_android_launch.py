"""Bounded first-frame verification on the disposable CI emulator only."""

import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

PACKAGE = "org.happyrun.app"
PROFILES = {
    "core": {"app_scroll", "task_state", "start_simulation"},
    "wizard": {"app_scroll", "framework_probe", "wizard_refresh"},
}


def visible(activity: str, xml: str, profile: str = "core") -> bool:
    if profile not in PROFILES:
        return False

    def has_area(bounds: str) -> bool:
        match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
        if not match:
            return False
        left, top, right, bottom = map(int, match.groups())
        return right > left and bottom > top

    resumed = re.search(
        r"(?:mResumedActivity|topResumedActivity).*org\.happyrun\.app/\.MainActivity\b",
        activity,
    )
    try:
        nodes = ET.fromstring(xml).iter("node")
        ids = {
            node.get("resource-id")
            for node in nodes
            if node.get("package") == PACKAGE and has_area(node.get("bounds", ""))
        }
    except ET.ParseError:
        return False
    return bool(resumed) and {f"{PACKAGE}:id/{name}" for name in PROFILES[profile]} <= ids


def unhealthy(log: str) -> bool:
    return bool(
        re.search(r"ANR in org\.happyrun\.app\b", log)
        or ("FATAL EXCEPTION" in log and "Process: org.happyrun.app," in log)
    )


def main() -> int:
    serial = os.environ.get("ANDROID_SERIAL", "")
    if os.environ.get("HAPPYRUN_DISPOSABLE_EMULATOR") != "1" or serial != "emulator-5554":
        raise SystemExit("Only the explicitly disposable CI emulator is supported")
    profile = os.environ.get("HAPPYRUN_ANDROID_LAUNCH_PROFILE", "core")
    if profile not in PROFILES:
        raise SystemExit("Unknown launch profile")
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)

    def adb(*args: str, timeout: float = 15) -> str:
        try:
            result = subprocess.run(
                ["adb", "-s", serial, *args], capture_output=True, timeout=timeout
            )
            text = (result.stdout + result.stderr).decode(errors="replace")
            return text if result.returncode == 0 else "ADB_COMMAND_FAILED\n" + text
        except subprocess.TimeoutExpired as exc:
            partial = (exc.stdout or b"") + (exc.stderr or b"")
            return "HOST_COMMAND_TIMEOUT\n" + partial.decode(errors="replace")

    if adb("shell", "getprop", "ro.kernel.qemu").strip() != "1":
        raise SystemExit("Target is not the disposable emulator")

    def snapshot(deadline: float) -> tuple[str, str, str]:
        def read(*args: str) -> str:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return "HOST_COMMAND_TIMEOUT"
            return adb(*args, timeout=min(15, remaining))

        activity = read("shell", "dumpsys", "activity", "activities")
        window = read("shell", "dumpsys", "window")
        log = read(
            "logcat",
            "-d",
            "-t",
            "1000",
            "-v",
            "threadtime",
            "AndroidRuntime:E",
            "ActivityManager:E",
            "*:S",
        )
        pid = read("shell", "pidof", PACKAGE)
        read("shell", "rm", "-f", "/sdcard/happyrun-launch.xml")
        dumped = read("shell", "uiautomator", "dump", "/sdcard/happyrun-launch.xml")
        xml = (
            read("shell", "cat", "/sdcard/happyrun-launch.xml")
            if "dumped to: /sdcard/happyrun-launch.xml" in dumped
            else ""
        )
        for name, text in (
            ("launch-activity.txt", activity),
            ("launch-window.txt", window),
            ("launch-logcat.txt", log),
            ("launch-pid.txt", pid),
            ("launch-ui.xml", xml),
        ):
            (out / name).write_text(text)
        return activity, xml, log

    # Read-only package-manager readiness. No repeated app starts.
    deadline = time.monotonic() + 60
    while "package:" not in adb("shell", "pm", "path", PACKAGE):
        if time.monotonic() >= deadline:
            snapshot(time.monotonic() + 30)
            return 1
        time.sleep(2)
    launch = adb("shell", "am", "start", "-W", "-n", PACKAGE + "/.MainActivity", timeout=45)
    (out / "launch.txt").write_text(launch)
    accepted = not launch.startswith(("ADB_COMMAND_FAILED", "HOST_COMMAND_TIMEOUT")) and bool(
        re.search(r"^Status: (?:ok|timeout)\s*$", launch, re.MULTILINE)
    )
    deadline = time.monotonic() + 120
    success = False
    while True:
        activity, xml, log = snapshot(deadline)
        if (
            time.monotonic() >= deadline
            or activity.startswith(("ADB_COMMAND_FAILED", "HOST_COMMAND_TIMEOUT"))
            or unhealthy(log)
            or not accepted
            or log.startswith(("ADB_COMMAND_FAILED", "HOST_COMMAND_TIMEOUT"))
        ):
            break
        if visible(activity, xml, profile):
            success = True
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(2)
    try:
        shot = subprocess.run(
            ["adb", "-s", serial, "exec-out", "screencap", "-p"], capture_output=True, timeout=15
        )
        if shot.returncode == 0:
            (out / "launch-screen.png").write_bytes(shot.stdout)
    except subprocess.TimeoutExpired:
        pass
    (out / "launch-verification.txt").write_text(
        f"profile={profile}\nvisible_resumed={success}\n"
        f"original_status_timeout={'Status: timeout' in launch}\n"
    )
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
