"""Private single-window numeric comparison, never calibration or causal evidence."""

import math
import re
from dataclasses import asdict, dataclass, field

from swu_happyrun.core.geo import distance_between_points_m
from swu_happyrun.core.models import GeoPoint
from swu_happyrun.drivers.command import ProbeError
from swu_happyrun.drivers.mumu.own_probe import OwnObservation, OwnProbe, OwnSample


def _finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _point(target, tolerance):
    if (
        type(target) is not tuple
        or len(target) != 2
        or not all(_finite(v) for v in target)
        or abs(target[0]) > 90
        or abs(target[1]) > 180
        or not _finite(tolerance)
        or tolerance < 0
    ):
        raise ProbeError("point_comparison_invalid")
    return GeoPoint(latitude=target[0], longitude=target[1])


def _validate_observation(value):
    # Structural validation is not provenance authentication. Only the trusted
    # OwnProbe helper correlates these fields to the actual request and binding.
    if (
        type(value) is not OwnObservation
        or not isinstance(value.nonce, str)
        or not re.fullmatch(r"[0-9a-f]{32}", value.nonce)
        or not isinstance(value.binding_digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", value.binding_digest)
        or not isinstance(value.boot_id, str)
        or not re.fullmatch(r"[A-Za-z0-9-]{1,128}", value.boot_id)
        or value.channel != "location"
        or type(value.duration_ms) is not int
        or value.duration_ms != 1000
        or type(value.window_start_ns) is not int
        or type(value.window_end_ns) is not int
        or not 0 <= value.window_start_ns < value.window_end_ns <= 2**63 - 1
        or value.window_end_ns - value.window_start_ns != 1_000_000_000
        or type(value.samples) is not tuple
        or not 1 <= len(value.samples) <= 128
    ):
        raise ProbeError("observation_payload_invalid")
    previous = value.window_start_ns - 1
    for sample in value.samples:
        if (
            type(sample) is not OwnSample
            or sample.channel != "location"
            or type(sample.elapsed_realtime_ns) is not int
            or not previous < sample.elapsed_realtime_ns < value.window_end_ns
            or sample.elapsed_realtime_ns < value.window_start_ns
            or type(sample.values) is not tuple
            or len(sample.values) != 2
            or not all(_finite(v) for v in sample.values)
            or abs(sample.values[0]) > 90
            or abs(sample.values[1]) > 180
            or not _finite(sample.accuracy)
            or sample.accuracy < 0
        ):
            raise ProbeError("observation_payload_invalid")
        previous = sample.elapsed_realtime_ns


@dataclass(frozen=True, repr=False)
class PointObservation:
    observation: OwnObservation
    target: tuple[float, float]
    tolerance_m: float
    distances_m: tuple[float, ...] = field(init=False)

    def __post_init__(self):
        target = _point(self.target, self.tolerance_m)
        _validate_observation(self.observation)
        # Apply the existing metric numerically to the declared raw numbers.
        # This does NOT establish that the vendor interprets its input as WGS84.
        object.__setattr__(
            self,
            "distances_m",
            tuple(
                distance_between_points_m(
                    target, GeoPoint(latitude=s.values[0], longitude=s.values[1])
                )
                for s in self.observation.samples
            ),
        )

    @property
    def sample_count(self):
        return len(self.observation.samples)

    @property
    def observation_status(self):
        return (
            "samples_within_declared_tolerance"
            if all(d <= self.tolerance_m for d in self.distances_m)
            else "samples_outside_declared_tolerance"
        )

    def private_dict(self):
        return {
            "schema": 1,
            "target": {"latitude": self.target[0], "longitude": self.target[1]},
            "tolerance_m": self.tolerance_m,
            "distances_m": self.distances_m,
            "observation": {
                "schema": 1,
                "cleanup_confirmed": True,
                "status": "samples_observed",
                **asdict(self.observation),
            },
            "observation_status": self.observation_status,
            "sample_count": self.sample_count,
            "coordinate_semantics": "raw_vendor_unverified",
            "comparison_semantics": "numeric_great_circle_only",
            "calibration": "unknown",
            "causal_attribution": "unverified",
            "injection_ack": "unconfirmed",
        }


def observe_declared_point(
    probe: OwnProbe, target: GeoPoint, tolerance_m: float
) -> PointObservation:
    """Exactly one existing window; invalid declarations start no observation.

    Preserve raw latitude/longitude order. No conversion, tolerance widening,
    matching retry, second point, calibration record or execution capability.
    """
    if type(target) is not GeoPoint:
        raise ProbeError("point_comparison_invalid")
    raw = (target.latitude, target.longitude)
    _point(raw, tolerance_m)
    observation = probe.sample_private("location", duration_ms=1000)
    return PointObservation(observation, raw, tolerance_m)
