"""One bounded group from issue 110. No dumps, remediation, or automatic retries."""

import argparse
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import time
import uuid
from pathlib import Path

SOURCE = "6a0dac84bf66125c7e2bd506bb0d8c988b1dcc34"
TREE = "09b5064a5e30495f7ced68b84fe453bd5d0413ce"
MANIFEST_HASH = "1b34864118722925ceeccf46a79cebf0325e8ccc0cf848f750144524ed9e023f"
GROUP_SECONDS = 1800
SETUP_SECONDS = 300
CAPTURE_SECONDS = 10
MAX_OUTPUT = 16 * 1024 * 1024
HEX = r"(?:[0-9a-fA-F]{1,16}|[0-9a-fA-F]{1,8}`[0-9a-fA-F]{8})"
MODULE = r"[a-zA-Z0-9_]{1,80}"


def load_manifest():
    raw = Path(__file__).with_name("issue110_groups.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != MANIFEST_HASH:
        raise ValueError("manifest_mismatch")
    result = json.loads(raw)
    if result["source"] != SOURCE or result["tree"] != TREE:
        raise ValueError("subject_mismatch")
    return result


def number(text):
    return int(text.replace("`", ""), 16)


def parse_capture(raw, nonce, *, target_pid=None):
    result = {
        "complete": False,
        "chance": "second",
        "original_fault_context_captured": False,
        "rejection": "markers_missing_or_duplicated",
    }
    prefix = f"SWU_{nonce}_"
    # Do not publish raw parse errors, paths, register values, arguments or symbol names.
    if raw.count(prefix + "BEGIN\n") != 1 or raw.count(prefix + "END\n") != 1:
        return result
    if raw.index(prefix + "END\n") < raw.index(prefix + "BEGIN\n"):
        result["rejection"] = "markers_out_of_order"
        return result
    body = raw.split(prefix + "BEGIN\n")[1].split(prefix + "END\n")[0]
    contexts = re.findall(rf"^{prefix}CONTEXT (.*)$", body, re.M)
    codes = re.findall(r"^\s*ExceptionCode:\s+(\S+)", body, re.M | re.I)
    if len(contexts) != 1 or [code.lower() for code in codes] != ["c0000005"]:
        result["rejection"] = "exception_or_context_invalid"
        return result
    context = re.fullmatch(rf"({HEX}) ({HEX}) ({HEX})", contexts[0])
    if not context:
        result["rejection"] = "context_invalid"
        return result
    pid, tid, ip = (number(x) for x in context.groups())
    if not pid or not tid or (target_pid is not None and pid != target_pid):
        result["rejection"] = "identity_mismatch"
        return result
    if body.count(prefix + "STACK\n") != 1 or body.count(prefix + "MODULES\n") != 1:
        result["rejection"] = "section_markers_invalid"
        return result
    if not (
        body.index(prefix + "CONTEXT ")
        < body.index(prefix + "STACK\n")
        < body.index(prefix + "MODULES\n")
    ):
        result["rejection"] = "section_order_invalid"
        return result
    stack, modules = body.split(prefix + "STACK\n")[1].split(prefix + "MODULES\n")
    ranges = []
    for start, end, name in re.findall(
        rf"^\s*({HEX})\s+({HEX})\s+({MODULE})(?:\s|$)", modules, re.M
    ):
        lo, hi = number(start), number(end)
        if lo < hi and len(ranges) < 256:
            ranges.append((lo, hi, name))

    def relative(address):
        matches = [
            {"module": name, "rva": hex(address - lo)}
            for lo, hi, name in ranges
            if lo <= address < hi
        ]
        return matches[0] if len(matches) == 1 else {"module": None, "address": hex(address)}

    addresses = [ip]
    for _, ret in re.findall(rf"^\s*[0-9a-fA-F]{{2}}\s+({HEX})\s+({HEX})\s+", stack, re.M):
        address = number(ret)
        if address and len(addresses) < 32:
            addresses.append(address)
    result.update(
        exception_code="0xc0000005",
        process_id=pid,
        thread_id=tid,
        instruction_pointer=hex(ip),
        fault=relative(ip),
        frames=[relative(address) for address in addresses],
        complete=bool(ranges and len(addresses) > 1 and relative(ip)["module"]),
        symbols="module_relative_only_no_matched_private_symbols",
    )
    result["rejection"] = (
        "modules_missing"
        if not ranges
        else "stack_returns_missing"
        if len(addresses) <= 1
        else "fault_module_unresolved"
        if not relative(ip)["module"]
        else None
    )
    return result


def classify(child_exit, debugger_exit, timed_out, evidence):
    if timed_out:
        return "supervisor_timeout"
    if child_exit is None:
        return "child_exit_unknown"
    if child_exit == 0xC0000005:
        return (
            "native_crash" if evidence.get("complete") else "native_crash_without_complete_capture"
        )
    if debugger_exit != 0:
        return "debugger_failed"
    return "no_crash_observed" if child_exit == 0 else "test_failed"


def pytest_argv(python, nodes, junit):
    return [
        str(python),
        "-m",
        "pytest",
        *nodes,
        "-vv",
        "-o",
        "faulthandler_timeout=60",
        "--durations=10",
        f"--junitxml={junit}",
    ]


def cdb_argv(cdb, init, symbols, target):
    return [
        str(cdb),
        "-hd",
        "-G",
        "-noshell",
        "-nosqm",
        "-sins",
        "-netsyms:no",
        "-y",
        str(symbols),
        "-cf",
        str(init),
        *target,
    ]


def debugger_scripts(nonce, terminal_path):
    if not re.fullmatch(r"[a-f0-9]{32}", nonce) or not re.fullmatch(
        r"[A-Za-z]:\\[-A-Za-z0-9_.\\]+", str(terminal_path)
    ):
        raise ValueError("unsafe_debugger_script_path")
    prefix = "SWU_" + nonce + "_"
    # $$>a< executes without echoing script commands into the capture protocol.
    init = f'sxd -c2 "$$>a<{terminal_path}" av\n.printf "{prefix}READY %x\\n", @$tpid\n'
    terminal = "\n".join(
        [
            f".echo {prefix}BEGIN",
            ".exr -1",
            ".ecxr",
            f'.printf "{prefix}CONTEXT %x %x %I64x\\n", @$tpid, @$tid, @$ip',
            f".echo {prefix}STACK",
            "knL 0x20",
            f".echo {prefix}MODULES",
            "lm",
            f".echo {prefix}END",
            "gn",
            "",
        ]
    )
    return init, terminal


def child_environment(original, python, root):
    system = original.get("SystemRoot") or original.get("SYSTEMROOT")
    if not system:
        raise ValueError("system_root_missing")
    root = Path(root)
    return {
        "SystemRoot": system,
        "WINDIR": system,
        "COMSPEC": str(Path(system) / "System32/cmd.exe"),
        "PATH": os.pathsep.join([str(Path(python).parent), str(Path(system) / "System32"), system]),
        "PATHEXT": ".COM;.EXE;.BAT;.CMD",
        "TEMP": str(root / "temp"),
        "TMP": str(root / "temp"),
        "USERPROFILE": str(root / "profile"),
        "APPDATA": str(root / "profile/Roaming"),
        "LOCALAPPDATA": str(root / "profile/Local"),
    }


def node_results(raw, nodes):
    output = []
    for node in nodes:
        matches = re.findall(
            r"^" + re.escape(node) + r"\s+(PASSED|FAILED|SKIPPED|ERROR|XFAIL|XPASS)\b", raw, re.M
        )
        output.append(
            {"node": node, "status": matches[0].lower() if len(matches) == 1 else "uncompleted"}
        )
    return output


def consume(root, group, attempt):
    if group not in ("1", "2") or attempt != "1":
        raise ValueError("repeat_not_authorized")
    marker = Path(root) / f"issue110-group-{group}.consumed"
    with marker.open("x", encoding="ascii") as stream:
        stream.write(SOURCE + "\n")


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def x64_pe(path):
    with Path(path).open("rb") as stream:
        if stream.read(2) != b"MZ":
            return False
        stream.seek(0x3C)
        offset = struct.unpack("<I", stream.read(4))[0]
        stream.seek(offset)
        return stream.read(6) == b"PE\0\0\x64\x86"


def remaining(deadline, maximum):
    seconds = min(maximum, deadline - time.monotonic())
    if seconds <= 0:
        raise ValueError("setup_budget_exhausted")
    return seconds


def parse_signature_progress(raw, nonce, *, version=1):
    result = {
        "complete": False,
        "marker_count": 0,
        "last_stage": None,
        "file_index": None,
        "elapsed_ms": None,
        "checkpoints_ms": [],
        "rejection": "no_markers",
    }
    if type(version) is not int or version not in (1, 2, 3, 4, 5, 6):
        return result | {"rejection": "unsupported_version"}
    stages = [("script_start", None)]
    if version > 1:
        result["protocol_version"] = version
        if version >= 3:
            stages += [("import_start", None), ("import_done", None)]
        stages += [("resolve_start", None), ("resolve_done", None)]
    if version >= 5:
        stages += [
            ("management_import_start", None),
            ("management_import_done", None),
            ("item_resolve_start", None),
            ("item_resolve_done", None),
        ]
    file_stages = ["trust_start", "trust_returned", "version_start"]
    if version >= 4:
        file_stages += ["item_returned", "version_info_returned", "version_parts_returned"]
    file_stages.append("version_done")
    stages += [(stage, file_index) for file_index in range(3) for stage in file_stages]
    if version == 6:
        stages += [
            ("json_prepare_start", None),
            ("utility_import_start", None),
            ("utility_import_done", None),
            ("json_resolve_start", None),
            ("json_resolve_done", None),
            ("json_generate_start", None),
            ("json_generated", None),
        ]
    stages.append(("script_done", None))
    if raw is None:
        return result
    if len(raw) > 65536:
        return result | {"rejection": "output_limit"}
    if isinstance(raw, bytes):
        raw = raw.decode("ascii", errors="replace")
    tag = ("SWU_SIG_" if version == 1 else f"SWU_SIG_V{version}_") + nonce
    prefix = tag + " "
    times = []
    truncated = False
    for line in raw.splitlines(keepends=True):
        partial_tag = (
            not line.endswith("\n") and line.startswith("SWU_SIG_") and tag.startswith(line)
        )
        if partial_tag:
            truncated = True
            break
        if not line.startswith(tag):
            continue
        if not line.endswith("\n"):
            truncated = True
            break
        match = re.fullmatch(re.escape(prefix) + r"([0-9]{1,2}) ([0-9]{1,6})\r?\n", line)
        if not match:
            return result | {"rejection": "invalid_markers"}
        index, elapsed = map(int, match.groups())
        if index != len(times) or index >= len(stages) or not (0 <= elapsed <= 300000):
            return result | {"rejection": "invalid_markers"}
        if times and elapsed < times[-1]:
            return result | {"rejection": "invalid_markers"}
        times.append(elapsed)
    if times:
        index = len(times) - 1
        stage, file_index = stages[index]
        result.update(
            marker_count=len(times),
            last_stage=stage,
            file_index=file_index,
            elapsed_ms=times[-1],
            checkpoints_ms=times,
            complete=len(times) == len(stages) and not truncated,
            rejection=None if len(times) == len(stages) else "incomplete",
        )
    if truncated:
        result["rejection"] = "truncated"
    return result


def installed_debugger(env, deadline, *, receipt=None):
    receipt = {} if receipt is None else receipt
    receipt.update(
        stage="binary_presence", tool_exit=None, run_elapsed_ms=None, run_timeout_seconds=None
    )
    root = (
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Windows Kits/10/Debuggers/x64"
    )
    paths = [root / name for name in ("cdb.exe", "dbgeng.dll", "dbghelp.dll")]
    if not all(path.is_file() and x64_pe(path) for path in paths):
        raise ValueError("installed_x64_debugger_missing")
    # Script timings exclude process startup. Trust-returned is not a verdict.
    # Explicit imports change initialization order before trust; this is not passive timing
    # or proof that autoload caused a prior timeout. No signature predicate is changed.
    # Utility import and JSON capture/re-emission happen only after the file loop.
    # These are diagnostic interventions; script_done does not prove parent receipt of stdout.
    # Only the fixed PSHOME manifests are tried; their presence on the runner is not assumed.
    # Only a generated hex nonce varies in this fixed script; no external shell content.
    nonce = uuid.uuid4().hex
    script = (
        """$ErrorActionPreference='Stop'; $clock=[Diagnostics.Stopwatch]::StartNew();
    function Mark([int]$n) {
      [Console]::Error.WriteLine(('SWU_SIG_V6_NONCE {0} {1}' -f $n,$clock.ElapsedMilliseconds));
      [Console]::Error.Flush();
    };
    Mark 0;
    $manifest=[IO.Path]::Combine($PSHOME,'Modules\\Microsoft.PowerShell.Security\\Microsoft.PowerShell.Security.psd1');
    if(-not [IO.File]::Exists($manifest)) {exit 4};
    Mark 1; $null=Import-Module -Name $manifest -ErrorAction Stop; Mark 2;
    Mark 3;
    $null=Get-Command -ListImported -Name Get-AuthenticodeSignature """
        """-CommandType Cmdlet -ErrorAction Stop;
    Mark 4;
    $management=[IO.Path]::Combine($PSHOME,'Modules\\Microsoft.PowerShell.Management\\Microsoft.PowerShell.Management.psd1');
    if(-not [IO.File]::Exists($management)) {exit 5};
    Mark 5; $null=Import-Module -Name $management -ErrorAction Stop; Mark 6;
    Mark 7;
    $null=Get-Command -ListImported -Name Get-Item -CommandType Cmdlet -ErrorAction Stop;
    Mark 8; $items=@(); $i=0; foreach($p in $args) {
    Mark (9+7*$i);
    $s=Get-AuthenticodeSignature -LiteralPath $p;
    Mark (10+7*$i);
    $publisher='(^|,\\s*)O=Microsoft Corporation(,|$)';
    if($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notmatch $publisher) {exit 3};
    Mark (11+7*$i);
    $item=Get-Item -LiteralPath $p;
    Mark (12+7*$i);
    $v=$item.VersionInfo;
    Mark (13+7*$i);
    $parts=@($v.FileMajorPart,$v.FileMinorPart,$v.FileBuildPart,$v.FilePrivatePart);
    Mark (14+7*$i);
    $items+=@{name=[IO.Path]::GetFileName($p); version=($parts -join '.')};
    Mark (15+7*$i); $i++;
    }; Mark 30;
    $utility=[IO.Path]::Combine($PSHOME,'Modules\\Microsoft.PowerShell.Utility\\Microsoft.PowerShell.Utility.psd1');
    if(-not [IO.File]::Exists($utility)) {exit 6};
    Mark 31; $null=Import-Module -Name $utility -ErrorAction Stop; Mark 32;
    Mark 33;
    $null=Get-Command -ListImported -Name ConvertTo-Json """
        """-CommandType Cmdlet -ErrorAction Stop;
    Mark 34; Mark 35;
    $json=ConvertTo-Json -Compress -InputObject @($items);
    Mark 36; $json; Mark 37"""
    ).replace("NONCE", nonce)
    # -File keeps filenames out of PowerShell's command-language parser.
    checker = Path(env["TEMP"]).parent / "verify-signatures.ps1"
    checker.write_text(script, encoding="utf-8")
    powershell = Path(env["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    receipt["stage"] = "signature_check"
    receipt["run_timeout_seconds"] = remaining(deadline, 30)
    run_started = time.monotonic()
    try:
        try:
            verified = subprocess.run(
                [
                    str(powershell),
                    "-NoProfile",
                    "-NonInteractive",
                    "-File",
                    str(checker),
                    *map(str, paths),
                ],
                env=env,
                capture_output=True,
                timeout=receipt["run_timeout_seconds"],
                check=False,
            )
        finally:
            # Total parent call elapsed includes spawn and timeout cleanup, not just startup.
            # End timing before parsing; never clamp it to the configured timeout.
            try:
                elapsed_ms = (time.monotonic() - run_started) * 1000
                if 0 <= elapsed_ms < float("inf"):
                    receipt["run_elapsed_ms"] = round(elapsed_ms, 3)
            except Exception:
                # Optional timing must never replace the subprocess outcome or exception.
                pass
    except subprocess.TimeoutExpired as error:
        receipt["progress"] = parse_signature_progress(error.stderr, nonce, version=6)
        raise
    receipt["progress"] = parse_signature_progress(verified.stderr, nonce, version=6)
    receipt["tool_exit"] = verified.returncode
    if verified.returncode != 0:
        if (
            verified.returncode == 4
            and receipt["progress"]["marker_count"] == 1
            and receipt["progress"]["rejection"] == "incomplete"
        ):
            receipt.update(stage="security_module_manifest", blocker="manifest_unavailable")
        elif (
            verified.returncode == 5
            and receipt["progress"]["marker_count"] == 5
            and receipt["progress"]["rejection"] == "incomplete"
        ):
            receipt.update(stage="management_module_manifest", blocker="manifest_unavailable")
        elif (
            verified.returncode == 6
            and receipt["progress"]["marker_count"] == 31
            and receipt["progress"]["rejection"] == "incomplete"
        ):
            receipt.update(stage="utility_module_manifest", blocker="manifest_unavailable")
        raise ValueError("debugger_signature_unverified")
    receipt["stage"] = "signature_json"
    data = json.loads(verified.stdout)
    if len(data) != 3 or any(not re.fullmatch(r"[0-9. ]{3,80}", item["version"]) for item in data):
        raise ValueError("debugger_version_unverified")
    receipt["stage"] = "binary_hashes"
    verified_data = [
        {"name": path.name, "version": item["version"], "sha256": sha256(path)}
        for item, path in zip(data, paths, strict=True)
    ]
    receipt["stage"] = "complete"
    return paths[0], verified_data


def verify_subject(subject, deadline):
    def git(*args):
        return (
            subprocess.run(
                ["git", "-C", str(subject), *args],
                capture_output=True,
                timeout=remaining(deadline, 10),
                check=True,
            )
            .stdout.decode()
            .strip()
        )

    if (
        git("rev-parse", "HEAD") != SOURCE
        or git("rev-parse", "HEAD^{tree}") != TREE
        or git("diff", "--name-only", "HEAD")
    ):
        raise ValueError("subject_mismatch")
    if (
        sys.version_info[:3] != (3, 11, 16)
        or struct.calcsize("P") != 8
        or sys.platform != "win32"
        or sys.prefix != sys.base_prefix
    ):
        raise ValueError("interpreter_mismatch")
    import importlib.metadata

    versions = {name: importlib.metadata.version(name) for name in ("pytest", "pydantic")}
    if versions != {"pytest": "9.1.1", "pydantic": "2.14.1"}:
        raise ValueError("dependency_mismatch")
    dll = Path(sys.base_prefix) / "python311.dll"
    if not dll.is_file() or not x64_pe(sys.executable) or not x64_pe(dll):
        raise ValueError("python_binary_unverified")
    return {
        "version": "3.11.16",
        "architecture": "x64",
        "dependencies": versions,
        "executable_sha256": sha256(sys.executable),
        "python311_sha256": sha256(dll),
        "build": list(__import__("platform").python_build()),
        "distribution": "astral_python_build_standalone_via_pinned_setup_uv",
        "topology": "direct_base_interpreter_frozen_deps_editable_project_not_original_venv",
        "project_version": importlib.metadata.version("swu-happyrun"),
        "original_machine_distribution_match": "unknown",
        "os_build": sys.getwindowsversion().build,
    }


def run_one(cdb, target, cwd, env, directory, seconds):
    from issue110_win32 import Session

    directory.mkdir()
    symbols = directory / "symbols"
    symbols.mkdir()
    nonce = uuid.uuid4().hex
    init, terminal = debugger_scripts(nonce, directory / "terminal.cdb")
    (directory / "init.cdb").write_text(init, encoding="ascii")
    (directory / "terminal.cdb").write_text(terminal, encoding="ascii")
    argv = cdb_argv(cdb, directory / "init.cdb", symbols, target)
    start = time.monotonic()
    raw, child_exit, cdb_exit, reason, cleaned, child_pid = Session().run(
        argv,
        cwd,
        env,
        directory / "raw.log",
        nonce,
        start + seconds,
        capture_seconds=CAPTURE_SECONDS,
        max_output=MAX_OUTPUT,
    )
    evidence = parse_capture(raw, nonce, target_pid=child_pid)
    result = {
        "child_exit": child_exit,
        "debugger_exit": cdb_exit,
        "target_pid": child_pid,
        "reason": reason,
        "elapsed_seconds": round(time.monotonic() - start, 3),
        "cleanup_verified": cleaned,
        "capture": evidence,
        "status": classify(child_exit, cdb_exit, reason == "timeout", evidence),
    }
    if not cleaned or reason not in ("exited", "timeout"):
        result["status"] = "harness_failed"
    return result, raw


def smoke_identity(raw, pid):
    return re.findall(r"^SMOKE_PID ([0-9]+)$", raw, re.M) == [str(pid)]


def controller_tests(env, root, setup_deadline):
    test = Path(__file__).resolve().parents[2] / "tests/delivery/test_issue110_capture.py"
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
                str(test.parent),
                str(test),
            ],
            cwd=root,
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
            timeout=remaining(setup_deadline, 30),
            check=False,
        )
    if result.returncode != 0:
        raise ValueError("controller_tests_failed")
    return True


def smoke(cdb, env, root, setup_deadline, *, receipt=None):
    python = sys.executable
    receipt = {} if receipt is None else receipt
    receipt["results"] = {}

    def run(target, name, seconds):
        receipt["stage"] = name
        remaining = setup_deadline - time.monotonic()
        if remaining < seconds:
            raise ValueError("setup_budget_exhausted")
        result, raw = run_one(cdb, target, root, env, root / name, seconds)
        # Preserve only fixed predicates and already-sanitized scalar outcomes before assertions.
        receipt["results"][name] = {
            key: result[key]
            for key in (
                "child_exit",
                "debugger_exit",
                "reason",
                "elapsed_seconds",
                "cleanup_verified",
            )
        } | {
            "capture_complete": result["capture"]["complete"],
            "capture_rejection": result["capture"].get("rejection"),
            "exact_pid_seen": smoke_identity(raw, result["target_pid"]),
            "stdout_seen": "SMOKE_OUT" in raw,
            "stderr_seen": "SMOKE_ERR" in raw,
            "reporter_seen": "Timeout (0:01:00)!" in raw,
            "descendant_started": "DESCENDANT_STARTED" in raw,
            "passed": False,
        }
        return result, raw

    for code in (0, 7):
        script = (
            "import os,sys; assert 'SWU_SECRET_CANARY' not in os.environ; "
            "print('SMOKE_PID',os.getpid()); print('SMOKE_OUT'); "
            f"print('SMOKE_ERR',file=sys.stderr); sys.exit({code})"
        )
        result, raw = run([python, "-c", script], f"exit-{code}", 15)
        if (
            result["child_exit"] != code
            or result["reason"] != "exited"
            or not result["cleanup_verified"]
            or not smoke_identity(raw, result["target_pid"])
            or not all(marker in raw for marker in ("SMOKE_OUT", "SMOKE_ERR"))
        ):
            raise ValueError("exit_smoke_failed")
        receipt["results"][f"exit-{code}"]["passed"] = True
    test = root / "test_smoke_av.py"
    test.write_text(
        "import time,faulthandler\ndef test_reporter_then_av():\n"
        "    time.sleep(61)\n    faulthandler._read_null()\n",
        encoding="ascii",
    )
    result, raw = run(
        [python, "-m", "pytest", str(test), "-vv", "-o", "faulthandler_timeout=60"], "av", 90
    )
    if (
        result["child_exit"] != 0xC0000005
        or result["reason"] != "exited"
        or not result["capture"]["complete"]
        or "Timeout (0:01:00)!" not in raw
        or not result["cleanup_verified"]
    ):
        raise ValueError("av_reporter_smoke_failed")
    receipt["results"]["av"]["passed"] = True
    script = (
        "import subprocess,sys,time; "
        "subprocess.Popen([sys.executable,'-c','import time;time.sleep(100)']); "
        "print('DESCENDANT_STARTED',flush=True); time.sleep(100)"
    )
    result, raw = run([python, "-c", script], "timeout", 5)
    if (
        result["reason"] != "timeout"
        or not result["cleanup_verified"]
        or "DESCENDANT_STARTED" not in raw
    ):
        raise ValueError("timeout_cleanup_smoke_failed")
    receipt["results"]["timeout"]["passed"] = True
    receipt["stage"] = "complete"
    return receipt


def main(*, preflight_only=False):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subject", type=Path, required=True)
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--group", choices=("1", "2"), required=True)
    parser.add_argument("--setup-started", type=float, required=True)
    args = parser.parse_args()
    report = {
        "schema": 1,
        "source": SOURCE,
        "tree": TREE,
        "group": args.group,
        "batch": "issue110-native-preflight-1"
        if preflight_only
        else "issue110-native-two-groups-1",
        "mode": "preflight_only" if preflight_only else "original_group",
        "status": "prerequisites_missing",
        "group_budget_seconds": GROUP_SECONDS,
        "reporter_seconds": 60,
        "debugger_perturbs_scheduling": True,
        "root_cause_established": False,
        "stage": "entry",
        "original_invocation_attempted": False,
        "original_group_started": False,
    }
    try:
        if (
            os.environ.get("GITHUB_RUN_ATTEMPT") != "1"
            or os.environ.get("GITHUB_REF") != "refs/heads/diagnostics/issue110-native-capture"
        ):
            raise ValueError("entry_scope_mismatch")
        elapsed = time.time() - args.setup_started
        if not 0 <= elapsed < SETUP_SECONDS:
            raise ValueError("setup_budget_exhausted")
        setup_deadline = time.monotonic() + SETUP_SECONDS - elapsed
        args.private.mkdir(parents=True, exist_ok=False)
        for directory in ("temp", "profile/Roaming", "profile/Local"):
            (args.private / directory).mkdir(parents=True, exist_ok=True)
        original = dict(os.environ, SWU_SECRET_CANARY="must-not-enter-debuggee")
        env = child_environment(original, sys.executable, args.private)
        report["stage"] = "verify_subject"
        report["interpreter"] = verify_subject(args.subject, setup_deadline)
        report["stage"] = "installed_debugger"
        report["debugger_check"] = {}
        cdb, report["debugger_binaries"] = installed_debugger(
            env, setup_deadline, receipt=report["debugger_check"]
        )
        report["stage"] = "controller_tests"
        report["controller_tests_passed"] = controller_tests(env, args.private, setup_deadline)
        report["stage"] = "smoke"
        report["smoke"] = {}
        smoke(cdb, env, args.private, setup_deadline, receipt=report["smoke"])
        if time.monotonic() >= setup_deadline:
            raise ValueError("setup_budget_exhausted")
        if preflight_only:
            report["status"] = "preflight_passed"
        else:
            report["stage"] = "original"
            nodes = load_manifest()["groups"][args.group]
            consume(args.private, args.group, os.environ["GITHUB_RUN_ATTEMPT"])
            report["manifest_sha256"] = MANIFEST_HASH
            target = pytest_argv(sys.executable, nodes, args.private / "private.xml")
            report["original_invocation_attempted"] = True
            report["original_group_started"] = None
            result, raw = run_one(
                cdb, target, args.subject, env, args.private / "original", GROUP_SECONDS
            )
            report.update(result)
            report["original_group_started"] = True if result["target_pid"] else None
            report["nodes"] = node_results(raw, nodes)
        report["stage"] = "complete"
    except Exception as error:
        # Error messages may contain raw command output or paths. Publish only a fixed code.
        allowed = {
            "entry_scope_mismatch",
            "setup_budget_exhausted",
            "installed_x64_debugger_missing",
            "debugger_signature_unverified",
            "debugger_version_unverified",
            "subject_mismatch",
            "interpreter_mismatch",
            "dependency_mismatch",
            "python_binary_unverified",
            "controller_tests_failed",
            "exit_smoke_failed",
            "av_reporter_smoke_failed",
            "timeout_cleanup_smoke_failed",
            "unsafe_debugger_script_path",
            "manifest_mismatch",
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
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    # A no-crash observation is not a repair; original exit remains in the report.
    return 0 if report["status"] in ("no_crash_observed", "preflight_passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
