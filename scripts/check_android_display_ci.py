"""Run display observation and six fail-closed cases on an explicitly disposable official AVD."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

PACKAGE = "org.happyrun.app"
METHODS = (
    "testWrongDisplayNeverClicks",
    "testStaleObservationNeverCompletes",
    "testFailedDumpNeverUsesOldXml",
    "testMultipleTasksNeverClicks",
    "testMissingWindowNeverClicks",
    "testTimeoutNeverCompletes",
)


def identity(text):
    display = None
    tasks, resumed = set(), set()
    for line in text.splitlines():
        match = re.fullmatch(r"Display #(\d+) \(activities from top to bottom\):", line)
        if match:
            display = int(match[1])
            continue
        if line and not line[0].isspace():
            display = None
        if display is None:
            continue
        if re.search(r"org\.happyrun\.app(?=[\s}/])", line):
            header = re.search(r"^\s*\* Task\{[^}]* #(\d+)\b", line)
            if header:
                tasks.add((display, int(header[1])))
            record = re.search(r"ActivityRecord\{[^}]* org\.happyrun\.app/([.\w$]+) t(\d+)\b", line)
            if record:
                pair = (display, int(record[2]))
                tasks.add(pair)
                if record[1] in (".MainActivity", "org.happyrun.app.MainActivity") and re.search(
                    r"(?:mResumedActivity:|topResumedActivity=)", line
                ):
                    resumed.add(pair)
    if len(tasks) != 1 or tasks != resumed:
        raise ValueError("Expected exactly one package task and its resumed MainActivity/display")
    return next(iter(tasks))


def case_passed(text, code):
    return (
        code == 0
        and "OK (1 test)" in text
        and "INSTRUMENTATION_CODE: -1" in text
        and not re.search(
            r"FAILURES!!!|INSTRUMENTATION_FAILED|INSTRUMENTATION_ABORTED|shortMsg=|"
            r"INSTRUMENTATION_STATUS_CODE: -[123]",
            text,
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delivery", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    serial = os.environ.get("ANDROID_SERIAL", "")
    if os.environ.get("HAPPYRUN_DISPOSABLE_EMULATOR") != "1" or not re.fullmatch(
        r"emulator-\d+", serial
    ):
        parser.error("Only an explicitly selected disposable official AVD is allowed")
    args.output.mkdir(parents=True, exist_ok=True)
    report = {
        "suite": "android-display-observation",
        "result": "failed",
        "tests": 0,
        "writes": 0,
        "writes_scope": "test-issued simulation/control/input actions only",
        "cases": [],
        "mumu_verified": False,
        "record_verified": False,
    }

    def adb(*command, timeout=30):
        return subprocess.run(
            ["adb", "-s", serial, *command], capture_output=True, text=True, timeout=timeout
        )

    try:
        report["phase"] = "paired_manifest"
        delivery = json.loads(args.delivery.read_text(encoding="utf-8"))
        cert = delivery["certificate_sha256"]
        if (
            delivery["app_package"] != PACKAGE
            or delivery["test_package"] != PACKAGE + ".test"
            or delivery["instrumentation_runner"] != "android.test.InstrumentationTestRunner"
            or not re.fullmatch("[0-9a-f]{64}", cert)
        ):
            raise ValueError("Invalid paired delivery manifest")
        report["delivery_sha256"] = hashlib.sha256(args.delivery.read_bytes()).hexdigest()
        report["phase"] = "disposable_avd_guard"
        probe = adb("shell", "getprop", "ro.kernel.qemu")
        if probe.returncode or probe.stdout.strip() != "1":
            raise ValueError("Not the disposable official AVD")
        report["phase"] = "own_activity_launch"
        launch = adb("shell", "am", "start", "-W", "-n", PACKAGE + "/.MainActivity", timeout=45)
        if launch.returncode or not re.search(r"^Status: ok\s*$", launch.stdout, re.M):
            raise ValueError("Own Activity launch did not succeed")
        report["phase"] = "unique_task_display"
        observed = adb("shell", "dumpsys", "activity", "activities")
        if observed.returncode:
            raise ValueError("Activity dump failed")
        display, task = identity(observed.stdout)
        report.update(display_id=display, task_id=task)
        report["phase"] = "testObserveOwnActivity"
        output = args.output / "observation.json"
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).with_name("check_mumu_observation.py")),
                "--serial",
                serial,
                "--display",
                str(display),
                "--task",
                str(task),
                "--signature-sha256",
                cert,
                "--isolated-no-personal-data",
                "--output",
                str(output),
            ],
            capture_output=True,
            text=True,
            timeout=40,
        )
        if result.returncode:
            raise ValueError("Bound own Activity observation failed")
        own = json.loads(output.read_text(encoding="utf-8"))
        if own["result"] != "observed" or own["writes"] != 0:
            raise ValueError("Missing successful bound observation")
        report["cases"].append("testObserveOwnActivity")
        report["tests"] = 1
        for method in METHODS:
            report["phase"] = method
            result = adb(
                "shell",
                "am",
                "instrument",
                "-w",
                "-r",
                "-e",
                "class",
                "org.happyrun.app.DisplayObservationTest#" + method,
                "org.happyrun.app.test/android.test.InstrumentationTestRunner",
            )
            (args.output / (method + ".txt")).write_text(result.stdout, encoding="utf-8")
            if not case_passed(result.stdout, result.returncode):
                raise ValueError("Instrumentation case failed: " + method)
            report["cases"].append(method)
            report["tests"] += 1
        report["result"] = "passed"
    except (ValueError, KeyError, OSError, subprocess.TimeoutExpired) as failure:
        report["failure"] = type(failure).__name__
        # Do not repeat raw command output/arguments; minimal synthetic-case metadata only.
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
