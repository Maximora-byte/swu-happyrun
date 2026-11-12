"""Real transport loss with the old Android process alive across a newer lease grant."""

import argparse
import copy
import json
import os
import re
import subprocess
import tempfile
import threading
from pathlib import Path
from uuid import uuid4

from check_android_durable_recovery import wait_for
from check_remote_https_android import adb, current, guard, prepare_job
from remote_https_fixture import server_fixture, trusted_client

PACKAGE = "org.happyrun.app"


class LeaseCapture:
    def __init__(self, app):
        self.app = app
        self.running_body = None

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
        if body["event"]["state"] == "running":
            self.running_body = body  # Private ephemeral lease, never emitted to evidence.
        index = 0

        async def replay():
            nonlocal index
            if index < len(messages):
                result = messages[index]
                index += 1
                return result
            return await receive()

        return await self.app(scope, replay, send)


def run(directory, certificates):
    guard()
    adb("shell", "am", "force-stop", PACKAGE)
    assert adb("shell", "pm", "clear", PACKAGE).strip() == "Success"
    with (
        server_fixture(directory, certificates, scenario="lost_renew") as fixture,
        trusted_client(certificates["ca.pem"]) as client,
    ):
        job, admin = prepare_job(client, fixture)
        capture = LeaseCapture(fixture["evidence"].app)
        fixture["evidence"].app = capture
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
            PACKAGE + ".remoteqa.RemoteLiveFenceAcceptanceTest#testOldProcessStopsAcrossNewFence",
        ]
        for key, value in {
            "origin": fixture["android_origin"],
            "agent": fixture["agent_id"],
            "device": fixture["device_id"],
            "token": fixture["agent_token"],
        }.items():
            command += ["-e", key, value]
        command += [PACKAGE + ".test/android.test.InstrumentationTestRunner"]
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8"
        )
        output = []

        def read():
            for line in process.stdout:
                output.append(line.rstrip())

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        try:
            assert fixture["evidence"].barrier.wait(18)
            assert fixture["evidence"].fault_used and fixture["evidence"].renew_count == 4

            def stopped():
                return re.search(
                    r"LIVE_FENCE STOPPED pid=(\d+) starts=1 ticks=(\d+) attempts=(\d+)",
                    "\n".join(output),
                )

            first = wait_for(stopped, 12)
            pid, ticks, attempts = map(int, first.groups())
            assert ticks > 0 and attempts >= ticks
            assert process.poll() is None
            assert str(pid) in adb("shell", "pidof", PACKAGE).split()
            original = current(client, fixture, job, admin)
            assert original["state"] == "running" and capture.running_body is not None
            attention = wait_for(
                lambda: (
                    v
                    if (v := current(client, fixture, job, admin))["state"] == "needs_attention"
                    else None
                ),
                40,
            )
            assert attention["reason_code"] == "lease_expired"
            response = client.post(
                fixture["origin"] + "/api/v1/jobs/" + job + "/resume",
                headers=admin,
                json={"expected_revision": attention["revision"], "action": "verify_only"},
            )
            response.raise_for_status()
            agent = {"Authorization": "Bearer " + fixture["agent_token"]}
            claimed = client.post(
                fixture["origin"] + "/api/v1/leases/claim",
                headers=agent,
                json={"device_id": fixture["device_id"]},
            )
            assert claimed.status_code == 200
            grant = claimed.json()
            assert grant["fence"] > original["fence"]
            newer = current(client, fixture, job, admin)
            assert newer["run_session_id"] == original["run_session_id"]
            assert newer["fence"] == grant["fence"] and newer["job_id"] == job
            assert process.poll() is None and str(pid) in adb("shell", "pidof", PACKAGE).split()
            stale = copy.deepcopy(capture.running_body)
            stale["event"].update(
                event_id=str(uuid4()), state="completed", expected_revision=newer["revision"]
            )
            rejected = client.post(
                fixture["origin"] + "/api/v1/jobs/" + job + "/events", headers=agent, json=stale
            )
            assert rejected.status_code == 409
            assert current(client, fixture, job, admin)["revision"] == newer["revision"]
            process.wait(timeout=15)
            reader.join(timeout=2)
            text = "\n".join(output)
            assert process.returncode == 0 and len(re.findall(r"OK \(1 test\)", text)) == 1
            assert not re.search(
                r"FAILURES|INSTRUMENTATION_(?:FAILED|ABORTED)|Exception|shortMsg=", text
            )
            expected = f"LIVE_FENCE PASS pid={pid} starts=1 ticks={ticks} attempts={attempts}"
            assert output.count(expected) == 1
            return {
                "case": "old_live_process_after_new_fence",
                "result": "passed",
                "old_process_alive_at_grant": True,
                "old_process_pid": pid,
                "controlled_scheduling_delay_ms": 5200,
                "fault_injected_at_renew": 4,
                "route_unfinished_at_loss": True,
                "accepted_ticks": ticks,
                "attempted_ticks": attempts,
                "counts_unchanged": True,
                "driver_stopped": True,
                "real_expiry": True,
                "fence_increased": True,
                "stale_event_status": 409,
                "simulation_only": True,
            }
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            process.stdout.close()
            adb("shell", "am", "force-stop", PACKAGE)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("qa/android-live-fence"))
    args = parser.parse_args()
    certificates = {
        name: args.private_dir / "certificates" / name
        for name in ("ca.pem", "server.pem", "server.key")
    }
    try:
        with tempfile.TemporaryDirectory(prefix="live-fence-", dir=args.private_dir) as directory:
            result = run(Path(directory), certificates)
    except Exception as error:  # noqa: BLE001 -- no credential-bearing raw exception output
        result = {
            "case": "old_live_process_after_new_fence",
            "result": "failed",
            "error_type": type(error).__name__,
        }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("ANDROID_LIVE_FENCE", result["result"])
    if result["result"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
