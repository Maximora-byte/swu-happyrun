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


PHASES = frozenset(
    {
        "arguments",
        "package",
        "signing_info",
        "signature",
        "display",
        "tasks",
        "task_id",
        "base_activity",
        "launch",
        "activity",
        "viewport",
        "binding",
        "success",
    }
)
METRICS = frozenset(
    {
        "observed_task_count",
        "observed_task_id",
        "observed_display_id",
        "signer_count",
        "window_visible",
        "controls_visible",
        "signature_matches",
        "installed_version_code",
    }
)
ASSERTIONS = {
    "Requires a disposable instance with no personal data": "isolation_missing",
    "API29+ is required for explicit task/display binding": "api_unsupported",
    "Use a fresh UUID for each invocation": "observation_id_invalid",
    "Installed signing identity must match the verified paired artifact": "signature_mismatch",
    "No such display": "display_missing",
    "Do not guess among same-package tasks": "task_count_mismatch",
    "Task must be selected by independent observation": "task_id_mismatch",
    "Own Activity not observed within the bounded window": "activity_timeout",
    "Observation rejected; writes=0": "binding_or_visibility_rejected",
}


def diagnostics(text: str, code: int):
    """Never persist raw stdout, stack traces, exception messages or arbitrary string values."""
    result = {
        "adb_exit": code if type(code) is int and -255 <= code <= 255 else None,
        "last_phase": "unknown",
        "assertion_code": "unclassified",
        "status_codes": [],
        "ok_one_test": "OK (1 test)" in text,
        "instrumentation_finished": "INSTRUMENTATION_CODE: -1" in text,
        "runner_marker": "none",
        "exception_kind": "unknown",
    }
    for marker, category in (
        ("INSTRUMENTATION_FAILED", "failed"),
        ("INSTRUMENTATION_ABORTED", "aborted"),
        ("shortMsg=", "short_message"),
        ("FAILURES!!!", "test_failures"),
        ("OK (1 test)", "one_test_success"),
    ):
        if marker in text:
            result["runner_marker"] = category
            break
    for kind in (
        "AssertionFailedError",
        "SecurityException",
        "IllegalArgumentException",
        "NullPointerException",
        "ClassNotFoundException",
    ):
        if re.search(r"(?:junit\.framework|java\.lang)\." + kind + r"(?=[:\s])", text):
            result["exception_kind"] = kind
            break
    for line in text.splitlines():
        if line.startswith("INSTRUMENTATION_STATUS: ") and "=" in line:
            key, value = line.removeprefix("INSTRUMENTATION_STATUS: ").split("=", 1)
            value = value.strip()
            if key == "observation_phase" and value in PHASES:
                result["last_phase"] = value
            elif key == "installed_signature_sha256" and re.fullmatch("[0-9a-f]{64}", value):
                result[key] = value
            elif key == "installed_package" and value == "org.happyrun.app":
                result[key] = value
            elif key in METRICS and re.fullmatch(r"-?\d{1,10}", value):
                number = int(value)
                if -1 <= number <= 2147483647:
                    result[key] = number
        elif line.startswith("INSTRUMENTATION_STATUS_CODE: "):
            value = line.removeprefix("INSTRUMENTATION_STATUS_CODE: ").strip()
            if value in {"-3", "-2", "-1", "0", "1", "2"}:
                result["status_codes"] = (result["status_codes"] + [int(value)])[-16:]
        # Only classify our own fixed assertion messages; never return the matched line.
        if "AssertionFailedError:" in line:
            for message, reason in ASSERTIONS.items():
                if "AssertionFailedError: " + message in line:
                    result["assertion_code"] = reason
                    break
    return result


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
    diagnostic = diagnostics("", 0)
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        diagnostic = diagnostics(result.stdout + "\n" + result.stderr, result.returncode)
        success = accepted(
            result.stdout,
            result.returncode,
            observation,
            args.display,
            args.task,
            args.signature_sha256,
        )
    except subprocess.TimeoutExpired as failure:
        pieces = []
        for partial in (failure.stdout, failure.stderr):
            if isinstance(partial, bytes):
                partial = partial.decode(errors="replace")
            pieces.append(partial or "")
        diagnostic = diagnostics("\n".join(pieces), -1)
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
        "diagnostics": diagnostic,
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
