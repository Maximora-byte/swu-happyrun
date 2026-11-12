"""Deterministic lifecycle failure injection; no emulator or live network required."""

import ast
import itertools
import json
import re
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts/remote_https_fixture.py"


def fixture_code(tmp_path, started=True, stuck=False):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    names = {
        "ERROR_TYPES",
        "JAVA_PHASES",
        "JAVA_ERRORS",
        "connection_evidence",
        "suite_contaminated",
        "remaining_not_run",
        "STACK_ALLOWLIST",
        "FixtureLifecycleError",
        "error_type",
        "thread_evidence",
        "project_thread_evidence",
        "instrumentation_evidence",
        "failure_evidence",
        "server_fixture",
    }
    nodes = [
        n
        for n in tree.body
        if getattr(n, "name", None) in names
        or isinstance(n, ast.Assign)
        and any(getattr(t, "id", None) in names for t in n.targets)
    ]
    sock = SimpleNamespace(
        bind=lambda address: None,
        getsockname=lambda: ("127.0.0.1", 9999),
        close=lambda: None,
    )
    server = SimpleNamespace(
        started=started,
        should_exit=False,
        run=lambda: None,
        server_state=SimpleNamespace(connections=set(), tasks=set()),
    )
    thread = SimpleNamespace(
        start=lambda: None,
        join=lambda timeout: None,
        is_alive=lambda: stuck,
        ident=-999,
    )
    clock = itertools.count()
    namespace = {
        "Path": Path,
        "contextmanager": contextmanager,
        "sys": sys,
        "re": re,
        "uuid4": lambda: "synthetic-id",
        "secrets": SimpleNamespace(token_urlsafe=lambda n: "PRIVATE_TOKEN"),
        "socket": SimpleNamespace(socket=lambda: sock),
        "create_app": lambda settings: object(),
        "ServerSettings": lambda *args: None,
        "RequestEvidence": lambda app, scenario: object(),
        "uvicorn": SimpleNamespace(
            Config=lambda *args, **kwargs: None, Server=lambda config: server
        ),
        "threading": SimpleNamespace(Thread=lambda **kwargs: thread),
        "time": SimpleNamespace(monotonic=lambda: next(clock), sleep=lambda seconds: None),
    }
    exec(  # noqa: S102 -- only reviewed local AST definitions, controlled dependency ports
        compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), namespace
    )
    certs = {
        "server.pem": tmp_path / "server.pem",
        "server.key": tmp_path / "server.key",
    }
    return namespace, certs


def test_legacy_finally_masks_body_error():
    @contextmanager
    def legacy():
        try:
            yield
        finally:
            raise RuntimeError("TLS fixture did not stop")

    with pytest.raises(RuntimeError) as error, legacy():
        raise AssertionError("PRIVATE_TOKEN")
    # Original report retained only RuntimeError, losing the primary failure category.
    assert type(error.value).__name__ == "RuntimeError"
    assert type(error.value.__context__).__name__ == "AssertionError"


@pytest.mark.parametrize("body_failed", [False, True])
def test_shutdown_failure_preserves_independent_body_outcome(tmp_path, body_failed):
    ns, certificates = fixture_code(tmp_path, stuck=True)
    diagnostics = {}
    with (
        pytest.raises(ns["FixtureLifecycleError"]) as error,
        ns["server_fixture"](tmp_path, certificates, diagnostics=diagnostics),
    ):
        if body_failed:
            raise AssertionError("PRIVATE_TOKEN")
    assert error.value.phase == "shutdown"
    assert diagnostics["fixture_shutdown_code"] == "shutdown_failed"
    assert diagnostics["fixture_body_error_type"] == ("AssertionError" if body_failed else None)
    evidence = ns["failure_evidence"](error.value, diagnostics)
    assert evidence["error_chain"] == (
        ["FixtureLifecycleError", "AssertionError"] if body_failed else ["FixtureLifecycleError"]
    )
    assert "PRIVATE_TOKEN" not in json.dumps(evidence)
    assert evidence["server_thread"]["alive"] is True


def test_startup_failure_has_distinct_code(tmp_path):
    ns, certificates = fixture_code(tmp_path, started=False)
    diagnostics = {}
    with (
        pytest.raises(ns["FixtureLifecycleError"]) as error,
        ns["server_fixture"](tmp_path, certificates, diagnostics=diagnostics),
    ):
        pytest.fail("body must not run")
    assert error.value.phase == "startup"
    assert diagnostics["fixture_startup_code"] == "startup_failed"


def test_body_failure_survives_successful_teardown(tmp_path):
    ns, certificates = fixture_code(tmp_path)
    diagnostics = {}
    with (
        pytest.raises(AssertionError),
        ns["server_fixture"](tmp_path, certificates, diagnostics=diagnostics),
    ):
        raise AssertionError("PRIVATE_TOKEN")
    assert diagnostics["fixture_body_error_type"] == "AssertionError"
    assert diagnostics["fixture_phase"] == "closed"


def test_normal_lifecycle_stays_successful(tmp_path):
    ns, certificates = fixture_code(tmp_path)
    diagnostics = {}
    with ns["server_fixture"](tmp_path, certificates, diagnostics=diagnostics):
        pass
    assert diagnostics["fixture_body_error_type"] is None
    assert diagnostics["fixture_phase"] == "closed"


def test_instrumentation_evidence_never_serializes_arbitrary_output(tmp_path):
    ns, _ = fixture_code(tmp_path)
    evidence = ns["instrumentation_evidence"](
        [
            "PRIVATE_TOKEN",
            "FOREGROUND_QA STOPPED starts=0",
            "FOREGROUND_QA PRIVATE_TOKEN",
            "Assertion failed: Timed out: Back stopped old Activity PRIVATE_TOKEN",
            "FAILURES!!!",
            "INSTRUMENTATION_STATUS: stream=PRIVATE_TOKEN",
        ]
    )
    assert evidence["markers"] == ["STOPPED starts=0"]
    assert evidence["known_assertions"] == ["Back stopped old Activity"]
    assert evidence["platform_failure"] is True
    assert "PRIVATE_TOKEN" not in json.dumps(evidence)


def test_thread_evidence_does_not_include_unlisted_frame_or_locals(tmp_path):
    ns, _ = fixture_code(tmp_path)
    secret = "PRIVATE_TOKEN"
    evidence = ns["thread_evidence"](
        SimpleNamespace(ident=__import__("threading").get_ident(), is_alive=lambda: True)
    )
    assert evidence["omitted_frames"] > 0
    assert secret not in json.dumps(evidence)
    assert str(tmp_path) not in json.dumps(evidence)
    assert all(set(frame) == {"file", "function", "line"} for frame in evidence["frames"])


def test_startup_and_shutdown_failures_both_retained(tmp_path):
    ns, certificates = fixture_code(tmp_path, started=False, stuck=True)
    diagnostics = {}
    with (
        pytest.raises(ns["FixtureLifecycleError"]) as error,
        ns["server_fixture"](tmp_path, certificates, diagnostics=diagnostics),
    ):
        pytest.fail("body must not run")
    assert error.value.phase == "shutdown"
    assert diagnostics["fixture_startup_code"] == "startup_failed"
    assert diagnostics["fixture_shutdown_code"] == "shutdown_failed"
    assert diagnostics["fixture_primary_phase"] == "startup"
    assert error.value.__cause__.phase == "startup"


@pytest.mark.parametrize(
    "role,method,path",
    [
        ("agent", "POST", "/api/v1/jobs/private/renew"),
        ("admin", "GET", "/api/v1/devices"),
        ("admin", "POST", "/api/v1/jobs/private/cancel"),
        ("unknown", "GET", "/api/v1/jobs/private"),
        ("health", "GET", "/api/v1/health"),
        ("unknown", "GET", "/PRIVATE_TOKEN"),
    ],
)
def test_connection_evidence_is_enum_only(tmp_path, role, method, path):
    ns, _ = fixture_code(tmp_path)
    transport = SimpleNamespace(
        is_closing=lambda: True,
        _ssl_protocol=SimpleNamespace(_state=SimpleNamespace(name="SHUTDOWN")),
    )
    connection = SimpleNamespace(
        scope={"method": method, "path": path, "headers": [("Authorization", "PRIVATE_TOKEN")]},
        transport=transport,
    )
    server = SimpleNamespace(server_state=SimpleNamespace(connections=[connection]))
    evidence = ns["connection_evidence"](server)
    assert evidence == [
        {"last_route_role": role, "transport_closing": True, "ssl_state": "SHUTDOWN"}
    ]
    assert "PRIVATE_TOKEN" not in json.dumps(evidence)
    transport._ssl_protocol._state.name = "PRIVATE_TOKEN"
    assert ns["connection_evidence"](server)[0]["ssl_state"] == "unknown"


def test_stage_and_error_markers_only_allow_fixed_enums(tmp_path):
    ns, _ = fixture_code(tmp_path)
    evidence = ns["instrumentation_evidence"](
        [
            "FOREGROUND_QA PHASE back_send_begin",
            "FOREGROUND_QA PHASE PRIVATE_TOKEN",
            "FOREGROUND_QA ERROR kind=SecurityException phase=home_shell_begin",
            "FOREGROUND_QA ERROR kind=PRIVATE_TOKEN phase=home_shell_begin",
            "FOREGROUND_QA CLEANUP_ERROR kind=IllegalStateException phase=cleanup_begin",
        ]
    )
    assert evidence["phases"] == ["back_send_begin"]
    assert len(evidence["errors"]) == 2
    assert "PRIVATE_TOKEN" not in json.dumps(evidence)


@pytest.mark.parametrize("contaminated", [True, False])
def test_actual_main_stops_only_after_fixture_shutdown_failure(tmp_path, contaminated):
    import tempfile

    ns, _ = fixture_code(tmp_path)
    script = ROOT / "scripts/check_foreground_activity_https.py"
    tree = ast.parse(script.read_text(encoding="utf-8"))
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    parser = SimpleNamespace(
        add_argument=lambda *a, **k: None,
        parse_args=lambda: SimpleNamespace(private_dir=tmp_path, output=tmp_path),
    )
    calls = []

    def run_case(case, directory, certificates, diagnostics):
        calls.append(case)
        if len(calls) == 1:
            diagnostics["fixture_phase"] = "shutdown" if contaminated else "closed"
            if contaminated:
                diagnostics["fixture_shutdown_code"] = "shutdown_failed"
                raise ns["FixtureLifecycleError"]("shutdown")
            raise AssertionError("PRIVATE_TOKEN")
        return {"case": case, "result": "passed"}

    ns.update(
        {
            "argparse": SimpleNamespace(ArgumentParser=lambda: parser),
            "Path": Path,
            "guard": lambda: None,
            "CASES": ("one", "two", "three"),
            "tempfile": tempfile,
            "run_case": run_case,
            "json": json,
        }
    )
    exec(compile(ast.Module(body=[main], type_ignores=[]), str(script), "exec"), ns)  # noqa: S102
    with pytest.raises(SystemExit) as error:
        ns["main"]()
    assert error.value.code == 1
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert len(report["cases"]) == 3
    assert calls == (["one"] if contaminated else ["one", "two", "three"])
    assert [r["result"] for r in report["cases"]] == (
        ["failed", "not_run", "not_run"] if contaminated else ["failed", "passed", "passed"]
    )
    assert "PRIVATE_TOKEN" not in json.dumps(report)


def test_java_stages_match_host_allowlist(tmp_path):
    ns, _ = fixture_code(tmp_path)
    source = (
        ROOT / "android/app/src/remoteQaAndroidTest/java/org/happyrun/app/remoteqa/"
        "RemoteForegroundActivityAcceptanceTest.java"
    ).read_text(encoding="utf-8")
    assert set(re.findall(r'phase\("([a-z_]+)"\)', source)) <= ns["JAVA_PHASES"]
    assert source.index('phase("back_send_begin")') < source.index(
        "sendKeyDownUpSync(KeyEvent.KEYCODE_BACK)"
    )
    assert source.index("sendKeyDownUpSync(KeyEvent.KEYCODE_BACK)") < source.index(
        'phase("back_send_return")'
    )
    assert 'primary=failure;errorMarker("ERROR",failure);throw failure;' in source
    assert "if(primary==null)throw cleanupFailure;" in source
    assert 'phase("cleanup_begin")' in source and 'phase("cleanup_return")' in source


def test_compiled_java_cleanup_preserves_primary_failure(tmp_path):
    import shutil
    import subprocess

    if shutil.which("java") is None:
        pytest.skip("Java compiler unavailable; no Java result claimed")
    source = (
        ROOT / "android/app/src/remoteQaAndroidTest/java/org/happyrun/app/remoteqa/"
        "RemoteForegroundActivityAcceptanceTest.java"
    ).read_text(encoding="utf-8")
    helpers = source[
        source.index("    private void phase(") : source.index("    private String arg(")
    ]
    tail = source[source.index("        } catch(Exception | AssertionError failure)") :]
    tail = tail[: tail.rfind("\n}")]
    java = (
        """
import java.util.*;
final class CleanupCheck {
 String diagnosticPhase="back_send_begin";
 boolean markerFails,cleanupFails;
 List<String> events=new ArrayList<>();
 final class Page {void finish(){if(cleanupFails)throw new IllegalStateException("PRIVATE_TOKEN");}}
 Page page=new Page();
 void marker(String value){
  if(markerFails)throw new RuntimeException("PRIVATE_TOKEN");events.add(value);
 }
 void ui(Runnable action){action.run();}
"""
        + helpers
        + """
 void exercise(boolean body)throws Exception {
  Throwable primary=null;
  try {if(body)throw new AssertionError("PRIVATE_TOKEN");
"""
        + tail
        + """
 public static void main(String[] args)throws Exception {
  for(int n=0;n<3;n++){
   CleanupCheck c=new CleanupCheck();c.cleanupFails=true;c.markerFails=n==2;
   try{c.exercise(n!=1);throw new RuntimeException("no failure");}
   catch(Throwable actual){
    if(n==1 ? !(actual instanceof IllegalStateException)
            : !(actual instanceof AssertionError))throw new AssertionError();
   }
   if(n==0){
    if(!c.events.get(0).startsWith("ERROR kind=AssertionError"))throw new AssertionError();
    if(!c.events.get(1).equals("PHASE cleanup_begin"))throw new AssertionError();
    if(!c.events.get(2).startsWith("CLEANUP_ERROR kind=IllegalStateException"))
      throw new AssertionError();
   }
   if(c.events.toString().contains("PRIVATE_TOKEN"))throw new AssertionError();
  }
  System.out.println("PASS 3 exact Java cleanup/diagnostic preservation checks");
 }
}
"""
    )
    path = tmp_path / "CleanupCheck.java"
    path.write_text(java, encoding="utf-8")
    subprocess.run(
        [
            "java",
            "com.sun.tools.javac.Main",
            "-source",
            "17",
            "-target",
            "17",
            "-d",
            str(tmp_path),
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    result = subprocess.run(
        ["java", "-cp", str(tmp_path), "CleanupCheck"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert "PASS 3 exact Java cleanup/diagnostic preservation checks" in result.stdout
