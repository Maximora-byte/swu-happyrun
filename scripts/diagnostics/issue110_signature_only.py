"""Verify installed debugger signatures only. Never execute CDB or any test group."""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import issue110_capture as capture


def signature_only():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subject", type=Path, required=True)
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--setup-started", type=float, required=True)
    args = parser.parse_args()
    report = {
        "schema": 1,
        "source": capture.SOURCE,
        "tree": capture.TREE,
        "mode": "signature_only",
        "status": "prerequisites_missing",
        "stage": "entry",
        "setup_budget_seconds": capture.SETUP_SECONDS,
        "signature_budget_seconds": 30,
        "debugger_invocation_attempted": False,
        "original_invocation_attempted": False,
        "original_group_started": False,
        "root_cause_established": False,
    }
    try:
        if (
            os.environ.get("GITHUB_REPOSITORY") != "Maximora-byte/swu-happyrun"
            or os.environ.get("GITHUB_RUN_ATTEMPT") != "1"
            or os.environ.get("GITHUB_REF") != "refs/heads/diagnostics/issue110-native-capture"
        ):
            raise ValueError("entry_scope_mismatch")
        elapsed = time.time() - args.setup_started
        if not 0 <= elapsed < capture.SETUP_SECONDS:
            raise ValueError("setup_budget_exhausted")
        deadline = time.monotonic() + capture.SETUP_SECONDS - elapsed
        args.private.mkdir(parents=True, exist_ok=False)
        for directory in ("temp", "profile/Roaming", "profile/Local"):
            (args.private / directory).mkdir(parents=True, exist_ok=True)
        env = capture.child_environment(os.environ, sys.executable, args.private)
        report["stage"] = "verify_subject"
        report["interpreter"] = capture.verify_subject(args.subject, deadline)
        report["stage"] = "installed_debugger"
        report["debugger_check"] = {}
        _, report["debugger_binaries"] = capture.installed_debugger(
            env, deadline, receipt=report["debugger_check"]
        )
        if time.monotonic() >= deadline:
            raise ValueError("setup_budget_exhausted")
        report.update(stage="complete", status="signature_verified")
    except Exception as error:
        # Never publish raw subprocess output, exception text, paths or certificate subjects.
        allowed = {
            "entry_scope_mismatch",
            "setup_budget_exhausted",
            "installed_x64_debugger_missing",
            "debugger_signature_unverified",
            "debugger_version_unverified",
            "subject_mismatch",
            "interpreter_mismatch",
            "dependency_mismatch",
            "python_binary_unverified",
        }
        report["blocker"] = (
            str(error)
            if type(error) is ValueError and str(error) in allowed
            else "harness_or_prerequisite_error"
        )
        report["error_category"] = (
            "subprocess_timeout"
            if isinstance(error, subprocess.TimeoutExpired)
            else "subprocess_failed"
            if isinstance(error, subprocess.CalledProcessError)
            else "invalid_json"
            if isinstance(error, json.JSONDecodeError)
            else "os_error"
            if isinstance(error, OSError)
            else "validation_error"
            if isinstance(error, ValueError)
            else "unexpected_error"
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report["status"] == "signature_verified" else 1


if __name__ == "__main__":
    raise SystemExit(signature_only())
