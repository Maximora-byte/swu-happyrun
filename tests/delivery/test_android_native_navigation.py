"""Run controlled Java regressions in the existing Python delivery test suite."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("java") is None, reason="Java compiler runtime unavailable")
def test_native_navigation_shared_budget_and_actual_adapter():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, str(root / "scripts/check_native_navigation.py")],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert "RED reproduced: requested 5000 ms budget failed at 1000 ms" in result.stdout
    assert "PASS 5 shared-deadline checks" in result.stdout
    assert "PASS 8 extracted-adapter checks (controlled ports, not ART)" in result.stdout
