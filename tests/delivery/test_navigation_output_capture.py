"""Synthetic JVM subprocesses exercise capture without collecting host diagnostics."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MARKERS = {
    "LegacyDeadlineRepro": (
        "RED reproduced: requested 5000 ms budget failed at 1000 ms "
        "before target appearance at 1500 ms\n"
    ),
    "org.happyrun.app.NativeViewDeadlineCheck": "PASS 5 shared-deadline checks\n",
    "NavigationAdapterCheck": "PASS 8 extracted-adapter checks (controlled ports, not ART)\n",
}


def synthetic_run(mode, stage="NavigationAdapterCheck", private_dir=None):
    # Replace only the JVM executable, preserving real pipes, process completion,
    # and timeout handling in the production script. Works on Windows and Unix.
    extra_args = ["--private-output-dir", str(private_dir)] if private_dir is not None else []
    launcher = f"""
import runpy, subprocess, sys
original = subprocess.run
markers = {MARKERS!r}
def run(command, **kwargs):
    if command[0] == "java":
        name = "javac" if command[1] == "com.sun.tools.javac.Main" else command[-1]
        out = markers.get(name, "").encode("ascii")
        err = b""
        code = 0
        mode = {mode!r} if name == {stage!r} else "ok"
        if mode == "crlf": out = out.replace(b"\\n", b"\\r\\n")
        if mode == "invalid_stderr": err = b"\\xbePRIVATE_SYNTHETIC"
        if mode == "invalid_stdout": out += b"\\xbePRIVATE_SYNTHETIC"
        if mode == "nonzero": code = 7; err = b"PRIVATE_SYNTHETIC"
        if mode == "unexpected": out += b"PRIVATE_SYNTHETIC"
        if mode == "stderr": err = b"PRIVATE_SYNTHETIC"
        if mode == "timeout":
            kwargs["timeout"] = 0.2
            program = "import os,time; os.write(2,b'PRIVATE_SYNTHETIC'); time.sleep(10)"
        else:
            program = ("import os,sys; os.write(1,"+repr(out)+"); os.write(2,"
                       +repr(err)+"); sys.exit("+str(code)+")")
        command = [sys.executable, "-c", program]
        if mode == "launch_error": command = ["synthetic-no-such-navigation-tool-59"]
    return original(command, **kwargs)
subprocess.run = run
sys.path.insert(0, {str(ROOT / "scripts")!r})
sys.argv = [{str(ROOT / "scripts/check_native_navigation.py")!r}] + {extra_args!r}
runpy.run_path(sys.argv[0], run_name="__main__")
"""
    return subprocess.run([sys.executable, "-c", launcher], capture_output=True, timeout=15)


@pytest.mark.parametrize("stage", ["javac", *MARKERS])
@pytest.mark.parametrize(
    "mode", ["invalid_stderr", "invalid_stdout", "nonzero", "unexpected", "stderr", "timeout"]
)
def test_command_failures_are_rejected_and_redacted(mode, stage):
    result = synthetic_run(mode, stage)
    if mode == "stderr" and stage == "javac":
        assert result.returncode == 0
        assert json.loads(result.stderr)["reason"] == "compiler_diagnostics"
        assert b"PRIVATE_SYNTHETIC" not in result.stdout + result.stderr
        return
    assert result.returncode != 0
    assert b"PRIVATE_SYNTHETIC" not in result.stdout + result.stderr
    report = json.loads(result.stderr)
    assert report["stage"] == stage
    assert (
        report["reason"]
        == {
            "invalid_stderr": "invalid_utf8",
            "invalid_stdout": "invalid_utf8",
            "nonzero": "nonzero_exit",
            "unexpected": "unexpected_stdout",
            "stderr": "unexpected_stderr",
            "timeout": "timeout",
        }[mode]
    )
    if mode.startswith("invalid_"):
        assert report["stream"] == mode.removeprefix("invalid_")


def test_success_requires_exact_outputs():
    result = synthetic_run("ok")
    assert result.returncode == 0
    assert result.stdout.decode("ascii").replace("\r\n", "\n") == "".join(MARKERS.values())
    assert result.stderr == b""


@pytest.mark.parametrize("stage", ["javac", *MARKERS])
def test_launch_failure_is_redacted(stage):
    result = synthetic_run("launch_error", stage)
    assert result.returncode != 0
    assert json.loads(result.stderr)["reason"] == "launch_error"
    assert b"synthetic-no-such" not in result.stderr


def test_windows_line_endings_are_accepted():
    result = synthetic_run("crlf")
    assert result.returncode == 0
    assert result.stdout.decode("ascii").replace("\r\n", "\n") == "".join(MARKERS.values())


def test_raw_failure_bytes_require_explicit_new_private_directory(tmp_path):
    directory = tmp_path / "private"
    result = synthetic_run("invalid_stderr", private_dir=directory)
    assert result.returncode != 0
    assert json.loads(result.stderr)["private_evidence"] == "saved_locally"
    assert (
        directory / "NavigationAdapterCheck.stderr.bin"
    ).read_bytes() == b"\xbePRIVATE_SYNTHETIC"
    assert b"PRIVATE_SYNTHETIC" not in result.stdout + result.stderr
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    result = synthetic_run("invalid_stdout", private_dir=directory)
    assert result.returncode != 0
    assert json.loads(result.stderr)["reason"] == "private_directory_unavailable"
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == before
