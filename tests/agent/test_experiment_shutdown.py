"""Synthetic clocks/signals only; never evidence about a real instance."""

from swu_happyrun.drivers.mumu import experiment_shutdown as subject


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Reader:
    def __init__(self, clock):
        self.clock, self.calls = clock, []
        self.changes = {}

    def read(self, kind, *, timeout, deadline):
        self.calls.append((kind, self.clock.now, timeout, deadline))
        self.clock.now += 0.1
        return self.changes.get((len(self.calls) - 1) // 4, {}).get(
            kind, subject.Signal(known=True, expected=True)
        )


def test_full_window_does_not_end_at_first_stop():
    clock = Clock()
    reader = Reader(clock)
    result = subject.observe_shutdown(reader, clock=clock, deadline=45.0)
    assert result.status == "sampled_shutdown_consistent"
    assert len(result.rounds) == 7
    assert result.finished - result.started >= 30
    assert [r.started for r in result.rounds] == [0, 5, 10, 15, 20, 25, 30]
    assert all(call[2] <= 1 for call in reader.calls)


def test_unknown_early_round_cannot_be_erased_by_last_three():
    clock = Clock()
    reader = Reader(clock)
    reader.changes[0] = {"adb": subject.Signal(known=False, expected=False)}
    result = subject.observe_shutdown(reader, clock=clock, deadline=45)
    assert result.status == "shutdown_unknown"
    assert result.missing == ("adb",)
    assert len(result.rounds) == 7


def test_observed_restart_is_latched_even_after_three_stopped_rounds():
    clock = Clock()
    reader = Reader(clock)
    reader.changes[1] = {"manager": subject.Signal(True, False, restarted=True)}
    result = subject.observe_shutdown(reader, clock=clock, deadline=45)
    assert result.status == "shutdown_unknown"
    assert result.restart_observed


def test_insufficient_budget_cannot_shorten_window_to_pass():
    clock = Clock()
    result = subject.observe_shutdown(Reader(clock), clock=clock, deadline=29)
    assert result.status == "shutdown_unknown"
    assert clock.now <= 29


def test_actual_read_and_cleanup_elapsed_consumes_total_deadline():
    clock = Clock()

    class Slow(Reader):
        def read(self, kind, *, timeout, deadline):
            self.clock.now += min(4, deadline - self.clock.now)
            return subject.Signal(True, True)

    result = subject.observe_shutdown(Slow(clock), clock=clock, deadline=45)
    assert result.status == "shutdown_unknown"
    assert result.finished <= 45
    assert len(result.rounds) < 7


def test_query_exception_is_unknown_not_unavailable_and_no_private_error():
    clock = Clock()

    class Broken(Reader):
        def read(self, kind, **kwargs):
            raise PermissionError("private serial and path")

    result = subject.observe_shutdown(Broken(clock), clock=clock, deadline=45)
    assert result.status == "shutdown_unknown"
    assert set(result.missing) == set(subject.SIGNALS)
    assert "private" not in repr(result)


def test_callback_cannot_pass_with_non_boolean_or_wrong_signal():
    clock = Clock()

    class Malformed(Reader):
        def read(self, kind, **kwargs):
            return subject.Signal("yes", True)

    result = subject.observe_shutdown(Malformed(clock), clock=clock, deadline=45)
    assert result.status == "shutdown_unknown"


def test_other_instance_change_early_is_never_forgotten():
    clock = Clock()
    reader = Reader(clock)
    reader.changes[0] = {"other_instances": subject.Signal(True, False)}
    result = subject.observe_shutdown(reader, clock=clock, deadline=45)
    assert result.status == "shutdown_unknown"


def test_second_interrupt_preserves_partial_rounds_without_further_reads():
    clock = Clock()

    class Interrupted(Reader):
        def read(self, kind, **kwargs):
            if len(self.calls) == 5:
                raise KeyboardInterrupt("private details")
            return super().read(kind, **kwargs)

    reader = Interrupted(clock)
    result = subject.observe_shutdown(reader, clock=clock, deadline=45)
    assert result.status == "shutdown_unknown"
    assert result.interrupted
    assert len(result.rounds) == 2
    assert len(reader.calls) == 5
    assert "private" not in repr(result)
