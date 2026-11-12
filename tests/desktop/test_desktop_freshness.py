"""Exercise real desktop JavaScript across disconnected workspace renders."""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest


def test_desktop_freshness_boundaries():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the desktop JavaScript regression")
    root = Path(__file__).resolve().parents[2]
    run_node_cases(node, root / "tests/desktop/test_desktop_freshness.cjs", root)


def run_node_cases(node, script, root, *, timeout=20):
    # node:test also runs when invoked directly. Avoid an unnecessary test-runner
    # child and pipe-reader EOF waits; the process deadline remains 20 seconds.
    timed_out = False
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        try:
            result = subprocess.run(
                [node, "--test-reporter=tap", str(script)],
                cwd=root,
                stdout=stdout,
                stderr=stderr,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            timed_out = True
        stdout.seek(0)
        stderr.seek(0)
        output = stdout.read().decode("utf-8", errors="replace").replace("\r\n", "\n")
        errors = stderr.read().decode("utf-8", errors="replace")
    diagnostics = output + "\n" + errors
    assert not timed_out, f"Node freshness deadline ({timeout}s) exceeded:\n{diagnostics}"
    assert result.returncode == 0, f"Node freshness exit {result.returncode}:\n{diagnostics}"
    # Exit zero alone can mean no tests ran. Require the entire seven-case receipt,
    # including no skipped, cancelled or TODO cases, not merely a success string.
    expected = {
        "tests": 7,
        "suites": 0,
        "pass": 7,
        "fail": 0,
        "cancelled": 0,
        "skipped": 0,
        "todo": 0,
    }
    valid = re.findall(r"^1\.\.(\d+)$", output, re.MULTILINE) == ["7"] and all(
        re.findall(rf"^# {name} (\d+)$", output, re.MULTILINE) == [str(count)]
        for name, count in expected.items()
    )
    assert valid, f"Incomplete Node freshness receipt:\n{diagnostics}"
