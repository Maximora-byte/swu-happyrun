"""Codex Issue 36: validate historical ownership before recovery rebind."""

import json

import pytest
from test_driver import persistent_driver, session_view
from test_runner import Client, Clock

from swu_happyrun.agent.journal import RunJournal
from swu_happyrun.agent.runner import AgentRunner
from swu_happyrun.core.profiles import LocalProfileStore
from swu_happyrun.drivers.base import DriverError
from swu_happyrun.drivers.fake import FakeDriver


def finished_state(tmp_path, changed):
    job, driver = persistent_driver(tmp_path)
    driver.prepare(job)
    driver.start(job)
    driver.tick(job, 10000)
    assert driver.route_progress.finished
    driver.stop()
    state = tmp_path / "fake-state.json"
    data = json.loads(state.read_text())
    other = "00000000-0000-0000-0000-000000000099"
    if changed == "agent":
        data["bound_view"]["agent_id"] = other
    elif changed == "no_agent":
        data["bound_view"]["agent_id"] = None
    elif changed == "session":
        data["bound_view"]["run_session_id"] = other
    elif changed == "spec":
        data["bound_view"]["spec"]["profile_revision"] = "f" * 64
        data["job"]["profile_revision"] = "f" * 64
    elif changed == "device":
        data["device_id"] = other
        data["bound_view"]["spec"]["device_id"] = other
        data["job"]["device_id"] = other
    elif changed == "fence":
        data["bound_view"]["fence"] = 3
    elif changed == "job":
        data["bound_view"]["job_id"] = other
    state.write_text(json.dumps(data))
    loaded = FakeDriver(
        job.device_id,
        LocalProfileStore(tmp_path / "profiles"),
        app_version=driver.app_version,
        state_path=state,
    )
    view = session_view(job, fence=2).model_copy(
        update={"recovery_action": "verify_only", "resume_phase": "verifying"}
    )
    return job, loaded, view, state


def test_mismatched_historical_agent_rejected_before_overwriting_state(tmp_path):
    _, driver, view, state = finished_state(tmp_path, "agent")
    before = state.read_bytes()
    with pytest.raises(DriverError, match="session_mismatch"):
        driver.bind_session(view)
    assert state.read_bytes() == before


@pytest.mark.parametrize(
    "changed", ["same", "agent", "no_agent", "session", "spec", "fence", "job"]
)
def test_reconstructed_runner_never_completes_another_agents_proof(tmp_path, changed):
    job, driver, view, state = finished_state(tmp_path, changed)
    clock = Clock()
    clock.utcnow = lambda: job.not_before
    client = Client(clock)
    client.job = view
    counts = driver.start_count, driver.tick_count, driver.stop_count
    before = state.read_bytes()

    def forbidden(*args):
        pytest.fail("verify-only must not prepare/start/tick")

    driver.prepare = driver.start = driver.tick = forbidden
    with RunJournal(tmp_path / "journal.sqlite3") as journal:
        result = AgentRunner(client, driver, journal, clock, device_id=job.device_id).run_once()
        assert result.state == ("completed" if changed == "same" else "needs_attention")
        assert ("completed" in client.states) is (changed == "same")
        assert (driver.start_count, driver.tick_count, driver.stop_count) == counts
        assert not journal.has_intent(result.job_id, "upload")
    if changed != "same":
        # Emergency stop may serialize the unchanged snapshot compactly.
        assert json.loads(state.read_text()) == json.loads(before)


def test_wrong_historical_device_rejected_during_load(tmp_path):
    with pytest.raises(DriverError, match="fake_state_invalid"):
        finished_state(tmp_path, "device")


def test_different_new_job_clears_old_completion_instead_of_inheriting_it(tmp_path):
    job, driver, view, state = finished_state(tmp_path, "same")
    view = view.model_copy(
        update={
            "job_id": "00000000-0000-0000-0000-000000000098",
            "run_session_id": "00000000-0000-0000-0000-000000000097",
        }
    )
    driver.bind_session(view)
    assert not driver.has_persisted_completion(view)
    assert json.loads(state.read_text())["route_finished"] is False
