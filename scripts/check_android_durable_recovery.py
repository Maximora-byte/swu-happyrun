"""One actual Android durable-finished recovery scenario, two process stages.
Uses existing remoteQa trust/fixture; never alters the original 15 or foreground 14 cases.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from uuid import uuid4

from check_remote_https_android import adb, current, guard, prepare_job
from remote_https_fixture import server_fixture, trusted_client

PACKAGE = "org.happyrun.app"
CLASS = PACKAGE + ".remoteqa.RemoteDurableRecoveryAcceptanceTest#testStage"


def wait_for(check, seconds=15):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        value = check()
        if value:
            return value
        time.sleep(0.2)
    raise AssertionError("bounded recovery observation missing")


class Barrier:
    def __init__(self, app, boundary):
        self.app = app
        self.boundary = boundary
        self.phase = "prepare"
        self.arrived = threading.Event()
        self.release = threading.Event()
        self.states = []
        self.completion_body = None

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].endswith("/events"):
            return await self.app(scope, receive, send)
        messages = []
        while True:
            message = await receive()
            messages.append(message)
            if not message.get("more_body", False):
                break
        body = json.loads(b"".join(m.get("body", b"") for m in messages))
        state = body["event"]["state"]
        if self.phase == "prepare" and state == self.boundary:
            self.arrived.set()
            boundary_deadline = time.monotonic() + 12
            while not self.release.is_set() and time.monotonic() < boundary_deadline:
                await asyncio.sleep(0.005)
            # Request is deliberately not applied: killed process cannot claim an event success.
            await send({"type": "http.response.start", "status": 503, "headers": []})
            await send({"type": "http.response.body", "body": b""})
            return
        if self.phase == "recover" and state == "completed" and self.completion_body is None:
            self.completion_body = body
            self.arrived.set()
            end = time.monotonic() + 3
            while not self.release.is_set() and time.monotonic() < end:
                await asyncio.sleep(0.005)
            if not self.release.is_set():
                raise AssertionError("completion fence probe not released")
        index = 0

        async def replay():
            nonlocal index
            if index < len(messages):
                value = messages[index]
                index += 1
                return value
            return await receive()

        status = None

        async def record(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        await self.app(scope, replay, record)
        if status == 200:
            self.states.append(state)


def launch(fixture, stage):
    command = [
        "adb",
        "-s",
        os.environ["ANDROID_SERIAL"],
        "shell",
        "am",
        "instrument",
        "-w",
        "-r",
        "-e",
        "class",
        CLASS,
    ]
    for name, value in {
        "stage": stage,
        "origin": fixture["android_origin"],
        "agent": fixture["agent_id"],
        "device": fixture["device_id"],
        "token": fixture["agent_token"],
    }.items():
        command += ["-e", name, value]
    command += [PACKAGE + ".test/android.test.InstrumentationTestRunner"]
    # Do not print this command, raw instrumentation output or credential-bearing exceptions.
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
    )
    output = []

    def reader():
        for line in process.stdout:
            output.append(line.rstrip())

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    return process, output, thread


def run(directory, certificates):
    guard()
    adb("shell", "am", "force-stop", PACKAGE)
    assert adb("shell", "pm", "clear", PACKAGE).strip() == "Success"
    with (
        server_fixture(directory, certificates) as fixture,
        trusted_client(certificates["ca.pem"]) as client,
    ):
        job, headers = prepare_job(client, fixture)
        barrier = Barrier(fixture["evidence"].app, "verifying")
        fixture["evidence"].app = barrier
        first, first_output, first_reader = launch(fixture, "prepare")
        try:
            assert barrier.arrived.wait(15), "Real verifying boundary not reached"
            expected = "DURABLE_RECOVERY READY starts=1 stopped=true persisted_finished=true"
            wait_for(lambda: expected in first_output, 3)
            assert first.poll() is None, "Prepare process ended before force-stop"
            adb("shell", "am", "force-stop", PACKAGE)
            first.wait(timeout=10)
            first_reader.join(timeout=2)
            assert first_output.count(expected) == 1
            assert "OK (1 test)" not in "\n".join(first_output), (
                "Prepare was not actually interrupted"
            )
        finally:
            if first.poll() is None:
                first.kill()
                first.wait(timeout=5)
            barrier.release.set()
            first.stdout.close()
        original = current(client, fixture, job, headers)
        assert original["state"] == "finishing"
        old_fence = original["fence"]
        old_session = original["run_session_id"]
        attention = wait_for(
            lambda: (
                value
                if (value := current(client, fixture, job, headers))["state"] == "needs_attention"
                else None
            ),
            40,
        )
        assert attention["reason_code"] == "lease_expired"
        reply = client.post(
            fixture["origin"] + "/api/v1/jobs/" + job + "/resume",
            headers=headers,
            json={"expected_revision": attention["revision"], "action": "verify_only"},
        )
        reply.raise_for_status()
        barrier.phase = "recover"
        barrier.states.clear()
        barrier.arrived.clear()
        barrier.release.clear()
        second, second_output, second_reader = launch(fixture, "recover")
        try:
            assert barrier.arrived.wait(15), "Real recovered completion request missing"
            current_view = current(client, fixture, job, headers)
            assert current_view["state"] == "verifying"
            assert (
                current_view["fence"] > old_fence and current_view["run_session_id"] == old_session
            )
            invalid = copy.deepcopy(barrier.completion_body)
            assert invalid is not None
            invalid["lease"]["fence"] = old_fence
            invalid["event"]["event_id"] = str(uuid4())
            reply = client.post(
                fixture["origin"] + "/api/v1/jobs/" + job + "/events",
                headers={"Authorization": "Bearer " + fixture["agent_token"]},
                json=invalid,
            )
            assert reply.status_code == 409
            unchanged = current(client, fixture, job, headers)
            assert (
                unchanged["revision"] == current_view["revision"]
                and unchanged["state"] == "verifying"
            )
            barrier.release.set()
            second.wait(timeout=15)
            second_reader.join(timeout=2)
            text = "\n".join(second_output)
            assert second.returncode == 0 and len(re.findall(r"OK \(1 test\)", text)) == 1
            assert not re.search(
                r"FAILURES|INSTRUMENTATION_(?:FAILED|ABORTED)|Exception|shortMsg=", text
            )
            assert (
                second_output.count(
                    "DURABLE_RECOVERY PASS state=completed starts=0 distance=0 stopped=true"
                )
                == 1
            )
            final = current(client, fixture, job, headers)
            assert (
                final["state"] == "completed"
                and final["run_session_id"] == old_session
                and final["fence"] > old_fence
            )
            assert barrier.states == ["verifying", "completed"]
            return {
                "case": "durable_finished_verify_only",
                "result": "passed",
                "process_stages": 2,
                "original_starts": 1,
                "recovery_starts": 0,
                "recovery_distance": 0,
                "driver_stopped": True,
                "server_state": "completed",
                "same_session": True,
                "fence_increased": True,
                "stale_completion_status": 409,
                "recovery_events": barrier.states,
            }
        finally:
            barrier.release.set()
            if second.poll() is None:
                second.kill()
                second.wait(timeout=5)
            second.stdout.close()
            adb("shell", "am", "force-stop", PACKAGE)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("qa/android-recovery"))
    args = parser.parse_args()
    guard()
    certificates = {
        name: args.private_dir / "certificates" / name
        for name in ("ca.pem", "server.pem", "server.key")
    }
    try:
        with tempfile.TemporaryDirectory(
            prefix="durable-recovery-", dir=args.private_dir
        ) as directory:
            result = run(Path(directory), certificates)
    except Exception as error:  # noqa: BLE001 -- raw exception may contain synthetic credential args
        result = {
            "case": "durable_finished_verify_only",
            "result": "failed",
            "error_type": type(error).__name__,
        }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "report.json").write_text(
        json.dumps(
            {
                "cases": [result],
                "android_instrumentation": True,
                "simulation_only": True,
                "mumu_verified": False,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print("ANDROID_DURABLE_RECOVERY", result["result"], flush=True)
    if result["result"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
