"""Synchronous synthetic transport boundary; no physical sensor commands.

No scheduler or replay queue exists here. Stop requires explicit transport
confirmation that the device-side queue is empty, not a local thread joining.
The test seam grants no capability and must never be registered as a device.
"""

from collections.abc import Callable
from math import isfinite
from threading import RLock
from time import monotonic
from typing import Protocol

from swu_happyrun.drivers.base import DriverError


class SyntheticSensorTransport(Protocol):
    def write(self, sample: tuple[float, ...]) -> None: ...
    def stop_and_confirm_empty(self) -> bool: ...


def _unguarded() -> None:
    raise DriverError("execution_guard_missing")


class MuMuSensors:
    def __init__(self) -> None:
        self._transport: SyntheticSensorTransport | None = None
        self._clock = monotonic
        self._guard: Callable[[], None] = _unguarded
        self._execution_binding_check: Callable[[], None] | None = None
        self._halted = False
        self._stop_confirmed = False
        self._lock = RLock()

    @classmethod
    def for_synthetic_testing(
        cls, *, transport: SyntheticSensorTransport, clock: Callable[[], float] = monotonic
    ) -> "MuMuSensors":
        result = cls()
        result._transport = transport
        result._clock = clock
        return result

    def configure_execution_guard(
        self,
        check: Callable[[], None],
        *,
        binding_check: Callable[[], None] | None = None,
    ) -> None:
        with self._lock:
            self._guard = check
            self._execution_binding_check = binding_check

    def write(self, sample: tuple[float, ...], *, deadline: float) -> None:
        with self._lock:
            if self._transport is None:
                raise DriverError("sensor_channel_unverified")
            if self._halted:
                raise DriverError("channel_halted")
            try:
                if (
                    not isinstance(sample, tuple)
                    or not sample
                    or any(type(v) not in (int, float) or not isfinite(v) for v in sample)
                ):
                    raise DriverError("invalid_sensor_sample")
                if (
                    type(deadline) not in (int, float)
                    or not isfinite(deadline)
                    or not self._clock() < deadline
                ):
                    raise DriverError("action_budget_exhausted")
                if self._execution_binding_check is not None:
                    self._execution_binding_check()
                self._guard()
                if self._halted:
                    raise DriverError("channel_halted")
                if self._execution_binding_check is not None:
                    self._execution_binding_check()
                if not self._clock() < deadline:
                    raise DriverError("action_budget_exhausted")
                # Recheck authority after the preceding validation/clock callback.
                self._guard()
                # The synchronous guard may consume the sample's shorter budget.
                # This final time read must be a pure monotonic observation.
                if not self._clock() < deadline:
                    raise DriverError("action_budget_exhausted")
                if self._halted:
                    raise DriverError("channel_halted")
                self._transport.write(sample)
            except Exception:
                self._halted = True
                raise

    def stop(self) -> None:
        # No lease guard: stopping remains possible after lease loss.
        self._halted = True
        with self._lock:
            if self._stop_confirmed:
                return
            try:
                if self._transport is None or self._transport.stop_and_confirm_empty() is not True:
                    raise DriverError("stop_unconfirmed")
            except Exception as exc:
                raise DriverError("stop_unconfirmed") from exc
            self._stop_confirmed = True
