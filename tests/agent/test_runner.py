from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from swu_happyrun.agent.client import ControlError
from swu_happyrun.agent.journal import RunJournal
from swu_happyrun.agent.runner import AgentRunner
from swu_happyrun.core.models import JobSpec, JobView, LeaseGrant, VerificationResult


class Clock:
    def __init__(self):
        self.seconds = 0

    def utcnow(self):
        return datetime(2026, 10, 18, tzinfo=UTC) + timedelta(seconds=self.seconds)

    def monotonic(self):
        return self.seconds

    def sleep(self, seconds):
        self.seconds += seconds


class Driver:
    def bind_session(self, view):
        self.view = view

    def configure_execution_guard(self, check):
        self.guard = check

    def __init__(self):
        self.calls = []

    def prepare(self, job):
        self.calls.append("prepare")

    def start(self, job):
        self.calls.append("start")

    def tick(self, job, elapsed_seconds):
        self.calls.append("tick")

    def stop(self):
        self.calls.append("stop")

    def verify(self, job):
        self.calls.append("verify")
        return VerificationResult(status="unknown", evidence=[], reason_code="simulation_only")


class Client:
    def __init__(self, clock):
        self.clock = clock
        self.states = []
        self.cancel = False
        self.lose = False
        spec = dict(
            protocol_version=1,
            mode="simulation",
            profile_id=str(uuid4()),
            profile_revision="a" * 64,
            route_id=str(uuid4()),
            route_revision="b" * 64,
            device_id=str(uuid4()),
            not_before=clock.utcnow(),
            deadline=clock.utcnow() + timedelta(hours=1),
        )
        if "expected_app_version" in JobSpec.model_fields:
            spec["expected_app_version"] = None
        data = dict(
            job_id=str(uuid4()),
            spec=JobSpec(**spec),
            state="leased",
            revision=1,
            desired_state="run",
            fence=1,
            agent_id=str(uuid4()),
            reason_code=None,
            resume_phase=None,
            recovery_action=None,
        )
        if "run_session_id" in JobView.model_fields:
            data["run_session_id"] = str(uuid4())
        self.job = JobView(**data)
        self.expiry = 30

    def claim(self, device_id):
        return LeaseGrant(
            job=self.job,
            lease_token="secret",
            fence=self.job.fence,
            expires_at=self.clock.utcnow() + timedelta(seconds=self.expiry),
        )

    def get_job(self, job_id):
        return self.job

    def renew(self, job_id, lease):
        if self.lose:
            raise ControlError("lost")
        return {
            "expires_at": self.clock.utcnow() + timedelta(seconds=30),
            "desired_state": "cancel" if self.cancel else "run",
        }

    def events(self, job_id, lease, event):
        self.states.append(event.state.value)
        self.job = self.job.model_copy(
            update={
                "state": event.state,
                "revision": self.job.revision + 1,
                "reason_code": event.reason_code,
                "resume_phase": event.resume_phase,
            }
        )
        return self.job

    def stop_ack(self, job_id, lease, event_id, expected_revision):
        self.states.append("stop_ack")
        return self.job


@pytest.fixture
def rig(tmp_path):
    clock = Clock()
    client, driver = Client(clock), Driver()
    with RunJournal(tmp_path / "runs.sqlite") as journal:
        runner = AgentRunner(
            client,
            driver,
            journal,
            clock,
            device_id=client.job.spec.device_id,
            sleep=clock.sleep,
            run_seconds=2,
        )
        yield runner, client, driver, journal, clock


def test_fake_loop_completes_without_claiming_valid_record(rig):
    runner, client, driver, journal, clock = rig
    result = runner.run_once()
    assert result.state == "completed"
    assert journal.has_intent(client.job.job_id, "start")
    assert driver.calls.index("stop") < driver.calls.index("verify")
    assert driver.calls.count("start") == 1


def test_crash_after_start_intent_does_not_restart(rig):
    runner, client, driver, journal, clock = rig
    journal.record_intent(client.job.job_id, 1, "start")
    runner.run_once()
    assert "start" not in driver.calls
    assert "tick" not in driver.calls


def test_lease_loss_stops_ticks(rig):
    runner, client, driver, journal, clock = rig
    original = driver.tick

    def tick(job, elapsed):
        original(job, elapsed)
        client.lose = True

    driver.tick = tick
    runner.run_once()
    assert driver.calls.count("tick") == 1
    assert driver.calls[-1] == "stop"


def test_expired_lease_before_start_blocks_side_effect(rig):
    runner, client, driver, journal, clock = rig
    client.expiry = 0
    runner.run_once()
    assert "start" not in driver.calls


def test_cancel_ack_after_driver_stop(rig):
    runner, client, driver, journal, clock = rig
    client.cancel = True
    original = client.stop_ack

    def ack(*args):
        assert driver.calls[-1] == "stop"
        return original(*args)

    client.stop_ack = ack
    runner.run_once()
    assert "stop_ack" in client.states
    assert "start" not in driver.calls


def test_stop_failure_never_acknowledges(rig):
    runner, client, driver, journal, clock = rig
    client.cancel = True

    def fail():
        raise RuntimeError("device unavailable")

    driver.stop = fail
    runner.run_once()
    assert "stop_ack" not in client.states


def test_verify_only_never_starts_ticks_or_prepares(rig):
    runner, client, driver, journal, clock = rig
    client.job = client.job.model_copy(
        update={"recovery_action": "verify_only", "resume_phase": "running"}
    )
    runner.run_once()
    assert "start" not in driver.calls and "tick" not in driver.calls
    assert "prepare" not in driver.calls
    assert "running" not in client.states


def test_start_response_uncertain_is_not_repeated(rig):
    runner, client, driver, journal, clock = rig

    def fail(job):
        driver.calls.append("start")
        raise TimeoutError("uncertain")

    driver.start = fail
    runner.run_once()
    runner.run_once()
    assert driver.calls.count("start") == 1


def test_stop_precedes_reporting_uncertain_failure(rig):
    runner, client, driver, journal, clock = rig

    def fail(job):
        raise TimeoutError()

    driver.start = fail
    original = client.events

    def event(*args):
        if args[-1].state == "needs_attention":
            assert driver.calls[-1] == "stop"
        return original(*args)

    client.events = event
    runner.run_once()
    assert client.job.state == "needs_attention"


def test_running_response_loss_never_starts(rig):
    runner, client, driver, journal, clock = rig
    original = client.events

    def event(*args):
        value = original(*args)
        if args[-1].state == "running":
            raise ControlError("response lost")
        return value

    client.events = event
    runner.run_once()
    assert "start" not in driver.calls


def test_slow_start_past_lease_never_ticks(rig):
    runner, client, driver, journal, clock = rig

    def start(job):
        driver.calls.append("start")
        clock.seconds += 31

    driver.start = start
    runner.run_once()
    assert "tick" not in driver.calls
    assert driver.calls[-1] == "stop"


def test_stop_ack_response_loss_reuses_persisted_event(rig):
    runner, client, driver, journal, clock = rig
    client.cancel = True
    event_ids = []

    def ack(job_id, lease, event_id, expected_revision):
        event_ids.append(event_id)
        if len(event_ids) == 1:
            raise ControlError("response lost")
        return client.job

    client.stop_ack = ack
    runner.run_once()
    assert len(event_ids) == 2
    assert event_ids[0] == event_ids[1]


def test_slow_renewal_with_insufficient_action_budget_never_starts(rig):
    runner, client, driver, journal, clock = rig
    original = client.renew
    renewals = 0

    def renew(*args):
        nonlocal renewals
        renewals += 1
        result = original(*args)
        if renewals == 3:
            clock.seconds += 29.9
        return result

    client.renew = renew
    runner.run_once()
    assert "start" not in driver.calls
    assert "tick" not in driver.calls


def test_long_run_sends_agent_heartbeat_without_refreshing_probe(rig):
    runner, client, driver, journal, clock = rig
    runner.run_seconds = 25
    runner.hello = object()
    heartbeats = []
    client.heartbeat = lambda hello: heartbeats.append((clock.monotonic(), hello))
    runner.run_once()
    assert len(heartbeats) == 2
    assert all(hello is runner.hello for _, hello in heartbeats)


def test_upload_uncertain_simulation_is_not_completed(rig):
    runner, client, driver, journal, clock = rig
    driver.verify = lambda job: VerificationResult(
        status="unknown", evidence=[], reason_code="upload_uncertain"
    )
    result = runner.run_once()
    assert result.state == "needs_attention"
    assert "completed" not in client.states


def test_runner_binds_session_and_effect_guard_before_driver_use(rig):
    runner, client, driver, journal, clock = rig
    seen = []
    driver.bind_session = lambda view: seen.append(("session", view.job_id))
    driver.configure_execution_guard = lambda check: seen.append(("guard", check))
    original = driver.prepare

    def prepare(job):
        assert [item[0] for item in seen] == ["session", "guard"]
        original(job)

    driver.prepare = prepare
    runner.run_once()
    assert len(seen) == 2


@pytest.mark.parametrize("failing_action", ["start", "tick"])
def test_retry_preflight_failure_reports_current_running_phase_immediately(rig, failing_action):
    runner, client, driver, journal, clock = rig
    client.job = client.job.model_copy(
        update={
            "recovery_action": "retry_preflight",
            "resume_phase": "leased",
        }
    )
    original = client.events

    def server_events(job_id, lease, event):
        previous_phase = client.job.resume_phase
        if event.state == "needs_attention" and event.resume_phase != client.job.state.value:
            raise ControlError("HTTP 409: current resume phase required")
        result = original(job_id, lease, event)
        if event.state != "needs_attention":
            # Recovery history survives ordinary state updates on the actual server.
            client.job = result.model_copy(update={"resume_phase": previous_phase})
        return client.job

    def fail(*args):
        driver.calls.append(failing_action)
        raise TimeoutError("uncertain device action")

    client.events = server_events
    setattr(driver, failing_action, fail)
    result = runner.run_once()
    assert result.state == "needs_attention"
    assert result.resume_phase == "running"
    assert driver.calls[-1] == "stop"
    assert clock.monotonic() < 30  # No expiry required to reconcile the failure.


@pytest.mark.parametrize("action", ["verify_only", "stop_only"])
def test_read_or_stop_recovery_attention_preserves_historical_phase(rig, action):
    runner, client, driver, journal, clock = rig
    client.job = client.job.model_copy(
        update={
            "recovery_action": action,
            "resume_phase": "running",
        }
    )
    original = client.events

    def server_events(job_id, lease, event):
        previous_phase = client.job.resume_phase
        result = original(job_id, lease, event)
        if event.state != "needs_attention":
            client.job = result.model_copy(update={"resume_phase": previous_phase})
        return client.job

    client.events = server_events
    if action == "stop_only":

        def fail_stop():
            raise TimeoutError("stop unconfirmed")

        driver.stop = fail_stop
    result = runner.run_once()
    assert result.state == "needs_attention"
    assert result.resume_phase == "running"
    assert "start" not in driver.calls
    assert "tick" not in driver.calls


def test_cancelled_job_reports_stop_failure_without_waiting_for_expiry(rig):
    runner, client, driver, journal, clock = rig
    client.job = client.job.model_copy(
        update={"desired_state": "cancel", "state": type(client.job.state).CANCELLING}
    )

    def stop():
        raise TimeoutError("stop unconfirmed")

    driver.stop = stop
    result = runner.run_once()
    assert result.state == "needs_attention"
    assert result.reason_code == "stop_unconfirmed"
    assert "stop_ack" not in client.states
    assert "start" not in driver.calls


def test_window_expiry_reports_attention_with_live_lease(rig):
    runner, client, driver, journal, clock = rig
    client.job.spec.deadline = clock.utcnow() + timedelta(seconds=10)

    def tick(*args):
        driver.calls.append("tick")
        clock.seconds += 11

    driver.tick = tick
    result = runner.run_once()
    assert result.state == "needs_attention"
    assert result.resume_phase == "running"
    assert driver.calls.count("tick") == 1
    assert driver.calls[-1] == "stop"


def test_cancel_race_stop_failure_reports_using_latest_server_revision(rig):
    from swu_happyrun.core.states import JobState

    runner, client, driver, journal, clock = rig
    original_renew = client.renew
    original_events = client.events

    def renew(*args):
        if client.job.state == "running":
            client.job = client.job.model_copy(
                update={
                    "state": JobState.CANCELLING,
                    "desired_state": "cancel",
                    "revision": client.job.revision + 1,
                }
            )
            client.cancel = True
        return original_renew(*args)

    def events(job_id, lease, event):
        if event.expected_revision != client.job.revision:
            raise ControlError("HTTP 409: stale revision")
        return original_events(job_id, lease, event)

    def stop():
        raise TimeoutError("stop unconfirmed")

    client.renew = renew
    client.events = events
    client.get_job = lambda job_id: client.job
    driver.stop = stop
    result = runner.run_once()
    assert result.state == "needs_attention"
    assert result.reason_code == "stop_unconfirmed"
    assert result.resume_phase == "cancelling"
    assert "stop_ack" not in client.states


def test_route_budget_exhaustion_is_not_completion(rig):
    from types import SimpleNamespace

    runner, client, driver, _, _ = rig
    driver.route_progress = SimpleNamespace(finished=False)
    result = runner.run_once()
    assert result.state == "needs_attention"
    assert result.reason_code == "simulation_incomplete"
    assert "completed" not in client.states


def test_route_gets_final_guarded_tick_at_budget_boundary(rig):
    from types import SimpleNamespace

    runner, _, driver, _, _ = rig
    driver.route_progress = SimpleNamespace(finished=False)
    elapsed = []

    def tick(job, seconds):
        driver.guard()
        elapsed.append(seconds)
        driver.route_progress.finished = seconds >= runner.run_seconds

    driver.tick = tick
    assert runner.run_once().state == "completed"
    assert elapsed[-1] == runner.run_seconds


def test_shutdown_after_intent_prevents_start(rig):
    import signal

    from swu_happyrun.agent.lifecycle import Shutdown

    runner, _, driver, journal, _ = rig
    shutdown = Shutdown()
    runner.shutdown = shutdown
    original = journal.record_intent

    def intent(*args):
        original(*args)
        shutdown.request(signal.SIGTERM)

    journal.record_intent = intent
    result = runner.run_once()
    assert result.state == "needs_attention"
    assert journal.has_intent(result.job_id, "start")
    assert "start" not in driver.calls
    assert "stop" in driver.calls


def test_renew_latency_cannot_advance_route_past_budget(rig):
    from types import SimpleNamespace

    runner, client, driver, _, clock = rig
    driver.route_progress = SimpleNamespace(finished=False)
    elapsed = []
    renew = client.renew

    def delayed(job_id, lease):
        if "start" in driver.calls:
            clock.sleep(3)
        return renew(job_id, lease)

    def tick(job, seconds):
        elapsed.append(seconds)
        driver.route_progress.finished = seconds > runner.run_seconds

    client.renew = delayed
    driver.tick = tick
    result = runner.run_once()
    assert result.state == "needs_attention"
    assert result.reason_code == "simulation_incomplete"
    assert max(elapsed) <= runner.run_seconds
