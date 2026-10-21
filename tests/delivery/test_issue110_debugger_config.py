"""Software-only tests. Session and prerequisite calls are always replaced."""

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/diagnostics/issue110_debugger_config.py"
NONCE = "a" * 32
VERSION = "10.0.26100.8249"


@pytest.fixture
def probe(monkeypatch):
    assert SCRIPT.exists(), "fixed normal-exit debugger configuration entry is missing"
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("issue110_debugger_config", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def private_bytes(body=b"private unverified sx format\r\n"):
    prefix = f"SWU_{NONCE}_".encode()
    return (
        prefix
        + b"CFG_OPEN\r\n"
        + body
        + prefix
        + b"CFG_CLOSE\r\n"
        + prefix
        + b"LOAD\r\n"
        + prefix
        + b"READY 2a\r\n"
        + b"CONFIG_PID 42\r\nCONFIG_OUT\r\nCONFIG_ERR\r\n"
    )


@pytest.mark.parametrize(
    "body",
    [
        b"arbitrary PRIVATE_CANARY\n",
        b"av - second chance\nCommand: fake\n",
        b"av conflicting\nav conflicting\n",
    ],
)
def test_no_invented_format_can_be_matched(probe, body):
    result = probe.observe(private_bytes(body), NONCE, VERSION, 42)
    assert result["configuration_readback"] == "format_unknown"
    assert result["script_load"] == "observed" and result["ready_identity"] is True
    assert result["stdout_seen"] is True and result["stderr_seen"] is True
    assert "PRIVATE_CANARY" not in json.dumps(result) and NONCE not in json.dumps(result)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda s: s.replace(b"CFG_OPEN", b"WRONG"),
        lambda s: s.replace(b"CFG_CLOSE", b"WRONG"),
        lambda s: s + f"SWU_{NONCE}_CFG_OPEN\n".encode(),
        lambda s: (
            s.replace(b"CFG_OPEN", b"TMP")
            .replace(b"CFG_CLOSE", b"CFG_OPEN")
            .replace(b"TMP", b"CFG_CLOSE")
        ),
        lambda s: s.replace(NONCE.encode(), b"b" * 32),
        lambda s: s.split(b"CFG_CLOSE")[0] + b"CFG_CLOSE",
        lambda s: s.replace(b"private", b"\xffprivate"),
        lambda s: b"x" * 65537,
    ],
)
def test_structural_bad_bytes_never_match_configuration(probe, mutation):
    result = probe.observe(mutation(private_bytes()), NONCE, VERSION, 42)
    assert result["configuration_readback"] not in ("matched", "format_unknown")
    assert "private" not in json.dumps(result)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda s: s.replace(b"_LOAD", b"_WRONG"),
        lambda s: s + f"SWU_{NONCE}_LOAD\n".encode(),
        lambda s: s.replace(b"_LOAD\r\n", b"_LOAD extra\r\n"),
        lambda s: s.split(b"_LOAD")[0] + b"_LOAD",
    ],
)
def test_load_unknown_or_invalid_is_independent_of_configuration(probe, mutation):
    result = probe.observe(mutation(private_bytes()), NONCE, VERSION, 42)
    assert result["script_load"] != "observed"
    assert result["configuration_readback"] != "matched"


def test_changed_version_and_wrong_ready_identity_never_pass(probe):
    assert (
        probe.observe(private_bytes(), NONCE, "10.0.0.1", 42)["configuration_readback"]
        == "version_mismatch"
    )
    assert probe.observe(private_bytes(), NONCE, VERSION, 43)["ready_identity"] is False
    assert probe.observe(b"", NONCE, VERSION, None)["ready_identity"] is None


def test_fixed_scripts_keep_original_filter_and_only_emit_probe_marker(probe):
    terminal = r"C:\private\terminal.cdb"
    loader = r"C:\private\load.cdb"
    init, terminal_text, load = probe.debugger_scripts(NONCE, terminal, loader)
    old_init, _ = probe.capture.debugger_scripts(NONCE, terminal)
    assert init.splitlines()[0] == old_init.splitlines()[0]
    assert terminal_text == f".echo SWU_{NONCE}_UNEXPECTED_CALLBACK\n"
    assert all(word not in terminal_text for word in (".ecxr", "knL", "lm", "gn"))
    assert load == f".echo SWU_{NONCE}_LOAD\n"
    assert init.splitlines() == [
        old_init.splitlines()[0],
        f".echo SWU_{NONCE}_CFG_OPEN",
        "sx",
        f".echo SWU_{NONCE}_CFG_CLOSE",
        f"$$>a<{loader}",
        old_init.splitlines()[1],
    ]
    assert not any(line in ("g", "gn", "gh") for line in init.splitlines())
    assert not any(word in load for word in (".ecxr", "knL", "lm", "BEGIN", "END", "gn"))
    for bad in (r"C:\private\bad path.cdb", "bad\ncommand"):
        with pytest.raises(ValueError):
            probe.debugger_scripts(NONCE, terminal, bad)


@pytest.fixture
def fixed_entry(probe, monkeypatch, tmp_path):
    private, output = tmp_path / "private", tmp_path / "public.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--subject",
            str(tmp_path / "subject"),
            "--private",
            str(private),
            "--output",
            str(output),
            "--setup-started",
            "100",
        ],
    )
    for key, value in {
        "GITHUB_REPOSITORY": "Maximora-byte/swu-happyrun",
        "GITHUB_REF": "refs/heads/diagnostics/issue110-native-capture",
        "GITHUB_RUN_ATTEMPT": "1",
        "SystemRoot": "C:\\Windows",
        "SWU_SECRET_CANARY": "PRIVATE_CANARY",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(probe.time, "time", lambda: 100)
    monkeypatch.setattr(probe.time, "monotonic", lambda: 200)
    monkeypatch.setattr(probe.uuid, "uuid4", lambda: SimpleNamespace(hex=NONCE))
    calls = []
    monkeypatch.setattr(
        probe.capture,
        "verify_subject",
        lambda *a: calls.append("subject") or {"PRIVATE_CANARY": "private"},
    )
    metadata = [
        {"name": name, "version": VERSION, "sha256": "b" * 64, "PRIVATE_CANARY": "private"}
        for name in ("cdb.exe", "dbgeng.dll", "dbghelp.dll")
    ]
    monkeypatch.setattr(
        probe.capture,
        "installed_debugger",
        lambda *a, **kw: calls.append("signature") or (Path("cdb.exe"), metadata),
    )
    monkeypatch.setattr(probe, "controller_tests", lambda *a: calls.append("controller") or True)
    real_scripts = probe.debugger_scripts
    monkeypatch.setattr(
        probe,
        "debugger_scripts",
        lambda nonce, terminal, loader: real_scripts(
            nonce, r"C:\private\terminal.cdb", r"C:\private\load.cdb"
        ),
    )

    def forbidden(*a, **kw):
        raise AssertionError("forbidden widened entry")

    for name in ("main", "smoke", "run_one", "consume", "load_manifest", "pytest_argv"):
        monkeypatch.setattr(probe.capture, name, forbidden)
    return probe, private, output, calls, metadata


@pytest.mark.parametrize(
    "state",
    [
        "normal",
        "bad_config",
        "load_missing",
        "no_exit",
        "exit7",
        "cleanup_unknown",
        "cleanup_false",
        "read_error",
        "invalid_bytes",
        "unexpected_callback",
    ],
)
def test_single_fixed_session_never_becomes_execution_ready(fixed_entry, monkeypatch, state):
    probe, private, output, calls, _ = fixed_entry
    seen = []

    def session(*args, **kw):
        seen.append((args, kw))
        calls.append("session")
        assert args[1] == private and args[4] == NONCE and args[5] == 215
        assert "SWU_SECRET_CANARY" not in args[2]
        assert args[0][-3:] == [sys.executable, "-c", probe.TARGET]
        assert "pytest" not in probe.TARGET and "faulthandler" not in probe.TARGET
        raw = private_bytes()
        if state == "bad_config":
            raw = raw.replace(b"CFG_OPEN", b"WRONG")
        if state == "load_missing":
            raw = raw.replace(b"_LOAD", b"_WRONG")
        if state == "invalid_bytes":
            raw += b"\xff"
        if state == "unexpected_callback":
            raw += f"SWU_{NONCE}_UNEXPECTED_CALLBACK\n".encode()
        if state != "read_error":
            args[3].write_bytes(raw)
        code = None if state == "no_exit" else 7 if state == "exit7" else 0
        cleanup = None if state == "cleanup_unknown" else state != "cleanup_false"
        # The decoded/normalized return is deliberately misleading. Use raw.log bytes.
        return private_bytes().decode(), code, code, "exited", cleanup, 42

    monkeypatch.setitem(
        sys.modules, "issue110_win32", SimpleNamespace(Session=lambda: SimpleNamespace(run=session))
    )
    assert probe.main() == 1
    report = json.loads(output.read_text())
    assert calls == ["subject", "signature", "controller", "session"] and len(seen) == 1
    assert not report["execution_ready"] and not report["passed"]
    assert not report["original_invocation_attempted"] and not report["original_group_started"]
    assert report["observation_timing"] == "after_session_target_may_have_run"
    assert report["configuration_readback"] != "matched"
    if state == "normal":
        assert report["target_exit"] == "verified" and report["owned_cleanup"] is True
    if state == "no_exit":
        assert report["target_exit"] == "unknown" and report["child_exit"] is None
    if state in ("exit7", "unexpected_callback"):
        assert report["target_exit"] == "failed"
    if state == "cleanup_unknown":
        assert report["owned_cleanup"] is None
    if state == "cleanup_false":
        assert report["owned_cleanup"] is False
    if state in ("bad_config", "invalid_bytes", "read_error"):
        assert report["configuration_readback"] != "format_unknown"
    assert set(report) == probe.PUBLIC_FIELDS
    text = output.read_text()
    assert all(
        value not in text
        for value in ("PRIVATE_CANARY", str(private), NONCE, "CONFIG_PID", "terminal.cdb")
    )
    assert all(set(item) == {"name", "version", "sha256"} for item in report["debugger_binaries"])


@pytest.mark.parametrize("stage", ["subject", "signature", "controller", "session"])
def test_failure_and_cancellation_never_retry_or_run_wider_entry(fixed_entry, monkeypatch, stage):
    probe, _, output, calls, _ = fixed_entry
    error = OSError("PRIVATE_CANARY")

    def fail(*a, **kw):
        calls.append(stage)
        raise error

    if stage == "subject":
        monkeypatch.setattr(probe.capture, "verify_subject", fail)
    elif stage == "signature":
        monkeypatch.setattr(probe.capture, "installed_debugger", fail)
    elif stage == "controller":
        monkeypatch.setattr(probe, "controller_tests", fail)
    else:
        monkeypatch.setitem(
            sys.modules,
            "issue110_win32",
            SimpleNamespace(Session=lambda: SimpleNamespace(run=fail)),
        )
    assert probe.main() == 1
    report = json.loads(output.read_text())
    assert (
        calls
        == ["subject", "signature", "controller", "session"][
            : ["subject", "signature", "controller", "session"].index(stage) + 1
        ]
    )
    assert report["error_category"] == "os_error" and "PRIVATE_CANARY" not in output.read_text()


@pytest.mark.parametrize("cancel", [KeyboardInterrupt("PRIVATE_CANARY"), SystemExit(7)])
def test_cancellation_propagates_without_a_session_retry(fixed_entry, monkeypatch, cancel):
    probe, _, _, calls, _ = fixed_entry

    def fail(*a, **kw):
        calls.append("session")
        raise cancel

    monkeypatch.setitem(
        sys.modules, "issue110_win32", SimpleNamespace(Session=lambda: SimpleNamespace(run=fail))
    )
    with pytest.raises(type(cancel)) as caught:
        probe.main()
    assert caught.value is cancel and calls.count("session") == 1


def test_full_fifteen_seconds_must_remain_before_the_only_session(fixed_entry, monkeypatch):
    probe, _, output, calls, _ = fixed_entry
    clock = iter([200, 486])  # Shared deadline 500; only 14 seconds left.
    monkeypatch.setattr(probe.time, "monotonic", lambda: next(clock))
    assert probe.main() == 1
    assert calls == ["subject", "signature", "controller"]
    report = json.loads(output.read_text())
    assert (
        report["blocker"] == "setup_budget_exhausted" and not report["session_invocation_attempted"]
    )


def test_fixed_controller_file_list_and_shared_thirty_second_budget(probe, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(probe.time, "monotonic", lambda: 100)
    monkeypatch.setattr(
        probe.subprocess,
        "run",
        lambda argv, **kw: calls.append((argv, kw)) or SimpleNamespace(returncode=0),
    )
    assert probe.controller_tests({}, tmp_path, 107)
    argv, options = calls[0]
    assert options["timeout"] == 7 and argv[-2:] == [
        str(ROOT / "tests/delivery/test_issue110_capture.py"),
        str(ROOT / "tests/delivery/test_issue110_debugger_config.py"),
    ]
    assert len(calls) == 1 and "--confcutdir" in argv


def test_workflow_is_hard_disabled_and_never_calls_an_old_native_entry():
    path = ROOT / ".github/workflows/issue110-debugger-config.yml"
    assert path.exists(), "disabled standalone workflow missing"
    text = path.read_text()
    assert "if: >-\n      false &&" in text
    assert "github.event.before == ''" in text
    assert (
        "github.run_attempt == 1" in text
        and "github.repository == 'Maximora-byte/swu-happyrun'" in text
    )
    assert "github.ref == 'refs/heads/diagnostics/issue110-native-capture'" in text
    assert "timeout-minutes: 8" in text and "retention-days: 1" in text
    assert "matrix" not in text and "workflow_dispatch" not in text
    assert text.count("issue110_debugger_config.py") == 1
    assert all(
        name not in text
        for name in ("issue110_preflight.py", "issue110_capture.py", "raw.log", "*.json")
    )


@pytest.mark.parametrize(
    "reason", ["api_error", "handshake_failed", "handshake_timeout", "exit_query_failed"]
)
def test_actual_session_failure_reasons_stay_distinct(fixed_entry, monkeypatch, reason):
    probe, _, output, _, _ = fixed_entry

    def session(*args, **kw):
        assert kw["max_output"] == probe.capture.MAX_OUTPUT
        args[3].write_bytes(private_bytes())
        return "", None, None, reason, False, 42

    monkeypatch.setitem(
        sys.modules, "issue110_win32", SimpleNamespace(Session=lambda: SimpleNamespace(run=session))
    )
    assert probe.main() == 1
    report = json.loads(output.read_text())
    assert report["reason"] == reason and report["target_exit"] == "unknown"


def test_post_observation_shared_deadline_is_not_renewed(fixed_entry, monkeypatch):
    probe, _, output, _, _ = fixed_entry
    clock = iter([200, 480, 501])
    monkeypatch.setattr(probe.time, "monotonic", lambda: next(clock))

    def session(*args, **kw):
        assert args[5] == 495
        args[3].write_bytes(private_bytes())
        return "", 0, 0, "exited", True, 42

    monkeypatch.setitem(
        sys.modules, "issue110_win32", SimpleNamespace(Session=lambda: SimpleNamespace(run=session))
    )
    assert probe.main() == 1
    report = json.loads(output.read_text())
    assert report["blocker"] == "setup_budget_exhausted" and report["stage"] != "complete"
    assert report["child_exit"] == 0 and report["owned_cleanup"] is True


@pytest.mark.parametrize("cancel", [KeyboardInterrupt("PRIVATE_CANARY"), SystemExit(7)])
def test_raw_read_cancellation_survives_ordinary_close_failure(fixed_entry, monkeypatch, cancel):
    probe, private, _, _, _ = fixed_entry
    original_open = Path.open

    class Stream:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.close()

        def read(self, count):
            assert count == probe.MAX_OUTPUT + 1
            raise cancel

        def close(self):
            raise OSError("PRIVATE_CANARY")

    def opened(path, *a, **kw):
        if path == private / "raw.log" and a == ("rb",):
            return Stream()
        return original_open(path, *a, **kw)

    monkeypatch.setattr(Path, "open", opened)
    monkeypatch.setitem(
        sys.modules,
        "issue110_win32",
        SimpleNamespace(
            Session=lambda: SimpleNamespace(run=lambda *a, **kw: ("", 0, 0, "exited", True, 42))
        ),
    )
    with pytest.raises(type(cancel)) as caught:
        probe.main()
    assert caught.value is cancel


@pytest.mark.parametrize(
    "field,value",
    [("version", "10.0.0.1"), ("name", "PRIVATE_CANARY"), ("sha256", "PRIVATE_CANARY")],
)
def test_unverified_metadata_cannot_reach_the_session(fixed_entry, field, value):
    probe, _, output, calls, metadata = fixed_entry
    metadata[0][field] = value
    assert probe.main() == 1 and calls == ["subject", "signature"]
    report = json.loads(output.read_text())
    assert report["blocker"] == "debugger_version_unverified"
    assert not report["session_invocation_attempted"] and report["debugger_binaries"] == []
    assert "PRIVATE_CANARY" not in output.read_text()


@pytest.mark.parametrize("option", ["--target", "--script", "--group", "--mode"])
def test_no_cli_override_to_wider_execution(fixed_entry, monkeypatch, option):
    probe, _, _, calls, _ = fixed_entry
    monkeypatch.setattr(sys, "argv", [*sys.argv, option, "PRIVATE_CANARY"])
    with pytest.raises(SystemExit) as caught:
        probe.main()
    assert caught.value.code == 2 and calls == []


def test_fixed_entry_does_not_reference_any_wider_entry():
    import ast

    tree = ast.parse(SCRIPT.read_text())
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    shared_calls = {
        node.func.attr
        for node in calls
        if isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "capture"
    }
    assert shared_calls == {
        "child_environment",
        "verify_subject",
        "installed_debugger",
        "cdb_argv",
        "remaining",
    }
    assert sum(isinstance(node.func, ast.Name) and node.func.id == "Session" for node in calls) == 1
    assert (
        "matched"
        not in SCRIPT.read_text().split("def observe(", 1)[1].split("def debugger_scripts(", 1)[0]
    )


def test_controller_failure_is_not_a_pass(probe, monkeypatch, tmp_path):
    monkeypatch.setattr(probe.time, "monotonic", lambda: 100)
    monkeypatch.setattr(probe.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=1))
    with pytest.raises(ValueError, match="^controller_tests_failed$"):
        probe.controller_tests({}, tmp_path, 107)
