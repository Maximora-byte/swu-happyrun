"""Portable fake-engine checks only; never load DbgEng or start a target."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HEADER = ROOT / "scripts/diagnostics/issue110_filter_probe_core.hpp"
HARNESS = ROOT / "tests/delivery/issue110_filter_probe_core_test.cpp"


def test_portable_filter_probe_core(tmp_path):
    assert HEADER.is_file(), "missing bounded no-target filter probe core"
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("portable C++17 compiler is not installed; native DbgEng is not tested")
    binary = tmp_path / "filter_probe_core_test"
    compiled = subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            "-I",
            str(ROOT),
            str(HARNESS),
            "-o",
            str(binary),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    ran = subprocess.run([str(binary)], capture_output=True, text=True, timeout=15, check=False)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert "portable fake-engine checks passed" in ran.stdout
