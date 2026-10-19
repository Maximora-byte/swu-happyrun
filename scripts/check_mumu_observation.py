"""Explicit isolated-instance instrumentation observation; no XML, input or reset commands."""

import argparse
import json
import re
import subprocess
import uuid
from pathlib import Path


def accepted(text: str, code: int, observation: str, display: int, task: int, signature: str):
    if code != 0 or re.search(
        r"FAILURES!!!|INSTRUMENTATION_FAILED|INSTRUMENTATION_ABORTED|shortMsg=|"
        r"INSTRUMENTATION_STATUS_CODE: -[123]",
        text,
    ):
        return False
    if "OK (1 test)" not in text or "INSTRUMENTATION_CODE: -1" not in text:
        return False
    expected = {
        "state": "observed",
        "observation_id": observation,
        "display_id": str(display),
        "task_id": str(task),
        "signature_sha256": signature,
        "writes": "0",
        "activity": "org.happyrun.app.MainActivity",
        "visible_controls": "app_scroll,framework_probe,wizard_refresh",
    }
    # Require the bound values in one completed status bundle, never splice old/partial bundles.
    bundles = []
    current = {}
    for line in text.splitlines():
        if line.startswith("INSTRUMENTATION_STATUS: ") and "=" in line:
            key, value = line.removeprefix("INSTRUMENTATION_STATUS: ").split("=", 1)
            if key in current:
                return False
            current[key] = value.strip()
        elif line.startswith("INSTRUMENTATION_STATUS_CODE: "):
            if line.strip() == "INSTRUMENTATION_STATUS_CODE: 0" and current.get("state"):
                bundles.append(current)
            current = {}
    return len(bundles) == 1 and all(bundles[0].get(k) == v for k, v in expected.items())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--display", required=True, type=int)
    parser.add_argument("--task", required=True, type=int)
    parser.add_argument("--signature-sha256", required=True)
    parser.add_argument("--isolated-no-personal-data", required=True, action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.display < 0 or args.task < 0 or not re.fullmatch("[0-9a-f]{64}", args.signature_sha256):
        parser.error("Require observed nonnegative task/display and lowercase signing SHA256")
    observation = str(uuid.uuid4())
    command = [
        "adb",
        "-s",
        args.serial,
        "shell",
        "am",
        "instrument",
        "-w",
        "-r",
        "-e",
        "class",
        "org.happyrun.app.DisplayObservationTest#testObserveOwnActivity",
        "-e",
        "isolated",
        "yes",
        "-e",
        "observationId",
        observation,
        "-e",
        "displayId",
        str(args.display),
        "-e",
        "taskId",
        str(args.task),
        "-e",
        "signatureSha256",
        args.signature_sha256,
        "org.happyrun.app.test/android.test.InstrumentationTestRunner",
    ]
    reason, success = "observation_rejected", False
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        success = accepted(
            result.stdout,
            result.returncode,
            observation,
            args.display,
            args.task,
            args.signature_sha256,
        )
    except subprocess.TimeoutExpired:
        reason = "host_timeout_device_runner_may_still_be_active"
    except OSError:
        reason = "adb_unavailable"
    report = {
        "observation_id": observation,
        "display_id": args.display,
        "task_id": args.task,
        "signature_sha256": args.signature_sha256,
        "result": "observed" if success else "failed",
        "writes": 0,
        "writes_scope": "test-issued simulation/control/input actions only",
        "reason": None if success else reason,
        "record_verified": False,
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
