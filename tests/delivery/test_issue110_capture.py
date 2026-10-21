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
    assert set(files) == {*expected, "issue110-native-capture.yml", "issue110-setup-only.yml"}
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
    predecessor = "github.event.before == '909b96ddd59067512ddb337b5f46567b06c2483f'"
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
