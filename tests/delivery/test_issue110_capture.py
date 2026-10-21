"""Pure tests for the narrow runner; never launch the original diagnostic groups."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/diagnostics/issue110_capture.py"


@pytest.fixture
def capture():
    assert SCRIPT.exists(), "bounded native evidence supervisor is missing"
    spec = importlib.util.spec_from_file_location("issue110_capture", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fixed_manifest_preserves_issue_order_and_subject(capture):
    manifest = capture.load_manifest()
    assert manifest["source"] == "6a0dac84bf66125c7e2bd506bb0d8c988b1dcc34"
    assert manifest["tree"] == "09b5064a5e30495f7ced68b84fe453bd5d0413ce"
    one, two = manifest["groups"]["1"], manifest["groups"]["2"]
    assert len(one) == len(two) == 12
    assert len(set(one + two)) == 24
    assert one[0].endswith("::test_runtime_cannot_be_constructed_copied_or_reused")
    assert one[9].endswith(
        "::test_retention_fault_boundaries_never_report_success_or_clear_occupancy[open]"
    )
    assert one[-1].endswith("::test_original_deadline_cannot_be_renewed_at_bind_or_cleanup")
    assert two[7].endswith(
        "::test_retention_binds_exact_original_reservation_and_intent[start_intent]"
    )
    assert two[-1].endswith("::test_close_overrun_is_not_reported_as_bounded_success")


def transcript(nonce="a" * 32):
    return f"""private-token must never be exported
SWU_{nonce}_BEGIN
ExceptionCode: c0000005 (Access violation)
SWU_{nonce}_CONTEXT 1a 2b 0000000010000012
SWU_{nonce}_STACK
 # Child-SP          RetAddr               Call Site
00 0000000000000100 0000000020000020 python311!private_token
01 0000000000000110 0000000000000000 kernel32!private_token
SWU_{nonce}_MODULES
0000000010000000 0000000010001000 python311 (export symbols) C:\\private\\x.pdb
0000000020000000 0000000020001000 kernel32 (deferred)
SWU_{nonce}_END
"""


def test_terminal_capture_exports_only_numeric_module_relative_frames(capture):
    result = capture.parse_capture(transcript(), "a" * 32)
    assert result["complete"] is True
    assert result["chance"] == "second"
    assert result["original_fault_context_captured"] is False
    assert result["thread_id"] == 43
    assert result["instruction_pointer"] == "0x10000012"
    assert result["fault"] == {"module": "python311", "rva": "0x12"}
    assert result["frames"] == [
        {"module": "python311", "rva": "0x12"},
        {"module": "kernel32", "rva": "0x20"},
    ]
    rendered = json.dumps(result)
    assert "private-token" not in rendered and "private_token" not in rendered
    assert "kernel32!" not in rendered


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s.replace("_END", "_TRUNCATED"),
        lambda s: s.replace("c0000005", "deadbeef"),
        lambda s: s + s,
        lambda s: s.replace("_CONTEXT 1a 2b", "_CONTEXT bad-input 2b"),
    ],
)
def test_malformed_or_duplicate_capture_is_not_complete(capture, mutate):
    result = capture.parse_capture(mutate(transcript()), "a" * 32)
    assert result["complete"] is False
    assert "private" not in json.dumps(result)


def test_missing_capture_is_not_no_crash_evidence(capture):
    result = capture.classify(0xC0000005, 0, False, capture.parse_capture("", "a" * 32))
    assert result == "native_crash_without_complete_capture"
    assert capture.classify(7, 0, False, {}) == "test_failed"
    assert capture.classify(None, 0, False, {}) == "child_exit_unknown"
    assert capture.classify(0, 0, True, {}) == "supervisor_timeout"


def test_command_keeps_reporter_and_never_wraps_target_in_uv(capture, tmp_path):
    nodes = capture.load_manifest()["groups"]["2"]
    argv = capture.pytest_argv("python.exe", nodes, tmp_path / "private.xml")
    assert argv[:3] == ["python.exe", "-m", "pytest"]
    assert argv[3:15] == nodes
    assert argv[15:19] == ["-vv", "-o", "faulthandler_timeout=60", "--durations=10"]
    cdb = capture.cdb_argv("cdb.exe", "init.cdb", "symbols", argv)
    assert all(flag in cdb for flag in ["-hd", "-G", "-noshell", "-nosqm", "-sins", "-netsyms:no"])
    assert not set(cdb[: cdb.index("python.exe")]) & {"-g", "-o", "-vf", "-iae", "-iaec", "-myob"}


def test_scripts_wait_for_handshake_and_pass_av_unhandled(capture):
    init, terminal = capture.debugger_scripts("a" * 32, r"C:\capture\terminal.cdb")
    assert "sxd -c2" in init
    assert "$$>a<" in init  # Documented no-command-echo script invocation.
    assert init.rstrip().endswith(";") is False
    assert "g\n" not in init
    assert "@$tpid" in init
    assert terminal.rstrip().endswith("gn")
    assert "knL 0x20" in terminal
    assert not any(
        word in init + terminal for word in ["gh", ".dump", ".shell", "!analyze", "kv", "kp"]
    )
    with pytest.raises(ValueError):
        capture.debugger_scripts("a" * 32, 'C:\\bad";gh')


def test_environment_is_allowlist_not_secret_name_denylist(capture, tmp_path):
    env = capture.child_environment(
        {
            "SystemRoot": r"C:\Windows",
            "PATH": "secret-path",
            "NEW_SECRET": "canary",
            "ACTIONS_RUNTIME_TOKEN": "token",
        },
        "python.exe",
        tmp_path,
    )
    assert "canary" not in json.dumps(env)
    assert "token" not in json.dumps(env)
    assert "secret-path" not in env["PATH"]
    assert "PYTEST_DISABLE_PLUGIN_AUTOLOAD" not in env
    assert env["TEMP"] == str(tmp_path / "temp")


def test_node_results_do_not_fill_in_unexecuted_nodes(capture):
    nodes = capture.load_manifest()["groups"]["1"]
    out = f"{nodes[0]} PASSED [  8%]\n{nodes[1]} SKIPPED (private reason) [16%]\n{nodes[2]} "
    result = capture.node_results(out, nodes)
    assert result[0]["status"] == "passed"
    assert result[1]["status"] == "skipped"
    assert all(item["status"] == "uncompleted" for item in result[2:])
    assert "private" not in json.dumps(result)


def test_consumption_marker_rejects_second_invocation(capture, tmp_path):
    capture.consume(tmp_path, "1", "1")
    with pytest.raises(FileExistsError):
        capture.consume(tmp_path, "1", "1")
    with pytest.raises(ValueError):
        capture.consume(tmp_path, "2", "2")


def test_fixed_branch_only_two_group_workflow_keeps_limits():
    path = ROOT / ".github/workflows/issue110-native-capture.yml"
    assert path.exists(), "isolated branch-only diagnostic workflow is missing"
    source = path.read_text()
    assert "workflow_dispatch:" not in source
    assert "pull_request:" not in source and "  push:" in source
    assert 'branches: ["diagnostics/issue110-native-capture"]' in source
    assert "github.ref == 'refs/heads/diagnostics/issue110-native-capture'" in source
    assert "max-parallel: 2" in source and 'group: ["1", "2"]' in source
    assert "timeout-minutes: 40" in source and "timeout-minutes: 5" in source
    assert "persist-credentials: false" in source
    assert "github.run_attempt == 1" in source
    assert "--group-budget 1800" not in source  # Budget is not caller-adjustable.
    assert "retention-days: 1" in source
    assert "*.log" not in source and "*.dmp" not in source and "*.xml" not in source


def test_capture_end_before_begin_is_rejected(capture):
    raw = transcript()
    end = "SWU_" + "a" * 32 + "_END\n"
    assert not capture.parse_capture(end + raw.replace(end, ""), "a" * 32)["complete"]


def test_pe_machine_verification_rejects_other_architectures(capture, tmp_path):
    path = tmp_path / "tool.exe"
    data = bytearray(128)
    data[:2] = b"MZ"
    data[0x3C:0x40] = (80).to_bytes(4, "little")
    data[80:86] = b"PE\0\0\x64\x86"
    path.write_bytes(data)
    assert capture.x64_pe(path)
    data[84:86] = b"\x4c\x01"
    path.write_bytes(data)
    assert not capture.x64_pe(path)


@pytest.fixture
def native():
    spec = importlib.util.spec_from_file_location(
        "issue110_win32", SCRIPT.with_name("issue110_win32.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_native_exit_259_is_not_confused_with_still_running(native):
    from types import SimpleNamespace

    session = object.__new__(native.Session)

    def status(handle, output):
        output._obj.value = 259
        return True

    session.kernel = SimpleNamespace(WaitForSingleObject=lambda h, t: 0, GetExitCodeProcess=status)
    assert session.exit_code(123) == 259
    session.kernel.WaitForSingleObject = lambda h, t: 258
    assert session.exit_code(123) is None


@pytest.mark.parametrize(
    ("open_ok", "assign_ok", "terminated", "delayed_exit"),
    [
        (True, True, True, False),
        (True, True, True, True),
        (False, True, True, False),
        (False, False, True, False),
        (False, False, False, False),
    ],
)
def test_exact_child_handle_precedes_go_and_cdb_exit_does_not_replace_child(
    native, monkeypatch, tmp_path, open_ok, assign_ok, terminated, delayed_exit
):
    from types import SimpleNamespace

    events = []
    target = tmp_path / "raw.log"
    nonce = "a" * 32
    target_pid = 42 if native.os.getpid() != 42 else 43
    session = object.__new__(native.Session)

    def create(*args):
        events.append(("create", args[5], args[8].lpAttributeList))
        return 101, 102, 103, 104

    def resume(handle):
        target.write_text(f"SWU_{nonce}_READY {target_pid:x}\n")
        events.append(("resume", handle))
        return 1

    def open_process(rights, inherit, pid):
        events.append(("open", rights, inherit, pid))
        return 201 if open_ok else None

    session.api = SimpleNamespace(
        CreateProcess=create,
        CloseHandle=lambda h: events.append(("close_thread", h)),
        TerminateProcess=lambda h, code: events.append(("terminate_unassigned", h, code)),
    )
    session.crt = SimpleNamespace(get_osfhandle=lambda fd: fd)
    session.kernel = SimpleNamespace(
        CreateJobObjectW=lambda a, b: 301,
        SetInformationJobObject=lambda *a: True,
        AssignProcessToJobObject=lambda job, proc: (
            events.append(("assign", job, proc)) or assign_ok
        ),
        ResumeThread=resume,
        OpenProcess=open_process,
        CloseHandle=lambda h: events.append(("close", h)),
        WaitForSingleObject=lambda h, ms: (
            events.append(("wait_unassigned", h, ms)) or (0 if terminated else 258)
        ),
    )

    def exit_code(handle):
        if handle == 201:
            return None if delayed_exit and ("advance",) not in events else 0xC0000005
        return 0 if handle == 101 else None

    session.exit_code = exit_code
    session.cleanup = lambda job: events.append(("cleanup", job)) or True
    monkeypatch.setattr(native.time, "sleep", lambda seconds: events.append(("advance",)))
    monkeypatch.setattr(native.subprocess, "STARTUPINFO", SimpleNamespace, raising=False)
    monkeypatch.setattr(native.subprocess, "STARTF_USESTDHANDLES", 256, raising=False)

    def write(fd, data):
        events.append(("write", data))
        return len(data)  # Fake child owns no real inherited pipe handle.

    monkeypatch.setattr(native.os, "write", write)
    result = session.run(
        ["cdb.exe", "python.exe"],
        tmp_path,
        {},
        target,
        nonce,
        native.time.monotonic() + 2,
        capture_seconds=1,
        max_output=1024,
    )
    assert ("cleanup", 301) in events
    if not assign_ok:
        assert ("terminate_unassigned", 101, 0xE0000110) in events
        assert ("wait_unassigned", 101, 5000) in events
        assert not any(event[0] in ("resume", "open", "write") for event in events)
        assert result[3] == "api_error" and result[4] is terminated
        return
    assert events.index(("assign", 301, 101)) < events.index(("resume", 102))
    assert ("open", 0x101000, False, target_pid) in events
    assert result[2] == 0
    if open_ok:
        assert events.index(("open", 0x101000, False, target_pid)) < events.index(("write", b"g\n"))
        assert result[1] == 0xC0000005
        assert result[3] == "exited"
        if delayed_exit:
            assert events.index(("advance",)) < events.index(("cleanup", 301))
    else:
        assert not any(event[0] == "write" for event in events)
        assert result[1] is None and result[3] == "api_error"


def test_setup_calls_never_receive_time_beyond_shared_deadline(capture, monkeypatch):
    monkeypatch.setattr(capture.time, "monotonic", lambda: 100)
    assert capture.remaining(105, 30) == 5
    with pytest.raises(ValueError, match="setup_budget_exhausted"):
        capture.remaining(100, 30)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s.replace("ExceptionCode:", "ExceptionCode: deadbeef\nExceptionCode:"),
        lambda s: s.replace(
            "_CONTEXT 1a 2b", "_CONTEXT 9999 8888 10000012\nSWU_" + "a" * 32 + "_CONTEXT 1a 2b"
        ),
        lambda s: s.replace("_CONTEXT 1a 2b", "_CONTEXT ` 2b"),
    ],
)
def test_capture_rejects_ambiguous_or_invalid_identity(capture, mutate):
    assert not capture.parse_capture(mutate(transcript()), "a" * 32)["complete"]


def test_capture_must_match_retained_process_identity(capture):
    assert capture.parse_capture(transcript(), "a" * 32, target_pid=26)["complete"]
    assert not capture.parse_capture(transcript(), "a" * 32, target_pid=27)["complete"]


def test_smoke_identity_requires_unique_full_line(capture):
    assert capture.smoke_identity("SMOKE_PID 123\n", 123)
    assert not capture.smoke_identity("SMOKE_PID 1234\n", 123)
    assert not capture.smoke_identity("SMOKE_PID 123\nSMOKE_PID 123\n", 123)
    assert not capture.smoke_identity("command: SMOKE_PID 123\n", 123)


def test_cleanup_failure_can_never_be_no_crash(capture, monkeypatch, tmp_path):
    import sys
    from types import SimpleNamespace

    fake = SimpleNamespace(run=lambda *a, **kw: ("", 0, 0, "exited", False, 42))
    monkeypatch.setitem(sys.modules, "issue110_win32", SimpleNamespace(Session=lambda: fake))
    monkeypatch.setattr(capture, "debugger_scripts", lambda *a: ("init", "terminal"))
    result, _ = capture.run_one("cdb.exe", ["python.exe"], tmp_path, {}, tmp_path / "run", 1)
    assert result["status"] == "harness_failed"
    assert result["cleanup_verified"] is False


def test_local_gate_runs_exact_controller_tests_with_shared_budget(capture, monkeypatch, tmp_path):
    from types import SimpleNamespace

    calls = []
    monkeypatch.setattr(capture.time, "monotonic", lambda: 100)
    monkeypatch.setattr(
        capture.subprocess,
        "run",
        lambda argv, **kw: calls.append((argv, kw)) or SimpleNamespace(returncode=0),
    )
    assert capture.controller_tests({"SAFE": "only"}, tmp_path, 107) is True
    argv, options = calls[0]
    assert argv[-1] == str(ROOT / "tests/delivery/test_issue110_capture.py")
    assert "--confcutdir" in argv and options["timeout"] == 7
    assert options["env"] == {"SAFE": "only"}
    monkeypatch.setattr(capture.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=1))
    with pytest.raises(ValueError, match="controller_tests_failed"):
        capture.controller_tests({}, tmp_path, 107)


def test_every_existing_push_workflow_excludes_diagnostic_branch():
    import fnmatch
    import re

    expected = {
        "android-remote-https.yml": ["dot/android-foreground-agent"],
        "checks.yml": ["main", "codex/**", "dot/**"],
        "container-smoke.yml": ["main", "dot/**", "codex/**"],
        "mumu-adapter-build-only.yml": ["dot/mumu-own-https-runner"],
    }
    files = {p.name: p for p in (ROOT / ".github/workflows").glob("*.yml")}
    assert set(files) == {
        *expected,
        "issue110-native-capture.yml",
        "issue110-setup-only.yml",
        "issue110-native-preflight.yml",
        "issue110-signature-only.yml",
    }
    for name, patterns in expected.items():
        trigger = files[name].read_text().split("\npermissions:")[0]
        match = re.search(r"  push:\s*\n    branches: \[([^\]]+)\]", trigger)
        assert match, name
        actual = [value.strip().strip("\"'") for value in match[1].split(",")]
        assert actual == patterns
        assert not any(
            fnmatch.fnmatchcase("diagnostics/issue110-native-capture", p) for p in actual
        )


def test_out_of_order_capture_sections_are_incomplete_not_errors(capture):
    raw = (
        transcript()
        .replace("_STACK", "_TEMP")
        .replace("_MODULES", "_STACK")
        .replace("_TEMP", "_MODULES")
    )
    assert not capture.parse_capture(raw, "a" * 32)["complete"]


def test_setup_correction_is_single_predecessor_guarded_and_observable():
    workflow = (ROOT / ".github/workflows/issue110-native-capture.yml").read_text()
    predecessor = "github.event.before == '10b699e5db338a785074064f54beed6b2116d0cb'"
    assert workflow.count(predecessor) == 2
    assert "github.event.created" not in workflow
    assert workflow.count("github.run_attempt == 1") == 2
    setup = (ROOT / "scripts/diagnostics/issue110_setup.ps1").read_text()
    assert setup.index("'python_install'") < setup.index("'python_find'")
    assert "@('python', 'install', '3.11.16', '--no-bin')" in setup
    assert "@('python', 'find', '--managed-python', '3.11.16')" in setup
    assert setup.index("IsNullOrWhiteSpace($found)") < setup.index("$found.Trim()")
    assert "WaitForExit([Math]::Min(100, $milliseconds))" in setup and "AddSeconds(300)" in setup
    assert "original_group_started = $false" in setup
    assert "tool_exit = $null" in setup and "tool_exit = $process.ExitCode" in setup
    assert "Write-Error" not in setup and "Write-Output" not in setup
    assert "issue110_setup.ps1" in workflow
    assert "ProcessStartInfo" in setup and "ArgumentList.Add($argument)" in setup
    assert "Start-Process" not in setup
    assert "UV_PYTHON_DOWNLOADS_JSON_URL" in setup and "UV_ASTRAL_MIRROR_URL" in setup
    assert "'UV_WORKING_DIR'" in setup and "'UV_PROJECT'" in setup
    assert "setup_descendant_cleanup = 'unverified'" in setup


def test_managed_base_install_override_is_explicit_and_limited_to_both_write_stages():
    setup = (ROOT / "scripts/diagnostics/issue110_setup.ps1").read_text()
    lines = [line for line in setup.splitlines() if "Invoke-UvStage '" in line]
    writes = [line for line in lines if "@('pip'," in line]
    assert len(writes) == 2
    assert all("'--python', $python, '--break-system-packages'" in line for line in writes)
    assert setup.count("'--break-system-packages'") == 2
    assert "'--system'" not in setup
    assert "UV_BREAK_SYSTEM_PACKAGES" not in setup
    assert "$info.Environment['UV_PYTHON_INSTALL_DIR'] = $installRoot" in setup
    assert "[void](New-Item -ItemType Directory -Path $installRoot)" in setup
    assert "[IO.FileAttributes]::ReparsePoint" in setup


@pytest.mark.parametrize(
    "scenario",
    [
        "success",
        "install_failure",
        "find_failure",
        "empty_find",
        "deadline",
        "timeout",
        "source_override",
        "working_dir_override",
        "project_override",
        "external_path",
        "prefix_collision",
        "traversal_path",
        "junction_path",
        "existing_install_dir",
        "frozen_export_failure",
        "frozen_sync_failure",
        "editable_install_failure",
    ],
)
def test_powershell_setup_stages_fail_closed_without_raw_artifacts(tmp_path, scenario):
    """Mandatory on the Windows runner; this Linux host has no PowerShell runtime."""
    import os
    import shutil
    import subprocess
    import time

    shell = shutil.which("pwsh.exe") or shutil.which("pwsh")
    if shell is None and os.name == "nt":
        installed = Path(os.environ["SystemRoot"]).parent / "Program Files/PowerShell/7/pwsh.exe"
        shell = str(installed) if installed.is_file() else None
    if shell is None:
        if os.name == "nt":
            pytest.fail("PowerShell setup gate prerequisite missing")
        pytest.skip("PowerShell is not installed on this non-Windows host")
    script = ROOT / "scripts/diagnostics/issue110_setup.ps1"
    driver = tmp_path / "setup-test.ps1"
    driver.write_text(
        r"""
param([string]$Setup)
function Get-Command {
    param($Name, $CommandType)
    [pscustomobject]@{Source='fake-uv.exe'}
}
function New-Object {
    param($TypeName)
    if ($TypeName -eq 'System.Diagnostics.ProcessStartInfo') {
        return [System.Diagnostics.ProcessStartInfo]::new()
    }
    $process = [pscustomobject]@{
        StartInfo=$null; ExitCode=0; HasExited=($env:SCENARIO -ne 'timeout')
        StandardOutput=$null; StandardError=$null
    }
    $process | Add-Member -MemberType ScriptMethod -Name Start -Value {
        $arguments = @($this.StartInfo.ArgumentList)
        if ($arguments[0] -ne '--no-config') { $this.ExitCode = 24 }
        if ($arguments[0] -eq '--no-config') { $arguments = $arguments[1..($arguments.Count-1)] }
        $stage = switch ($arguments[0]) {
            'python' { 'python_' + $arguments[1] }
            'export' { 'frozen_export' }
            'pip' { if ($arguments[1] -eq 'sync') { 'frozen_sync' } else { 'editable_install' } }
        }
        $calls = Join-Path $env:RUNNER_TEMP 'calls.txt'
        Add-Content -LiteralPath $calls -Value ($stage + ':' + ($arguments -join '|'))
        if ($stage -eq 'python_install') {
            $owned = Join-Path $env:RUNNER_TEMP 'issue110-python-1'
            if ($this.StartInfo.Environment['UV_PYTHON_INSTALL_DIR'] -ne $owned -or
                '--no-bin' -notin $arguments) {
                $this.ExitCode = 24
            }
            if ($env:SCENARIO -eq 'junction_path') {
                $outside = Join-Path $env:RUNNER_TEMP 'outside'
                [void](New-Item -ItemType Directory -Path $outside)
                $kind = if ($IsWindows) { 'Junction' } else { 'SymbolicLink' }
                $link = Split-Path $env:FAKE_PYTHON
                [void](New-Item -ItemType $kind -Path $link -Target $outside)
            } else {
                [void](New-Item -ItemType Directory -Force -Path (Split-Path $env:FAKE_PYTHON))
            }
            Set-Content -LiteralPath $env:FAKE_PYTHON -Value 'fake interpreter'
        }
        if (($stage -eq 'python_install' -and $env:SCENARIO -eq 'install_failure') -or
            ($stage -eq 'python_find' -and $env:SCENARIO -eq 'find_failure')) {
            $this.ExitCode = 23
        }
        if ($env:SCENARIO -eq ($stage + '_failure')) { $this.ExitCode = 23 }
        # uv 0.12.19 refuses writes to its managed base without this explicit flag.
        if ($arguments[0] -eq 'pip' -and '--break-system-packages' -notin $arguments) {
            $this.ExitCode = 2
        }
        $body = if ($stage -eq 'python_find' -and $env:SCENARIO -ne 'empty_find') {
            $env:FAKE_PYTHON
        } else { '' }
        $bytes = [Text.Encoding]::UTF8.GetBytes($body)
        $this.StandardOutput = [IO.StreamReader]::new([IO.MemoryStream]::new($bytes))
        $errorBytes = [Text.Encoding]::UTF8.GetBytes('PRIVATE_RAW_CANARY')
        $this.StandardError = [IO.StreamReader]::new([IO.MemoryStream]::new($errorBytes))
        return $true
    }
    $process | Add-Member -MemberType ScriptMethod -Name WaitForExit -Value {
        param($ms)
        return $this.HasExited
    }
    $process | Add-Member -MemberType ScriptMethod -Name Kill -Value {
        param($tree)
        $this.HasExited = $true
        Set-Content -LiteralPath (Join-Path $env:RUNNER_TEMP 'killed.txt') -Value $tree
    }
    $process | Add-Member -MemberType ScriptMethod -Name Dispose -Value { }
    return $process
}
if ($env:SCENARIO -eq 'timeout') {
    $env:ISSUE110_SETUP_STARTED = [DateTimeOffset]::UtcNow.AddSeconds(-294).ToUnixTimeSeconds()
}
& $Setup -Group '1'
exit $LASTEXITCODE
""",
        encoding="utf-8",
    )
    install_root = tmp_path / "issue110-python-1"
    python = install_root / "cpython-3.11.16" / "fake python.exe"
    if scenario == "external_path":
        python = tmp_path / "external python.exe"
    elif scenario == "prefix_collision":
        python = tmp_path / "issue110-python-1-other" / "fake python.exe"
    elif scenario == "traversal_path":
        python = install_root / ".." / "external python.exe"
    elif scenario == "junction_path":
        python = install_root / "linked" / "fake python.exe"
    elif scenario == "existing_install_dir":
        install_root.mkdir()
    env = dict(
        os.environ,
        RUNNER_TEMP=str(tmp_path),
        GITHUB_WORKSPACE=str(tmp_path),
        GITHUB_ENV=str(tmp_path / "github-env"),
        SCENARIO=scenario,
        FAKE_PYTHON=str(python),
        ISSUE110_SETUP_STARTED=str(int(time.time()) - (301 if scenario == "deadline" else 0)),
    )
    if scenario == "source_override":
        env["UV_PYTHON_INSTALL_MIRROR"] = "https://invalid.example/PRIVATE_RAW_CANARY"
    elif scenario == "working_dir_override":
        env["UV_WORKING_DIR"] = str(tmp_path)
    elif scenario == "project_override":
        env["UV_PROJECT"] = str(tmp_path)
    result = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-File", str(driver), str(script)],
        env=env,
        capture_output=True,
        timeout=15,
        check=False,
    )
    receipt_text = (tmp_path / "evidence/group-1.json").read_text(encoding="utf-8-sig")
    receipt = json.loads(receipt_text)
    assert "PRIVATE_RAW_CANARY" not in receipt_text
    assert "PRIVATE_RAW_CANARY" not in result.stdout.decode(errors="replace")
    assert "PRIVATE_RAW_CANARY" not in result.stderr.decode(errors="replace")
    calls_path = tmp_path / "calls.txt"
    stages = (
        [line.split(":")[0] for line in calls_path.read_text().splitlines()]
        if calls_path.exists()
        else []
    )
    if scenario == "success":
        assert result.returncode == 0
        assert stages == [
            "python_install",
            "python_find",
            "frozen_export",
            "frozen_sync",
            "editable_install",
        ]
        assert receipt["status"] == "setup_complete" and receipt["original_group_started"] is None
        assert (tmp_path / "github-env").read_text().strip() == f"ISSUE110_PYTHON={python}"
    else:
        assert result.returncode == 1
        assert receipt["status"] == "prerequisites_missing"
        assert receipt["original_group_started"] is False
        assert not (tmp_path / "github-env").exists()
        if scenario in {"source_override", "working_dir_override", "project_override"}:
            assert stages == [] and receipt["blocker"] == "python_source_override"
        elif scenario == "existing_install_dir":
            assert stages == [] and receipt["blocker"] == "python_install_directory_exists"
        elif scenario in {"external_path", "prefix_collision", "traversal_path", "junction_path"}:
            assert stages == ["python_install", "python_find"]
            assert receipt["blocker"] == "python_path_not_owned"
        elif scenario in {
            "frozen_export_failure",
            "frozen_sync_failure",
            "editable_install_failure",
        }:
            order = [
                "python_install",
                "python_find",
                "frozen_export",
                "frozen_sync",
                "editable_install",
            ]
            failed_stage = scenario.removesuffix("_failure")
            assert stages == order[: order.index(failed_stage) + 1]
            assert receipt["setup_stage"] == failed_stage and receipt["tool_exit"] == 23
            assert receipt["blocker"] == "setup_stage_failed"
        elif scenario == "deadline":
            assert stages == [] and receipt["blocker"] == "setup_deadline"
        elif scenario == "timeout":
            assert stages == ["python_install"] and receipt["tool_exit"] is None
            assert (tmp_path / "killed.txt").exists()
        else:
            assert stages == (
                ["python_install"]
                if scenario == "install_failure"
                else ["python_install", "python_find"]
            )
            assert receipt["tool_exit"] == (0 if scenario == "empty_find" else 23)
            assert receipt["blocker"] == (
                "python_path_missing" if scenario == "empty_find" else "setup_stage_failed"
            )


@pytest.mark.parametrize(
    "field,value",
    [
        ("child_exit", 7),
        ("reason", "capture_timeout"),
        ("capture_complete", False),
        ("reporter_seen", False),
        ("cleanup_verified", False),
    ],
)
def test_failed_av_gate_preserves_each_private_free_predicate(
    capture, tmp_path, monkeypatch, field, value
):
    receipt = {}
    calls = []

    def run(cdb, target, cwd, env, directory, seconds):
        calls.append(directory.name)
        code = 0 if directory.name == "exit-0" else 7
        result = dict(
            child_exit=code,
            debugger_exit=0,
            target_pid=123,
            reason="exited",
            elapsed_seconds=1.0,
            cleanup_verified=True,
            capture={"complete": False},
        )
        raw = "SMOKE_PID 123\nSMOKE_OUT\nSMOKE_ERR\nPRIVATE_CANARY\n"
        if directory.name == "av":
            result["child_exit"] = 0xC0000005
            result["capture"] = {"complete": True, "rejection": None}
            raw += "Timeout (0:01:00)!\n"
            if field == "capture_complete":
                result["capture"]["complete"] = value
                result["capture"]["rejection"] = "markers_missing_or_duplicated"
            elif field == "reporter_seen":
                raw = raw.replace("Timeout (0:01:00)!", "")
            else:
                result[field] = value
        return result, raw

    monkeypatch.setattr(capture, "run_one", run)
    with pytest.raises(ValueError, match="av_reporter_smoke_failed"):
        capture.smoke("cdb.exe", {}, tmp_path, capture.time.monotonic() + 300, receipt=receipt)
    assert calls == ["exit-0", "exit-7", "av"]
    assert receipt["stage"] == "av"
    assert receipt["results"]["exit-0"]["passed"] is True
    assert receipt["results"]["exit-7"]["passed"] is True
    av = receipt["results"]["av"]
    assert av[field] == value and av["passed"] is False
    assert av["debugger_exit"] == 0
    assert "PRIVATE_CANARY" not in json.dumps(receipt)


@pytest.mark.parametrize("failure", ["timeout", "json"])
def test_debugger_check_failure_keeps_fixed_substage_without_private_error(
    capture, monkeypatch, tmp_path, failure
):
    from types import SimpleNamespace

    receipt = {}
    monkeypatch.setattr(capture.Path, "is_file", lambda self: True)
    monkeypatch.setattr(capture, "x64_pe", lambda path: True)

    def run(*args, **kwargs):
        if failure == "timeout":
            raise capture.subprocess.TimeoutExpired(
                "PRIVATE_CANARY", kwargs["timeout"], output=b"PRIVATE_CANARY"
            )
        return SimpleNamespace(returncode=0, stdout=b"PRIVATE_CANARY", stderr=b"")

    monkeypatch.setattr(capture.subprocess, "run", run)
    error = capture.subprocess.TimeoutExpired if failure == "timeout" else json.JSONDecodeError
    with pytest.raises(error):
        capture.installed_debugger(
            {"TEMP": str(tmp_path / "temp"), "SystemRoot": "windows"},
            capture.time.monotonic() + 300,
            receipt=receipt,
        )
    assert receipt["stage"] == ("signature_check" if failure == "timeout" else "signature_json")
    assert receipt["tool_exit"] == (None if failure == "timeout" else 0)
    assert "PRIVATE_CANARY" not in json.dumps(receipt)


@pytest.mark.parametrize("fail_stage", [None, "installed_debugger", "smoke"])
def test_preflight_entry_cannot_consume_or_launch_original(
    capture, monkeypatch, tmp_path, fail_stage
):
    import sys

    output = tmp_path / "receipt.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "preflight",
            "--subject",
            str(tmp_path),
            "--private",
            str(tmp_path / "private"),
            "--output",
            str(output),
            "--group",
            "1",
            "--setup-started",
            str(capture.time.time()),
        ],
    )
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/diagnostics/issue110-native-capture")
    monkeypatch.setenv("SystemRoot", "windows")
    monkeypatch.setattr(capture, "verify_subject", lambda *a: {})

    def debugger(*a, receipt=None):
        if fail_stage == "installed_debugger":
            receipt.update(stage="signature_check", tool_exit=None)
            raise capture.subprocess.TimeoutExpired("PRIVATE_CANARY", 30, output=b"PRIVATE_CANARY")
        return "cdb.exe", []

    def smoke(*a, receipt=None):
        receipt.update(stage="av", results={"av": {"child_exit": 7, "passed": False}})
        if fail_stage == "smoke":
            raise ValueError("av_reporter_smoke_failed")
        return receipt

    monkeypatch.setattr(capture, "installed_debugger", debugger)
    monkeypatch.setattr(capture, "controller_tests", lambda *a: True)
    monkeypatch.setattr(capture, "smoke", smoke)

    def prohibited(*a, **kw):
        pytest.fail("preflight must never load/consume/invoke an original group")

    for name in ("load_manifest", "consume", "pytest_argv", "run_one"):
        monkeypatch.setattr(capture, name, prohibited)
    code = capture.main(preflight_only=True)
    receipt = json.loads(output.read_text())
    assert code == (1 if fail_stage else 0)
    assert receipt["original_invocation_attempted"] is False
    assert receipt["original_group_started"] is False
    assert "PRIVATE_CANARY" not in output.read_text()
    if fail_stage:
        assert receipt["stage"] == fail_stage
        if fail_stage == "installed_debugger":
            assert receipt["error_category"] == "subprocess_timeout"
        else:
            assert receipt["smoke"]["results"]["av"]["child_exit"] == 7
    else:
        assert receipt["status"] == "preflight_passed"


def test_capture_rejection_enum_identifies_missing_protocol_without_raw_data(capture):
    result = capture.parse_capture("PRIVATE_CANARY", "a" * 32)
    assert result["rejection"] == "markers_missing_or_duplicated"
    assert capture.parse_capture(transcript(), "a" * 32)["rejection"] is None
    assert "PRIVATE_CANARY" not in json.dumps(result)


def test_dedicated_preflight_script_hardcodes_only_preflight(monkeypatch):
    import runpy
    import sys
    from types import SimpleNamespace

    calls = []
    monkeypatch.setitem(
        sys.modules, "issue110_capture", SimpleNamespace(main=lambda **kw: calls.append(kw) or 0)
    )
    path = ROOT / "scripts/diagnostics/issue110_preflight.py"
    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(path), run_name="__main__")
    assert error.value.code == 0
    assert calls == [{"preflight_only": True}]


@pytest.mark.parametrize("failed_stage", ["exit-0", "exit-7", "timeout", None])
def test_all_smoke_stages_preserve_success_or_failure_before_raise(
    capture, monkeypatch, tmp_path, failed_stage
):
    receipt = {}
    calls = []

    def run(cdb, target, cwd, env, directory, seconds):
        name = directory.name
        calls.append(name)
        child_exit = {"exit-0": 0, "exit-7": 7, "av": 0xC0000005, "timeout": None}[name]
        result = dict(
            child_exit=child_exit,
            debugger_exit=7 if name == "av" else 0,
            target_pid=123,
            reason="timeout" if name == "timeout" else "exited",
            elapsed_seconds=1.0,
            cleanup_verified=name != failed_stage,
            capture={"complete": name == "av", "rejection": None},
        )
        raw = (
            "SMOKE_PID 123\nSMOKE_OUT\nSMOKE_ERR\nTimeout (0:01:00)!\n"
            "DESCENDANT_STARTED\nPRIVATE_CANARY"
        )
        return result, raw

    monkeypatch.setattr(capture, "run_one", run)
    if failed_stage:
        with pytest.raises(ValueError):
            capture.smoke("cdb.exe", {}, tmp_path, capture.time.monotonic() + 300, receipt=receipt)
        assert receipt["stage"] == failed_stage
        assert calls[-1] == failed_stage
        assert receipt["results"][failed_stage]["passed"] is False
    else:
        capture.smoke("cdb.exe", {}, tmp_path, capture.time.monotonic() + 300, receipt=receipt)
        assert receipt["stage"] == "complete"
        assert len(calls) == 4
        assert all(item["passed"] for item in receipt["results"].values())
        assert receipt["results"]["av"]["debugger_exit"] == 7
    assert "PRIVATE_CANARY" not in json.dumps(receipt)


def test_native_preflight_workflow_is_one_job_without_original_entry():
    path = ROOT / ".github/workflows/issue110-native-preflight.yml"
    assert path.exists()
    workflow = path.read_text()
    assert "github.event.before == '5d8bdd26471994a682f79ec93217897713fdbe47'" in workflow
    assert "github.repository == 'Maximora-byte/swu-happyrun'" in workflow
    assert "github.ref == 'refs/heads/diagnostics/issue110-native-capture'" in workflow
    assert workflow.count("github.run_attempt == 1") == 1
    assert "workflow_dispatch" not in workflow and "pull_request" not in workflow
    assert "timeout-minutes: 8" in workflow and "strategy:" not in workflow
    assert "matrix." not in workflow and "aggregate:" not in workflow
    assert workflow.count("issue110_preflight.py") == 1
    assert "issue110_capture.py" not in workflow
    assert "-Group '1'" in workflow and "--group '1'" in workflow
    assert "ISSUE110_SETUP_STARTED" in workflow
    assert "3.11.16" in workflow and '"0.12.19"' in workflow
    assert "ref: 6a0dac84bf66125c7e2bd506bb0d8c988b1dcc34" in workflow
    assert "retention-days: 1" in workflow
    assert "*.log" not in workflow and "*.xml" not in workflow and "*.dmp" not in workflow
    for name in ("issue110-native-capture.yml", "issue110-setup-only.yml"):
        assert "5d8bdd26471994a682f79ec93217897713fdbe47" not in (path.parent / name).read_text()


def signature_markers(count=14, nonce="b" * 32):
    return "".join(f"SWU_SIG_{nonce} {index} {index * 10}\n" for index in range(count)).encode()


def signature_markers_v2(count=16, nonce="b" * 32):
    return "".join(f"SWU_SIG_V2_{nonce} {index} {index * 10}\n" for index in range(count)).encode()


def signature_markers_v3(count=18, nonce="b" * 32):
    return "".join(f"SWU_SIG_V3_{nonce} {index} {index * 10}\n" for index in range(count)).encode()


def signature_markers_v4(count=27, nonce="b" * 32):
    return "".join(f"SWU_SIG_V4_{nonce} {index} {index * 10}\n" for index in range(count)).encode()


@pytest.mark.parametrize("count", [0, 1, 2, 3, 4, 5, 9, 13, 14])
def test_signature_progress_accepts_only_the_fixed_ordered_prefix(capture, count):
    result = capture.parse_signature_progress(signature_markers(count), "b" * 32)
    assert result["marker_count"] == count
    assert result["complete"] is (count == 14)
    assert result["elapsed_ms"] == ((count - 1) * 10 if count else None)
    assert result["rejection"] == (None if count == 14 else "incomplete" if count else "no_markers")
    if count == 2:
        assert result["last_stage"] == "trust_start"
        assert result["file_index"] == 0
    if count == 9:
        assert result["last_stage"] == "version_done"
        assert result["file_index"] == 1


@pytest.mark.parametrize(
    "raw",
    [
        signature_markers(2) + signature_markers(2),
        signature_markers(1) + b"SWU_SIG_" + b"b" * 32 + b" 9 10\n",
        signature_markers(2) + b"SWU_SIG_" + b"b" * 32 + b" 2 1\n",
        b"SWU_SIG_" + b"b" * 32 + b" 0 -1\n",
        b"SWU_SIG_" + b"b" * 32 + b" 0 300001\n",
        b"SWU_SIG_" + b"b" * 32 + b" 0 PRIVATE_CANARY\n",
        signature_markers() + b"SWU_SIG_" + b"b" * 32 + b" 14 140\n",
    ],
)
def test_signature_progress_rejects_malformed_ambiguous_or_nonmonotonic_markers(capture, raw):
    result = capture.parse_signature_progress(raw, "b" * 32)
    assert result["complete"] is False and result["marker_count"] == 0
    assert result["rejection"] == "invalid_markers"
    assert "PRIVATE_CANARY" not in json.dumps(result)


def test_signature_progress_preserves_only_complete_lines_before_truncation(capture):
    raw = b"PRIVATE_CANARY\n" + signature_markers(2) + b"SWU_SIG_" + b"b" * 32 + b" 2 "
    result = capture.parse_signature_progress(raw, "b" * 32)
    assert result["marker_count"] == 2 and result["last_stage"] == "trust_start"
    assert result["rejection"] == "truncated" and result["complete"] is False
    assert "PRIVATE_CANARY" not in json.dumps(result)
    assert (
        capture.parse_signature_progress(signature_markers(nonce="c" * 32), "b" * 32)[
            "marker_count"
        ]
        == 0
    )
    assert capture.parse_signature_progress(None, "b" * 32)["rejection"] == "no_markers"
    assert capture.parse_signature_progress(b"X" * 65537, "b" * 32)["rejection"] == "output_limit"


@pytest.mark.parametrize("deadline, expected_timeout", [(150, 30), (105, 5)])
@pytest.mark.parametrize(
    "count, last_stage",
    [
        (8, "version_start"),
        (9, "item_returned"),
        (10, "version_info_returned"),
        (11, "version_parts_returned"),
    ],
)
def test_signature_timeout_keeps_safe_partial_markers_and_the_original_timeout(
    capture, monkeypatch, tmp_path, deadline, expected_timeout, count, last_stage
):
    from types import SimpleNamespace

    receipt = {}
    monkeypatch.setattr(capture.Path, "is_file", lambda self: True)
    monkeypatch.setattr(capture, "x64_pe", lambda path: True)
    monkeypatch.setattr(capture.uuid, "uuid4", lambda: SimpleNamespace(hex="b" * 32))
    monkeypatch.setattr(capture.time, "monotonic", lambda: 100)
    error = capture.subprocess.TimeoutExpired(
        "PRIVATE_CANARY",
        30,
        output=b"PRIVATE_CANARY",
        stderr=signature_markers_v4(count) + b"PRIVATE_CANARY\n",
    )

    def run(argv, **kwargs):
        assert kwargs["timeout"] == expected_timeout and kwargs["check"] is False
        assert argv[1:4] == ["-NoProfile", "-NonInteractive", "-File"]
        script = Path(argv[4]).read_text()
        assert "Get-AuthenticodeSignature -LiteralPath $p" in script
        assert "$s.Status -ne 'Valid'" in script
        assert "$s.SignerCertificate.Subject -notmatch $publisher" in script
        assert "Microsoft Corporation" in script
        assert "[Console]::Error.Flush()" in script
        assert script.index("Mark 0") < script.index("foreach($p in $args)")
        manifest = (
            "$manifest=[IO.Path]::Combine($PSHOME,"
            "'Modules\\Microsoft.PowerShell.Security\\Microsoft.PowerShell.Security.psd1')"
        )
        presence = "if(-not [IO.File]::Exists($manifest)) {exit 4}"
        imported = "$null=Import-Module -Name $manifest -ErrorAction Stop"
        probe = (
            "$null=Get-Command -ListImported -Name Get-AuthenticodeSignature "
            "-CommandType Cmdlet -ErrorAction Stop"
        )
        assert script.index("Mark 0") < script.index(manifest) < script.index(presence)
        assert script.index(presence) < script.index("Mark 1")
        assert script.index("Mark 1") < script.index(imported) < script.index("Mark 2")
        assert script.index("Mark 3") < script.index(probe) < script.index("Mark 4")
        assert script.index("Mark 4") < script.index("foreach($p in $args)")
        assert script.count("Import-Module") == script.count("Get-Command") == 1
        for excluded in ("Join-Path", "Test-Path", "-Force", "PSModuleAutoLoadingPreference"):
            assert excluded not in script
        call = "$s=Get-AuthenticodeSignature -LiteralPath $p"
        assert script.index("Mark (5+7*$i)") < script.index(call)
        assert script.index(call) < script.index("Mark (6+7*$i)")
        ordered = [
            "Mark (7+7*$i)",
            "$item=Get-Item -LiteralPath $p;",
            "Mark (8+7*$i)",
            "$v=$item.VersionInfo;",
            "Mark (9+7*$i)",
            "$parts=@($v.FileMajorPart,$v.FileMinorPart,$v.FileBuildPart,$v.FilePrivatePart);",
            "Mark (10+7*$i)",
            "$items+=@{name=[IO.Path]::GetFileName($p); version=($parts -join '.')};",
            "Mark (11+7*$i)",
            "ConvertTo-Json -Compress -InputObject @($items)",
            "Mark 26",
        ]
        positions = [script.index(statement) for statement in ordered]
        assert positions == sorted(positions)
        assert script.count("Get-Item") == script.count(".VersionInfo") == 1
        assert "Microsoft.PowerShell.Management" not in script
        assert "FileVersionInfo]::GetVersionInfo" not in script
        raise error

    monkeypatch.setattr(capture.subprocess, "run", run)
    with pytest.raises(capture.subprocess.TimeoutExpired) as raised:
        capture.installed_debugger(
            {"TEMP": str(tmp_path / "temp"), "SystemRoot": "windows"}, deadline, receipt=receipt
        )
    assert raised.value is error
    assert receipt["tool_exit"] is None and receipt["stage"] == "signature_check"
    assert receipt["progress"]["marker_count"] == count
    assert receipt["progress"]["last_stage"] == last_stage
    assert receipt["progress"]["file_index"] == 0
    assert receipt["run_timeout_seconds"] == expected_timeout
    assert receipt["run_elapsed_ms"] == 0
    assert "PRIVATE_CANARY" not in json.dumps(receipt)


@pytest.mark.parametrize("code", [0, 3])
def test_signature_markers_never_replace_process_trust_verdict(
    capture, monkeypatch, tmp_path, code
):
    from types import SimpleNamespace

    receipt = {}
    monkeypatch.setattr(capture.Path, "is_file", lambda self: True)
    monkeypatch.setattr(capture, "x64_pe", lambda path: True)
    monkeypatch.setattr(capture, "sha256", lambda path: "0" * 64)
    monkeypatch.setattr(capture.uuid, "uuid4", lambda: SimpleNamespace(hex="b" * 32))
    data = [
        {"name": name, "version": "10.0.26100.8249"}
        for name in ("cdb.exe", "dbgeng.dll", "dbghelp.dll")
    ]
    monkeypatch.setattr(
        capture.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=code, stdout=json.dumps(data).encode(), stderr=signature_markers_v4()
        ),
    )
    if code:
        with pytest.raises(ValueError, match="debugger_signature_unverified"):
            capture.installed_debugger(
                {"TEMP": str(tmp_path / "temp"), "SystemRoot": "windows"},
                capture.time.monotonic() + 300,
                receipt=receipt,
            )
    else:
        _, binaries = capture.installed_debugger(
            {"TEMP": str(tmp_path / "temp"), "SystemRoot": "windows"},
            capture.time.monotonic() + 300,
            receipt=receipt,
        )
        assert binaries == [item | {"sha256": "0" * 64} for item in data]
    assert receipt["tool_exit"] == code
    assert receipt["progress"]["complete"] is True
    assert receipt["stage"] == ("signature_check" if code else "complete")


@pytest.mark.parametrize(
    "suffix, rejection",
    [
        (b"SWU_SIG_" + b"b" * 32 + b"X 0 1\n", "invalid_markers"),
        (b"SWU_SIG_" + b"b" * 32 + b"\t0 1\n", "invalid_markers"),
        (b"SWU_SIG_" + b"b" * 32 + b"\n", "invalid_markers"),
        (b"SWU_SIG_" + b"b" * 32, "truncated"),
        (b"SWU_SIG_bbbb", "truncated"),
    ],
)
def test_signature_same_nonce_corruption_cannot_leave_complete(capture, suffix, rejection):
    result = capture.parse_signature_progress(signature_markers() + suffix, "b" * 32)
    assert result["complete"] is False
    assert result["rejection"] == rejection


@pytest.mark.parametrize("failure", [None, "subject", "timeout", "trust", "expired", "scope"])
def test_signature_only_entry_cannot_reach_native_or_original_paths(
    capture, monkeypatch, tmp_path, failure
):
    import runpy
    import sys

    path = ROOT / "scripts/diagnostics/issue110_signature_only.py"
    assert path.exists(), "fixed signature-only entry is missing"
    output = tmp_path / "receipt.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(path),
            "--subject",
            str(tmp_path),
            "--private",
            str(tmp_path / "private"),
            "--output",
            str(output),
            "--setup-started",
            "600" if failure == "expired" else "990",
        ],
    )
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2" if failure == "scope" else "1")
    monkeypatch.setenv("GITHUB_REPOSITORY", "Maximora-byte/swu-happyrun")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/diagnostics/issue110-native-capture")
    monkeypatch.setenv("SystemRoot", "windows")
    monkeypatch.setitem(sys.modules, "issue110_capture", capture)
    monkeypatch.setattr(capture.time, "time", lambda: 1000)
    monkeypatch.setattr(capture.time, "monotonic", lambda: 200)
    calls = []

    def subject(path, deadline):
        calls.append("subject")
        assert deadline == 490
        if failure == "subject":
            raise ValueError("subject_mismatch")
        return {}

    def debugger(env, deadline, *, receipt):
        calls.append("signature")
        assert deadline == 490
        assert "GITHUB_TOKEN" not in env
        receipt.update(stage="signature_check", tool_exit=None)
        if failure == "timeout":
            receipt["progress"] = capture.parse_signature_progress(signature_markers(2), "b" * 32)
            raise capture.subprocess.TimeoutExpired("PRIVATE_CANARY", 30, output=b"PRIVATE_CANARY")
        if failure == "trust":
            receipt["tool_exit"] = 3
            raise ValueError("debugger_signature_unverified")
        receipt.update(stage="complete", tool_exit=0)
        return "cdb.exe", []

    def prohibited(*args, **kwargs):
        pytest.fail("signature-only entry reached a prohibited controller/native/original path")

    for name in (
        "main",
        "controller_tests",
        "smoke",
        "run_one",
        "load_manifest",
        "consume",
        "pytest_argv",
        "cdb_argv",
        "debugger_scripts",
    ):
        monkeypatch.setattr(capture, name, prohibited)
    monkeypatch.setattr(capture, "verify_subject", subject)
    monkeypatch.setattr(capture, "installed_debugger", debugger)
    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(path), run_name="__main__")
    assert error.value.code == (1 if failure else 0)
    report = json.loads(output.read_text())
    assert report["mode"] == "signature_only"
    assert report["original_invocation_attempted"] is False
    assert report["original_group_started"] is False
    assert report["debugger_invocation_attempted"] is False
    assert report["root_cause_established"] is False
    assert report["signature_budget_seconds"] == 30
    assert report["setup_budget_seconds"] == 300
    assert "PRIVATE_CANARY" not in output.read_text()
    assert calls == (
        []
        if failure in ("expired", "scope")
        else ["subject"]
        if failure == "subject"
        else ["subject", "signature"]
    )
    if failure == "timeout":
        assert report["error_category"] == "subprocess_timeout"
        assert report["debugger_check"]["progress"]["last_stage"] == "trust_start"
        assert report["debugger_check"]["tool_exit"] is None
    elif not failure:
        assert report["status"] == "signature_verified"


def test_signature_only_entry_has_no_mode_override(capture, monkeypatch, tmp_path):
    import runpy
    import sys

    path = ROOT / "scripts/diagnostics/issue110_signature_only.py"
    assert path.exists()
    monkeypatch.setitem(sys.modules, "issue110_capture", capture)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(path),
            "--subject",
            str(tmp_path),
            "--private",
            str(tmp_path / "private"),
            "--output",
            str(tmp_path / "receipt.json"),
            "--setup-started",
            "0",
            "--group",
            "1",
        ],
    )
    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(path), run_name="__main__")
    assert error.value.code == 2
    assert not (tmp_path / "receipt.json").exists()


def test_signature_only_workflow_has_one_spent_predecessor_and_no_wider_entry():
    path = ROOT / ".github/workflows/issue110-signature-only.yml"
    assert path.exists(), "signature-only workflow is missing"
    workflow = path.read_text()
    predecessor = "2f32cc59ca1c781ae65b6c2fb8c156de39a3dc66"
    assert workflow.count("github.event.before == '" + predecessor + "'") == 1
    assert "github.repository == 'Maximora-byte/swu-happyrun'" in workflow
    assert "github.ref == 'refs/heads/diagnostics/issue110-native-capture'" in workflow
    assert workflow.count("github.run_attempt == 1") == 1
    assert 'branches: ["diagnostics/issue110-native-capture"]' in workflow
    assert "timeout-minutes: 8" in workflow
    assert "ISSUE110_SETUP_STARTED" in workflow and "issue110_setup.ps1 -Group '1'" in workflow
    assert "3.11.16" in workflow and '"0.12.19"' in workflow
    assert "ref: 6a0dac84bf66125c7e2bd506bb0d8c988b1dcc34" in workflow
    assert workflow.count("issue110_signature_only.py") == 1
    for excluded in (
        "workflow_dispatch",
        "pull_request",
        "strategy:",
        "matrix.",
        "aggregate:",
        "issue110_capture.py",
        "issue110_preflight.py",
        "--group",
        "pytest",
        "cdb.exe",
    ):
        assert excluded not in workflow
    published = workflow.split("          path: |\n")[1].split("          if-no-files-found:")[0]
    assert published.split() == ["evidence/group-1.json", "evidence/signature.json"]
    assert "retention-days: 1" in workflow
    for other in path.parent.glob("*.yml"):
        if other != path:
            assert predecessor not in other.read_text()


@pytest.mark.parametrize(
    "count, stage, file_index",
    [
        (0, None, None),
        (1, "script_start", None),
        (2, "resolve_start", None),
        (3, "resolve_done", None),
        (4, "trust_start", 0),
        (5, "trust_returned", 0),
        (6, "version_start", 0),
        (7, "version_done", 0),
        (8, "trust_start", 1),
        (12, "trust_start", 2),
        (15, "version_done", 2),
        (16, "script_done", None),
    ],
)
def test_signature_v2_maps_discovery_without_reinterpreting_legacy(
    capture, count, stage, file_index
):
    result = capture.parse_signature_progress(signature_markers_v2(count), "b" * 32, version=2)
    assert result["protocol_version"] == 2
    assert result["marker_count"] == count
    assert result["last_stage"] == stage and result["file_index"] == file_index
    assert result["complete"] is (count == 16)
    assert (
        capture.parse_signature_progress(signature_markers(2), "b" * 32)["last_stage"]
        == "trust_start"
    )


@pytest.mark.parametrize("version", [-1, 0, 5, True, "2"])
def test_signature_progress_rejects_unsupported_protocol(capture, version):
    result = capture.parse_signature_progress(signature_markers_v2(), "b" * 32, version=version)
    assert result["rejection"] == "unsupported_version"
    assert result["complete"] is False and result["marker_count"] == 0


def test_archived_two_marker_signature_receipt_keeps_legacy_meaning(capture):
    raw = (
        b"SWU_SIG_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb 0 13\n"
        b"SWU_SIG_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb 1 27\n"
    )
    result = capture.parse_signature_progress(raw, "b" * 32)
    assert result["last_stage"] == "trust_start" and result["file_index"] == 0
    assert result["checkpoints_ms"] == [13, 27] and result["complete"] is False
    assert capture.parse_signature_progress(raw, "b" * 32, version=2)["marker_count"] == 0


@pytest.mark.parametrize(
    "raw, rejection",
    [
        (signature_markers(), "no_markers"),
        (signature_markers_v2(2) + signature_markers_v2(2), "invalid_markers"),
        (signature_markers_v2(2) + b"SWU_SIG_V2_" + b"b" * 32 + b" 3 30\n", "invalid_markers"),
        (signature_markers_v2(2) + b"SWU_SIG_V2_" + b"b" * 32 + b" 2 1\n", "invalid_markers"),
        (signature_markers_v2() + b"SWU_SIG_V2_" + b"b" * 32 + b"\t16 160\n", "invalid_markers"),
        (signature_markers_v2(2) + b"SWU_SIG_V2_" + b"b" * 32 + b" 2 ", "truncated"),
        (signature_markers_v2() + b"SWU_SIG_V2_bbbb", "truncated"),
    ],
)
def test_signature_v2_rejects_foreign_malformed_and_truncated_streams(capture, raw, rejection):
    result = capture.parse_signature_progress(raw, "b" * 32, version=2)
    assert not result["complete"] and result["rejection"] == rejection
    if rejection == "truncated" and result["marker_count"] == 2:
        assert result["last_stage"] == "resolve_start" and result["file_index"] is None
    assert not capture.parse_signature_progress(signature_markers_v2(), "b" * 32)["complete"]


@pytest.mark.parametrize(
    "outcome, duration", [("success", 0.125), ("trust", 0.25), ("timeout", 30.75), ("launch", 0.01)]
)
def test_signature_parent_elapsed_is_total_call_not_script_or_timeout(
    capture, monkeypatch, tmp_path, outcome, duration
):
    from types import SimpleNamespace

    clock = [100.0]
    calls = []
    receipt = {}
    monkeypatch.setattr(capture.Path, "is_file", lambda self: True)
    monkeypatch.setattr(capture, "x64_pe", lambda path: True)
    monkeypatch.setattr(capture, "sha256", lambda path: "0" * 64)
    monkeypatch.setattr(capture.uuid, "uuid4", lambda: SimpleNamespace(hex="b" * 32))
    monkeypatch.setattr(capture.time, "monotonic", lambda: clock[0])
    original_parser = capture.parse_signature_progress

    def parse(*args, **kwargs):
        clock[0] += 1  # Parsing time must not be included in the parent subprocess-call metric.
        return original_parser(*args, **kwargs)

    monkeypatch.setattr(capture, "parse_signature_progress", parse)
    error = (
        capture.subprocess.TimeoutExpired("PRIVATE_CANARY", 30, stderr=signature_markers_v4(2))
        if outcome == "timeout"
        else OSError("PRIVATE_CANARY")
    )
    data = [
        {"name": name, "version": "10.0.26100.8249"}
        for name in ("cdb.exe", "dbgeng.dll", "dbghelp.dll")
    ]

    def run(argv, **kwargs):
        calls.append(argv)
        assert kwargs["timeout"] == 30
        clock[0] += duration
        if outcome in ("timeout", "launch"):
            raise error
        return SimpleNamespace(
            returncode=3 if outcome == "trust" else 0,
            stdout=json.dumps(data).encode(),
            stderr=signature_markers_v4(),
        )

    monkeypatch.setattr(capture.subprocess, "run", run)
    if outcome == "success":
        capture.installed_debugger(
            {"TEMP": str(tmp_path / "temp"), "SystemRoot": "windows"}, 150, receipt=receipt
        )
    elif outcome == "trust":
        with pytest.raises(ValueError, match="debugger_signature_unverified"):
            capture.installed_debugger(
                {"TEMP": str(tmp_path / "temp"), "SystemRoot": "windows"}, 150, receipt=receipt
            )
    else:
        with pytest.raises(type(error)) as raised:
            capture.installed_debugger(
                {"TEMP": str(tmp_path / "temp"), "SystemRoot": "windows"}, 150, receipt=receipt
            )
        assert raised.value is error
    assert len(calls) == 1
    assert receipt["run_elapsed_ms"] == round(duration * 1000, 3)
    assert receipt["run_timeout_seconds"] == 30
    assert "PRIVATE_CANARY" not in json.dumps(receipt)
    if outcome == "timeout":
        assert receipt["run_elapsed_ms"] > receipt["run_timeout_seconds"] * 1000
        assert receipt["progress"]["elapsed_ms"] == 10
        assert receipt["progress"]["last_stage"] == "import_start"


def test_signature_expired_budget_records_no_call_elapsed(capture, monkeypatch, tmp_path):
    receipt = {}
    monkeypatch.setattr(capture.Path, "is_file", lambda self: True)
    monkeypatch.setattr(capture, "x64_pe", lambda path: True)
    monkeypatch.setattr(capture.time, "monotonic", lambda: 100)
    monkeypatch.setattr(
        capture.subprocess, "run", lambda *a, **kw: pytest.fail("expired budget launched a process")
    )
    with pytest.raises(ValueError, match="setup_budget_exhausted"):
        capture.installed_debugger(
            {"TEMP": str(tmp_path / "temp"), "SystemRoot": "windows"}, 100, receipt=receipt
        )
    assert receipt["run_elapsed_ms"] is None and receipt["run_timeout_seconds"] is None


@pytest.mark.parametrize(
    "end_clock",
    [
        RuntimeError("PRIVATE_CANARY"),
        OSError("PRIVATE_CANARY"),
        float("nan"),
        float("inf"),
        99.9,
        1e308,
    ],
)
def test_signature_invalid_end_clock_never_replaces_original_timeout(
    capture, monkeypatch, tmp_path, end_clock
):
    receipt = {}
    clocks = iter([100.0, 100.0, end_clock])
    monkeypatch.setattr(capture.Path, "is_file", lambda self: True)
    monkeypatch.setattr(capture, "x64_pe", lambda path: True)

    def clock():
        value = next(clocks)
        if isinstance(value, Exception):
            raise value
        return value

    error = capture.subprocess.TimeoutExpired("PRIVATE_CANARY", 30)

    def run(*args, **kwargs):
        raise error

    monkeypatch.setattr(capture.time, "monotonic", clock)
    monkeypatch.setattr(capture.subprocess, "run", run)
    with pytest.raises(capture.subprocess.TimeoutExpired) as raised:
        capture.installed_debugger(
            {"TEMP": str(tmp_path / "temp"), "SystemRoot": "windows"}, 150, receipt=receipt
        )
    assert raised.value is error
    assert receipt["run_elapsed_ms"] is None
    assert receipt["tool_exit"] is None
    assert "PRIVATE_CANARY" not in json.dumps(receipt, allow_nan=False)


@pytest.mark.parametrize(
    "count, stage, file_index",
    [
        (0, None, None),
        (1, "script_start", None),
        (2, "import_start", None),
        (3, "import_done", None),
        (4, "resolve_start", None),
        (5, "resolve_done", None),
        (6, "trust_start", 0),
        (7, "trust_returned", 0),
        (8, "version_start", 0),
        (9, "version_done", 0),
        (10, "trust_start", 1),
        (14, "trust_start", 2),
        (17, "version_done", 2),
        (18, "script_done", None),
    ],
)
def test_signature_v3_separates_fixed_import_from_loaded_command_lookup(
    capture, count, stage, file_index
):
    result = capture.parse_signature_progress(signature_markers_v3(count), "b" * 32, version=3)
    assert result["protocol_version"] == 3
    assert result["marker_count"] == count
    assert result["last_stage"] == stage and result["file_index"] == file_index
    assert result["complete"] is (count == 18)


def test_archived_v2_two_marker_receipt_is_still_resolve_not_import(capture):
    raw = (
        b"SWU_SIG_V2_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb 0 10\n"
        b"SWU_SIG_V2_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb 1 16\n"
    )
    result = capture.parse_signature_progress(raw, "b" * 32, version=2)
    assert result["last_stage"] == "resolve_start" and result["file_index"] is None
    assert result["checkpoints_ms"] == [10, 16] and result["complete"] is False
    assert capture.parse_signature_progress(raw, "b" * 32, version=3)["marker_count"] == 0


@pytest.mark.parametrize(
    "raw, rejection",
    [
        (signature_markers(), "no_markers"),
        (signature_markers_v2(), "no_markers"),
        (signature_markers_v3(2) + signature_markers_v3(2), "invalid_markers"),
        (signature_markers_v3(2) + b"SWU_SIG_V3_" + b"b" * 32 + b" 3 30\n", "invalid_markers"),
        (signature_markers_v3(2) + b"SWU_SIG_V3_" + b"b" * 32 + b" 2 1\n", "invalid_markers"),
        (signature_markers_v3() + b"SWU_SIG_V3_" + b"b" * 32 + b"\t18 180\n", "invalid_markers"),
        (signature_markers_v3(2) + b"SWU_SIG_V3_" + b"b" * 32 + b" 2 ", "truncated"),
        (signature_markers_v3() + b"SWU_SIG_V3_bbbb", "truncated"),
    ],
)
def test_signature_v3_rejects_foreign_malformed_and_truncated_streams(capture, raw, rejection):
    result = capture.parse_signature_progress(raw, "b" * 32, version=3)
    assert not result["complete"] and result["rejection"] == rejection
    if rejection == "truncated" and result["marker_count"] == 2:
        assert result["last_stage"] == "import_start" and result["file_index"] is None
    for version in (1, 2):
        legacy = capture.parse_signature_progress(signature_markers_v3(), "b" * 32, version=version)
        assert legacy["marker_count"] == 0 and not legacy["complete"]


@pytest.mark.parametrize("prefix_count", [0, 1, 2])
def test_signature_missing_fixed_manifest_is_explicit_without_raw_error_or_fallback(
    capture, monkeypatch, tmp_path, prefix_count
):
    from types import SimpleNamespace

    receipt = {}
    calls = []
    monkeypatch.setattr(capture.Path, "is_file", lambda self: True)
    monkeypatch.setattr(capture, "x64_pe", lambda path: True)
    monkeypatch.setattr(capture.uuid, "uuid4", lambda: SimpleNamespace(hex="b" * 32))
    monkeypatch.setattr(
        capture, "sha256", lambda path: pytest.fail("missing manifest hashed files")
    )

    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(
            returncode=4,
            stdout=b"PRIVATE_CANARY",
            stderr=signature_markers_v4(prefix_count) + b"PRIVATE_CANARY\n",
        )

    monkeypatch.setattr(capture.subprocess, "run", run)
    with pytest.raises(ValueError, match="^debugger_signature_unverified$"):
        capture.installed_debugger(
            {"TEMP": str(tmp_path / "temp"), "SystemRoot": "windows"},
            capture.time.monotonic() + 300,
            receipt=receipt,
        )
    assert len(calls) == 1 and receipt["tool_exit"] == 4
    if prefix_count == 1:
        assert receipt["stage"] == "security_module_manifest"
        assert receipt["blocker"] == "manifest_unavailable"
    else:
        assert receipt["stage"] == "signature_check" and "blocker" not in receipt
    assert not receipt["progress"]["complete"]
    assert "PRIVATE_CANARY" not in json.dumps(receipt, allow_nan=False)


@pytest.mark.parametrize(
    "count, stage, file_index",
    [
        (0, None, None),
        (1, "script_start", None),
        (2, "import_start", None),
        (3, "import_done", None),
        (4, "resolve_start", None),
        (5, "resolve_done", None),
        (6, "trust_start", 0),
        (7, "trust_returned", 0),
        (8, "version_start", 0),
        (9, "item_returned", 0),
        (10, "version_info_returned", 0),
        (11, "version_parts_returned", 0),
        (12, "version_done", 0),
        (13, "trust_start", 1),
        (20, "trust_start", 2),
        (26, "version_done", 2),
        (27, "script_done", None),
    ],
)
def test_signature_v4_separates_item_property_and_integer_reads(capture, count, stage, file_index):
    result = capture.parse_signature_progress(signature_markers_v4(count), "b" * 32, version=4)
    assert result["protocol_version"] == 4 and result["marker_count"] == count
    assert result["last_stage"] == stage and result["file_index"] == file_index
    assert result["complete"] is (count == 27)


def test_archived_v3_version_start_receipt_keeps_its_original_meaning(capture):
    times = [13, 27, 154, 155, 162, 168, 209, 221]
    raw = "".join(
        f"SWU_SIG_V3_{'b' * 32} {index} {elapsed}\n" for index, elapsed in enumerate(times)
    ).encode()
    result = capture.parse_signature_progress(raw, "b" * 32, version=3)
    assert result["last_stage"] == "version_start" and result["file_index"] == 0
    assert result["checkpoints_ms"] == times and result["marker_count"] == 8
    assert not result["complete"]
    later = capture.parse_signature_progress(signature_markers_v3(9), "b" * 32, version=3)
    assert later["last_stage"] == "version_done"
    assert capture.parse_signature_progress(raw, "b" * 32, version=4)["marker_count"] == 0


@pytest.mark.parametrize(
    "raw, rejection",
    [
        (signature_markers(), "no_markers"),
        (signature_markers_v2(), "no_markers"),
        (signature_markers_v3(), "no_markers"),
        (signature_markers_v4(9) + signature_markers_v4(9), "invalid_markers"),
        (signature_markers_v4(9) + b"SWU_SIG_V4_" + b"b" * 32 + b" 10 100\n", "invalid_markers"),
        (signature_markers_v4(9) + b"SWU_SIG_V4_" + b"b" * 32 + b" 9 1\n", "invalid_markers"),
        (signature_markers_v4() + b"SWU_SIG_V4_" + b"b" * 32 + b"\t27 270\n", "invalid_markers"),
        (signature_markers_v4(9) + b"SWU_SIG_V4_" + b"b" * 32 + b" 9 ", "truncated"),
        (signature_markers_v4() + b"SWU_SIG_V4_bbbb", "truncated"),
    ],
)
def test_signature_v4_rejects_foreign_malformed_and_truncated_streams(capture, raw, rejection):
    result = capture.parse_signature_progress(raw, "b" * 32, version=4)
    assert not result["complete"] and result["rejection"] == rejection
    if rejection == "truncated" and result["marker_count"] == 9:
        assert result["last_stage"] == "item_returned" and result["file_index"] == 0
    for version in (1, 2, 3):
        legacy = capture.parse_signature_progress(signature_markers_v4(), "b" * 32, version=version)
        assert legacy["marker_count"] == 0 and not legacy["complete"]
