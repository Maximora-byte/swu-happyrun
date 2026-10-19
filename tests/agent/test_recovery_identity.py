"""Additional identity boundaries for Issue 36, without changing driver tests."""

import json

import pytest
from test_driver import session_view
from test_profiles import setup_profiles

from swu_happyrun.core.profiles import LocalProfileStore
from swu_happyrun.drivers.fake import FakeDriver


@pytest.mark.parametrize("change", ["same", "agent", "device"])
def test_persisted_completion_requires_same_agent_and_device(tmp_path, change):
    job, school, _ = setup_profiles(tmp_path / "profiles")
    state = tmp_path / "fake.json"
    driver = FakeDriver(
        job.device_id,
        LocalProfileStore(tmp_path / "profiles"),
        app_version=school.app_version,
        state_path=state,
    )
    view = session_view(job)
    driver.bind_session(view)
    driver.prepare(job)
    driver.start(job)
    driver.tick(job, 10000)
    assert driver.route_progress.finished
    driver.stop()
    recovery = view.model_copy(update={"fence": 2, "recovery_action": "verify_only"})
    driver.bind_session(recovery)
    data = json.loads(state.read_text())
    changed = "00000000-0000-0000-0000-000000000099"
    if change == "agent":
        data["bound_view"]["agent_id"] = changed
    elif change == "device":
        data["device_id"] = changed
        data["job"]["device_id"] = changed
        data["bound_view"]["spec"]["device_id"] = changed
    state.write_text(json.dumps(data))
    before = state.read_bytes()
    counts = driver.start_count, driver.tick_count, driver.stop_count
    assert driver.has_persisted_completion(recovery) is (change == "same")
    assert state.read_bytes() == before
    assert (driver.start_count, driver.tick_count, driver.stop_count) == counts
