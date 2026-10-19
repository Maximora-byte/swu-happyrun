"""Host-only safety tests; no ADB, MuMu, private keys or device claims."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


class MumuHttpsTests(unittest.TestCase):
    def module(self):
        path = ROOT / "scripts/check_mumu_https.py"
        self.assertTrue(path.exists(), "independent MuMu entrypoint must exist")
        spec = importlib.util.spec_from_file_location("check_mumu_https", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_no_execution_without_explicit_flags(self):
        m = self.module()
        with self.assertRaises(ValueError):
            m.execution_gate(False, True)
        with self.assertRaises(ValueError):
            m.execution_gate(True, False)
        m.execution_gate(True, True)

    def test_host_is_explicit_private_numeric_address(self):
        m = self.module()
        self.assertEqual("127.0.0.1", m.private_host("127.0.0.1"))
        self.assertEqual("192.168.20.3", m.private_host("192.168.20.3"))
        for value in ["0.0.0.0", "::", "8.8.8.8", "example.test", "127.0.0.1;id", "169.254.1.1"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                m.private_host(value)

    def test_reject_shell_metacharacters_and_empty_serial(self):
        m = self.module()
        for value in ["", "-s", "one two", "x;id", "$(id)", "a\nb"]:
            with self.assertRaises(ValueError):
                m.serial_value(value)
        self.assertEqual("127.0.0.1:1234", m.serial_value("127.0.0.1:1234"))

    def test_result_parser_requires_exact_single_marker_and_finish(self):
        m = self.module()
        output = (
            "MUMU_HTTPS PASS case=completed starts=1 stopped=true\n"
            "OK (1 test)\nINSTRUMENTATION_CODE: -1\n"
        )
        self.assertEqual(1, m.parse_result(output, 0, "completed")["starts"])
        for altered in [
            output + output,
            output.replace("stopped=true", "stopped=false"),
            output.replace("INSTRUMENTATION_CODE: -1", ""),
            output + "INSTRUMENTATION_FAILED",
            output.replace("completed", "cancel"),
        ]:
            with self.assertRaises(RuntimeError):
                m.parse_result(altered, 0, "completed")
        with self.assertRaises(RuntimeError):
            m.parse_result(output, 1, "completed")

    def test_report_never_turns_missing_adapter_into_pass(self):
        m = self.module()
        report = m.not_run_report("guarded_adapter_missing")
        self.assertTrue(all(c["result"] == "not_run" for c in report["cases"]))
        self.assertFalse(report["device_verified"])
        self.assertFalse(report["activity_ui_verified"])
        self.assertEqual("not_run", report["runtime_status"])

    def test_installed_apk_path_is_one_own_base_apk(self):
        m = self.module()
        self.assertEqual(
            "/data/app/~~Ab==/org.happyrun.app-X==/base.apk",
            m.apk_path("package:/data/app/~~Ab==/org.happyrun.app-X==/base.apk\n"),
        )
        for value in [
            "package:/data/app/a/base.apk\npackage:/data/app/b/base.apk",
            "package:/data/app/$(id)/base.apk",
            "package:/sdcard/other.apk",
            "",
        ]:
            with self.assertRaises(RuntimeError):
                m.apk_path(value)

    def test_bound_session_uses_monotonic_freshness(self):
        m = self.module()
        with patch.object(m.time, "monotonic", return_value=10):
            session = m.BoundSession("instance", "serial", "boot", "signature")
        with patch.object(m.time, "monotonic", return_value=41):
            with self.assertRaises(RuntimeError):
                session.assert_fresh()
        with patch.object(m.time, "monotonic", return_value=9):
            with self.assertRaises(RuntimeError):
                session.assert_fresh()

    def test_run_directory_is_exclusive_and_symlink_rejected(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            created = m.private_run_directory(root)
            self.assertEqual(root, created.parent)
            self.assertEqual([], list(created.iterdir()))
            link = root / "link"
            try:
                link.symlink_to(created, target_is_directory=True)
            except OSError:
                self.skipTest("symlink creation unavailable")
            with self.assertRaises(ValueError):
                m.private_run_directory(link)

    def test_no_pm_clear_or_old_avd_guard_override_in_new_source(self):
        m = self.module()
        source = Path(m.__file__).read_text()
        self.assertNotIn('pm", "clear', source)
        self.assertNotIn("HAPPYRUN_DISPOSABLE_EMULATOR", source)
        self.assertNotIn("10.0.2.2", source)


if __name__ == "__main__":
    unittest.main()


def test_adapter_namespace_and_guards_are_required():
    path = (
        ROOT
        / "android/app/src/remoteQaAndroidTest/java/org/happyrun/app/remoteqa"
        / "RemoteMumuHttpsAcceptanceTest.java"
    )
    assert path.exists(), "guarded adapter must exist before any MuMu runtime is enabled"
    source = path.read_text()
    for value in [
        "getApkContentsSigners",
        "mumu-https-qa",
        "CREATE_NEW",
        "NOFOLLOW_LINKS",
        "owner",
        "bootId",
        "RemoteForegroundSession",
        "RemoteAgentRunner",
        "driver.stopped()",
        "journal.hasStart",
        "allowOwnSimulation",
    ]:
        assert value in source
    for forbidden in [
        "FLAG_ACTIVITY_CLEAR_TASK",
        "deleteRecursively",
        "Runtime.getRuntime().exec",
        "setHostnameVerifier",
        "setDefaultSSLSocketFactory",
    ]:
        assert forbidden not in source


def test_adapter_requires_exact_local_hash_and_declared_capability():
    import check_mumu_https as m

    assert hasattr(m, "require_adapter"), "must bind installed test APK to exact reviewed adapter"
    path = (
        ROOT
        / "android/app/src/remoteQaAndroidTest/java/org/happyrun/app/remoteqa"
        / "RemoteMumuHttpsAcceptanceTest.java"
    )
    import hashlib

    relative = str(path.relative_to(ROOT))
    manifest = {
        "runtime_capabilities": ["mumu-own-simulation-v1"],
        "adapter": {
            "files": [{"path": relative, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}]
        },
    }
    m.require_adapter(manifest)
    manifest["adapter"]["files"][0]["sha256"] = "0" * 64
    with unittest.TestCase().assertRaises(RuntimeError):
        m.require_adapter(manifest)


def test_command_contains_only_explicit_serial_own_class_and_safe_values():
    import check_mumu_https as m

    assert hasattr(m, "instrument_command"), "explicit fixed-package command builder required"
    from types import SimpleNamespace

    args = SimpleNamespace(adb=Path("/trusted/adb"), serial="127.0.0.1:1234")
    binding = SimpleNamespace(
        boot="00000000-0000-4000-8000-000000000001", signature="a" * 64, task=42, display=0
    )
    fixture = {
        "origin": "https://127.0.0.1:12345",
        "agent_id": "00000000-0000-4000-8000-000000000002",
        "device_id": "00000000-0000-4000-8000-000000000003",
        "agent_token": "synthetic_token",
    }
    command = m.instrument_command(
        args, binding, fixture, "completed", "00000000-0000-4000-8000-000000000004"
    )
    assert command[:5] == ["/trusted/adb", "-s", args.serial, "shell", "am"]
    assert command[-1] == "org.happyrun.app.test/android.test.InstrumentationTestRunner"
    assert m.CLASS in command
    fixture["agent_token"] = "x;id"
    with unittest.TestCase().assertRaises(ValueError):
        m.instrument_command(
            args, binding, fixture, "completed", "00000000-0000-4000-8000-000000000004"
        )


def test_changed_identity_or_apk_cannot_refresh_bound_session():
    import check_mumu_https as m

    assert hasattr(m, "validate_current"), "current identity gate required before each action"
    from types import SimpleNamespace

    binding = SimpleNamespace(boot="boot", engine_version="15", host_version="6.8.4.0")
    pair = {"app": {"sha256": "a" * 64}, "test": {"sha256": "b" * 64}}
    observed = {
        "state": "device",
        "boot": "boot",
        "engine_version": "15",
        "host_version": "6.8.4.0",
        "instance_running": True,
        "app_sha256": "a" * 64,
        "test_sha256": "b" * 64,
    }
    m.validate_current(binding, pair, observed)
    for key, value in [
        ("state", "offline"),
        ("boot", "other"),
        ("engine_version", "14"),
        ("host_version", None),
        ("instance_running", False),
        ("app_sha256", "x"),
        ("test_sha256", "x"),
    ]:
        with unittest.TestCase().assertRaises(RuntimeError):
            m.validate_current(binding, pair, {**observed, key: value})


def test_remote_terminal_assertions_reject_cancel_without_stop_ack():
    import check_mumu_https as m

    assert hasattr(m, "assert_server_result"), "real server assertions required"
    from types import SimpleNamespace

    evidence = SimpleNamespace(records=[], fault_used=False, renew_count=0)
    with unittest.TestCase().assertRaises(AssertionError):
        m.assert_server_result("cancel", [{"state": "cancelled"}], evidence)
    evidence.records = [{"path": "/api/v1/jobs/synthetic/stop-ack", "status": 200}]
    m.assert_server_result("cancel", [{"state": "cancelled"}], evidence)
    with unittest.TestCase().assertRaises(AssertionError):
        m.assert_server_result("two_jobs", [{"state": "completed"}, {"state": "running"}], evidence)
    with unittest.TestCase().assertRaises(AssertionError):
        m.assert_server_result("restart", [{"state": "completed", "reason_code": None}], evidence)


def test_adb_query_and_stop_are_bound_to_exact_own_package(monkeypatch):
    import check_mumu_https as m

    assert hasattr(m, "OwnAdb"), "explicit own device transport required"
    from types import SimpleNamespace

    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout=b"device\n", returncode=0)

    monkeypatch.setattr(m.subprocess, "run", run)
    adb = m.OwnAdb(Path("/trusted/adb"), "127.0.0.1:1234")
    assert adb.query("get-state") == "device"
    adb.stop()
    assert calls[0][0] == ["/trusted/adb", "-s", "127.0.0.1:1234", "get-state"]
    assert calls[1][0][-4:] == ["shell", "am", "force-stop", "org.happyrun.app"]
    assert all(call[1].get("shell", False) is False for call in calls)


def test_main_preflight_never_operates_device(monkeypatch, tmp_path):
    import check_mumu_https as m

    assert hasattr(m, "main"), "preflight CLI required"

    def no_device(*a, **k):
        raise AssertionError("preflight must not invoke ADB")

    monkeypatch.setattr(m, "OwnAdb", no_device)
    monkeypatch.setattr(
        m, "verify_public_bundle", lambda args: {"adapter": None, "runtime_capabilities": []}
    )
    output = tmp_path / "report.json"
    code = m.main(
        [
            "--bundle",
            str(tmp_path / "bundle"),
            "--ca-cert",
            str(tmp_path / "ca"),
            "--server-cert",
            str(tmp_path / "leaf"),
            "--host",
            "127.0.0.1",
            "--output",
            str(output),
        ]
    )
    assert code == 2
    report = json.loads(output.read_text())
    assert report["runtime_status"] == "not_run"
    assert all(c["result"] == "not_run" for c in report["cases"])


def test_suite_stops_after_first_failure_and_preserves_not_run(monkeypatch, tmp_path):
    import check_mumu_https as m

    assert hasattr(m, "execute_suite"), "suite must stop after uncertain device result"
    from types import SimpleNamespace

    args = SimpleNamespace(adb="adb", serial="serial", private_dir=tmp_path)
    monkeypatch.setattr(m, "OwnAdb", lambda *a: object())
    monkeypatch.setattr(m, "open_binding", lambda *a: object())
    calls = []

    def run_case(case, *a):
        calls.append(case)
        raise RuntimeError("private-path-and-token-must-not-appear")

    monkeypatch.setattr(m, "run_case", run_case)
    report = m.execute_suite(args, {"pairs": {"remoteQa": {}}, "source": {"commit": "synthetic"}})
    assert calls == ["completed"]
    assert report["cases"][0]["result"] == "failed"
    assert all(c["result"] == "not_run" for c in report["cases"][1:])
    assert "private-path" not in json.dumps(report)
    assert report["runtime_status"] == "failed"


def test_output_is_exclusive_and_never_aliases_private_inputs(tmp_path):
    from types import SimpleNamespace

    import check_mumu_https as m

    assert hasattr(m, "reserve_report"), "report must be reserved safely before any operation"
    secret = tmp_path / "private.key"
    secret.write_text("synthetic sentinel")
    args = SimpleNamespace(
        output=secret,
        server_key=secret,
        ca_cert=tmp_path / "ca",
        server_cert=tmp_path / "leaf",
        binding=tmp_path / "binding",
        bundle=tmp_path / "bundle",
    )
    with unittest.TestCase().assertRaises((ValueError, FileExistsError)):
        m.reserve_report(args)
    assert secret.read_text() == "synthetic sentinel"
    args.output = tmp_path / "new.json"
    with m.reserve_report(args) as output:
        output.write("{}")
    with unittest.TestCase().assertRaises((ValueError, FileExistsError)):
        m.reserve_report(args)
    args.output = tmp_path / "linked.json"
    try:
        args.output.symlink_to(secret)
    except OSError:
        return
    with unittest.TestCase().assertRaises((ValueError, FileExistsError, OSError)):
        m.reserve_report(args)
    assert secret.read_text() == "synthetic sentinel"


def test_server_assertions_cannot_be_disabled_by_python_optimization():
    import subprocess

    code = """
from check_mumu_https import assert_server_result, assert_recovery_identity
from types import SimpleNamespace
e = SimpleNamespace(records=[], fault_used=False, renew_count=0)
for case, views in [('completed',[{'state':'running'}]), ('cancel',[{'state':'cancelled'}]),
                    ('restart',[{'state':'completed'}]), ('lost_renew',[{'state':'running'}])]:
    try: assert_server_result(case,views,e)
    except AssertionError: pass
    else: raise SystemExit('unsafe acceptance under optimization')
for recovered in [{'run_session_id':'other','fence':3}, {'run_session_id':'same','fence':2}]:
    try: assert_recovery_identity(recovered,'same',2)
    except AssertionError: pass
    else: raise SystemExit('unsafe recovery under optimization')
assert_recovery_identity({'run_session_id':'same','fence':3},'same',2)
"""
    import os

    result = subprocess.run(
        [sys.executable, "-O", "-c", code],
        env={**os.environ, "PYTHONPATH": str(ROOT / "scripts")},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_case_report_retains_body_and_cleanup_failure():
    import check_mumu_https as m

    assert hasattr(m, "case_report"), "body and cleanup need independent terminal evidence"
    report = m.case_report(
        "completed",
        None,
        "RuntimeError",
        "FixtureLifecycleError",
        "OSError",
        "cancel_controller_failed",
    )
    assert report["result"] == "failed"
    assert report["body_error_type"] == "RuntimeError"
    assert report["fixture_error_type"] == "FixtureLifecycleError"
    assert report["cleanup_error_type"] == "OSError"
    assert report["controller_error"] == "cancel_controller_failed"
    report = m.case_report("completed", {"starts": 1, "stopped": True}, None, None, None, None)
    assert report["result"] == "passed"


def test_real_case_orchestrator_preserves_three_failures(monkeypatch, tmp_path):
    from contextlib import contextmanager
    from types import SimpleNamespace

    import check_mumu_https as m

    @contextmanager
    def fixture(*args):
        try:
            yield {"evidence": object()}
        finally:
            raise RuntimeError("fixture private data")

    @contextmanager
    def client(*args):
        yield object()

    monkeypatch.setitem(sys.modules, "mumu_https_fixture", SimpleNamespace(local_fixture=fixture))
    monkeypatch.setitem(
        sys.modules,
        "check_remote_https_android",
        SimpleNamespace(prepare_job=lambda *a: ("job", {}), current=lambda *a: {}),
    )
    monkeypatch.setitem(
        sys.modules,
        "check_foreground_activity_https",
        SimpleNamespace(create_job=lambda *a: "other"),
    )
    monkeypatch.setitem(
        sys.modules,
        "remote_https_fixture",
        SimpleNamespace(
            trusted_client=client, error_type=lambda e: type(e).__name__ if e else None
        ),
    )
    checks = []

    def refresh(*args):
        checks.append(1)
        if len(checks) > 1:
            raise OSError("cleanup private data")

    monkeypatch.setattr(m, "refresh_binding", refresh)
    monkeypatch.setattr(m, "stop_bound_package", lambda *a: None)
    monkeypatch.setattr(m, "instrument_command", lambda *a: [])

    def body(*args):
        raise RuntimeError("body private data")

    monkeypatch.setattr(m, "run_instrumentation", body)
    args = SimpleNamespace(
        server_cert="leaf", server_key="key", host="127.0.0.1", port=0, ca_cert="ca"
    )
    report = m.run_case(
        "completed", args, SimpleNamespace(assert_fresh=lambda: None), {}, object(), tmp_path
    )
    assert report["result"] == "failed"
    assert report["body_error_type"] == "RuntimeError"
    assert report["fixture_error_type"] == "RuntimeError"
    assert report["cleanup_error_type"] == "OSError"
    assert "private data" not in json.dumps(report)


def test_interruption_keeps_body_and_local_process_cleanup_errors(monkeypatch):
    import threading
    from types import SimpleNamespace

    import check_mumu_https as m

    class Event:
        def wait(self, *a):
            return False

        def set(self):
            pass

        def is_set(self):
            return False

    class Thread:
        def __init__(self, *a, **k):
            pass

        def start(self):
            pass

        def join(self, *a, **k):
            pass

        def is_alive(self):
            return False

    class Process:
        stdout = SimpleNamespace(readline=lambda *a: "", close=lambda: None)

        def poll(self):
            return None

        def kill(self):
            raise OSError("private failure")

        def wait(self, *a, **k):
            return 0

    monkeypatch.setattr(threading, "Event", Event)
    monkeypatch.setattr(threading, "Thread", Thread)
    monkeypatch.setattr(m.subprocess, "Popen", lambda *a, **k: Process())
    assert hasattr(m, "OwnedProcessFailure"), "interruption body and cleanup must both survive"
    with unittest.TestCase().assertRaises(m.OwnedProcessFailure) as caught:
        m.interrupt_after_durable_start([], object(), object())
    assert caught.exception.diagnostics["body_error_type"] == "RuntimeError"
    assert caught.exception.diagnostics["cleanup_error_types"] == ["OSError"]
    assert "private" not in json.dumps(caught.exception.diagnostics)


def test_restart_rejects_malformed_utf8_without_stopping_package(monkeypatch):
    import io
    import threading
    from types import SimpleNamespace

    import check_mumu_https as m

    class Event:
        value = False

        def set(self):
            self.value = True

        def is_set(self):
            return self.value

        def wait(self, *a):
            return self.value

    class Thread:
        def __init__(self, target, **kwargs):
            self.target = target

        def start(self):
            self.target()

        def join(self, **kwargs):
            pass

        def is_alive(self):
            return False

    stopped = []

    def process(*args, **kwargs):
        data = b"MUMU_HTTPS READY restart starts=1 persisted_start=true\n\xff\n"
        return SimpleNamespace(
            stdout=io.TextIOWrapper(
                io.BytesIO(data), encoding=kwargs["encoding"], errors=kwargs["errors"]
            ),
            poll=lambda: None,
            kill=lambda: None,
            wait=lambda **kw: 0,
        )

    monkeypatch.setattr(threading, "Event", Event)
    monkeypatch.setattr(threading, "Thread", Thread)
    monkeypatch.setattr(m.subprocess, "Popen", process)
    monkeypatch.setattr(m, "stop_bound_package", lambda *a: stopped.append(True))
    with unittest.TestCase().assertRaises(m.OwnedProcessFailure):
        m.interrupt_after_durable_start([], object(), object())
    assert stopped == []


@pytest.mark.parametrize(
    "late_error,expected", [(1, "reader_output_limit"), (2, "reader_decode_failed")]
)
def test_restart_rejects_reader_errors_after_ready(monkeypatch, late_error, expected):
    import threading
    from types import SimpleNamespace

    import check_mumu_https as m

    events = []

    class Event:
        value = False

        def __init__(self):
            events.append(self)

        def set(self):
            self.value = True

        def is_set(self):
            return self.value

        def wait(self, *a):
            return self.value

    class Thread:
        def __init__(self, **kwargs):
            pass

        def start(self):
            events[0].set()

        def join(self, **kwargs):
            events[late_error].set()

        def is_alive(self):
            return False

    process = SimpleNamespace(
        stdout=SimpleNamespace(close=lambda: None),
        poll=lambda: None,
        kill=lambda: None,
        wait=lambda **k: 0,
    )
    monkeypatch.setattr(threading, "Event", Event)
    monkeypatch.setattr(threading, "Thread", Thread)
    monkeypatch.setattr(m.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(m, "stop_bound_package", lambda *a: None)
    with unittest.TestCase().assertRaises(m.OwnedProcessFailure) as caught:
        m.interrupt_after_durable_start([], object(), object())
    assert expected in caught.exception.diagnostics["cleanup_error_types"]
