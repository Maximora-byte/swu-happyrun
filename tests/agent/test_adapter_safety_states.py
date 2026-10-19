"""Existing runner safety contracts with a synthetic driver, not app selectors."""

import pytest
from test_runner import rig as rig

from swu_happyrun.core.models import VerificationResult
from swu_happyrun.drivers.base import DriverError


def test_unknown_page_preflight_never_starts(rig):
    runner, client, driver, journal, clock = rig

    def unknown_page(job):
        raise DriverError("unknown_page")

    driver.prepare = unknown_page
    result = runner.run_once()
    assert result.state == "needs_attention"
    assert "start" not in driver.calls
    assert "tick" not in driver.calls
    assert not journal.has_intent(result.job_id, "start")
    assert "succeeded" not in client.states


@pytest.mark.parametrize("status", ["pending", "unknown", "invalid"])
@pytest.mark.parametrize("recovery", [False, True])
def test_device_unconfirmed_record_never_succeeds_or_replays(rig, status, recovery):
    runner, client, driver, journal, clock = rig
    spec = client.job.spec.model_copy(
        update={"mode": "device", "expected_app_version": "0.0.0-test"}
    )
    client.job = client.job.model_copy(
        update={
            "spec": spec,
            "recovery_action": "verify_only" if recovery else None,
        }
    )
    driver.verify = lambda job: VerificationResult(status=status, evidence=[], reason_code=None)
    result = runner.run_once()
    assert result.state == "needs_attention"
    assert result.reason_code == "verification_pending"
    assert "succeeded" not in client.states
    assert "completed" not in client.states
    assert driver.calls.count("start") == (0 if recovery else 1)
    assert not journal.has_intent(result.job_id, "upload")
    if recovery:
        assert "prepare" not in driver.calls
        assert "tick" not in driver.calls
