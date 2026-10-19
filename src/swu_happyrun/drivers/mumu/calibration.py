"""Local calibration evidence. No wire models or physical channel activation."""

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import TYPE_CHECKING

from swu_happyrun.core.coordinates import to_wgs84
from swu_happyrun.core.geo import distance_between_points_m
from swu_happyrun.core.models import GeoPoint
from swu_happyrun.drivers.base import DriverError

if TYPE_CHECKING:
    from swu_happyrun.drivers.mumu.binding import MumuBinding


def normalize(point: GeoPoint, crs: str) -> GeoPoint:
    try:
        return to_wgs84(longitude=point.longitude, latitude=point.latitude, source_crs=crs)
    except (ValueError, TypeError, AttributeError) as exc:
        raise DriverError("invalid_calibration_coordinate") from exc


@dataclass(frozen=True)
class CalibrationSample:
    target: GeoPoint
    observed: GeoPoint
    observed_crs: str


@dataclass(frozen=True)
class CalibrationRecord:
    binding_digest: str
    host_version: str
    engine_version: str
    app_version: str
    channel: str
    input_crs: str
    observed_at: datetime
    expires_at: datetime
    max_error_m: float
    samples: tuple[CalibrationSample, ...]

    def validate(self, binding: "MumuBinding", *, now: datetime, channel: str) -> None:
        """Recheck mutable nested points and current identity on EVERY use.

        The caller supplies freshness and error limits from the explicit test
        plan. In-range swapped axes cannot be inferred from numbers alone;
        controlled target/readback comparison is required to detect those.
        """
        try:
            if (
                not self.binding_digest
                or self.binding_digest != binding.digest
                or self.host_version != binding.host_version
                or self.engine_version != binding.engine_version
                or self.app_version != binding.app_version
                or not all((self.host_version, self.engine_version, self.app_version))
                or not self.channel
                or self.channel != channel
                or self.input_crs not in ("WGS84", "GCJ02", "BD09")
                or any(
                    t.tzinfo is None or t.utcoffset() is None
                    for t in (now, self.observed_at, self.expires_at)
                )
                or not self.observed_at <= now < self.expires_at
                or type(self.max_error_m) not in (int, float)
                or not isfinite(self.max_error_m)
                or self.max_error_m < 0
                or not self.samples
            ):
                raise DriverError("calibration_unverified")
            for sample in self.samples:
                target = normalize(sample.target, self.input_crs)
                observed = normalize(sample.observed, sample.observed_crs)
                if distance_between_points_m(target, observed) > self.max_error_m:
                    raise DriverError("calibration_error_exceeded")
        except (AttributeError, TypeError, OverflowError) as exc:
            raise DriverError("calibration_unverified") from exc
