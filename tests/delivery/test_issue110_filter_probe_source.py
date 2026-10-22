"""Source-only safety checks and portable blocked entry, not Windows validation."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts/diagnostics/issue110_filter_command_probe.cpp"


def source_text():
    assert SOURCE.is_file(), "missing source-only DbgEng adapter and blocked entry"
    return SOURCE.read_text(encoding="utf-8")


def test_entry_is_unconditionally_blocked(tmp_path):
    source = source_text()
    # A command-line or preprocessor path reaching the factory must break this guard.
    main = source.split("int main()", 1)[1]
    assert not re.search(r"#|getenv|argc|argv|DebugCreate|make_|run_probe", main)
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("no portable C++ compiler; Windows branch is not tested")
    binary = tmp_path / "blocked_filter_probe"
    compiled = subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            str(SOURCE),
            "-o",
            str(binary),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    environment = os.environ | {"ISSUE110_ENABLE_NATIVE": "1", "ISSUE110_RUN": "1"}
    for arguments in ([], ["--run"], ["--native", "--approve"]):
        ran = subprocess.run(
            [str(binary), *arguments],
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        assert ran.returncode == 2
        assert ran.stderr == ""
        assert json.loads(ran.stdout) == {
            "status": "blocked",
            "execution_ready": False,
            "passed": False,
            "native_execution_attempted": False,
            "reason": "source_only_unverified_windows_integration",
        }


def test_adapter_uses_official_interfaces_without_loading_or_target_paths():
    source = source_text()
    assert "#include <windows.h>" in source
    assert "#include <initguid.h>" in source
    assert "#include <DbgEng.h>" in source
    assert "decltype(&DebugCreate)" in source
    assert "IID_IDebugClient" in source
    assert "IID_IDebugControl" in source
    assert "IID_IDebugOutputCallbacks" in source
    assert "public IDebugOutputCallbacks" in source
    forbidden_calls = (
        "LoadLibrary",
        "GetProcAddress",
        "FreeLibrary",
        "DebugConnect",
        "CreateProcess",
        "AttachProcess",
        "OpenDumpFile",
        "StartProcessServer",
        "StartServer",
        "AddExtension",
        "SetExceptionFilterSecondCommand",
        "SetEventFilterCommand",
        "SetExceptionFilterParameters",
        "WaitForEvent",
        "DispatchCallbacks",
        "CreateFile",
        "fopen",
        "system",
        "getenv",
    )
    for forbidden in forbidden_calls:
        assert not re.search(rf"\b{forbidden}\w*\s*\(", source), forbidden
    assert "__uuidof" not in source
    assert "#pragma comment(lib" not in source
    # There must be exactly one fresh-client creation path, not an injected existing client.
    assert source.count("unverified_debug_create(") == 1
    assert "GetExceptionFilterParameters" in source
    assert "GetExceptionFilterSecondCommand" in source
    assert "GetNumberEventFilters" in source
    assert source.count("->Execute(") == 2
    assert "GetDebuggeeType" in source


def test_output_capture_has_flush_boundaries_and_same_thread_guards():
    source = source_text()
    assert source.count("->FlushCallbacks()") == 3
    assert "STDMETHODIMP QueryInterface" in source
    assert "STDMETHODIMP_(ULONG) AddRef() noexcept override" in source
    assert "STDMETHODIMP_(ULONG) Release() noexcept override" in source
    assert "STDMETHODIMP Output(ULONG" in source
    assert "GetCurrentThreadId()" in source
    assert "SetOutputCallbacks(nullptr)" in source
    assert "UNVERIFIED" in source


def test_no_target_requires_zero_qualifier_and_api_outputs_start_unknown():
    source = source_text()
    assert "target_class == DEBUG_CLASS_UNINITIALIZED && qualifier == 0" in source
    assert "reply.bytes.fill(0xa5)" in source
    assert "static_cast<ULONG>(reply.bytes.size())" in source
    assert "ULONG events = unknown, specific = unknown, arbitrary = unknown;" in source
    assert "cleanup_.wrong_thread = wrong_thread_.load" in source
    # These are source guards, not proof of the uncompiled Windows branch's ABI.
    assert "output mask" in source
    assert "completeness" in source


def test_post_stage_target_query_is_not_suppressed_by_prior_failure():
    source = source_text()
    target_method = source.split("TargetReply no_target() override {", 1)[1].split(
        "FilterReply enumerate_filters()", 1
    )[0]
    assert "usable()" not in target_method
    assert "if (!can_query_target())" in target_method
    gate = source.split("bool can_query_target() noexcept {", 1)[1].split("bool usable()", 1)[0]
    assert "blocked_" not in gate
    assert "callback_->violation" not in gate
    assert "GetCurrentThreadId()" in gate
    assert "control_ != nullptr" in gate


def test_unknown_debuggee_classes_are_not_reported_as_known_targets():
    source = source_text()
    target_method = source.split("TargetReply no_target() override {", 1)[1].split(
        "FilterReply enumerate_filters()", 1
    )[0]
    assert "target_class == DEBUG_CLASS_KERNEL || target_class == DEBUG_CLASS_USER_WINDOWS" in (
        target_method
    )
    assert "TargetState state = TargetState::unknown;" in target_method


def test_close_rejects_wrong_thread_before_non_atomic_state_access():
    source = source_text()
    close = source.split("CloseResult close() noexcept override {", 1)[1].split(
        "const NativeObservations& observations()", 1
    )[0]
    rejection, owner_only = close.split("if (closed_) return cleanup_;", 1)
    assert "GetCurrentThreadId() != owner_thread_" in rejection
    assert "wrong_thread_.store(true, std::memory_order_relaxed)" in rejection
    assert "CloseResult rejected;" in rejection
    assert "rejected.wrong_thread = true;" in rejection
    assert "return rejected;" in rejection
    assert "cleanup_" not in rejection
    assert "closed_" not in rejection
    assert "closed_ = true;" in owner_only
