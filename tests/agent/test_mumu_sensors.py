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
