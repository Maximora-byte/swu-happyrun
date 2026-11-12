"""Exercise the real panel JavaScript against deterministic DOM/HTTP boundaries."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_mumu_panel_boundaries():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the panel JavaScript regression")
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [node, "--test", "tests/desktop/test_mumu_panel.cjs"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
