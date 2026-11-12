"""Bounded joint shutdown observations, never native ACK or queue clearance.

The reader is a trusted, independently reviewed adapter, not user-supplied JSON.
It must bind manager fields, exact ADB serial, PID plus creation time and owned
descendants, and the other three instances. No such Windows adapter ships here.
Missing executables, parse errors, absent manager entries and permission failures
must produce unknown signals, never successful negative observations.
"""

from dataclasses import dataclass

SIGNALS = ("manager", "adb", "processes", "other_instances")


@dataclass(frozen=True)
class Signal:
    known: bool
    expected: bool
    identity_changed: bool = False
    restarted: bool = False


@dataclass(frozen=True)
class ObservationRound:
    started: float
    finished: float
    signals: tuple[Signal, ...]


@dataclass(frozen=True)
class ShutdownObservation:
    status: str
    started: float
    finished: float
    rounds: tuple[ObservationRound, ...]
    missing: tuple[str, ...]
    identity_changed: bool
    restart_observed: bool
    interrupted: bool


def observe_shutdown(reader, *, clock, deadline: float) -> ShutdownObservation:
    """Seven sequential joint samples at fixed offsets over at least 30 seconds.

    Caller supplies the SAME deadline created on entering shutdown, including
    sealing, draining, revalidation, intent persistence, command and cleanup.
    Adapter calls must honor both timeout and absolute deadline. Python/OS/filesystem
    scheduling is not hard real-time; overruns are reported unknown, not hidden.
    """
    started = clock.monotonic()
    rounds, missing = [], set()
    identity_changed = restart = False
    interrupted = False
    reliable = True
    for index in range(7):
        scheduled = started + index * 5.0
        if scheduled >= deadline:
            break
        remaining_wait = scheduled - clock.monotonic()
        if remaining_wait > 0:
            try:
                clock.sleep(min(remaining_wait, max(0, deadline - clock.monotonic())))
            except BaseException:
                interrupted = True
                break
        began = clock.monotonic()
        if began >= deadline:
            break
        signals = []
        for kind in SIGNALS:
            remaining = deadline - clock.monotonic()
            signal = Signal(False, False)
            if remaining > 0 and not interrupted:
                try:
                    candidate = reader.read(kind, timeout=min(1.0, remaining), deadline=deadline)
                    if isinstance(candidate, Signal) and all(
                        type(value) is bool
                        for value in (
                            candidate.known,
                            candidate.expected,
                            candidate.identity_changed,
                            candidate.restarted,
                        )
                    ):
                        signal = candidate
                except Exception:
                    pass  # Fixed missing signal only; never stringify exceptions.
                except BaseException:
                    interrupted = True
            if clock.monotonic() > deadline:
                signal = Signal(False, False, signal.identity_changed, signal.restarted)
            if not signal.known:
                missing.add(kind)
                reliable = False
            if kind == "other_instances" and not signal.expected:
                reliable = False
            identity_changed |= signal.identity_changed
            restart |= signal.restarted
            signals.append(signal)
        rounds.append(ObservationRound(began, clock.monotonic(), tuple(signals)))
        if clock.monotonic() >= deadline or interrupted:
            break
    finished = clock.monotonic()
    consistent = (
        len(rounds) == 7
        and finished - started >= 30.0
        and finished <= deadline
        and reliable
        and not identity_changed
        and not restart
        and not interrupted
        and all(signal.known and signal.expected for row in rounds[-3:] for signal in row.signals)
    )
    return ShutdownObservation(
        "sampled_shutdown_consistent" if consistent else "shutdown_unknown",
        started,
        finished,
        tuple(rounds),
        tuple(sorted(missing)),
        identity_changed,
        restart,
        interrupted,
    )
