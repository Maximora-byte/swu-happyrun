"""Fail-closed physical boundary with an explicit synthetic calibration seam.

No real transport is supplied or enabled. MuMu12 mappings, gateway ports and
commands are intentionally absent pending version-specific help/readback.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from threading import RLock
from typing import TYPE_CHECKING, Protocol

from swu_happyrun.core.geo import distance_between_points_m
from swu_happyrun.core.models import GeoPoint
from swu_happyrun.drivers.base import DriverError
from swu_happyrun.drivers.mumu.calibration import CalibrationRecord, normalize
from swu_happyrun.drivers.mumu.sensors import _unguarded

if TYPE_CHECKING:
    from swu_happyrun.drivers.mumu.binding import MumuBinding


class SyntheticLocationTransport(Protocol):
    """Synthetic writes and readback are WGS84, without compensation."""

    def write(self, point: GeoPoint) -> None: ...
    def read(self) -> GeoPoint: ...
    def stop_and_confirm_empty(self) -> bool: ...


class MuMuLocation:
    def __init__(self) -> None:
        self.write_count = 0
        self._transport: SyntheticLocationTransport | None = None
        self._guard: Callable[[], None] = _unguarded
        self._halted = False
        self._stop_confirmed = False
        self._lock = RLock()

    @classmethod
    def for_synthetic_testing(
        cls,
        *,
        transport: SyntheticLocationTransport,
        calibration: CalibrationRecord,
        binding: "MumuBinding",
        binding_check: Callable[[], None],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> "MuMuLocation":
        result = cls()
        result._transport = transport
        result._calibration = calibration
        result._binding = binding
        result._binding_check = binding_check
        result._clock = clock
        return result

    def configure_execution_guard(self, check: Callable[[], None]) -> None:
        with self._lock:
            self._guard = check

    def write(self, point: GeoPoint, *, input_crs: str) -> None:
        with self._lock:
            if self._transport is None:
                raise DriverError("coordinate_mapping_unverified")
            if self._halted:
                raise DriverError("channel_halted")
            try:
                self._calibration.validate(self._binding, now=self._clock(), channel="synthetic")
                if input_crs != self._calibration.input_crs:
                    raise DriverError("calibration_crs_mismatch")
                target = normalize(point, input_crs)
                self._binding_check()
                self._guard()
                if self._halted:
                    raise DriverError("channel_halted")
                self._calibration.validate(self._binding, now=self._clock(), channel="synthetic")
                self._transport.write(target)
                self.write_count += 1
                observed = normalize(self._transport.read(), "WGS84")
                if distance_between_points_m(target, observed) > self._calibration.max_error_m:
                    raise DriverError("coordinate_readback_mismatch")
            except Exception:
                self._halted = True
                raise

    def stop(self) -> None:
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
