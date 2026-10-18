"""Actual TCP AgentRunner faults with the packaged FakeDriver and durable journals."""

import subprocess
import sys
from datetime import UTC, datetime

import pytest
from integration_fixture import create_fixture
from test_http_protocol import DEVICE_ID

from swu_happyrun.agent.client import ControlClient, ControlError
from swu_happyrun.agent.journal import RunJournal
from swu_happyrun.agent.runner import AgentRunner
from swu_happyrun.core.clock import SystemClock
from swu_happyrun.core.profiles import LocalProfileStore
from swu_happyrun.drivers.fake import FakeDriver


@pytest.fixture
def runtime(service, tmp_path):
    s = service
    s.clock.now = datetime.now(UTC)
    spec = create_fixture(tmp_path, DEVICE_ID)
    s.spec = spec.model_dump(mode="json")
    assert s.hello().status_code == 200
    created = s.create()
    assert created.status_code == 201
    return s, tmp_path, created.json()


def make_runner(
    s, root, *, scenario="normal", client_type=ControlClient, driver_type=FakeDriver, run_seconds=2
):
    client = client_type(s.url, "integration-agent")
    journal = RunJournal(root / "journal.sqlite3")
    driver = driver_type(
        DEVICE_ID,
        LocalProfileStore(root / "profiles"),
        scenario=scenario,
        state_path=root / "fake.json",
        route_speed_mps=2,
    )
    runner = AgentRunner(
        client,
        driver,
        journal,
        SystemClock(),
        device_id=DEVICE_ID,
        run_seconds=run_seconds,
        tick_seconds=0.05,
    )
    return runner, driver, journal, client


def test_real_agent_completes_fake_only(runtime):
    s, root, created = runtime
    runner, driver, journal, client = make_runner(s, root)
    try:
        result = runner.run_once()
        assert result.state == "completed"
        assert driver.route_progress.finished
        assert driver.route_progress.distance_m == driver.route_progress.total_distance_m
        assert driver.route_progress.speed_mps == 0  # Finished motion is stopped.
        assert (
            driver.route_progress.distance_m / driver.route_progress.elapsed_seconds
            == pytest.approx(2)
        )
        assert driver.start_count == 1 and driver.stop_count == 1
        assert journal.has_intent(created["job_id"], "start")
        assert not journal.has_intent(created["job_id"], "upload")
        assert runner.run_once() is None
        assert driver.start_count == 1
    finally:
        journal.close()
        client.close()


def test_budget_exhaustion_is_attention_not_fake_completion(runtime):
    s, root, created = runtime
    runner, driver, journal, client = make_runner(s, root, run_seconds=0.05)
    try:
        result = runner.run_once()
        assert result.state == "needs_attention"
        assert result.reason_code == "simulation_incomplete"
        assert not driver.route_progress.finished
        assert driver.start_count == 1 and driver.stop_count == 1
        assert not driver.verify(result.spec).evidence
        assert not journal.has_intent(created["job_id"], "upload")
        assert runner.run_once() is None
        assert driver.start_count == 1
        current = s.get("jobs/" + created["job_id"]).json()
        assert current["state"] == "needs_attention"
        assert current["reason_code"] == "simulation_incomplete"
    finally:
        journal.close()
        client.close()


@pytest.mark.parametrize("scenario", ["start_crash", "upload_uncertain"])
def test_uncertainty_and_verify_recovery_never_restarts(runtime, scenario):
    s, root, created = runtime
    runner, driver, journal, client = make_runner(s, root, scenario=scenario)
    try:
        result = runner.run_once()
        assert result.state == "needs_attention"
        assert driver.start_count == 1
        assert runner.run_once() is None
        response = s.post(
            "jobs/" + created["job_id"] + "/resume",
            {"action": "verify_only", "expected_revision": result.revision},
            admin=True,
        )
        assert response.status_code == 200, response.text
        recovered = runner.run_once()
        assert recovered.state == "needs_attention"  # Unknown is not fabricated completion.
        assert driver.start_count == 1
        assert not journal.has_intent(created["job_id"], "upload")
    finally:
        journal.close()
        client.close()


def test_cancel_with_actual_http_stop_ack_response_loss(runtime):
    s, root, created = runtime

    class LostAckClient(ControlClient):
        lost = False
        calls = []

        def stop_ack(self, job_id, lease, event_id, expected_revision):
            self.calls.append((event_id, expected_revision))
            result = super().stop_ack(job_id, lease, event_id, expected_revision)
            if not self.lost:
                self.lost = True
                raise ControlError("injected response loss after HTTP commit")
            return result

    class CancellingDriver(FakeDriver):
        def tick(self, job, elapsed):
            super().tick(job, elapsed)
            assert s.post("jobs/" + created["job_id"] + "/cancel", admin=True).status_code == 200

    runner, driver, journal, client = make_runner(
        s, root, client_type=LostAckClient, driver_type=CancellingDriver
    )
    try:
        result = runner.run_once()
        assert result.state == "cancelled"
        assert driver.start_count == 1 and driver.stop_count == 1
        assert len(client.calls) == 2 and client.calls[0] == client.calls[1]
    finally:
        journal.close()
        client.close()


def test_running_receipt_loss_no_start(runtime):
    s, root, created = runtime

    class LostRunningClient(ControlClient):
        def events(self, job_id, lease, event):
            result = super().events(job_id, lease, event)
            if event.state == "running":
                raise ControlError("injected running receipt loss")
            return result

    runner, driver, journal, client = make_runner(s, root, client_type=LostRunningClient)
    try:
        runner.run_once()
        assert driver.start_count == 0
        assert not journal.has_intent(created["job_id"], "start")
        s.clock.advance(31)
        assert s.claim().status_code == 204
        result = s.get("jobs/" + created["job_id"]).json()
        assert result["state"] == "needs_attention"
        assert result["resume_phase"] == "running"
    finally:
        journal.close()
        client.close()


def test_process_crash_persists_intent_and_restart_never_starts_again(runtime):
    s, root, created = runtime
    program = """
import os,sys
from pathlib import Path
from swu_happyrun.agent.client import ControlClient
from swu_happyrun.agent.journal import RunJournal
from swu_happyrun.agent.runner import AgentRunner
from swu_happyrun.core.clock import SystemClock
from swu_happyrun.core.profiles import LocalProfileStore
from swu_happyrun.drivers.fake import FakeDriver
class Crash(FakeDriver):
    def start(self,job):
        super().start(job)
        os._exit(73)
root=Path(sys.argv[2])
d=Crash(sys.argv[3],LocalProfileStore(root/'profiles'),state_path=root/'fake.json')
r=AgentRunner(ControlClient(sys.argv[1],'integration-agent'),d,RunJournal(root/'journal.sqlite3'),SystemClock(),device_id=sys.argv[3])
r.run_once()
"""
    result = subprocess.run(
        [sys.executable, "-c", program, s.url, str(root), DEVICE_ID],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 73, result.stderr
    with RunJournal(root / "journal.sqlite3") as journal:
        assert journal.has_intent(created["job_id"], "start")
    # Crash loses grant credentials. Advance server time and explicitly authorize recovery.
    s.clock.advance(31)
    assert s.claim().status_code == 204
    attention = s.get("jobs/" + created["job_id"]).json()
    assert attention["state"] == "needs_attention"
    assert (
        s.post(
            "jobs/" + created["job_id"] + "/resume",
            {"action": "verify_only", "expected_revision": attention["revision"]},
            admin=True,
        ).status_code
        == 200
    )
    runner, driver, journal, client = make_runner(s, root)
    try:
        recovered = runner.run_once()
        assert recovered.state == "needs_attention"
        assert driver.start_count == 1 and driver.stop_count == 1
    finally:
        journal.close()
        client.close()


def test_lease_loss_stops_and_keeps_reservation(runtime):
    s, root, created = runtime

    class ExpiringDriver(FakeDriver):
        def tick(self, job, elapsed):
            super().tick(job, elapsed)
            s.clock.advance(31)

    runner, driver, journal, client = make_runner(s, root, driver_type=ExpiringDriver)
    try:
        runner.run_once()
        assert driver.start_count == 1 and driver.stop_count == 1
        attention = s.get("jobs/" + created["job_id"]).json()
        assert attention["state"] == "needs_attention"
        assert s.hello().status_code == 200
        assert s.create().status_code == 201
        assert s.claim().status_code == 204
    finally:
        journal.close()
        client.close()


def test_failed_stop_never_claims_completion(runtime):
    s, root, created = runtime
    runner, driver, journal, client = make_runner(s, root, scenario="stop_failure")
    try:
        result = runner.run_once()
        assert result.state == "needs_attention"
        assert driver.start_count == 1
        assert s.get("jobs/" + created["job_id"]).json()["state"] == "needs_attention"
    finally:
        journal.close()
        client.close()


def test_two_process_device_lock_blocks_claim(runtime):
    import time

    from swu_happyrun.agent.journal import UnsafeReplay

    s, root, created = runtime
    program = """
import sys,time
from pathlib import Path
from swu_happyrun.agent.journal import RunJournal
root=Path(sys.argv[1])
with RunJournal(root/'journal.sqlite3') as j:
    with j.device_lock(sys.argv[2]):
        (root/'locked').write_text('ready')
        while not (root/'release').exists(): time.sleep(.02)
"""
    holder = subprocess.Popen([sys.executable, "-c", program, str(root), DEVICE_ID], cwd=root)
    try:
        end = time.monotonic() + 10
        while not (root / "locked").exists() and time.monotonic() < end:
            assert holder.poll() is None
            time.sleep(0.02)
        assert (root / "locked").exists()
        runner, driver, journal, client = make_runner(s, root)
        try:
            with pytest.raises(UnsafeReplay):
                runner.run_once()
            assert s.get("jobs/" + created["job_id"]).json()["state"] == "queued"
            assert driver.start_count == 0
        finally:
            journal.close()
            client.close()
    finally:
        (root / "release").write_text("release")
        holder.wait(timeout=10)
    assert holder.returncode == 0


def test_retry_preflight_then_start_failure_reports_running_attention_immediately(runtime):
    s, root, created = runtime
    grant = s.claim().json()
    attention = s.event(grant, "needs_attention", phase="leased").json()
    response = s.post(
        "jobs/" + created["job_id"] + "/resume",
        {"expected_revision": attention["revision"], "action": "retry_preflight"},
        admin=True,
    )
    assert response.status_code == 200
    runner, driver, journal, client = make_runner(s, root, scenario="start_crash")
    try:
        result = runner.run_once()
        assert driver.start_count == 1
        assert result.state == "needs_attention"
        current = s.get("jobs/" + created["job_id"]).json()
        assert current["state"] == "needs_attention"
        assert current["resume_phase"] == "running"
    finally:
        journal.close()
        client.close()


def test_cancel_stop_failure_reports_attention_immediately(runtime):
    from swu_happyrun.drivers.base import DriverError

    s, root, created = runtime

    class CannotStop(FakeDriver):
        def tick(self, job, elapsed):
            super().tick(job, elapsed)
            assert s.post("jobs/" + created["job_id"] + "/cancel", admin=True).status_code == 200

        def stop(self):
            raise DriverError("injected_stop_failure")

    runner, driver, journal, client = make_runner(s, root, driver_type=CannotStop)
    try:
        runner.run_once()
        assert driver.start_count == 1
        current = s.get("jobs/" + created["job_id"]).json()
        assert current["state"] == "needs_attention"
        assert current["desired_state"] == "cancel"
        assert current["reason_code"] == "stop_unconfirmed"
    finally:
        journal.close()
        client.close()
