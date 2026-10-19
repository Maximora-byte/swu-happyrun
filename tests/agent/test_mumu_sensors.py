"""A synthetic queue exercises stop semantics, not physical step counts."""

import pytest

from swu_happyrun.drivers.base import DriverError


class Queue:
    def __init__(self):
        self.pending = []
        self.clear = True
        self.stops = 0

    def write(self, sample):
        self.pending.append(sample)

    def stop_and_confirm_empty(self):
        self.stops += 1
        if self.clear is True:
            self.pending.clear()
        return self.clear


def controller():
    from swu_happyrun.drivers.mumu.sensors import MuMuSensors

    queue = Queue()
    now = [0.0]
    sensors = MuMuSensors.for_synthetic_testing(transport=queue, clock=lambda: now[0])
    sensors.configure_execution_guard(lambda: None)
    return sensors, queue, now


def test_default_closed():
    from swu_happyrun.drivers.mumu.sensors import MuMuSensors

    with pytest.raises(DriverError):
        MuMuSensors().write((1.0,), deadline=1.0)


def test_stop_confirms_queue_clear_and_remains_idempotent():
    sensors, queue, _ = controller()
    sensors.write((1.0,), deadline=1.0)
    sensors.stop()
    sensors.stop()
    assert queue.pending == []
    assert queue.stops == 1
    with pytest.raises(DriverError):
        sensors.write((2.0,), deadline=1.0)


@pytest.mark.parametrize("ack", [False, None, 1, "true"])
def test_unconfirmed_stop_is_not_thread_exit_or_truthy_ack(ack):
    sensors, queue, _ = controller()
    sensors.write((1.0,), deadline=1.0)
    queue.clear = ack
    with pytest.raises(DriverError, match="stop_unconfirmed"):
        sensors.stop()
    assert queue.pending == [(1.0,)]
    with pytest.raises(DriverError):
        sensors.write((2.0,), deadline=1.0)
    queue.clear = True
    sensors.stop()
    assert queue.pending == []


def test_cancellation_drops_backlog_even_after_guard_is_replaced():
    sensors, queue, _ = controller()
    sensors.write((1.0,), deadline=1.0)

    def reject():
        raise DriverError("cancelled")

    sensors.configure_execution_guard(reject)
    with pytest.raises(DriverError, match="cancelled"):
        sensors.write((2.0,), deadline=1.0)
    sensors.configure_execution_guard(lambda: None)
    with pytest.raises(DriverError):
        sensors.write((3.0,), deadline=1.0)
    assert queue.pending == [(1.0,)]
    sensors.stop()


@pytest.mark.parametrize("deadline", [0.0, -1.0, float("nan"), float("inf")])
def test_exhausted_or_invalid_budget_has_zero_writes(deadline):
    sensors, queue, _ = controller()
    with pytest.raises(DriverError):
        sensors.write((1.0,), deadline=deadline)
    assert queue.pending == []


def test_guard_time_consumption_checked_before_transport():
    sensors, queue, now = controller()
    sensors.configure_execution_guard(lambda: now.__setitem__(0, 2.0))
    with pytest.raises(DriverError):
        sensors.write((1.0,), deadline=1.0)
    assert queue.pending == []


def test_stop_timeout_is_unconfirmed():
    sensors, queue, _ = controller()

    def timeout():
        raise TimeoutError()

    queue.stop_and_confirm_empty = timeout
    with pytest.raises(DriverError, match="stop_unconfirmed"):
        sensors.stop()


def test_reentrant_stop_during_guard_cannot_write_after_confirmation():
    sensors, queue, _ = controller()
    sensors.configure_execution_guard(sensors.stop)
    with pytest.raises(DriverError):
        sensors.write((1.0,), deadline=1.0)
    assert queue.pending == []


@pytest.mark.parametrize("sample", [(), (float("nan"),), (float("inf"),), (True,), [1.0]])
def test_invalid_sensor_values_never_write(sample):
    sensors, queue, _ = controller()
    with pytest.raises(DriverError):
        sensors.write(sample, deadline=1.0)
    assert queue.pending == []


@pytest.mark.parametrize("event", ["lease_expired", "budget_exhausted", "cancel", "stop"])
def test_authority_change_during_final_clock_read_has_zero_writes(event):
    from types import SimpleNamespace

    from swu_happyrun.agent.runner import AgentRunner, Cancelled, LeaseLost

    sensors, queue, now = controller()
    runner = AgentRunner(
        None, None, None, SimpleNamespace(monotonic=lambda: now[0]), device_id="synthetic"
    )
    runner.job = SimpleNamespace(desired_state="run", recovery_action=None)
    runner._lease_deadline, runner._job_deadline = 30, 600
    reads = 0

    def clock():
        nonlocal reads
        reads += 1
        if reads == 2:
            if event == "lease_expired":
                now[0] = 31
            elif event == "budget_exhausted":
                now[0] = 25
            elif event == "cancel":
                runner.job.desired_state = "cancel"
            else:
                sensors.stop()
        return now[0]

    sensors._clock = clock
    sensors.configure_execution_guard(runner._effect_guard)
    with pytest.raises((LeaseLost, Cancelled, DriverError)):
        sensors.write((1.0,), deadline=300)
    assert queue.pending == []
    assert runner._lease_deadline == 30
    sensors.configure_execution_guard(lambda: None)
    with pytest.raises(DriverError, match="channel_halted"):
        sensors.write((2.0,), deadline=300)
    sensors.stop()


def test_stop_during_final_guard_has_zero_writes():
    sensors, queue, _ = controller()
    checks = 0

    def guard():
        nonlocal checks
        checks += 1
        if checks == 2:
            sensors.stop()

    sensors.configure_execution_guard(guard)
    with pytest.raises(DriverError, match="channel_halted"):
        sensors.write((1.0,), deadline=300)
    assert queue.pending == []


def test_final_guard_time_consumption_cannot_exceed_action_deadline():
    sensors, queue, now = controller()
    checks = 0

    def guard():
        nonlocal checks
        checks += 1
        if checks == 2:
            now[0] = 2.0

    sensors.configure_execution_guard(guard)
    with pytest.raises(DriverError, match="action_budget_exhausted"):
        sensors.write((1.0,), deadline=1.0)
    assert queue.pending == []


@pytest.mark.parametrize("event", ["action_deadline", "lease_expired", "cancel", "stop"])
def test_composed_binding_observation_rechecked_before_sensor_write(event):
    from types import SimpleNamespace

    from swu_happyrun.agent.runner import AgentRunner, Cancelled, LeaseLost
    from swu_happyrun.drivers.mumu.driver import MuMuDriver

    sensors, queue, now = controller()
    clock = SimpleNamespace(monotonic=lambda: now[0])
    runner = AgentRunner(None, None, None, clock, device_id="synthetic")
    runner.job = SimpleNamespace(desired_state="run", recovery_action=None)
    runner._lease_deadline, runner._job_deadline = 30, 600
    observations = 0

    def binding_check():
        nonlocal observations
        observations += 1
        if observations == 2:
            if event == "action_deadline":
                now[0] = 2
            elif event == "lease_expired":
                now[0] = 31
            elif event == "cancel":
                runner.job.desired_state = "cancel"
            else:
                sensors.stop()

    driver = MuMuDriver.for_synthetic_testing(
        fake=SimpleNamespace(device_id="synthetic", configure_execution_guard=lambda _: None),
        sensors=sensors,
        binding_check=binding_check,
        clock=clock,
    )
    driver.configure_execution_guard(runner._effect_guard)
    with pytest.raises((DriverError, LeaseLost, Cancelled)):
        sensors.write((1.0,), deadline=1 if event == "action_deadline" else 300)
    assert observations == 2
    assert queue.pending == []
    assert runner._lease_deadline == 30
    sensors.stop()
