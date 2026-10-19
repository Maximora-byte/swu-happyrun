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
            str(source.with_name("ObservationReport.java")),
            str(source.with_name("ObservationPrivateFile.java")),
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
    # Exercise actual Java serializer -> actual strict Python decoder, not a Python-only fake.
    from types import SimpleNamespace

    from swu_happyrun.drivers.mumu.own_probe import OwnProbe

    report = subprocess.run(
        [
            java,
            "-cp",
            str(tmp_path),
            "org.happyrun.app.observation.OwnedObservationCheck",
            "synthetic-private-report",
        ],
        capture_output=True,
        timeout=10,
        check=True,
    ).stdout
    binding = SimpleNamespace(
        package="org.happyrun.app", boot_id="synthetic-boot", identity_digest="b" * 64
    )
    probe = OwnProbe(
        Path("unused"), binding, binding_check=lambda: None, authorization_check=lambda: None
    )
    samples = probe._decode(report, "a" * 32, "location", 10)
    assert samples[0].values == (1.25, 2.75)
    assert samples[0].elapsed_realtime_ns == 101
    assert samples[0].accuracy == 3.5


def test_private_bridge_is_wired_to_actual_own_observation():
    source = (
        ROOT
        / "android/app/src/androidTest/java/org/happyrun/app/observation"
        / "AndroidObservationTest.java"
    )
    text = source.read_text()
    assert "testPrivateReadbackWhenRequested" in text
    assert "AndroidObservation.start(" in text
    assert "ObservationPrivateFile.write(" in text
    assert "getFilesDir()" in text
    assert "/proc/sys/kernel/random/boot_id" in text
    assert "BuildConfig.BUILD_TYPE" in text
