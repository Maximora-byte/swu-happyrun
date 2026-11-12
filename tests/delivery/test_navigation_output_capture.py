"""Synthetic JVM subprocesses exercise capture without collecting host diagnostics."""

import json
import re
import shutil
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
        name = "javac" if "com.sun.tools.javac.Main" in command else command[-1]
        out = markers.get(name, "").encode("ascii")
        err = b""
        code = 0
        mode = {mode!r} if name == {stage!r} else "ok"
        if mode == "requires_utf8":
            required = ["-Dstdout.encoding=UTF-8", "-Dstderr.encoding=UTF-8"]
            boundary = command.index(
                "com.sun.tools.javac.Main" if name == "javac" else "-cp")
            if not all(option in command[1:boundary] for option in required):
                code = 7
            if name == "javac": err = "合成编译诊断".encode("utf-8")
        if mode == "crlf": out = out.replace(b"\\n", b"\\r\\n")
        if mode == "unicode_stdout": out += "合成输出".encode("utf-8")
        if mode == "unicode_stderr": err = "合成诊断".encode("utf-8")
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


@pytest.mark.parametrize("stage", ["javac", *MARKERS])
def test_each_jvm_requests_utf8_before_main_class(stage):
    result = synthetic_run("requires_utf8", stage)
    assert result.returncode == 0
    assert result.stdout.decode("ascii").replace("\r\n", "\n") == "".join(MARKERS.values())
    if stage == "javac":
        report = json.loads(result.stderr)
        assert report["reason"] == "compiler_diagnostics"
        assert report["stderr_bytes"] == len("合成编译诊断".encode())
    else:
        assert result.stderr == b""


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_valid_non_ascii_does_not_bypass_success_protocol(stream):
    result = synthetic_run("unicode_" + stream)
    assert result.returncode != 0
    report = json.loads(result.stderr)
    assert report["reason"] == "unexpected_" + stream
    assert "合成".encode() not in result.stdout + result.stderr


def require_standard_stream_overrides():
    version = subprocess.run(["java", "-version"], capture_output=True, timeout=10)
    assert version.returncode == 0, "Cannot determine installed JVM feature version"
    features = re.findall(
        rb'(?m)^(?:openjdk|java) version "([0-9]+)', version.stdout + version.stderr
    )
    assert len(features) == 1, "Unrecognized JVM version; do not assume stream-property support"
    if int(features[0]) < 19:
        pytest.skip("Standard UTF-8 stream overrides documented from JDK 19; navigation still runs")


@pytest.mark.parametrize("feature", [17, 18, 19, 25])
def test_standard_stream_probe_version_boundary(monkeypatch, feature):
    def version(command, **kwargs):
        assert command == ["java", "-version"]
        assert kwargs == {"capture_output": True, "timeout": 10}
        return subprocess.CompletedProcess(
            command, 0, b"", f'openjdk version "{feature}.0.1"'.encode()
        )

    monkeypatch.setattr(subprocess, "run", version)
    if feature < 19:
        with pytest.raises(pytest.skip.Exception, match="documented from JDK 19"):
            require_standard_stream_overrides()
    else:
        require_standard_stream_overrides()


@pytest.mark.parametrize(
    "returncode, output",
    [(1, b'java version "25"'), (0, b"unknown"), (0, b'java version "17"\njava version "25"')],
)
def test_standard_stream_probe_unknown_version_fails(monkeypatch, returncode, output):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], returncode, b"", output),
    )
    with pytest.raises(AssertionError):
        require_standard_stream_overrides()


@pytest.mark.skipif(shutil.which("java") is None, reason="Java compiler runtime unavailable")
@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_actual_jvm_non_ascii_stream_contract(tmp_path, stream):
    require_standard_stream_overrides()
    # ASCII Java source with Unicode escapes removes source-file charset ambiguity.
    # Exercise the actual production runner after its unchanged navigation checks.
    source = tmp_path / "StreamEncodingCheck.java"
    source.write_text(
        r"class StreamEncodingCheck { public static void main(String[] args) {"
        r'if (args[0].equals("stdout")) System.out.print("\u4e2d\u6587");'
        r'else System.err.print("\u4e2d\u6587"); }}',
        encoding="ascii",
    )
    launcher = f"""
import contextlib, io, runpy, sys
sys.argv = [{str(ROOT / "scripts/check_native_navigation.py")!r}]
namespace = runpy.run_path(sys.argv[0], run_name="__main__")
with contextlib.redirect_stdout(io.StringIO()) as captured:
    namespace["run_checked"](["java", {str(source)!r}, {stream!r}],
                             "NavigationAdapterCheck", {("中文" if stream == "stdout" else "")!r})
assert captured.getvalue() == "中文"
print("PROBE_OK")
"""
    result = subprocess.run([sys.executable, "-c", launcher], capture_output=True, timeout=60)
    output = result.stdout.decode("utf-8", errors="strict").replace("\r\n", "\n")
    if stream == "stdout":
        assert result.returncode == 0
        assert output == "".join(MARKERS.values()) + "PROBE_OK\n"
    else:
        assert result.returncode != 0
        report = json.loads(result.stderr.splitlines()[-1])
        assert report["reason"] == "unexpected_stderr"
        assert report["stderr_bytes"] == len("中文".encode())
        assert "中文".encode() not in result.stderr
