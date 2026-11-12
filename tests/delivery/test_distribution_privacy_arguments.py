"""Reject ignored/missing privacy-check inputs instead of inspecting unrelated dist files."""

import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts/check_distribution_privacy.py"


@pytest.fixture
def distributions(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    wheel, source = dist / "candidate.whl", dist / "candidate.tar.gz"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("safe.py", "pass\n")
    with tarfile.open(source, "w:gz") as archive:
        archive.add(wheel, arcname="source/safe.whl")
    return tmp_path, wheel, source


@pytest.mark.parametrize("invalid", ["dist", "missing.whl", "unknown.txt"])
def test_explicit_invalid_input_is_never_ignored(distributions, invalid):
    cwd, _, _ = distributions
    result = subprocess.run([sys.executable, str(SCRIPT), invalid], cwd=cwd, capture_output=True)
    assert result.returncode != 0


def test_empty_default_set_fails(tmp_path):
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=tmp_path, capture_output=True)
    assert result.returncode != 0


def test_explicit_verified_pair_and_default_pair_pass(distributions):
    cwd, wheel, source = distributions
    for args in ([], [str(wheel), str(source)]):
        result = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd, capture_output=True)
        assert result.returncode == 0, result.stderr
