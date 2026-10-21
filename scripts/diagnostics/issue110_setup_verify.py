"""One fixed Windows setup-only verification; never launches the native controller."""

import argparse
import hashlib
import json
import os
import struct
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

SOURCE = "6a0dac84bf66125c7e2bd506bb0d8c988b1dcc34"
TREE = "09b5064a5e30495f7ced68b84fe453bd5d0413ce"


def clean_environment(source):
    blocked = set(
        (
            "UV_PYTHON_INSTALL_MIRROR UV_PYTHON_DOWNLOADS_JSON_URL UV_ASTRAL_MIRROR_URL "
            "UV_PYTHON_CPYTHON_BUILD UV_CONFIG_FILE UV_WORKING_DIR UV_PROJECT"
        ).split()
    )
    if any(value and key.upper() in blocked for key, value in source.items()):
        raise ValueError("setup_source_override")
    keep = set(
        (
            "PATH SYSTEMROOT WINDIR SYSTEMDRIVE COMSPEC PATHEXT USERPROFILE APPDATA "
            "LOCALAPPDATA PROGRAMFILES PROGRAMFILES(X86) TEMP TMP RUNNER_TEMP "
            "RUNNER_TOOL_CACHE GITHUB_WORKSPACE ISSUE110_SETUP_STARTED"
        ).split()
    )
    return {key: value for key, value in source.items() if key.upper() in keep}


def test_summary(path):
    if path.stat().st_size > 4194304:
        raise ValueError("setup_output_limit")
    tree = ET.parse(path).getroot()
    counts = {
        key: sum(int(s.attrib.get(key, 0)) for s in tree.iter("testsuite"))
        for key in ("tests", "failures", "errors", "skipped")
    }
    if any(value < 0 or value > 1000 for value in counts.values()):
        raise ValueError("independent_tests_incomplete")
    failed = [
        index
        for index, case in enumerate(tree.iter("testcase"))
        if case.find("failure") is not None or case.find("error") is not None
    ]
    return counts, [index for index in failed if index < 1000][:100]


def save(output, receipt):
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


def run_stage(command, stage, private, output, receipt, deadline, cap):
    receipt.update(
        setup_stage=stage,
        tool_exit=None,
        setup_parent_exit_verified=None,
        setup_descendant_cleanup="unverified",
    )
    save(output, receipt)
    end = min(deadline - 2, time.monotonic() + cap)
    if end <= time.monotonic():
        raise ValueError("setup_deadline")
    log = private / f"{stage}.log"
    with log.open("wb") as stream:
        child = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT)
        stage_completed = False
        try:
            while child.poll() is None:
                if time.monotonic() >= end:
                    raise ValueError("setup_deadline")
                if log.stat().st_size > 4194304:
                    raise ValueError("setup_output_limit")
                time.sleep(0.05)
            receipt["tool_exit"] = child.returncode
            receipt["setup_parent_exit_verified"] = True
            if log.stat().st_size > 4194304:
                raise ValueError("setup_output_limit")
            if child.returncode != 0:
                raise ValueError("stage_failed")
            stage_completed = True
        finally:
            try:
                if child.poll() is not None:
                    receipt["setup_parent_exit_verified"] = True
                else:
                    child.kill()
                    try:
                        child.wait(timeout=1)
                        receipt["setup_parent_exit_verified"] = True
                    except subprocess.TimeoutExpired:
                        receipt["setup_parent_exit_verified"] = False
            except Exception:
                # Preserve an already-failed stage; cleanup failure is not evidence of exit.
                if stage_completed:
                    raise
            finally:
                save(output, receipt)
    return log


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pwsh", required=True)
    parser.add_argument("--uv", required=True)
    args = parser.parse_args()
    workspace = Path(os.environ["GITHUB_WORKSPACE"])
    os.chdir(workspace)
    output = workspace / "evidence/setup-only.json"
    output.parent.mkdir(exist_ok=True)
    receipt = dict(
        schema=1,
        source=SOURCE,
        tree=TREE,
        status="prerequisites_missing",
        original_group_started=False,
        native_started=False,
        setup_stage="entry",
    )
    save(output, receipt)
    try:
        if sys.platform != "win32" or sys.version_info[:2] != (3, 12) or struct.calcsize("P") != 8:
            raise ValueError("preinstalled_python_missing")
        toolcache = Path(os.environ["RUNNER_TOOL_CACHE"]) / "Python"
        if not Path(sys.executable).resolve().is_relative_to(toolcache.resolve()):
            raise ValueError("preinstalled_python_missing")
        deadline = (
            time.monotonic() + 300 - (time.time() - int(os.environ["ISSUE110_SETUP_STARTED"]))
        )
        private = Path(os.environ["RUNNER_TEMP"]) / "issue110-setup-verify"
        private.mkdir()
        # Setup-only subprocesses do not receive inherited application credentials.
        clean = clean_environment(os.environ)
        os.environ.clear()
        os.environ.update(clean)
        os.environ["GITHUB_ENV"] = str(private / "helper-env")
        os.environ["UV_CACHE_DIR"] = str(private / "uv-cache")

        def run(command, stage, cap=30):
            return run_stage(command, stage, private, output, receipt, deadline, cap)

        if not run([args.uv, "--version"], "uv_version").read_text().startswith("uv 0.12.19 "):
            raise ValueError("uv_version_mismatch")
        for revision, expected in (("HEAD", SOURCE), ("HEAD^{tree}", TREE)):
            if (
                run(["git", "-C", "subject", "rev-parse", revision], "source_check")
                .read_text()
                .strip()
                != expected
            ):
                raise ValueError("source_mismatch")
        lock = hashlib.sha256((workspace / "subject/uv.lock").read_bytes()).hexdigest()
        venv = private / "independent-venv"
        run([sys.executable, "-I", "-m", "venv", "--without-pip", str(venv)], "independent_venv")
        independent = str(venv / "Scripts/python.exe")
        run(
            [args.uv, "--no-config", "pip", "install", "--python", independent, "pytest==9.1.1"],
            "independent_pytest",
            60,
        )
        config = private / "pytest.ini"
        config.write_text("[pytest]\n", encoding="ascii")
        tests = workspace / "harness/tests/delivery"
        junit = private / "tests.xml"
        test_command = [
            independent,
            "-I",
            "-m",
            "pytest",
            "-q",
            "-c",
            str(config),
            "--confcutdir",
            str(tests),
            f"--junitxml={junit}",
            str(tests / "test_issue110_capture.py"),
            str(tests / "test_issue110_setup_verify.py"),
        ]
        try:
            run(test_command, "independent_tests", 45)
        finally:
            if junit.exists():
                counts, failed = test_summary(junit)
                receipt.update(controller_tests=counts, failed_case_indexes=failed)
                save(output, receipt)
        if (
            not counts["tests"]
            or failed
            or any(counts[key] for key in ("failures", "errors", "skipped"))
        ):
            raise ValueError("independent_tests_incomplete")
        run(
            [
                args.pwsh,
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(workspace / "harness/scripts/diagnostics/issue110_setup.ps1"),
                "-Group",
                "1",
            ],
            "real_setup",
            112,
        )
        entries = (private / "helper-env").read_text(encoding="utf-8-sig").splitlines()
        paths = [
            line.removeprefix("ISSUE110_PYTHON=")
            for line in entries
            if line.startswith("ISSUE110_PYTHON=")
        ]
        if len(paths) != 1 or not Path(paths[0]).resolve().is_relative_to(
            (Path(os.environ["RUNNER_TEMP"]) / "issue110-python-1").resolve()
        ):
            raise ValueError("python_path_not_owned")
        probe = (
            "import importlib.metadata as m,json,sys,struct;from pathlib import Path;"
            "assert sys.version_info[:3]==(3,11,16) and struct.calcsize('P')==8;"
            "assert sys.prefix==sys.base_prefix;"
            "v={n:m.version(n) for n in ('pytest','pydantic','swu-happyrun')};"
            "assert v=={'pytest':'9.1.1','pydantic':'2.14.1','swu-happyrun':'0.1.0'};"
            "d=json.loads(m.distribution('swu-happyrun').read_text('direct_url.json'));"
            "assert d['dir_info']['editable'] and d['url']==Path('subject').resolve().as_uri();"
            "print(json.dumps(v))"
        )
        versions = json.loads(run([paths[0], "-I", "-c", probe], "identity").read_text())
        run([args.uv, "--no-config", "pip", "check", "--python", paths[0]], "package_check")
        if (
            run(
                ["git", "-C", "subject", "status", "--porcelain", "--untracked-files=no"],
                "source_unchanged",
            )
            .read_text()
            .strip()
        ):
            raise ValueError("source_mismatch")
        if hashlib.sha256((workspace / "subject/uv.lock").read_bytes()).hexdigest() != lock:
            raise ValueError("source_mismatch")
        receipt.update(
            status="setup_verified",
            versions=versions,
            lock_sha256=lock,
            interpreter_owned=True,
            direct_base=True,
        )
        save(output, receipt)
        return 0
    except Exception as exc:
        known = {
            "setup_deadline",
            "setup_output_limit",
            "stage_failed",
            "preinstalled_python_missing",
            "uv_version_mismatch",
            "source_mismatch",
            "independent_tests_incomplete",
            "python_path_not_owned",
            "setup_source_override",
        }
        receipt["blocker"] = (
            str(exc) if isinstance(exc, ValueError) and str(exc) in known else "setup_api_error"
        )
        save(output, receipt)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
