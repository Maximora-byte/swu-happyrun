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
