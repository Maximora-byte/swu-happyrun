"""Exercise real desktop JavaScript across disconnected workspace renders."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_desktop_freshness_boundaries():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the desktop JavaScript regression")
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [node, "--test", "tests/desktop/test_desktop_freshness.cjs"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
