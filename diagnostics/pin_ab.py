"""One authorized finite Windows experiment. Never retries or modifies source tests."""

import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

SOURCE_SHA = "6acdbeabd9fb54f33d27749bf0a2fd343c844b0d"
B_KEY = "cpython-3.11.16-windows-x86_64-none"
NODES = (
    "test_issue_and_read_pin_readonly_never_ready[False]",
    "test_old_pin_remains_valid_until_exact_expiry",
    "test_journal_intent_and_result_changes_preserve_pin_not_ready",
)


def select_distribution(rows):
    matches = [row for row in rows if row.get("key") == B_KEY]
    if len(matches) != 1:
        raise ValueError("Exact B distribution absent or ambiguous; no substitute authorized")
    url = urlparse(matches[0].get("url", ""))
    if url.scheme != "https" or not (
        (
            url.netloc == "releases.astral.sh"
            and url.path.startswith("/github/python-build-standalone/releases/download/")
        )
        or (
            url.netloc == "github.com"
            and url.path.startswith("/astral-sh/python-build-standalone/releases/download/")
        )
    ):
        raise ValueError("B distribution source is not the official Astral release route")
    return matches[0]


def cells():
    return [
        (rep, arm, node)
        for rep in (1, 2)
        for node in NODES
        for arm in (("A", "B") if rep == 1 else ("B", "A"))
    ]


def classify(output, code, timed_out):
    return {
        "outcome": (
            "outer_timeout_incomplete"
            if timed_out
            else "access_violation"
            if "Windows fatal exception: access violation" in output
            else "pass"
            if code == 0
            else "nonzero_exit"
        ),
        "diagnostic_fired": "Timeout (0:01:00)!" in output,
        "diagnostic_dump_review_required": "Timeout (0:01:00)!" in output,
        "access_violation": "Windows fatal exception: access violation" in output,
        "returncode": code,
    }


def remaining_seconds(deadline, now):
    return max(0.0, deadline - now)


def bounded_wait(process, command_deadline, clock=time.monotonic):
    """Reserve cleanup within the original deadline; own handle only, never bare PID."""
    try:
        return (
            process.wait(timeout=max(0.0, remaining_seconds(command_deadline, clock()) - 2)),
            False,
            None,
        )
    except subprocess.TimeoutExpired:
        try:
            process.kill()
            code = process.wait(timeout=remaining_seconds(command_deadline, clock()))
            return code, True, None
        except Exception as error:
            return None, True, f"{type(error).__name__}: {error}"


def main():
    if sys.platform != "win32":
        raise SystemExit("This experiment requires the authorized disposable Windows runner")
    source = Path(os.environ["GITHUB_WORKSPACE"]) / "source"
    out = Path(os.environ["GITHUB_WORKSPACE"]) / "diagnostic-evidence"
    out.mkdir()
    start = float(os.environ["DIAGNOSTIC_MONOTONIC_START"])
    # The 45-minute job hard cap includes all provisioning; reserve 2m for evidence upload.
    deadline = start + 43 * 60
    report = {
        "source_sha_required": SOURCE_SHA,
        "workflow_sha": os.environ["GITHUB_SHA"],
        "workflow_ref": os.environ["GITHUB_REF"],
        "run_id": os.environ["GITHUB_RUN_ID"],
        "image_os": os.environ.get("ImageOS"),
        "image_version": os.environ.get("ImageVersion"),
        "os": platform.platform(),
        "budget_seconds_including_setup": 45 * 60,
        "controller_cutoff_seconds_including_setup": 43 * 60,
        "distribution_confound": "A toolcache vs B Astral standalone; not pure patch isolation",
        "commands": [],
        "cells": [],
        "status": "provisioning",
    }

    def save():
        report["elapsed_seconds_including_setup"] = time.monotonic() - start
        (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    def run(label, command, *, cwd=source, env=None, limit=None, required=True):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("Session budget exhausted; no extra invocation")
        budget = min(remaining, limit) if limit else remaining
        record = {
            "label": label,
            "command": [str(x) for x in command],
            "budget_seconds": budget,
            "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        report["commands"].append(record)
        save()
        log = out / (label + ".log")
        command_deadline = min(deadline, time.monotonic() + budget)
        with log.open("wb") as stream:
            process = subprocess.Popen(
                record["command"], cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT
            )
            code, timed_out, cleanup_error = bounded_wait(process, command_deadline)
        record["cleanup_error"] = cleanup_error
        output = log.read_text(encoding="utf-8", errors="replace")
        record.update(classify(output, code, timed_out))
        save()
        print(json.dumps(record), flush=True)
        if required and (code != 0 or timed_out or cleanup_error):
            raise RuntimeError(f"Provisioning/preflight failed: {label}; retained original log")
        return output, record

    try:
        sha, _ = run("source-sha", ["git", "rev-parse", "HEAD"])
        if sha.strip() != SOURCE_SHA:
            raise RuntimeError("Wrong immutable source checkout")
        tree, _ = run("source-tree", ["git", "rev-parse", "HEAD^{tree}"])
        report["source_tree"] = tree.strip()
        report["lock_sha256"] = hashlib.sha256((source / "uv.lock").read_bytes()).hexdigest()
        uv_version, _ = run("uv-version", ["uv", "--version"])
        if uv_version.split()[:2] != ["uv", "0.12.19"]:
            raise RuntimeError("Wrong uv version; no upgrade/substitute authorized")
        catalog, _ = run(
            "B-official-catalog",
            [
                "uv",
                "python",
                "list",
                B_KEY,
                "--all-versions",
                "--only-downloads",
                "--output-format",
                "json",
            ],
        )
        report["B_catalog_entry"] = select_distribution(json.loads(catalog))
        save()  # Verify exact available official distribution before installing B.
        a = Path(os.environ["RUNNER_TOOL_CACHE"]) / "Python" / "3.11.9" / "x64" / "python.exe"
        if not a.is_file():
            raise RuntimeError("Required A toolcache interpreter absent; no substitute")
        run("B-install", ["uv", "python", "install", B_KEY])
        b_output, _ = run(
            "B-path", ["uv", "python", "find", "--managed-python", "--no-python-downloads", B_KEY]
        )
        b = Path(b_output.strip())
        probe = (
            "import sys,platform,struct,json,hashlib,pathlib; "
            "print(json.dumps(dict(version=sys.version,version_short=platform.python_version(),"
            "implementation=platform.python_implementation(),bits=struct.calcsize('P')*8,"
            "executable=sys.executable,build=platform.python_build(),"
            "executable_sha256=hashlib.sha256(pathlib.Path(sys.executable).read_bytes()).hexdigest())))"
        )
        envs = {}
        interpreters = {}
        for arm, interpreter, expected in (("A", a, "3.11.9"), ("B", b, "3.11.16")):
            info, _ = run(arm + "-interpreter", [interpreter, "-c", probe])
            metadata = json.loads(info)
            if (metadata["version_short"], metadata["bits"], metadata["implementation"]) != (
                expected,
                64,
                "CPython",
            ):
                raise RuntimeError("Wrong interpreter identity")
            report[arm + "_interpreter"] = metadata
            environment = os.environ.copy()
            environment["UV_PROJECT_ENVIRONMENT"] = str(
                Path(os.environ["RUNNER_TEMP"]) / ("pin-ab-venv-" + arm)
            )
            environment["UV_PYTHON"] = str(interpreter)
            environment["UV_PYTHON_DOWNLOADS"] = "never"
            run(
                arm + "-sync",
                [
                    "uv",
                    "sync",
                    "--extra",
                    "server",
                    "--extra",
                    "agent",
                    "--extra",
                    "dev",
                    "--frozen",
                ],
                env=environment,
            )
            executable = Path(environment["UV_PROJECT_ENVIRONMENT"]) / "Scripts" / "python.exe"
            inventory, _ = run(
                arm + "-packages",
                [
                    executable,
                    "-c",
                    "import importlib.metadata as m,json; "
                    "print(json.dumps(sorted((d.metadata['Name'].lower(),d.version) "
                    "for d in m.distributions())))",
                ],
                env=environment,
            )
            report[arm + "_packages"] = json.loads(inventory)
            interpreters[arm] = executable
            envs[arm] = environment
        if report["A_packages"] != report["B_packages"]:
            raise RuntimeError("Dependency inventories differ; no uncontrolled comparison")
        report["status"] = "running"
        save()
        for index, (rep, arm, node) in enumerate(cells(), 1):
            label = f"cell-{index:02}-{arm}-rep{rep}"
            # Each subprocess gets a unique private synthetic pytest temp root.
            temp = Path(os.environ["RUNNER_TEMP"]) / label
            _, record = run(
                label,
                [
                    interpreters[arm],
                    "-m",
                    "pytest",
                    "-vv",
                    "-o",
                    "faulthandler_timeout=60",
                    "--durations=20",
                    "--basetemp",
                    temp,
                    "tests/agent/test_enrollment_review_pin.py::" + node,
                ],
                env=envs[arm],
                limit=180,
                required=False,
            )
            report["cells"].append({"arm": arm, "repetition": rep, "node": node, **record})
            save()
            if record["cleanup_error"]:
                raise RuntimeError("Owned process cleanup uncertain; cell retained, no more cells")
        status, _ = run(
            "source-final-status", ["git", "status", "--porcelain", "--untracked-files=no"]
        )
        if (
            status.strip()
            or hashlib.sha256((source / "uv.lock").read_bytes()).hexdigest()
            != report["lock_sha256"]
        ):
            raise RuntimeError("Tracked source/lock changed unexpectedly")
        report["status"] = "finite_matrix_completed"
        save()
        return 1 if any(cell["outcome"] != "pass" for cell in report["cells"]) else 0
    except Exception as error:
        report["status"] = "blocked_or_incomplete"
        report["blocker"] = f"{type(error).__name__}: {error}"
        save()
        print(report["blocker"], flush=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
