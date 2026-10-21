"""Bounded pytest execution and exact full-suite shard receipts, never crash recovery.

The runner explicitly loads this file as a plugin only in its direct pytest child.
The verifier uses the standard library and does not execute artifact-provided code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE_COUNTERS = ("passed", "skipped", "xfailed", "xpassed")
COUNTERS = NODE_COUNTERS + tuple(f"subtest_{key}" for key in NODE_COUNTERS)


def partition(nodes: list[str], index: int, count: int) -> list[str]:
    if (
        type(index) is not int
        or type(count) is not int
        or not 0 <= index < count <= len(nodes)
        or any(not isinstance(node, str) or not node for node in nodes)
        or len(set(nodes)) != len(nodes)
    ):
        raise ValueError("empty, duplicate or invalid full-suite partition")
    return nodes[index::count]


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"missing or invalid receipt: {path.name}") from error


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, timeout=15).strip()


def identity(expected_sha: str) -> dict:
    if git("rev-parse", "HEAD") != expected_sha or git("status", "--porcelain"):
        raise ValueError("the tested checkout must be clean at the exact expected SHA")
    return {
        "sha": expected_sha,
        "tree": git("rev-parse", "HEAD^{tree}"),
        "lock_sha256": hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest(),
        "os": platform.system(),
        "python_minor": f"{sys.version_info.major}.{sys.version_info.minor}",
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
        "attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "local"),
    }


def validate_identity(value: dict) -> None:
    required = (
        "sha",
        "tree",
        "lock_sha256",
        "os",
        "python_minor",
        "python",
        "implementation",
        "platform",
        "pytest",
        "run_id",
        "attempt",
    )
    if not isinstance(value, dict) or any(
        not isinstance(value.get(key), str) or not value[key].strip() for key in required
    ):
        raise ValueError("missing or mistyped receipt identity")
    for key, length in (("sha", 40), ("tree", 40), ("lock_sha256", 64)):
        if re.fullmatch(r"[0-9a-f]{" + str(length) + r"}", value[key]) is None:
            raise ValueError("invalid source identity hash")
    if (
        re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+[a-zA-Z0-9.+-]*", value["python"]) is None
        or value["python_minor"] != ".".join(value["python"].split(".")[:2])
        or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+[a-zA-Z0-9.+-]*", value["pytest"]) is None
    ):
        raise ValueError("invalid or inconsistent interpreter/pytest version")


def outcome_label(reports: list[dict]) -> str:
    if any(report["outcome"] == "skipped" for report in reports):
        return "xfailed" if any(report["wasxfail"] for report in reports) else "skipped"
    return "xpassed" if any(report["wasxfail"] for report in reports) else "passed"


def pytest_addoption(parser):
    group = parser.getgroup("full-suite CI receipt")
    group.addoption("--ci-receipt", required=True)
    group.addoption("--ci-index", type=int, required=True)
    group.addoption("--ci-count", type=int, required=True)


def pytest_configure(config):
    import pytest

    # Decorate only when pytest loads the plugin; the aggregate needs no pytest.
    pytest.hookimpl(hookwrapper=True, tryfirst=True)(Recorder.pytest_collection_modifyitems)
    config.pluginmanager.register(Recorder(config), "full-suite-ci-recorder")


class Recorder:
    def __init__(self, config):
        self.config = config
        self.output = Path(config.getoption("--ci-receipt"))
        self.manifest = read_json(self.output / "invocation.json")
        self.manifest["identity"]["pytest"] = __import__("pytest").__version__
        self.events = (self.output / "events.jsonl").open("x", encoding="utf-8")
        self.selected = []

    def emit(self, **event):
        self.events.write(json.dumps(event, sort_keys=True) + "\n")
        self.events.flush()

    def pytest_collection_modifyitems(self, session, config, items):
        original = [item.nodeid for item in items]
        yield
        # Other plugins may add skip markers, but cannot silently remove/reorder nodes.
        if original != [item.nodeid for item in items] or session.testsfailed:
            raise ValueError("collection changed or failed before the full-suite audit")
        if config.args != ["tests"] or any(
            getattr(config.option, option, None)
            for option in ("keyword", "markexpr", "ignore", "ignore_glob", "lf", "collectonly")
        ):
            raise ValueError("full-suite CI forbids collection selectors")
        index, count = config.getoption("--ci-index"), config.getoption("--ci-count")
        self.selected = partition(original, index, count)
        self.manifest.update(collected=original, selected=self.selected, index=index, count=count)
        write_json(self.output / "manifest.json", self.manifest)
        selected = set(self.selected)
        excluded = [item for item in items if item.nodeid not in selected]
        items[:] = [item for item in items if item.nodeid in selected]
        config.hook.pytest_deselected(items=excluded)

    def pytest_runtest_logstart(self, nodeid, location):
        self.emit(kind="start", nodeid=nodeid)

    def pytest_runtest_logreport(self, report):
        # pytest 9's built-in subtests emit extra call reports, not extra items.
        subtest = (
            type(report).__module__ == "_pytest.subtests"
            and type(report).__name__ == "SubtestReport"
        )
        self.emit(
            kind="subtest" if subtest else "report",
            nodeid=report.nodeid,
            when=report.when,
            outcome=report.outcome,
            wasxfail=hasattr(report, "wasxfail"),
        )

    def pytest_runtest_logfinish(self, nodeid, location):
        self.emit(kind="finish", nodeid=nodeid)

    def pytest_sessionfinish(self, session, exitstatus):
        write_json(
            self.output / "session.json",
            {
                "exitstatus": int(exitstatus),
                "testsfailed": session.testsfailed,
                "testscollected": session.testscollected,
            },
        )
        self.events.close()


def lifecycle_counts(output: Path, selected: list[str]) -> Counter:
    try:
        events = [json.loads(line) for line in (output / "events.jsonl").read_text().splitlines()]
    except (OSError, ValueError) as error:
        raise ValueError("missing or invalid node events") from error
    counts = Counter({key: 0 for key in COUNTERS})
    position, current, reports = 0, None, []
    for event in events:
        node, kind = event["nodeid"], event["kind"]
        if kind == "start":
            if current is not None or position >= len(selected) or node != selected[position]:
                raise ValueError("duplicate, unknown or out-of-order node start")
            current, reports = node, []
        elif current != node:
            raise ValueError("event without its selected node lifecycle")
        elif kind in {"report", "subtest"}:
            if event["outcome"] not in {"passed", "skipped"}:
                raise ValueError("failed node or subtest")
            if kind == "subtest":
                if event["when"] != "call" or [r["when"] for r in reports] != ["setup"]:
                    raise ValueError("subtest outside its call lifecycle")
                counts[f"subtest_{outcome_label([event])}"] += 1
            else:
                reports.append(event)
        elif kind == "finish":
            phases = [report["when"] for report in reports]
            expected = ["setup", "call", "teardown"]
            if reports and reports[0]["outcome"] == "skipped":
                expected = ["setup", "teardown"]
            if phases != expected:
                raise ValueError("missing or duplicate node phase")
            counts[outcome_label(reports)] += 1
            position, current = position + 1, None
        else:
            raise ValueError("unknown node event")
    if current is not None or position != len(selected):
        raise ValueError("incomplete node lifecycles")
    return counts


def verify_shard(output: Path) -> tuple[dict, Counter]:
    manifest = read_json(output / "manifest.json")
    if manifest.get("schema") != 1:
        raise ValueError("unknown receipt schema")
    validate_identity(manifest.get("identity"))
    selected = partition(manifest["collected"], manifest["index"], manifest["count"])
    if manifest["selected"] != selected:
        raise ValueError("selection does not match the full collection partition")
    process, session = read_json(output / "process.json"), read_json(output / "session.json")
    if process["returncode"] != 0 or process["timed_out"] or not process["identity_unchanged"]:
        raise ValueError("pytest crashed, timed out, failed or changed the checkout")
    if (
        session["exitstatus"] != 0
        or session["testsfailed"] != 0
        or session["testscollected"] != len(selected)
    ):
        raise ValueError("pytest session is not successfully complete")
    return manifest, lifecycle_counts(output, selected)


def verify_matrix(
    root: Path,
    *,
    expected_sha: str,
    expected_tree: str,
    expected_lock_sha256: str,
    run_id: str,
    attempt: str,
    expected: list[tuple[str, str, int]],
    job_results: list[str],
) -> dict:
    if (
        not expected
        or len({(os_name, python) for os_name, python, _ in expected}) != len(expected)
        or any(type(count) is not int or count < 1 for _, _, count in expected)
    ):
        raise ValueError("invalid expected matrix")
    wanted = {
        (os_name, python, index): count
        for os_name, python, count in expected
        for index in range(count)
    }
    found, groups = {}, {}
    totals = Counter({key: 0 for key in COUNTERS})
    for path in sorted(root.rglob("manifest.json")):
        manifest, counts = verify_shard(path.parent)
        identity = manifest["identity"]
        key = (identity["os"], identity["python_minor"], manifest["index"])
        if key not in wanted or key in found or manifest["count"] != wanted[key]:
            raise ValueError("unexpected, duplicate or wrong-sized shard")
        if (
            identity["sha"],
            identity["tree"],
            identity["lock_sha256"],
            identity["run_id"],
            identity["attempt"],
        ) != (expected_sha, expected_tree, expected_lock_sha256, run_id, attempt):
            raise ValueError("receipt is from a different candidate or run attempt")
        group = key[:2]
        # Runner image release may vary across machines; interpreter and source may not.
        stable_identity = {k: v for k, v in identity.items() if k != "platform"}
        signature = (stable_identity, manifest["collected"])
        if group in groups and groups[group] != signature:
            raise ValueError("shards disagree about source, interpreter or full collection")
        groups[group] = signature
        found[key] = manifest["selected"]
        totals.update(counts)
    if set(found) != set(wanted):
        raise ValueError("missing required matrix shards")
    for group, (_, collected) in groups.items():
        union = [node for key, nodes in found.items() if key[:2] == group for node in nodes]
        if Counter(union) != Counter(collected):
            raise ValueError("full collection was not covered exactly once")
    if not job_results or any(result != "success" for result in job_results):
        raise ValueError("required matrix jobs did not all succeed")
    return dict(totals)


def run_suite(output: Path, index: int, count: int, budget: int, expected_sha: str) -> int:
    if not 0 < budget <= 1500:
        raise ValueError("pytest budget must be positive and at most 1500 seconds")
    if any(os.environ.get(name) for name in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS")):
        raise ValueError("PYTEST_ADDOPTS/PYTEST_PLUGINS must not hide selection or affect children")
    initial = identity(expected_sha)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "invocation.json", {"schema": 1, "identity": initial})
    command = [
        sys.executable,
        "-m",
        "pytest",
        "tests",
        "-vv",
        "-o",
        "faulthandler_timeout=60",
        "--durations=20",
        "-p",
        "scripts.ci_python_suite",
        "--ci-receipt",
        str(output),
        "--ci-index",
        str(index),
        "--ci-count",
        str(count),
        "--junitxml",
        str(output / "junit.xml"),
    ]
    started, timed_out = time.monotonic(), False
    child = subprocess.Popen(command, cwd=ROOT)
    try:
        child.wait(timeout=budget)
    except subprocess.TimeoutExpired:
        timed_out = True
        child.kill()
        child.wait(timeout=15)
    try:
        unchanged = identity(expected_sha) == initial
    except (ValueError, subprocess.SubprocessError):
        unchanged = False
    write_json(
        output / "process.json",
        {
            "returncode": child.returncode,
            "timed_out": timed_out,
            "elapsed_seconds": time.monotonic() - started,
            "budget_seconds": budget,
            "identity_unchanged": unchanged,
        },
    )
    _, counts = verify_shard(output)
    print(json.dumps(dict(counts), sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--index", type=int, required=True)
    run.add_argument("--count", type=int, required=True)
    run.add_argument("--budget-seconds", type=int, required=True)
    run.add_argument("--expected-sha", required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--root", type=Path, required=True)
    verify.add_argument("--expected-sha", required=True)
    verify.add_argument("--run-id", required=True)
    verify.add_argument("--attempt", required=True)
    verify.add_argument("--expect", action="append", required=True, help="OS:Python:shard-count")
    verify.add_argument("--job-result", action="append", required=True)
    args = parser.parse_args()
    try:
        if args.command == "run":
            return run_suite(
                args.output.resolve(),
                args.index,
                args.count,
                args.budget_seconds,
                args.expected_sha,
            )
        expected = [
            (os_name, python, int(count))
            for os_name, python, count in (value.split(":") for value in args.expect)
        ]
        source = identity(args.expected_sha)
        counts = verify_matrix(
            args.root,
            expected_sha=args.expected_sha,
            expected_tree=source["tree"],
            expected_lock_sha256=source["lock_sha256"],
            run_id=args.run_id,
            attempt=args.attempt,
            expected=expected,
            job_results=args.job_result,
        )
        print(json.dumps(counts, sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f"Full-suite receipt rejected: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
