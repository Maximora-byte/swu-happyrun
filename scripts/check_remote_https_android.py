"""Actual AVD -> TLS -> installed Python app acceptance. Synthetic isolated data only."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import threading
import time
import traceback
from datetime import UTC, datetime, timedelta
from pathlib import Path

from remote_https_fixture import issue_certificates, server_fixture, trusted_client

CASES = (
    "completed",
    "bad_ca",
    "bad_san",
    "plaintext",
    "redirect",
    "bad_token",
    "cancel",
    "local_stop",
    "lost_renew",
    "lost_event",
    "restart",
    "verify_only",
    "stop_only",
    "bad_profile",
    "expired",
)
PACKAGE = "org.happyrun.app"
TEST_CLASS = PACKAGE + ".remoteqa.RemoteHttpsAcceptanceTest#testScenario"


def adb(*args, timeout=90):
    return subprocess.run(
        ["adb", "-s", os.environ["ANDROID_SERIAL"], *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    ).stdout


def guard():
    serial = os.environ.get("ANDROID_SERIAL", "")
    if os.environ.get("HAPPYRUN_DISPOSABLE_EMULATOR") != "1" or not re.fullmatch(
        r"emulator-[0-9]+", serial
    ):
        raise RuntimeError("Only explicitly disposable emulator is allowed")
    if adb("shell", "getprop", "ro.kernel.qemu").strip() != "1":
        raise RuntimeError("Not a verified emulator")


def command(fixture, scenario):
    token = (
        "deliberately-wrong-synthetic-token" if scenario == "bad_token" else fixture["agent_token"]
    )
    args = [
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
        TEST_CLASS,
    ]
    for key, value in {
        "scenario": scenario,
        "origin": fixture["android_origin"],
        "agent": fixture["agent_id"],
        "device": fixture["device_id"],
        "token": token,
    }.items():
        args.extend(["-e", key, value])
    return [*args, PACKAGE + ".test/android.test.InstrumentationTestRunner"]


def instrumentation(fixture, scenario):
    # Never print command or raw stderr: command contains one-use synthetic credentials.
    result = subprocess.run(
        command(fixture, scenario), capture_output=True, text=True, encoding="utf-8", timeout=90
    )
    output = result.stdout
    if (
        result.returncode
        or not re.search(r"OK \(1 test\)", output)
        or re.search(r"FAILURES|INSTRUMENTATION_FAILED|Exception", output)
    ):
        raise RuntimeError("Android instrumentation failed: " + scenario)
    matches = re.findall(
        r"REMOTE_QA_STATE state=([a-z_]+) starts=(\d+) stopped=(true|false)", output
    )
    if len(matches) != 1:
        raise RuntimeError("Missing unambiguous Android observation")
    state, starts, stopped = matches[0]
    return {
        "android_state": state,
        "driver_starts": int(starts),
        "driver_stopped": stopped == "true",
    }


def prepare_job(client, fixture, bad_profile=False):
    headers = {"Authorization": "Bearer " + fixture["admin_token"]}
    origin = fixture["origin"]
    response = client.post(
        origin + "/api/v1/devices",
        headers=headers,
        json={"agent_id": fixture["agent_id"], "device_id": fixture["device_id"]},
    )
    response.raise_for_status()
    now = datetime.now(UTC)
    spec = {
        "protocol_version": 1,
        "mode": "simulation",
        "expected_app_version": None,
        "profile_id": "11111111-1111-4111-8111-111111111111",
        "profile_revision": "0" * 64
        if bad_profile
        else "b9005da1c3470e5583d0950e085b7eecae8860ca4d3df909b485847265b3da3f",
        "route_id": "22222222-2222-4222-8222-222222222222",
        "route_revision": "2098e955d3f5d998ec252128d63e4dbbcfbdd2ef81edd7496ad746ae52dc6f1c",
        "device_id": fixture["device_id"],
        "not_before": (now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
        "deadline": (now + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
    }
    response = client.post(
        origin + "/api/v1/jobs", headers={**headers, "Idempotency-Key": "remote-qa-only"}, json=spec
    )
    response.raise_for_status()
    return response.json()["job_id"], headers


def current(client, fixture, job, headers):
    response = client.get(fixture["origin"] + "/api/v1/jobs/" + job, headers=headers)
    response.raise_for_status()
    return response.json()


def run_case(case, directory, certificates):
    guard()
    adb("shell", "am", "force-stop", PACKAGE)
    if adb("shell", "pm", "clear", PACKAGE).strip() != "Success":
        raise RuntimeError("Disposable app reset failed")
    certificate = {"bad_ca": "other", "bad_san": "wrong"}.get(case, "server")
    scenario = "lost_renew" if case in {"verify_only", "stop_only"} else case
    with server_fixture(directory, certificates, certificate, scenario) as fixture:
        if case in {"bad_ca", "bad_san"}:
            result = instrumentation(fixture, case)
            assert not fixture["evidence"].records, "TLS rejection reached HTTP"
            return {
                "case": case,
                "result": "passed",
                **result,
                "server_state": None,
                "request_count": 0,
            }
        with trusted_client(certificates["ca.pem"]) as client:
            job, headers = prepare_job(client, fixture, case == "bad_profile")
            control_errors = []

            def cancel_controller():
                try:
                    if not fixture["evidence"].barrier.wait(12):
                        raise RuntimeError("Running renewal barrier not reached")
                    response = client.post(
                        fixture["origin"] + "/api/v1/jobs/" + job + "/cancel", headers=headers
                    )
                    response.raise_for_status()
                except Exception:
                    control_errors.append("cancel_controller_failed")
                finally:
                    fixture["evidence"].release.set()

            controller = None
            if case == "cancel":
                controller = threading.Thread(target=cancel_controller, daemon=True)
                controller.start()
            if case == "restart":
                with (directory / "interrupted-private.log").open("w+") as output:
                    process = subprocess.Popen(
                        command(fixture, "restart_prepare"),
                        stdout=output,
                        stderr=subprocess.DEVNULL,
                    )
                    try:
                        assert fixture["evidence"].barrier.wait(12), (
                            "No durable-running interruption barrier"
                        )
                        time.sleep(0.3)
                        adb("shell", "am", "force-stop", PACKAGE)
                        process.wait(timeout=10)
                        output.seek(0)
                        assert "ready_for_process_kill" in output.read(), (
                            "Missing Android durable-start observation"
                        )
                    finally:
                        if process.poll() is None:
                            process.kill()
                            process.wait(timeout=5)
                initial = {"driver_starts": 1}
            else:
                initial = instrumentation(fixture, scenario)
            if controller:
                controller.join(timeout=5)
                assert not controller.is_alive() and not control_errors, (
                    "Cancellation controller failed"
                )
            if case in {"restart", "verify_only", "stop_only"}:
                deadline = time.monotonic() + 40
                view = current(client, fixture, job, headers)
                while view["state"] != "needs_attention" and time.monotonic() < deadline:
                    time.sleep(0.2)
                    view = current(client, fixture, job, headers)
                assert view["state"] == "needs_attention", "Real lease did not expire to attention"
                original_session = view["run_session_id"]
                response = client.post(
                    fixture["origin"] + "/api/v1/jobs/" + job + "/resume",
                    headers=headers,
                    json={
                        "expected_revision": view["revision"],
                        "action": "stop_only" if case == "stop_only" else "verify_only",
                    },
                )
                response.raise_for_status()
                fixture["evidence"].scenario = "normal"
                result = instrumentation(fixture, "restart_recover" if case == "restart" else case)
                assert result["driver_starts"] == 0 and initial["driver_starts"] == 1
                assert current(client, fixture, job, headers)["run_session_id"] == original_session
            else:
                result = initial
            view = current(client, fixture, job, headers)
            if case in {"bad_profile", "local_stop", "verify_only", "restart"}:
                expected_reason = {
                    "bad_profile": "unsupported_simulation_profile",
                    "local_stop": "execution_uncertain",
                    "verify_only": "verification_pending",
                    "restart": "verification_pending",
                }[case]
                assert view["state"] == "needs_attention" and view["reason_code"] == expected_reason
            if case == "lost_renew":
                assert fixture["evidence"].barrier.is_set() and fixture["evidence"].fault_used
                assert fixture["evidence"].renew_count == 4
                assert view["state"] == "running" and result["driver_stopped"]
            if case == "lost_event":
                assert fixture["evidence"].barrier.is_set() and fixture["evidence"].fault_used
                assert fixture["evidence"].event_count == 4
                assert fixture["evidence"].committed_states.count("finishing") == 1
                assert "completed" not in fixture["evidence"].committed_states
                assert view["state"] == "finishing" and result["driver_stopped"]
            if case == "expired":
                assert view["state"] == "queued" and view["reason_code"] == "lease_expired"
                assert any(
                    r["path"].endswith("/renew") and r["status"] == 409
                    for r in fixture["evidence"].records
                )
            if case == "completed":
                assert view["state"] == "completed"
            elif case in {"cancel", "stop_only"}:
                assert view["state"] == "cancelled"
            elif case in {"bad_token", "plaintext", "redirect"}:
                assert view["state"] == "queued" and view["fence"] == 0
            else:
                assert view["state"] != "completed"
            return {
                "case": case,
                "result": "passed",
                **result,
                "server_state": view["state"],
                "request_count": len(fixture["evidence"].records),
            }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "run"))
    parser.add_argument("--private-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("qa/android-remote"))
    parser.add_argument("--ca-resource", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        certs = issue_certificates(args.private_dir / "certificates")
        if args.ca_resource is None:
            parser.error("--ca-resource is required for prepare")
        args.ca_resource.parent.mkdir(parents=True, exist_ok=True)
        args.ca_resource.write_bytes(certs["ca.pem"].read_bytes())
        return
    guard()
    ui = adb(
        "shell",
        "am",
        "instrument",
        "-w",
        "-r",
        "-e",
        "class",
        "org.happyrun.app.RemoteAgentActivityTest",
        PACKAGE + ".test/android.test.InstrumentationTestRunner",
    )
    if not re.search(r"OK \(3 tests\)", ui) or re.search(r"FAILURES|INSTRUMENTATION_FAILED", ui):
        raise RuntimeError("Remote UI input/lifecycle checks failed")
    certs = {
        name: args.private_dir / "certificates" / name
        for name in (
            "ca.pem",
            "server.pem",
            "server.key",
            "wrong.pem",
            "wrong.key",
            "other.pem",
            "other.key",
        )
    }
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    for case in CASES:
        try:
            with tempfile.TemporaryDirectory(prefix="case-", dir=args.private_dir) as directory:
                result = run_case(case, Path(directory), certs)
        except Exception as error:
            frame = traceback.extract_tb(error.__traceback__)[-1]
            result = {
                "case": case,
                "result": "failed",
                "error_type": type(error).__name__,
                "error_file": Path(frame.filename).name,
                "error_line": frame.lineno,
            }
        results.append(result)
        print("REMOTE_HTTPS_QA", case, result["result"], flush=True)
        (args.output / "report.json").write_text(
            json.dumps(
                {
                    "cases": results,
                    "android_http": True,
                    "remote_ui_tests": 3,
                    "simulation_only": True,
                    "real_device_verified": False,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    if any(result["result"] != "passed" for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
