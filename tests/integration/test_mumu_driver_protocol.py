"""R4 synthetic boundary through the existing runner and actual loopback server."""

import importlib
from datetime import UTC, datetime, timedelta

import pytest
from test_http_protocol import DEVICE_ID
from test_http_runner import runtime  # noqa: F401

from swu_happyrun.agent.client import ControlClient, ControlError
from swu_happyrun.agent.journal import RunJournal
from swu_happyrun.agent.runner import AgentRunner, LeaseLost
from swu_happyrun.core.profiles import LocalProfileStore
from swu_happyrun.drivers.base import DeviceDriver, DriverError
from swu_happyrun.drivers.fake import FakeDriver
from swu_happyrun.drivers.mumu.sensors import MuMuSensors


def driver_class():
    try:
        module = importlib.import_module("swu_happyrun.drivers.mumu.driver")
    except ModuleNotFoundError:
        pytest.fail("R4 MuMuDriver composition is missing")
    return module.MuMuDriver


class SyntheticClock:
    def __init__(self):
        self.wall = datetime.now(UTC)
        self.seconds = 0

    def utcnow(self):
        return self.wall + timedelta(seconds=self.seconds)

    def monotonic(self):
        return self.seconds

    def sleep(self, seconds):
        self.seconds += seconds


class Transport:
    def __init__(self):
        self.writes = []
        self.stops = 0
        self.confirm = True
        self.on_write = lambda: None

    def write(self, sample):
        self.on_write()
        self.writes.append(sample)

    def stop_and_confirm_empty(self):
        self.stops += 1
        return self.confirm


@pytest.fixture
def composed(runtime):  # noqa: F811
    s, root, created = runtime
    clock = SyntheticClock()
    s.clock.utcnow = clock.utcnow
    transport = Transport()
    sensors = MuMuSensors.for_synthetic_testing(transport=transport, clock=clock.monotonic)
    fake = FakeDriver(
        DEVICE_ID, LocalProfileStore(root / "profiles"), clock=clock, route_speed_mps=2
    )
    driver = driver_class().for_synthetic_testing(
        fake=fake, sensors=sensors, binding_check=lambda: None, clock=clock
    )
    journal = RunJournal(root / "mumu-journal.sqlite3")
    client = ControlClient(s.url, "integration-agent")
    runner = AgentRunner(
        client,
        driver,
        journal,
        clock,
        device_id=DEVICE_ID,
        sleep=clock.sleep,
        run_seconds=2,
        tick_seconds=0.5,
    )
    try:
        yield s, created, runner, driver, fake, transport, journal, client, clock
    finally:
        journal.close()
        client.close()


def test_real_entry_is_closed_and_advertises_no_capabilities():
    driver = driver_class()(DEVICE_ID)
    assert isinstance(driver, DeviceDriver)
    assert driver.inspect().capabilities == []
    assert driver.inspect().backend == "mumu"
    for action in (driver.prepare, driver.start):
        with pytest.raises(DriverError, match="unsupported_by_candidate"):
            action(None)
    with pytest.raises(DriverError, match="unsupported_by_candidate"):
        driver.tick(None, 0)
    with pytest.raises(DriverError, match="stop_unconfirmed"):
        driver.stop()
    result = driver.verify(None)
    assert result.status == "unknown" and not result.evidence
    assert result.reason_code == "unsupported_by_candidate"


def test_prepare_has_no_transport_side_effects(composed):
    s, created, runner, driver, fake, transport, journal, client, clock = composed
    grant = client.claim(DEVICE_ID)
    driver.bind_session(grant.job)
    driver.prepare(grant.job.spec)
    assert fake.start_count == fake.tick_count == transport.stops == 0
    assert transport.writes == []
    assert driver.inspect().backend == "fake"
    assert driver.inspect().capabilities == []


def test_running_accepted_and_persisted_intent_precede_actions(composed):
    s, created, runner, driver, fake, transport, journal, client, clock = composed
    original = fake.start

    def start(job):
        assert s.get("jobs/" + job_id).json()["state"] == "running"
        with RunJournal(journal_path) as persisted:
            assert persisted.has_intent(job_id, "start")
        original(job)

    job_id = created["job_id"]
    journal_path = (
        journal.path
        if hasattr(journal, "path")
        else s.settings.database_path.parent / "mumu-journal.sqlite3"
    )
    fake.start = start
    result = runner.run_once()
    assert result.state == "completed"
    assert fake.start_count == 1 and transport.writes
    assert transport.stops == 1
    assert not journal.has_intent(job_id, "upload")


def test_running_receipt_loss_produces_zero_actions(composed):
    s, created, runner, driver, fake, transport, journal, client, clock = composed
    original = client.events

    def events(job_id, lease, event):
        result = original(job_id, lease, event)
        if event.state == "running":
            raise ControlError("lost receipt")
        return result

    client.events = events
    runner.run_once()
    assert fake.start_count == fake.tick_count == 0
    assert transport.writes == []
    assert not journal.has_intent(created["job_id"], "start")


@pytest.mark.parametrize("fault", ["cancel", "lost", "expired"])
def test_fault_after_first_write_stops_without_more_ticks(composed, fault):
    s, created, runner, driver, fake, transport, journal, client, clock = composed

    def fault_after_write():
        if fault == "cancel":
            assert s.post("jobs/" + created["job_id"] + "/cancel", admin=True).status_code == 200
        elif fault == "expired":
            clock.sleep(31)
        else:

            def lost(*args):
                raise ControlError("connection lost")

            client.renew = lost

    transport.on_write = fault_after_write
    runner.run_once()
    assert len(transport.writes) == 1
    assert transport.stops == 1
    assert not journal.has_intent(created["job_id"], "upload")
    if fault == "cancel":
        assert s.get("jobs/" + created["job_id"]).json()["state"] == "cancelled"


def test_unconfirmed_stop_never_acknowledges_cancel(composed):
    s, created, runner, driver, fake, transport, journal, client, clock = composed
    transport.confirm = False
    transport.on_write = lambda: s.post("jobs/" + created["job_id"] + "/cancel", admin=True)

    def ack(*args):
        pytest.fail("unconfirmed device stop must never acknowledge cancellation")

    client.stop_ack = ack
    result = runner.run_once()
    assert result.state == "needs_attention"
    assert result.reason_code == "stop_unconfirmed"
    assert result.desired_state == "cancel"
    assert not journal.has_intent(created["job_id"], "upload")


def test_verify_only_never_restarts_ticks_or_uploads(composed):
    s, created, runner, driver, fake, transport, journal, client, clock = composed
    grant = s.claim().json()
    for state in ("preflight", "ready", "running"):
        grant["job"] = s.event(grant, state).json()
    attention = s.event(grant, "needs_attention", phase="running").json()
    assert (
        s.post(
            "jobs/" + created["job_id"] + "/resume",
            {"action": "verify_only", "expected_revision": attention["revision"]},
            admin=True,
        ).status_code
        == 200
    )
    result = runner.run_once()
    assert result.state == "needs_attention"
    assert fake.start_count == fake.tick_count == 0
    assert transport.writes == []
    assert not journal.has_intent(created["job_id"], "upload")


def test_expired_guard_and_cancel_binding_write_nothing(composed):
    s, created, runner, driver, fake, transport, journal, client, clock = composed
    grant = client.claim(DEVICE_ID)
    driver.bind_session(grant.job)
    driver.prepare(grant.job.spec)

    def expired():
        raise LeaseLost("expired fence")

    driver.configure_execution_guard(expired)
    with pytest.raises(LeaseLost):
        driver.start(grant.job.spec)
    assert fake.start_count == 0 and transport.writes == []
    driver.bind_session(grant.job.model_copy(update={"desired_state": "cancel"}))
    driver.configure_execution_guard(lambda: None)
    with pytest.raises(DriverError):
        driver.start(grant.job.spec)
    assert fake.start_count == 0 and transport.writes == []


def make_location(clock):
    from swu_happyrun.core.models import GeoPoint
    from swu_happyrun.drivers.mumu.binding import resolve_binding
    from swu_happyrun.drivers.mumu.calibration import CalibrationRecord, CalibrationSample
    from swu_happyrun.drivers.mumu.location import MuMuLocation

    observation = dict(
        instance_index="0",
        adb_serial="synthetic-serial",
        host_version="6.8.4.0",
        engine_version="15",
        app_version="1.0",
        package="test.fake",
        display_id=0,
        task_id=1,
        boot_id="synthetic-boot",
        observation_id="00000000-0000-4000-8000-000000000001",
        observed_at=clock.utcnow().isoformat(),
        mapping_source="local_review",
        mapped_instance_index="0",
        mapped_adb_serial="synthetic-serial",
        observed_display_id=0,
        observed_task_id=1,
        matching_task_count=1,
    )
    binding = resolve_binding(
        instance_index="0",
        adb_serial="synthetic-serial",
        observation=observation,
        now=clock.utcnow(),
    )
    point = GeoPoint(latitude=0.2, longitude=0.2)
    calibration = CalibrationRecord(
        binding_digest=binding.digest,
        host_version=binding.host_version,
        engine_version=binding.engine_version,
        app_version=binding.app_version,
        channel="synthetic",
        input_crs="WGS84",
        observed_at=clock.utcnow(),
        expires_at=clock.utcnow() + timedelta(seconds=30),
        max_error_m=0.1,
        samples=(CalibrationSample(target=point, observed=point, observed_crs="WGS84"),),
    )

    class LocationTransport(Transport):
        def write(self, sample):
            self.observed = sample
            super().write(sample)

        def read(self):
            return self.observed

    transport = LocationTransport()

    def check():
        return binding.assert_current(observation, now=clock.utcnow())

    location = MuMuLocation.for_synthetic_testing(
        transport=transport,
        calibration=calibration,
        binding=binding,
        binding_check=check,
        clock=clock.utcnow,
    )
    return location, transport, observation, check


def test_r1_r2_actual_binding_location_composition(composed):
    s, created, runner, driver, fake, transport, journal, client, clock = composed
    location, location_transport, observation, check = make_location(clock)
    runner.driver = driver_class().for_synthetic_testing(
        fake=fake, sensors=driver._sensors, binding_check=check, clock=clock, location=location
    )
    result = runner.run_once()
    assert result.state == "completed"
    assert location_transport.writes
    assert location_transport.writes[-1] == fake.route_progress.position
    assert location_transport.stops == 1
    assert runner.driver.inspect().capabilities == []


def test_r1_changed_boot_stops_before_next_location_or_sensor_write(composed):
    s, created, runner, driver, fake, transport, journal, client, clock = composed
    location, location_transport, observation, check = make_location(clock)
    runner.driver = driver_class().for_synthetic_testing(
        fake=fake, sensors=driver._sensors, binding_check=check, clock=clock, location=location
    )

    def restart():
        observation["boot_id"] = "synthetic-restarted"

    location_transport.on_write = restart
    result = runner.run_once()
    assert result.state == "needs_attention"
    assert len(location_transport.writes) == 1
    assert transport.writes == []
    assert location_transport.stops == transport.stops == 1


def test_stop_attempts_both_channels_when_first_unconfirmed(composed):
    s, created, runner, driver, fake, transport, journal, client, clock = composed
    location, location_transport, observation, check = make_location(clock)
    location_transport.confirm = False
    runner.driver = driver_class().for_synthetic_testing(
        fake=fake, sensors=driver._sensors, binding_check=check, clock=clock, location=location
    )
    result = runner.run_once()
    assert result.state == "needs_attention"
    assert result.reason_code == "stop_unconfirmed"
    assert transport.stops == 1
    assert location_transport.stops >= 1


def test_synthetic_seam_never_returns_backend_supplied_app_evidence(composed):
    from swu_happyrun.core.models import VerificationResult

    s, created, runner, driver, fake, transport, journal, client, clock = composed
    fake.verify = lambda job: VerificationResult.model_construct(
        status="valid", evidence=[], reason_code=None
    )
    # An injected backend status cannot turn this explicitly synthetic seam into
    # record verification; the real runner still applies simulation semantics.
    assert driver.verify(None).status == "unknown"
    assert driver.verify(None).evidence == []


@pytest.mark.parametrize("fault", ["stale_fence", "cancel"])
def test_server_rejects_changed_authority_before_start(composed, fault):
    s, created, runner, driver, fake, transport, journal, client, clock = composed
    original = client.events

    def events(job_id, lease, event):
        result = original(job_id, lease, event)
        if event.state == "running":
            if fault == "stale_fence":
                runner.lease = lease.model_copy(update={"fence": lease.fence + 1})
            else:
                assert s.post("jobs/" + job_id + "/cancel", admin=True).status_code == 200
        return result

    client.events = events
    runner.run_once()
    assert fake.start_count == fake.tick_count == 0
    assert transport.writes == []


def test_existing_start_intent_is_not_replayed(composed):
    s, created, runner, driver, fake, transport, journal, client, clock = composed
    journal.record_intent(created["job_id"], 1, "start")
    result = runner.run_once()
    assert result.state == "needs_attention"
    assert fake.start_count == fake.tick_count == 0
    assert transport.writes == []


def test_synthetic_seam_rejects_device_mode(composed):
    s, created, runner, driver, fake, transport, journal, client, clock = composed
    grant = client.claim(DEVICE_ID)
    device_spec = grant.job.spec.model_copy(
        update={"mode": "device", "expected_app_version": "test-1"}
    )
    with pytest.raises(DriverError):
        driver.bind_session(grant.job.model_copy(update={"spec": device_spec}))
    assert fake.start_count == fake.tick_count == 0
    assert transport.writes == []
    assert driver.inspect().backend == "fake"
    assert driver.inspect().capabilities == []


def test_lower_fence_rebind_rejected_by_existing_session_binding(composed):
    s, created, runner, driver, fake, transport, journal, client, clock = composed
    grant = client.claim(DEVICE_ID)
    driver.bind_session(grant.job.model_copy(update={"fence": grant.job.fence + 1}))
    with pytest.raises(DriverError, match="stale_fence"):
        driver.bind_session(grant.job)
    assert fake.start_count == fake.tick_count == 0
    assert transport.writes == []


def test_synthetic_inspection_cannot_advertise_physical_capabilities(composed):
    s, created, runner, driver, fake, transport, journal, client, clock = composed
    original = fake.inspect()
    fake.inspect = lambda: original.model_copy(
        update={"backend": "mumu", "capabilities": ["location_write"]}
    )
    inspected = driver.inspect()
    assert inspected.backend == "fake"
    assert inspected.capabilities == []


def test_r3_unknown_cannot_become_simulation_or_record_success(composed):
    """Independent-review regression: rejection does not activate the R3 adapter."""
    from swu_happyrun.drivers.budao.records import verify_result

    s, created, runner, driver, fake, transport, journal, client, clock = composed
    fake.verify = lambda job: verify_result(None, session=None, now=clock.utcnow())
    result = runner.run_once()
    assert result.state == "needs_attention"
    assert result.reason_code == "verification_pending"
    assert driver.verify(None).status == "unknown"
    assert not driver.verify(None).evidence
    assert not journal.has_intent(created["job_id"], "upload")
