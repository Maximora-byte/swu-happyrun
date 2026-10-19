"""Offline WGS84 polyline execution; no device, network or record side effects.

Distances use the existing spherical WGS84-coordinate distance approximation.
Interpolation is linear in latitude/longitude, matching validate_route's polygon
segments (not an ellipsoidal geodesic). Source CRS is explicit; no loops or jitter is inferred.
Explicit ``now`` values must come from one monotonic clock, never wall time.
"""

import math
from bisect import bisect_right
from dataclasses import dataclass

from swu_happyrun.core.canonical import profile_revision
from swu_happyrun.core.clock import Clock, SystemClock
from swu_happyrun.core.coordinates import normalize_points
from swu_happyrun.core.geo import distance_between_points_m, validate_route
from swu_happyrun.core.models import GeoPoint, RouteProfile, SchoolProfile


@dataclass(frozen=True)
class RouteProgress:
    state: str
    position: GeoPoint
    distance_m: float
    total_distance_m: float
    progress: float
    elapsed_seconds: float
    speed_mps: float
    finished: bool


class RouteExecution:
    """Single-owner local state machine. Pause/resume are not remote commands.

    Late ticks sample one current position, never replay a burst of missed points.
    Stop freezes the last sampled point without reading a potentially broken clock.
    A new execution object is required after completion or stop; recovery never
    implicitly restarts a route. The caller owns serialization and cancellation.
    """

    def __init__(
        self,
        route: RouteProfile,
        school: SchoolProfile,
        *,
        speed_mps: float,
        clock: Clock | None = None,
    ):
        reasons = validate_route(route, school)
        if reasons:
            raise ValueError(reasons[0])
        rules = dict(school.rules)
        if (
            type(speed_mps) not in (int, float)
            or not math.isfinite(speed_mps)
            or not 0 < speed_mps <= rules["maximum_speed_mps"]
            or speed_mps < rules["minimum_speed_mps"]
        ):
            raise ValueError("invalid_route_speed")
        self._initialize(route, speed_mps=speed_mps, clock=clock)
        if self.duration_seconds > rules["maximum_duration_seconds"]:
            raise ValueError("duration_exceeds_maximum")

    @classmethod
    def for_local_replay(
        cls,
        route: RouteProfile,
        *,
        speed_mps: float,
        maximum_duration_seconds: float,
        clock: Clock,
    ) -> "RouteExecution":
        """Bounded local prefix playback, without any school-rule assertion.

        The explicit time budget caps *active* playback. A prefix stops at that
        budget without jumping to the route endpoint or claiming completion.
        The ordinary constructor retains all SchoolProfile validation.
        """
        for value, reason in (
            (speed_mps, "invalid_route_speed"),
            (maximum_duration_seconds, "invalid_route_duration"),
        ):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError(reason)
        route = RouteProfile.model_validate(route.model_dump(mode="python"))
        if route.revision != profile_revision(route):
            raise ValueError("route_revision_mismatch")
        points = normalize_points(route)
        if any(
            abs(b.longitude - a.longitude) >= 180 for a, b in zip(points, points[1:], strict=False)
        ):
            raise ValueError("unsupported_antimeridian_segment")
        result = cls.__new__(cls)
        result._initialize(route, speed_mps=speed_mps, clock=clock)
        result.maximum_duration_seconds = float(maximum_duration_seconds)
        result.duration_seconds = min(result.duration_seconds, maximum_duration_seconds)
        return result

    def _initialize(self, route: RouteProfile, *, speed_mps: float, clock: Clock | None):
        self._route = RouteProfile.model_validate(route.model_dump(mode="python"))
        self._points = normalize_points(self._route)
        self._speed = float(speed_mps)
        self.segment_distances = tuple(
            distance_between_points_m(a, b)
            for a, b in zip(self._points, self._points[1:], strict=False)
        )
        cumulative = [0.0]
        for distance in self.segment_distances:
            cumulative.append(cumulative[-1] + distance)
        self._cumulative = tuple(cumulative)
        self.total_distance_m = cumulative[-1]
        self.duration_seconds = self.total_distance_m / self._speed
        if not math.isfinite(self.duration_seconds) or self.duration_seconds <= 0:
            raise ValueError("invalid_route_duration")
        self._full_duration_seconds = self.duration_seconds
        self._clock = clock or SystemClock()
        self._state = "ready"
        self._last: float | None = None
        self._elapsed = 0.0

    def _time(self, now: float | None) -> float:
        value = self._clock.monotonic() if now is None else now
        if (
            type(value) not in (int, float)
            or not math.isfinite(value)
            or value < 0
            or (self._last is not None and value < self._last)
        ):
            raise ValueError("invalid_monotonic_time")
        return float(value)

    @property
    def snapshot(self) -> RouteProgress:
        distance = min(self.total_distance_m, self._elapsed * self._speed)
        if self._state == "completed":
            distance = self.total_distance_m
        if distance >= self.total_distance_m:
            position = self._points[-1].model_copy(deep=True)
        else:
            index = bisect_right(self._cumulative, distance) - 1
            a, b = self._points[index : index + 2]
            fraction = (distance - self._cumulative[index]) / self.segment_distances[index]
            position = GeoPoint(
                latitude=a.latitude + (b.latitude - a.latitude) * fraction,
                longitude=a.longitude + (b.longitude - a.longitude) * fraction,
            )
        return RouteProgress(
            state=self._state,
            position=position,
            distance_m=distance,
            total_distance_m=self.total_distance_m,
            progress=distance / self.total_distance_m,
            elapsed_seconds=self._elapsed,
            speed_mps=self._speed if self._state == "running" else 0.0,
            finished=self._state == "completed",
        )

    def start(self, *, now: float | None = None) -> RouteProgress:
        if self._state != "ready":
            raise ValueError("invalid_route_state")
        self._last = self._time(now)
        self._state = "running"
        return self.snapshot

    def tick(self, *, now: float | None = None) -> RouteProgress:
        if self._state == "ready":
            raise ValueError("invalid_route_state")
        value = self._time(now)
        if self._state == "running":
            elapsed = self._elapsed + (value - self._last)
            if not math.isfinite(elapsed):
                raise ValueError("invalid_monotonic_time")
            self._elapsed = min(elapsed, self.duration_seconds)
            if self._elapsed >= self.duration_seconds:
                self._state = (
                    "completed" if self._elapsed >= self._full_duration_seconds else "stopped"
                )
        self._last = value
        return self.snapshot

    def pause(self, *, now: float | None = None) -> RouteProgress:
        if self._state != "running":
            raise ValueError("invalid_route_state")
        self.tick(now=now)
        if self._state == "running":
            self._state = "paused"
        return self.snapshot

    def resume(self, *, now: float | None = None) -> RouteProgress:
        if self._state != "paused":
            raise ValueError("invalid_route_state")
        self._last = self._time(now)
        self._state = "running"
        return self.snapshot

    def stop(self) -> RouteProgress:
        if self._state != "completed":
            self._state = "stopped"
        return self.snapshot
