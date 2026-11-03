"""Real JVM callback/lifecycle checks; not Android runtime or injection evidence."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_owned_observation_callbacks(tmp_path):
    java = shutil.which("java")
    if java is None:
        pytest.skip("Java unavailable")
    source = (
        ROOT
        / "android/app/src/androidTest/java/org/happyrun/app/observation/ObservationWindow.java"
    )
    assert source.is_file(), "bounded own-probe observer is not implemented"
    result = subprocess.run(
        [
            java,
            "com.sun.tools.javac.Main",
            "-d",
            str(tmp_path),
            str(source),
            str(source.with_name("ObservationSession.java")),
            str(ROOT / "tests/java/OwnedObservationCheck.java"),
        ],
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run(
        [java, "-cp", str(tmp_path), "org.happyrun.app.observation.OwnedObservationCheck"],
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert b"owned-observation: passed" in result.stdout
