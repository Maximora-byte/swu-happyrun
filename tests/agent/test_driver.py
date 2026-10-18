import pytest
from test_profiles import setup_profiles


def session_view(
    job,
    *,
    job_id="00000000-0000-0000-0000-000000000010",
    session_id="00000000-0000-0000-0000-000000000011",
    fence=1,
):
    from swu_happyrun.core.models import JobView

    return JobView(
        job_id=job_id,
        spec=job,
        state="leased",
        revision=1,
        desired_state="run",
        fence=fence,
        agent_id="00000000-0000-0000-0000-000000000012",
        reason_code=None,
        resume_phase=None,
        recovery_action=None,
        run_session_id=session_id,
    )


def driver_fixture(tmp_path):
    from swu_happyrun.core.profiles import LocalProfileStore
    from swu_happyrun.drivers.fake import FakeDriver

    job, school, _ = setup_profiles(tmp_path)
    driver = FakeDriver(job.device_id, LocalProfileStore(tmp_path), app_version=school.app_version)
    driver.bind_session(session_view(job))
    return job, driver


def test_fake_lifecycle_has_no_record_evidence(tmp_path):
    from swu_happyrun.drivers.base import DeviceDriver

    job, driver = driver_fixture(tmp_path)
    assert isinstance(driver, DeviceDriver)
    assert driver.inspect().backend == "fake"
    assert driver.inspect().capabilities == []
    driver.prepare(job)
    assert driver.start_count == 0
    driver.start(job)
    driver.tick(job, 1.0)
    driver.stop()
    driver.stop()
    assert driver.start_count == 1
    assert driver.tick_count == 1
    assert driver.stop_count == 1
    result = driver.verify(job)
    assert result.status == "unknown"
    assert result.reason_code == "simulation_only"
    assert result.evidence == []


@pytest.mark.parametrize("change", ["device", "revision", "identity", "missing", "unprepared"])
def test_rejected_start_has_zero_side_effects(tmp_path, change):
    from swu_happyrun.core.profiles import ProfileError
    from swu_happyrun.drivers.base import DriverError

    job, driver = driver_fixture(tmp_path)
    driver.prepare(job)
    if change == "device":
        job = job.model_copy(update={"mode": "device", "expected_app_version": "test-1"})
    elif change == "revision":
        job.route_revision = "f" * 64
    elif change == "identity":
        job.device_id = "00000000-0000-0000-0000-000000000004"
    elif change == "missing":
        next((tmp_path / "routes").rglob("*.json")).unlink()
    elif change == "unprepared":
        driver.stop()
    with pytest.raises((DriverError, ProfileError)):
        driver.start(job)
    assert driver.start_count == 0
    assert driver.tick_count == 0


def test_duplicate_start_and_restart_are_rejected(tmp_path):
    from swu_happyrun.drivers.base import DriverError

    job, driver = driver_fixture(tmp_path)
    driver.prepare(job)
    driver.start(job)
    with pytest.raises(DriverError):
        driver.start(job)
    driver.stop()
    with pytest.raises(DriverError):
        driver.start(job)
    assert driver.start_count == 1


@pytest.mark.parametrize("elapsed", [-1.0, float("nan"), float("inf"), True])
def test_invalid_tick_is_not_applied(tmp_path, elapsed):
    from swu_happyrun.drivers.base import DriverError

    job, driver = driver_fixture(tmp_path)
    driver.prepare(job)
    driver.start(job)
    with pytest.raises(DriverError):
        driver.tick(job, elapsed)
    assert driver.tick_count == 0


def test_tick_cannot_go_backwards_or_continue_after_stop(tmp_path):
    from swu_happyrun.drivers.base import DriverError

    job, driver = driver_fixture(tmp_path)
    driver.prepare(job)
    driver.start(job)
    driver.tick(job, 2.0)
    with pytest.raises(DriverError):
        driver.tick(job, 1.0)
    driver.stop()
    with pytest.raises(DriverError):
        driver.tick(job, 3.0)
    assert driver.tick_count == 1


def test_unknown_mumu_coordinate_mapping_blocks_write():
    from swu_happyrun.core.models import GeoPoint
    from swu_happyrun.drivers.base import DriverError
    from swu_happyrun.drivers.mumu.location import MuMuLocation

    location = MuMuLocation()
    with pytest.raises(DriverError, match="coordinate_mapping_unverified"):
        location.write(GeoPoint(latitude=0.0, longitude=0.0), input_crs="WGS84")
    assert location.write_count == 0


def test_verify_requires_a_started_simulation(tmp_path):
    from swu_happyrun.drivers.base import DriverError

    job, driver = driver_fixture(tmp_path)
    driver.prepare(job)
    driver.stop()
    with pytest.raises(DriverError):
        driver.verify(job)


def test_failed_reprepare_cannot_reuse_old_configuration(tmp_path):
    from swu_happyrun.core.profiles import ProfileError
    from swu_happyrun.drivers.base import DriverError

    job, driver = driver_fixture(tmp_path)
    driver.prepare(job)
    bad = job.model_copy(update={"route_revision": "f" * 64})
    with pytest.raises(ProfileError):
        driver.prepare(bad)
    with pytest.raises(DriverError):
        driver.start(job)
    assert driver.start_count == 0


def scenario_driver(tmp_path, scenario):
    from swu_happyrun.core.profiles import LocalProfileStore
    from swu_happyrun.drivers.fake import FakeDriver

    job, school, _ = setup_profiles(tmp_path)
    driver = FakeDriver(
        job.device_id,
        LocalProfileStore(tmp_path),
        app_version=school.app_version,
        scenario=scenario,
    )
    driver.bind_session(session_view(job))
    return job, driver


def test_start_crash_is_ambiguous_and_cannot_repeat(tmp_path):
    from swu_happyrun.drivers.base import DriverError

    job, driver = scenario_driver(tmp_path, "start_crash")
    driver.prepare(job)
    with pytest.raises(DriverError, match="start_uncertain"):
        driver.start(job)
    with pytest.raises(DriverError, match="start_not_prepared"):
        driver.start(job)
    assert driver.start_count == 1
    driver.stop()
    assert driver.stop_count == 1


def test_failed_stop_is_not_a_stop_ack(tmp_path):
    from swu_happyrun.drivers.base import DriverError

    job, driver = scenario_driver(tmp_path, "stop_failure")
    driver.prepare(job)
    driver.start(job)
    with pytest.raises(DriverError, match="stop_unconfirmed"):
        driver.stop()
    assert driver.stop_count == 0
    with pytest.raises(DriverError, match="verification_not_ready"):
        driver.verify(job)
    driver.stop()
    assert driver.stop_count == 1


def test_upload_uncertain_never_produces_a_valid_record(tmp_path):
    job, driver = scenario_driver(tmp_path, "upload_uncertain")
    driver.prepare(job)
    driver.start(job)
    driver.stop()
    for _ in range(2):
        result = driver.verify(job)
        assert result.status == "unknown"
        assert result.reason_code == "upload_uncertain"
        assert result.evidence == []
    assert driver.start_count == 1


def test_inspect_timeout_is_not_capability_success(tmp_path):
    _, driver = scenario_driver(tmp_path, "inspect_timeout")
    with pytest.raises(TimeoutError):
        driver.inspect()
    assert driver.start_count == 0


def test_tick_failure_can_be_cleaned_up(tmp_path):
    from swu_happyrun.drivers.base import DriverError

    job, driver = scenario_driver(tmp_path, "tick_failure")
    driver.prepare(job)
    driver.start(job)
    with pytest.raises(DriverError, match="tick_failed"):
        driver.tick(job, 1.0)
    assert driver.tick_count == 0
    driver.stop()
    assert driver.stop_count == 1


def test_unknown_fault_scenario_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="unknown_fake_scenario"):
        scenario_driver(tmp_path, "typo")


def persistent_driver(tmp_path, scenario=None):
    from swu_happyrun.core.profiles import LocalProfileStore
    from swu_happyrun.drivers.fake import FakeDriver

    job, school, _ = setup_profiles(tmp_path / "profiles")
    is_new = not (tmp_path / "fake-state.json").exists()
    driver = FakeDriver(
        job.device_id,
        LocalProfileStore(tmp_path / "profiles"),
        app_version=school.app_version,
        scenario=scenario,
        state_path=tmp_path / "fake-state.json",
    )
    if is_new:
        driver.bind_session(session_view(job))
    return job, driver


def test_restarted_fake_verifies_stopped_state_without_prepare(tmp_path):
    job, driver = persistent_driver(tmp_path)
    driver.prepare(job)
    driver.start(job)
    driver.tick(job, 1.0)
    driver.stop()
    _, recovered = persistent_driver(tmp_path)
    assert recovered.verify(job).reason_code == "simulation_only"
    assert recovered.start_count == 1
    assert recovered.stop_count == 1


def test_restart_after_start_crash_does_not_repeat_start(tmp_path):
    from swu_happyrun.drivers.base import DriverError

    job, driver = persistent_driver(tmp_path, "start_crash")
    driver.prepare(job)
    with pytest.raises(DriverError, match="start_uncertain"):
        driver.start(job)
    _, recovered = persistent_driver(tmp_path)
    with pytest.raises(DriverError, match="start_not_prepared"):
        recovered.start(job)
    with pytest.raises(DriverError, match="driver_active"):
        recovered.prepare(job)
    assert recovered.start_count == 1
    recovered.stop()
    assert recovered.stop_count == 1


def test_restart_preserves_upload_uncertain(tmp_path):
    job, driver = persistent_driver(tmp_path, "upload_uncertain")
    driver.prepare(job)
    driver.start(job)
    driver.stop()
    _, recovered = persistent_driver(tmp_path)
    assert recovered.verify(job).reason_code == "upload_uncertain"
    assert recovered.start_count == 1


def test_corrupt_fake_state_fails_closed(tmp_path):
    from swu_happyrun.drivers.base import DriverError

    (tmp_path / "fake-state.json").write_text("{broken")
    with pytest.raises(DriverError, match="fake_state_invalid"):
        persistent_driver(tmp_path)


def test_effect_guard_rechecked_after_profile_validation(tmp_path):
    from swu_happyrun.drivers.base import DriverError

    job, driver = driver_fixture(tmp_path)
    driver.prepare(job)

    def expired():
        raise DriverError("lease_expired")

    driver.configure_execution_guard(expired)
    with pytest.raises(DriverError, match="lease_expired"):
        driver.start(job)
    assert driver.start_count == 0


def test_tick_guard_blocks_effect_but_never_blocks_stop(tmp_path):
    from swu_happyrun.drivers.base import DriverError

    job, driver = driver_fixture(tmp_path)
    driver.prepare(job)
    driver.start(job)

    def expired():
        raise DriverError("lease_expired")

    driver.configure_execution_guard(expired)
    with pytest.raises(DriverError, match="lease_expired"):
        driver.tick(job, 1.0)
    assert driver.tick_count == 0
    driver.stop()
    assert driver.stop_count == 1


def test_cannot_reprepare_previous_started_job(tmp_path):
    from swu_happyrun.drivers.base import DriverError

    job, driver = driver_fixture(tmp_path)
    driver.prepare(job)
    driver.start(job)
    driver.stop()
    with pytest.raises(DriverError, match="job_already_started"):
        driver.prepare(job)
    assert driver.start_count == 1


def test_driver_reusable_for_distinct_future_job(tmp_path):
    from datetime import timedelta

    job, driver = driver_fixture(tmp_path)
    driver.prepare(job)
    driver.start(job)
    driver.stop()
    future = job.model_copy(
        update={
            "not_before": job.not_before + timedelta(days=1),
            "deadline": job.deadline + timedelta(days=1),
        }
    )
    driver.bind_session(
        session_view(
            future,
            job_id="00000000-0000-0000-0000-000000000020",
            session_id="00000000-0000-0000-0000-000000000021",
        )
    )
    driver.prepare(future)
    driver.start(future)
    driver.stop()
    assert driver.start_count == 2


def test_broken_state_symlink_is_not_fresh_state(tmp_path):
    from swu_happyrun.drivers.base import DriverError

    (tmp_path / "fake-state.json").symlink_to(tmp_path / "missing.json")
    with pytest.raises(DriverError, match="fake_state_invalid"):
        persistent_driver(tmp_path)


def test_session_cannot_change_for_same_job(tmp_path):
    from swu_happyrun.drivers.base import DriverError

    job, driver = driver_fixture(tmp_path)
    with pytest.raises(DriverError, match="session_mismatch"):
        driver.bind_session(session_view(job, session_id="00000000-0000-0000-0000-000000000022"))


def test_recovery_rebind_accepts_same_session_higher_fence(tmp_path):
    job, driver = persistent_driver(tmp_path)
    driver.prepare(job)
    driver.start(job)
    driver.stop()
    _, recovered = persistent_driver(tmp_path)
    recovered.bind_session(session_view(job, fence=2))
    assert recovered.verify(job).reason_code == "simulation_only"
    assert recovered.start_count == 1


def test_stale_session_fence_rejected(tmp_path):
    from swu_happyrun.drivers.base import DriverError

    job, driver = driver_fixture(tmp_path)
    driver.bind_session(session_view(job, fence=2))
    with pytest.raises(DriverError, match="stale_fence"):
        driver.bind_session(session_view(job, fence=1))


def test_inspect_creates_fresh_probe_identity(tmp_path):
    _, driver = driver_fixture(tmp_path)
    first, second = driver.inspect(), driver.inspect()
    assert first.probe_id != second.probe_id


@pytest.mark.parametrize("action", ["verify_only", "stop_only"])
def test_fresh_driver_cannot_start_from_recovery_binding(tmp_path, action):
    from swu_happyrun.drivers.base import DriverError

    job, driver = driver_fixture(tmp_path)
    view = session_view(job).model_copy(
        update={"recovery_action": action, "resume_phase": "verifying"}
    )
    driver.bind_session(view)
    with pytest.raises(DriverError, match="recovery_cannot_start"):
        driver.prepare(job)
    assert driver.start_count == 0


def test_cancel_binding_blocks_tick_but_allows_stop(tmp_path):
    from swu_happyrun.drivers.base import DriverError

    job, driver = driver_fixture(tmp_path)
    driver.prepare(job)
    driver.start(job)
    from swu_happyrun.core.states import JobState

    view = session_view(job).model_copy(
        update={"state": JobState.CANCELLING, "desired_state": "cancel"}
    )
    driver.bind_session(view)
    with pytest.raises(DriverError, match="cancel_requested"):
        driver.tick(job, 1.0)
    driver.stop()
    assert driver.tick_count == 0
