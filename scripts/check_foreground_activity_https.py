"""Second-stage, actual Activity/HTTPS acceptance; original remote suite stays unchanged.
Requires already installed remoteQa app and matching test APK on disposable official AVD.
No screenshots or raw instrumentation logs: credential widgets must never be captured.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from check_remote_https_android import adb, guard
from remote_https_fixture import (
    error_type,
    failure_evidence,
    instrumentation_evidence,
    server_fixture,
    trusted_client,
)

PACKAGE = "org.happyrun.app"
CLASS = PACKAGE + ".remoteqa.RemoteForegroundActivityAcceptanceTest#testScenario"
CASES = (
    "two_jobs",
    "disconnect_idle",
    "disconnect_running",
    "back_idle",
    "back_running",
    "home_idle",
    "home_running",
    "rotate_idle",
    "rotate_running",
    "auth_latch",
    "attention_latch",
    "transport_latch",
    "storage_latch",
    "rapid_toggle",
)


def wait_for(test, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = test()
        if result:
            return result
        time.sleep(0.03)
    raise AssertionError("bounded QA condition not reached")


def create_job(client, fixture, headers, key, bad=False):
    now = datetime.now(UTC)
    spec = {
        "protocol_version": 1,
        "mode": "simulation",
        "expected_app_version": None,
        "profile_id": "11111111-1111-4111-8111-111111111111",
        "profile_revision": "0" * 64
        if bad
        else "b9005da1c3470e5583d0950e085b7eecae8860ca4d3df909b485847265b3da3f",
        "route_id": "22222222-2222-4222-8222-222222222222",
        "route_revision": "2098e955d3f5d998ec252128d63e4dbbcfbdd2ef81edd7496ad746ae52dc6f1c",
        "device_id": fixture["device_id"],
        "not_before": (now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
        "deadline": (now + timedelta(minutes=3)).isoformat().replace("+00:00", "Z"),
    }
    reply = client.post(
        fixture["origin"] + "/api/v1/jobs",
        headers={**headers, "Idempotency-Key": key},
        json=spec,
    )
    reply.raise_for_status()
    return reply.json()["job_id"]


def current(client, fixture, headers, job):
    reply = client.get(fixture["origin"] + "/api/v1/jobs/" + job, headers=headers)
    reply.raise_for_status()
    return reply.json()


def require_instrumentation_success(returncode, output, starts):
    """Fail closed on platform status, JUnit count, and exact controlled result marker."""
    combined = "\n".join(output)
    assert returncode == 0
    assert len(re.findall(r"OK \(1 test\)", combined)) == 1
    assert not re.search(
        r"FAILURES|INSTRUMENTATION_(?:FAILED|ABORTED)|Exception|shortMsg=", combined
    )
    assert output.count(f"FOREGROUND_QA PASS starts={starts} stopped=true") == 1


def run_case(case, directory, certificates, diagnostics=None):
    diagnostics = diagnostics if diagnostics is not None else {}
    diagnostics["host_phase"] = "guard"
    guard()
    adb("shell", "am", "force-stop", PACKAGE)
    assert adb("shell", "pm", "clear", PACKAGE).strip() == "Success"
    scenario = "lost_renew" if case == "transport_latch" else "normal"
    diagnostics["host_phase"] = "server_startup"
    with (
        server_fixture(
            directory, certificates, scenario=scenario, diagnostics=diagnostics
        ) as fixture,
        trusted_client(certificates["ca.pem"]) as client,
    ):
        diagnostics["host_phase"] = "prepare_device"
        headers = {"Authorization": "Bearer " + fixture["admin_token"]}
        reply = client.post(
            fixture["origin"] + "/api/v1/devices",
            headers=headers,
            json={"agent_id": fixture["agent_id"], "device_id": fixture["device_id"]},
        )
        reply.raise_for_status()
        incoming = []
        real_app = fixture["evidence"].app

        async def observe(scope, receive, send):
            # Compare only in memory; retained observations contain no headers or credentials.
            authorization = dict(scope.get("headers", [])).get(b"authorization", b"")
            is_agent = authorization in {
                ("Bearer " + fixture["agent_token"]).encode(),
                b"Bearer invalid-synthetic-only",
            }
            if scope["type"] == "http" and is_agent:
                incoming.append((scope["path"], time.monotonic()))
            await real_app(scope, receive, send)

        fixture["evidence"].app = observe
        job = None
        if case.endswith("_running") or case in {"attention_latch", "transport_latch"}:
            job = create_job(client, fixture, headers, "initial", case == "attention_latch")
        token = "invalid-synthetic-only" if case == "auth_latch" else fixture["agent_token"]
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
        for key, value in {
            "scenario": case,
            "origin": fixture["android_origin"],
            "agent": fixture["agent_id"],
            "device": fixture["device_id"],
            "token": token,
        }.items():
            command += ["-e", key, value]
        command += [PACKAGE + ".test/android.test.InstrumentationTestRunner"]
        # Kept in memory only. Never print command, raw stdout/stderr, or exception detail.
        diagnostics["host_phase"] = "instrumentation_start"
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

        reader_thread = threading.Thread(target=reader, daemon=True)
        reader_thread.start()

        def marker(name):
            prefix = "FOREGROUND_QA " + name
            if process.poll() is not None:
                reader_thread.join(timeout=1)
                if not any(line.startswith(prefix) for line in output):
                    raise AssertionError("instrumentation ended before required UI observation")
            return next((line for line in output if line.startswith(prefix)), None)

        try:
            diagnostics["host_phase"] = "ui_observation"
            heartbeat_delay = None
            if case == "two_jobs":
                wait_for(lambda: marker("WAITING"), 15)
                wait_for(lambda: any(path.endswith("/heartbeat") for path, _ in incoming), 16)
                first_hello = next(t for path, t in incoming if path.endswith("/hello"))
                first_heartbeat = next(t for path, t in incoming if path.endswith("/heartbeat"))
                heartbeat_delay = first_heartbeat - first_hello
                assert 9.8 <= heartbeat_delay <= 15
                first = create_job(client, fixture, headers, "first")
                a = wait_for(
                    lambda: (
                        value
                        if (value := current(client, fixture, headers, first))["state"]
                        == "completed"
                        else None
                    ),
                    15,
                )
                second = create_job(client, fixture, headers, "second")
                b = wait_for(
                    lambda: (
                        value
                        if (value := current(client, fixture, headers, second))["state"]
                        == "completed"
                        else None
                    ),
                    15,
                )
                assert b["fence"] > a["fence"] and a["run_session_id"] != b["run_session_id"]
                assert sum(path.endswith("/renew") for path, _ in incoming) == 10
                wait_for(lambda: marker("TWO_DONE"), 5)
            if case == "rapid_toggle":
                wait_for(lambda: marker("RECONNECTED"), 20)
                job = create_job(client, fixture, headers, "reconnected-work")
                wait_for(
                    lambda: current(client, fixture, headers, job)["state"] == "completed",
                    15,
                )
                wait_for(lambda: marker("RAPID_DONE"), 5)
            diagnostics["host_phase"] = "await_stopped"
            stopped = wait_for(lambda: marker("STOPPED"), 30)
            expected_starts = (
                2
                if case == "two_jobs"
                else (
                    1
                    if case.endswith("_running") or case in {"transport_latch", "rapid_toggle"}
                    else 0
                )
            )
            assert stopped == "FOREGROUND_QA STOPPED starts=" + str(expected_starts)
            before = len(incoming)
            diagnostics["host_phase"] = "sentinel_create"
            sentinel = create_job(client, fixture, headers, "after-stopped")
            diagnostics["host_phase"] = "instrumentation_finish"
            process.wait(timeout=10)
            reader_thread.join(timeout=2)
            diagnostics["host_phase"] = "validate_stopped"
            require_instrumentation_success(process.returncode, output, expected_starts)
            assert len(incoming) == before, "HTTP continued after UI stop/latch/return"
            assert current(client, fixture, headers, sentinel)["state"] == "queued"
            if case == "auth_latch":
                assert any(r["status"] == 401 for r in fixture["evidence"].records)
                assert not any(path.endswith("/claim") for path, _ in incoming)
            if case == "attention_latch":
                state = current(client, fixture, headers, job)
                assert (
                    state["state"] == "needs_attention"
                    and state["reason_code"] == "unsupported_simulation_profile"
                )
            if case == "transport_latch":
                assert fixture["evidence"].fault_used and fixture["evidence"].barrier.is_set()
                assert (
                    fixture["evidence"].renew_count == 4
                    and current(client, fixture, headers, job)["state"] == "running"
                )
            if case.endswith("_running"):
                assert current(client, fixture, headers, job)["state"] != "completed"
            if case == "storage_latch":
                assert not incoming
            if case == "rapid_toggle":
                assert current(client, fixture, headers, job)["state"] == "completed"
            result = {
                "case": case,
                "result": "passed",
                "driver_starts": expected_starts,
                "driver_stopped": True,
                "agent_requests": len(incoming),
            }
            if heartbeat_delay is not None:
                result["first_heartbeat_seconds"] = round(heartbeat_delay, 3)
            diagnostics["body_outcome"] = "passed"
            return result
        except Exception as error:
            diagnostics["body_outcome"] = "failed"
            diagnostics["body_error_type"] = error_type(error)
            raise
        finally:
            diagnostics["instrumentation"] = instrumentation_evidence(output)
            diagnostics["agent_requests"] = len(incoming)
            diagnostics["process_returncode"] = process.poll()
            diagnostics["cleanup_phase"] = "instrumentation_process"
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            process.stdout.close()
            diagnostics["cleanup_phase"] = "adb_force_stop"
            adb("shell", "am", "force-stop", PACKAGE)
            diagnostics["cleanup_phase"] = "done"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("qa/android-foreground"))
    args = parser.parse_args()
    guard()
    certificates = {
        name: args.private_dir / "certificates" / name
        for name in ("ca.pem", "server.pem", "server.key")
    }
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    for case in CASES:
        diagnostics = {}
        try:
            with tempfile.TemporaryDirectory(
                prefix="foreground-", dir=args.private_dir
            ) as temporary:
                result = run_case(case, Path(temporary), certificates, diagnostics)
        except Exception as error:  # noqa: BLE001 -- never expose credential-bearing command errors
            result = {
                "case": case,
                "result": "failed",
                "error_type": error_type(error),
                "diagnostics": failure_evidence(error, diagnostics),
            }
        results.append(result)
        print("FOREGROUND_ACTIVITY_QA", case, result["result"], flush=True)
        (args.output / "report.json").write_text(
            json.dumps(
                {
                    "cases": results,
                    "simulation_only": True,
                    "android_activity_https": True,
                    "mumu_verified": False,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    if any(r["result"] != "passed" for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
