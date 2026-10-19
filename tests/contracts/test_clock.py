from datetime import UTC, datetime

from swu_happyrun.core.clock import Clock, SystemClock


def test_system_clock_satisfies_protocol():
    clock = SystemClock()
    assert isinstance(clock, Clock)
    assert clock.utcnow().tzinfo is UTC
    assert abs((clock.utcnow() - datetime.now(UTC)).total_seconds()) < 2
    assert clock.monotonic() <= clock.monotonic()
