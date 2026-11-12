import ast
import asyncio
import importlib.util
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load():
    spec = importlib.util.spec_from_file_location(
        "control_diag", ROOT / "scripts/remote_instrumentation_diagnostics.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_control_fields_are_exact_allowlisted_and_elapsed_bounded():
    marker = (
        "REMOTE_QA CONTROL code=request_timeout status=0 retryable=true ambiguous=true "
        "phase=hello_begin elapsed_ms=5002 elapsed_capped=false"
    )
    result = load().summarize(marker, 0)
    assert result["controls"] == [
        {
            "code": "request_timeout",
            "status": 0,
            "retryable": True,
            "ambiguous": True,
            "phase": "hello_begin",
            "elapsed_ms": 5002,
            "elapsed_capped": False,
        }
    ]
    assert (
        load().summarize(marker.replace("status=0", "status=other"), 0)["controls"][0]["status"]
        is None
    )
    assert load().summarize(marker.replace("5002", "-1"), 0)["controls"][0]["elapsed_ms"] == -1
    for invalid in [
        marker.replace("request_timeout", "PRIVATE_TOKEN"),
        marker.replace("status=0", "status=999"),
        marker.replace("5002", "60001"),
        marker.replace("hello_begin", "PRIVATE_TOKEN"),
    ]:
        assert load().summarize(invalid, 0)["controls"] == []


def fixture_parts(clock):
    tree = ast.parse((ROOT / "scripts/remote_https_fixture.py").read_text(encoding="utf-8"))
    nodes = [
        node
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef))
        and node.name in {"RequestEvidence", "hello_evidence"}
    ]
    ns = {
        "threading": threading,
        "time": SimpleNamespace(monotonic=lambda: clock[0]),
        "asyncio": asyncio,
        "json": json,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<fixture>", "exec"), ns)
    return ns


@pytest.mark.parametrize("status", [200, 401, 503])
def test_actual_asgi_hello_observations_preserve_status_and_send_completion(status):
    clock = [10.0]
    ns = fixture_parts(clock)
    observed = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": status, "headers": []})
        clock[0] = 10.025
        await send({"type": "http.response.body", "body": b"PRIVATE_TOKEN"})

    evidence = ns["RequestEvidence"](app)

    async def send(message):
        observed.append(ns["hello_evidence"](evidence))

    asyncio.run(
        evidence({"type": "http", "method": "POST", "path": "/api/v1/agents/hello"}, None, send)
    )
    summary = ns["hello_evidence"](evidence)
    assert summary["count"] == 1
    assert summary["observations"][0]["status"] == status
    assert summary["observations"][0]["send_complete"] is True
    assert summary["observations"][0]["elapsed_ms"] <= 26
    assert observed[-1]["observations"][0]["response_generated"] is True
    assert observed[-1]["observations"][0]["send_complete"] is False
    assert "PRIVATE_TOKEN" not in str(summary)


def test_send_failure_is_never_completed_and_elapsed_is_capped():
    clock = [0.0]
    ns = fixture_parts(clock)

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"PRIVATE_TOKEN"})

    async def send(message):
        if message["type"] == "http.response.body":
            raise OSError("PRIVATE_TOKEN")

    evidence = ns["RequestEvidence"](app)
    with pytest.raises(IOError):
        asyncio.run(
            evidence({"type": "http", "method": "POST", "path": "/api/v1/agents/hello"}, None, send)
        )
    clock[0] = 99.0
    item = ns["hello_evidence"](evidence)["observations"][0]
    assert item == {
        "status": 200,
        "response_generated": True,
        "send_complete": False,
        "elapsed_ms": 60000,
        "elapsed_capped": True,
    }


def test_no_hello_has_explicit_zero_and_no_raw_fields():
    ns = fixture_parts([1.0])

    async def app(scope, receive, send):
        pass

    evidence = ns["RequestEvidence"](app)
    assert ns["hello_evidence"](evidence) == {"count": 0, "count_capped": False, "observations": []}


@pytest.mark.parametrize(
    "code",
    [
        "transport_failed",
        "request_timeout",
        "http_rejected",
        "invalid_response",
        "closed",
        "busy",
        "control_failure",
    ],
)
def test_each_safe_control_code_survives(code):
    marker = (
        f"REMOTE_QA CONTROL code={code} status=401 retryable=false ambiguous=false "
        "phase=hello_begin elapsed_ms=1 elapsed_capped=false"
    )
    assert load().summarize(marker, 0)["controls"][0]["code"] == code


def test_real_tls_hello_observation(tmp_path):
    import shutil
    import time

    if shutil.which("openssl") is None:
        pytest.skip("Official OpenSSL unavailable; no TLS execution claimed")
    spec = importlib.util.spec_from_file_location(
        "hello_real_fixture", ROOT / "scripts/remote_https_fixture.py"
    )
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    certificates = fixture.issue_certificates(tmp_path / "certificates")
    with fixture.server_fixture(tmp_path / "server", certificates) as running:
        with fixture.trusted_client(certificates["ca.pem"]) as client:
            response = client.post(
                running["origin"] + "/api/v1/agents/hello",
                headers={"Authorization": "Bearer " + running["agent_token"]},
                json={"protocol_version": 1, "agent_id": running["agent_id"], "devices": []},
            )
            assert response.status_code == 200
        deadline = time.monotonic() + 1
        summary = fixture.hello_evidence(running["evidence"])
        while not summary["observations"][0]["send_complete"] and time.monotonic() < deadline:
            time.sleep(0.01)
            summary = fixture.hello_evidence(running["evidence"])
        assert summary["count"] == 1
        item = summary["observations"][0]
        assert item["status"] == 200 and item["response_generated"] and item["send_complete"]
        assert 0 <= item["elapsed_ms"] <= 60000
        assert running["agent_token"] not in json.dumps(summary)
