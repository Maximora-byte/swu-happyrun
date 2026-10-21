"""Disabled, fixed normal-exit probe, not an exception-chain or capture verification.

Session resumes at READY; observations are checked only after it returns, when the
normal target may already have run. The terminal callback only emits a marker,
not the original capture body. No exact-version private sx sample is available:
configuration cannot be matched, and execution_ready is always false. Original
Only a 64 KiB raw.log prefix is read for this observation. The existing Session
16 MiB polling threshold is not a hard disk-write cap. Raw bytes stay private,
with no authorized retention channel; hosted-runner disposal loses them. Never
publish those bytes.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

import issue110_capture as capture

VERSION = "10.0.26100.8249"
MAX_OUTPUT = 65536
TARGET = (
    "import os,sys; assert 'SWU_SECRET_CANARY' not in os.environ; "
    "print('CONFIG_PID',os.getpid()); print('CONFIG_OUT'); "
    "print('CONFIG_ERR',file=sys.stderr); sys.exit(0)"
)
PUBLIC_FIELDS = {
    "schema",
    "source",
    "tree",
    "mode",
    "status",
    "stage",
    "execution_ready",
    "passed",
    "observation_timing",
    "format_basis",
    "sample_access",
    "setup_budget_seconds",
    "signature_budget_seconds",
    "controller_budget_seconds",
    "session_budget_seconds",
    "signature_verified",
    "controller_tests_passed",
    "session_invocation_attempted",
    "original_invocation_attempted",
    "original_group_started",
    "configuration_readback",
    "script_load",
    "target_exit",
    "owned_cleanup",
    "child_exit",
    "debugger_exit",
    "reason",
    "ready_identity",
    "stdout_seen",
    "stderr_seen",
    "unexpected_callback",
    "debugger_binaries",
    "blocker",
    "error_category",
}


def observe(raw, nonce, version, target_pid):
    """Frame structure only. Opaque sx content never establishes configuration."""
    result = dict(
        configuration_readback="not_observed",
        script_load="not_observed",
        ready_identity=None,
        stdout_seen=None,
        stderr_seen=None,
        unexpected_callback=None,
    )
    if not raw:
        return result
    result.update(configuration_readback="invalid", script_load="invalid")
    if len(raw) > MAX_OUTPUT or not re.fullmatch(r"[a-f0-9]{32}", nonce):
        return result
    try:
        text = raw.decode("utf-8", errors="strict").replace("\r\n", "\n")
    except UnicodeDecodeError:
        return result
    if not text.endswith("\n") or "\r" in text:
        return result
    lines = text.split("\n")[:-1]
    prefix = "SWU_" + nonce + "_"
    markers = [line for line in lines if line.startswith("SWU_")]
    allowed = {prefix + name for name in ("CFG_OPEN", "CFG_CLOSE", "LOAD", "UNEXPECTED_CALLBACK")}
    if any(
        line not in allowed and not re.fullmatch(prefix + r"READY [0-9a-fA-F]+", line)
        for line in markers
    ):
        return result
    opened = [i for i, line in enumerate(lines) if line == prefix + "CFG_OPEN"]
    closed = [i for i, line in enumerate(lines) if line == prefix + "CFG_CLOSE"]
    loaded = [i for i, line in enumerate(lines) if line == prefix + "LOAD"]
    ready = [(i, line) for i, line in enumerate(lines) if line.startswith(prefix + "READY ")]
    result["unexpected_callback"] = prefix + "UNEXPECTED_CALLBACK" in markers
    if len(ready) == 1:
        result["ready_identity"] = (
            type(target_pid) is int
            and target_pid > 0
            and int(ready[0][1].split()[1], 16) == target_pid
            and [line for line in lines if line.startswith("CONFIG_PID ")]
            == [f"CONFIG_PID {target_pid}"]
        )
        if len(opened) == len(closed) == 1 and opened[0] < closed[0] < ready[0][0]:
            result["configuration_readback"] = (
                "format_unknown" if version == VERSION else "version_mismatch"
            )
        if len(loaded) == 1 and loaded[0] < ready[0][0] and (not closed or max(closed) < loaded[0]):
            result["script_load"] = "observed"
    result["stdout_seen"] = lines.count("CONFIG_OUT") == 1
    result["stderr_seen"] = lines.count("CONFIG_ERR") == 1
    return result


def debugger_scripts(nonce, terminal_path, load_path):
    if not re.fullmatch(r"[a-f0-9]{32}", nonce) or any(
        not re.fullmatch(r"[A-Za-z]:\\[-A-Za-z0-9_.\\]+", str(path))
        for path in (terminal_path, load_path)
    ):
        raise ValueError("unsafe_debugger_script_path")
    prefix = "SWU_" + nonce + "_"
    init = "\n".join(
        [
            f'sxd -c2 "$$>a<{terminal_path}" av',
            f".echo {prefix}CFG_OPEN",
            "sx",
            f".echo {prefix}CFG_CLOSE",
            f"$$>a<{load_path}",
            f'.printf "{prefix}READY %x\\n", @$tpid',
            "",
        ]
    )
    return init, f".echo {prefix}UNEXPECTED_CALLBACK\n", f".echo {prefix}LOAD\n"


def controller_tests(env, root, deadline):
    tests = Path(__file__).resolve().parents[2] / "tests/delivery"
    config = root / "controller-pytest.ini"
    config.write_text("[pytest]\n", encoding="ascii")
    with (root / "controller-tests.log").open("wb") as output:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-c",
                str(config),
                "--confcutdir",
                str(tests),
                str(tests / "test_issue110_capture.py"),
                str(tests / "test_issue110_debugger_config.py"),
            ],
            cwd=root,
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
            timeout=capture.remaining(deadline, 30),
            check=False,
        )
    if result.returncode != 0:
        raise ValueError("controller_tests_failed")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subject", type=Path, required=True)
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--setup-started", type=float, required=True)
    args = parser.parse_args()
    report = {
        "schema": 1,
        "source": capture.SOURCE,
        "tree": capture.TREE,
        "mode": "debugger_configuration_only",
        "status": "blocked",
        "stage": "entry",
        "execution_ready": False,
        "passed": False,
        "observation_timing": "after_session_target_may_have_run",
        "format_basis": "exact_version_private_sample_unavailable",
        "sample_access": "no_authorized_retention_channel",
        "setup_budget_seconds": capture.SETUP_SECONDS,
        "signature_budget_seconds": 30,
        "controller_budget_seconds": 30,
        "session_budget_seconds": 15,
        "signature_verified": None,
        "controller_tests_passed": None,
        "session_invocation_attempted": False,
        "original_invocation_attempted": False,
        "original_group_started": False,
        "configuration_readback": "not_observed",
        "script_load": "not_observed",
        "target_exit": "unknown",
        "owned_cleanup": None,
        "child_exit": None,
        "debugger_exit": None,
        "reason": None,
        "ready_identity": None,
        "stdout_seen": None,
        "stderr_seen": None,
        "unexpected_callback": None,
        "debugger_binaries": [],
        "blocker": None,
        "error_category": None,
    }
    try:
        if (
            os.environ.get("GITHUB_REPOSITORY") != "Maximora-byte/swu-happyrun"
            or os.environ.get("GITHUB_RUN_ATTEMPT") != "1"
            or os.environ.get("GITHUB_REF") != "refs/heads/diagnostics/issue110-native-capture"
        ):
            raise ValueError("entry_scope_mismatch")
        elapsed = time.time() - args.setup_started
        if not 0 <= elapsed < capture.SETUP_SECONDS:
            raise ValueError("setup_budget_exhausted")
        deadline = time.monotonic() + capture.SETUP_SECONDS - elapsed
        args.private.mkdir(parents=True, exist_ok=False)
        for directory in ("temp", "profile/Roaming", "profile/Local", "symbols"):
            (args.private / directory).mkdir(parents=True, exist_ok=True)
        env = capture.child_environment(
            dict(os.environ, SWU_SECRET_CANARY="configuration_probe_canary"),
            sys.executable,
            args.private,
        )
        report["stage"] = "verify_subject"
        capture.verify_subject(args.subject, deadline)
        report["stage"] = "installed_debugger"
        cdb, metadata = capture.installed_debugger(env, deadline, receipt={})
        if [item.get("name") for item in metadata] != [
            "cdb.exe",
            "dbgeng.dll",
            "dbghelp.dll",
        ] or any(
            item.get("version") != VERSION
            or not re.fullmatch(r"[a-f0-9]{64}", item.get("sha256", ""))
            for item in metadata
        ):
            raise ValueError("debugger_version_unverified")
        report["debugger_binaries"] = [
            {key: item[key] for key in ("name", "version", "sha256")} for item in metadata
        ]
        report["signature_verified"] = True
        report["stage"] = "controller_tests"
        report["controller_tests_passed"] = controller_tests(env, args.private, deadline)
        nonce = uuid.uuid4().hex
        init, terminal, loader = (
            args.private / name for name in ("init.cdb", "terminal.cdb", "load.cdb")
        )
        for path, content in zip(
            (init, terminal, loader), debugger_scripts(nonce, terminal, loader), strict=True
        ):
            path.write_text(content, encoding="ascii")
        argv = capture.cdb_argv(cdb, init, args.private / "symbols", [sys.executable, "-c", TARGET])
        from issue110_win32 import Session

        start = time.monotonic()
        if deadline - start < 15:
            raise ValueError("setup_budget_exhausted")
        report.update(stage="session", session_invocation_attempted=True)
        raw_path = args.private / "raw.log"
        _, child, debugger, reason, cleanup, pid = Session().run(
            argv,
            args.private,
            env,
            raw_path,
            nonce,
            start + 15,
            capture_seconds=capture.CAPTURE_SECONDS,
            max_output=capture.MAX_OUTPUT,
        )
        report.update(
            child_exit=child if type(child) is int and 0 <= child <= 0xFFFFFFFF else None,
            debugger_exit=debugger
            if type(debugger) is int and 0 <= debugger <= 0xFFFFFFFF
            else None,
            reason=reason
            if reason
            in {
                "exited",
                "timeout",
                "output_limit",
                "capture_timeout",
                "api_error",
                "handshake_failed",
                "handshake_timeout",
                "exit_query_failed",
            }
            else "unknown",
            owned_cleanup=cleanup if type(cleanup) is bool else None,
        )
        report["stage"] = "observe"
        try:
            stream = raw_path.open("rb")
            read_completed = False
            try:
                raw = stream.read(MAX_OUTPUT + 1)
                read_completed = True
            finally:
                try:
                    stream.close()
                except Exception:
                    if read_completed:
                        raise
            report.update(observe(raw, nonce, VERSION, pid))
        except OSError:
            report["configuration_readback"] = "read_error"
        if report["child_exit"] is not None and report["debugger_exit"] is not None:
            report["target_exit"] = (
                "verified"
                if (
                    report["child_exit"] == report["debugger_exit"] == 0
                    and report["reason"] == "exited"
                    and report["ready_identity"] is True
                    and report["stdout_seen"] is True
                    and report["stderr_seen"] is True
                    and report["unexpected_callback"] is False
                )
                else "failed"
            )
        if time.monotonic() >= deadline:
            raise ValueError("setup_budget_exhausted")
        report.update(stage="complete", blocker="configuration_format_unavailable")
    except Exception as error:
        allowed = {
            "entry_scope_mismatch",
            "setup_budget_exhausted",
            "debugger_version_unverified",
            "controller_tests_failed",
        }
        report["blocker"] = (
            str(error)
            if type(error) is ValueError and str(error) in allowed
            else "harness_or_prerequisite_error"
        )
        report["error_category"] = (
            "subprocess_timeout"
            if isinstance(error, subprocess.TimeoutExpired)
            else "subprocess_failed"
            if isinstance(error, subprocess.CalledProcessError)
            else "invalid_json"
            if isinstance(error, json.JSONDecodeError)
            else "os_error"
            if isinstance(error, OSError)
            else "validation_error"
            if isinstance(error, ValueError)
            else "unexpected_error"
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({key: report[key] for key in sorted(PUBLIC_FIELDS)}, indent=2, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
