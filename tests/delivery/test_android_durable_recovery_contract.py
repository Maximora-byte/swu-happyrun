"""Local barrier contracts only; not Android execution evidence."""

import ast
import asyncio
import json
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/check_android_durable_recovery.py"


def barrier_type():
    tree = ast.parse(SCRIPT.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Barrier")
    scope = {"asyncio": asyncio, "threading": threading, "time": time, "json": json}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SCRIPT), "exec"), scope)  # noqa: S102 -- reviewed local class only
    return scope["Barrier"]


def exercise(barrier, state, status=200):
    async def run():
        sent = []

        async def receive():
            return {
                "type": "http.request",
                "body": json.dumps({"event": {"state": state}}).encode(),
                "more_body": False,
            }

        async def send(message):
            sent.append(message)

        await barrier({"type": "http", "path": "/api/v1/jobs/synthetic/events"}, receive, send)
        return sent

    return asyncio.run(run())


def test_prepare_never_fakes_success_or_applies_held_event():
    calls = []

    async def app(scope, receive, send):
        calls.append(scope)

    barrier = barrier_type()(app, "verifying")
    barrier.release.set()
    sent = exercise(barrier, "verifying")
    assert sent[0]["status"] == 503 and not calls and barrier.arrived.is_set()
    assert not barrier.states


def test_recovery_records_only_real_success():
    async def app(scope, receive, send):
        await receive()
        await send({"type": "http.response.start", "status": 200})
        await send({"type": "http.response.body", "body": b""})

    barrier = barrier_type()(app, "verifying")
    barrier.phase = "recover"
    barrier.release.set()
    exercise(barrier, "completed")
    assert barrier.states == ["completed"] and barrier.arrived.is_set()
    assert barrier.completion_body["event"]["state"] == "completed"


def test_rejected_stale_event_is_not_recorded_as_commit():
    async def app(scope, receive, send):
        await receive()
        await send({"type": "http.response.start", "status": 409})
        await send({"type": "http.response.body", "body": b""})

    barrier = barrier_type()(app, "verifying")
    barrier.phase = "recover"
    barrier.release.set()
    exercise(barrier, "completed")
    assert not barrier.states


def test_durable_and_interruption_assertions_are_present():
    java = (
        ROOT
        / "android/app/src/remoteQaAndroidTest/java/org/happyrun/app/remoteqa"
        / "RemoteDurableRecoveryAcceptanceTest.java"
    ).read_text()
    for requirement in (
        "journal.finished(job.jobId,job.runSessionId)",
        "driver.finished()",
        "driver.stopped()",
        "driver.startCount()==1",
        '"completed",result.state',
        "0,driver.startCount()",
        "0.0,driver.distanceM(),0.0",
    ):
        assert requirement in java
    for forbidden in (
        "FakeAgentClient",
        "callActivityOnStop",
        "journal.stopped(",
        "journal.startIntent(",
    ):
        assert forbidden not in java
    host = SCRIPT.read_text()
    assert '"force-stop"' in host and "guard()" in host
    assert "reply.status_code == 409" in host
    assert 'barrier.states == ["verifying", "completed"]' in host
