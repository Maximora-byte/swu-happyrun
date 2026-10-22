"""Unactivated local-only normal-exit observation, using the current interpreter.

External invocation must use -I -S -B. A runtime flag check cannot undo startup
code already executed by an incorrectly launched interpreter. Dependencies are
fixed, byte-hash pinned, and executed from those same bytes without sys.path edits.
The entry's own hash is evidence, NOT self-authentication; external delivery must
bind the reviewed commit/tree/file hashes before any separately authorized run.

No project installation, CI identity, controller tests, AV, capture, or original
groups. Session still resumes at READY: all frame checks are retrospective. The
terminal is the harmless configuration probe marker, not the capture script.
Opaque sx remains format_unknown, never passed/execution_ready. Raw stays in the
exclusive private directory: no upload, expiry, deletion, or ACL modification.
300 seconds is a shared admission/check deadline, not a hard process wall cap;
the one 15-second Session retains its existing owned-process cleanup allowance.
Held directory handles do not freeze ACLs or all trusted-actor concurrent changes.
Console/stderr (including cancellation tracebacks) must stay private; share only
the fixed JSON whitelist, and only under a separate sharing authorization.
"""

import argparse
import hashlib
import json
import os
import struct
import subprocess
import sys
import time
import types
import uuid
from pathlib import Path

EXPECTED_DEPENDENCIES = {
    "issue110_capture": "f516ac8b6079ee8afd40d2a54f8c9ad08d722c8bc0e8d49a89151b7e29915a13",
    "issue110_debugger_config": "1a9e619f209218731030bc1b41dde1deee30b22ec2f6b52f3fa5a4af53f3b79a",
    "issue110_win32": "96f56feaeaace3061c7c66f1fa66b486d2f191b23bcabd7231b5b3765bf47096",
    "issue110_local_acl": "cd5c1984707611b221ee8f8d6163157367558aba5cdd273869bdf183fde0b05f",
}


def read_bounded(path, limit):
    stream = path.open("rb")
    completed = False
    try:
        data = stream.read(limit + 1)
        completed = True
        return data
    finally:
        try:
            stream.close()
        except Exception:
            if completed:
                raise


def hash_file(path):
    stream = Path(path).open("rb")
    completed = False
    try:
        result = hashlib.file_digest(stream, "sha256").hexdigest()
        completed = True
        return result
    finally:
        try:
            stream.close()
        except Exception:
            if completed:
                raise


def write_text(path, data, encoding):
    stream = path.open("x", encoding=encoding)
    completed = False
    try:
        stream.write(data)
        completed = True
    finally:
        try:
            stream.close()
        except Exception:
            if completed:
                raise


def write_json(path, value):
    write_text(path, json.dumps(value, indent=2, allow_nan=False) + "\n", "utf-8")


DEBUGGER_HASHES = {
    "cdb.exe": "31789c2c2645d5fdafb1621c47b0db8bc2fbca47b510a0e4e6fdede0479ce105",
    "dbgeng.dll": "1b81eabc0da30032cf93541789242c193cfe426a36f33f1fea452b600f1304c3",
    "dbghelp.dll": "140adb286a11fbdfb63b6d8dff30039c50ff9c88b6909be9ce8292680d5be2af",
}
PUBLIC_FIELDS = {
    "schema",
    "mode",
    "status",
    "passed",
    "execution_ready",
    "observation_timing",
    "format_basis",
    "sample_access",
    "setup_budget_seconds",
    "signature_budget_seconds",
    "session_budget_seconds",
    "stage",
    "interpreter",
    "code_identity",
    "signature_verified",
    "debugger_binaries",
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
    "blocker",
    "error_category",
}
OBSERVATION_FIELDS = (
    "configuration_readback",
    "script_load",
    "ready_identity",
    "stdout_seen",
    "stderr_seen",
    "unexpected_callback",
)


def failure(error):
    safe = {
        "setup_budget_exhausted",
        "interpreter_identity_unverified",
        "debugger_identity_unverified",
        "private_directory_unverified",
        "drive_mapping_unverified",
        "acl_unverified",
        "private_path_unverified",
        "repository_identity_unverified",
        "token_unverified",
        "windows_required",
        "launch_flags_unverified",
        "dependency_hash_mismatch",
        "dependency_state_unverified",
    }
    value = error.args[0] if type(error) is ValueError and len(error.args) == 1 else None
    return {
        "blocker": value
        if type(value) is str and value in safe
        else "prerequisite_or_harness_error",
        "error_category": (
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
        ),
    }


def load_dependencies():
    sources = {}
    for name, expected in EXPECTED_DEPENDENCIES.items():
        path = Path(__file__).with_name(name + ".py")
        raw = read_bounded(path, 1024 * 1024)
        if len(raw) > 1024 * 1024 or hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("dependency_hash_mismatch")
        sources[name] = (path, raw)
    if any(name in sys.modules for name in sources):
        raise ValueError("dependency_state_unverified")
    modules = {}
    for name, (path, raw) in sources.items():
        module = types.ModuleType(name)
        module.__file__ = str(path)
        sys.modules[name] = module
        exec(compile(raw, str(path), "exec"), module.__dict__)
        modules[name] = module
    return modules


def run_local(root, deadline):
    if not all(
        getattr(sys.flags, name, 0) == 1 for name in ("isolated", "no_site", "dont_write_bytecode")
    ):
        raise ValueError("launch_flags_unverified")
    if time.monotonic() >= deadline:
        raise ValueError("setup_budget_exhausted")
    modules = load_dependencies()
    capture, config, win32, acl = (modules[name] for name in EXPECTED_DEPENDENCIES)
    acl.components(root, mode="prepared_top_level")
    api = acl.Native()
    repository_handle = api.open_directory(Path(__file__).resolve().parents[2])
    completed = False
    try:
        attributes, repository_identity = api.information(repository_handle)
        if not attributes & 0x10 or attributes & 0x400:
            raise ValueError("repository_identity_unverified")
        completed = True
    finally:
        try:
            api.close(repository_handle)
        except Exception:
            if completed:
                raise
    report = {
        "schema": 1,
        "mode": "local_normal_exit_observation",
        "status": "blocked",
        "passed": False,
        "execution_ready": False,
        "observation_timing": "after_session_target_may_have_run",
        "format_basis": "exact_version_private_sample_unavailable",
        "sample_access": "private_in_place_only_no_upload",
        "setup_budget_seconds": 300,
        "signature_budget_seconds": 30,
        "session_budget_seconds": 15,
        "stage": "interpreter_identity",
        "interpreter": {},
        "code_identity": [],
        "signature_verified": None,
        "debugger_binaries": [],
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
        "blocker": None,
        "error_category": None,
    }
    with acl.PrivateDirectory(
        root, api, forbidden_identity=repository_identity, mode="prepared_top_level"
    ) as directory:
        private = directory.path
        completed = False
        try:
            report["interpreter"] = verify_runtime(api, capture, private)
            report["code_identity"] = [
                {"name": name + ".py", "sha256": value}
                for name, value in EXPECTED_DEPENDENCIES.items()
            ] + [{"name": "issue110_debugger_config_local.py", "sha256": hash_file(__file__)}]
            for name in ("temp", "profile", "profile/Roaming", "profile/Local", "symbols"):
                (private / name).mkdir()
            env = capture.child_environment(
                dict(os.environ, SWU_SECRET_CANARY="local_probe_canary"), sys.executable, private
            )
            report["stage"] = "installed_debugger"
            if time.monotonic() >= deadline:
                raise ValueError("setup_budget_exhausted")
            cdb, metadata = capture.installed_debugger(env, deadline, receipt={})
            expected = [
                {"name": name, "version": config.VERSION, "sha256": value}
                for name, value in DEBUGGER_HASHES.items()
            ]
            if metadata != expected:
                raise ValueError("debugger_identity_unverified")
            report.update(signature_verified=True, debugger_binaries=expected)
            nonce = uuid.uuid4().hex
            init, terminal, loader = (
                private / name for name in ("init.cdb", "terminal.cdb", "load.cdb")
            )
            for path, text in zip(
                (init, terminal, loader),
                config.debugger_scripts(nonce, terminal, loader),
                strict=True,
            ):
                write_text(path, text, "ascii")
            argv = capture.cdb_argv(
                cdb,
                init,
                private / "symbols",
                [sys.executable, "-I", "-S", "-B", "-c", config.TARGET],
            )
            directory.revalidate()
            start = time.monotonic()
            if deadline - start < 15:
                raise ValueError("setup_budget_exhausted")
            report.update(stage="session", session_invocation_attempted=True)
            raw_path = private / "raw.log"
            _, child, debugger, reason, cleanup, pid = win32.Session().run(
                argv,
                private,
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
                observed = config.observe(
                    read_bounded(raw_path, config.MAX_OUTPUT), nonce, config.VERSION, pid
                )
                report.update({key: observed[key] for key in OBSERVATION_FIELDS})
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
            completed = True
        except Exception as error:
            report.update(failure(error))
            raise
        finally:
            try:
                write_json(
                    private / "summary.json", {key: report[key] for key in sorted(PUBLIC_FIELDS)}
                )
            except Exception:
                if completed:
                    raise
    return report


def verify_runtime(api, capture, private):
    dll_handle = getattr(sys, "dllhandle", None)
    if (
        sys.implementation.name != "cpython"
        or sys.version_info[:2] < (3, 11)
        or struct.calcsize("P") != 8
        or type(dll_handle) is not int
        or not 0 < dll_handle < 1 << 64
        or not sys.executable
    ):
        raise ValueError("interpreter_identity_unverified")
    process_executable, dll = api.module_path(None), api.module_path(dll_handle)
    if api.file_identity(sys.executable) != api.file_identity(process_executable) or not all(
        capture.x64_pe(path) for path in (sys.executable, dll)
    ):
        raise ValueError("interpreter_identity_unverified")
    report = {
        "implementation": "cpython",
        "version": list(sys.version_info[:3]),
        "prefixes_differ": sys.prefix != sys.base_prefix,
        "venv_status": "unknown",
        "binaries": [
            {"name": name, "sha256": hash_file(path)}
            for name, path in (("python_executable", sys.executable), ("python_runtime_dll", dll))
        ],
    }
    write_json(
        private / "interpreter-private.json",
        {
            "sys_version": sys.version,
            "sys_executable": sys.executable,
            "process_executable": process_executable,
            "python_dll": dll,
            "sys_prefix": sys.prefix,
            "sys_base_prefix": sys.base_prefix,
        },
    )
    return report


def main():
    started = time.monotonic()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-root", required=True)
    args = parser.parse_args()
    try:
        report = run_local(args.private_root, started + 300)
        print(json.dumps({key: report[key] for key in sorted(PUBLIC_FIELDS)}, allow_nan=False))
    except Exception as error:
        print(
            json.dumps(
                {
                    "mode": "local_normal_exit_observation",
                    "status": "blocked",
                    "stage": "entry",
                    **failure(error),
                },
                allow_nan=False,
            )
        )
    return 1  # A format-unknown observation is never an acceptance result.


if __name__ == "__main__":
    raise SystemExit(main())
