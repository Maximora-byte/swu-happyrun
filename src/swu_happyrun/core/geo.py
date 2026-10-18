"""Conservative WGS84 route validation. No implicit coordinate conversion."""

import math

from pydantic import ValidationError

from swu_happyrun.core.models import GeoPoint, RouteProfile, SchoolProfile

_REQUIRED_RULES = {
    "minimum_distance_m",
    "maximum_duration_seconds",
    "minimum_speed_mps",
    "maximum_speed_mps",
}


def _xy(point: GeoPoint) -> tuple[float, float]:
    return point.longitude, point.latitude


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on(a, b, p):
    return (
        _cross(a, b, p) == 0
        and min(a[0], b[0]) <= p[0] <= max(a[0], b[0])
        and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])
    )


def _intersects(a, b, c, d):
    return (
        (_cross(a, b, c) * _cross(a, b, d) < 0 and _cross(c, d, a) * _cross(c, d, b) < 0)
        or _on(a, b, c)
        or _on(a, b, d)
        or _on(c, d, a)
        or _on(c, d, b)
    )


def _inside(p, polygon):
    inside = False
    for a, b in zip(polygon, polygon[1:] + polygon[:1], strict=True):
        if _on(a, b, p):
            return True
        if (a[1] > p[1]) != (b[1] > p[1]):
            x = a[0] + (p[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if p[0] < x:
                inside = not inside
    return inside


def _valid_polygon(polygon):
    if len(polygon) < 3 or len(set(polygon)) != len(polygon):
        return False
    edges = list(zip(polygon, polygon[1:] + polygon[:1], strict=True))
    if sum(a[0] * b[1] - b[0] * a[1] for a, b in edges) == 0:
        return False
    # Antimeridian-spanning polygons require an explicit spherical representation.
    if max(p[0] for p in polygon) - min(p[0] for p in polygon) >= 180:
        return False
    for i, (a, b) in enumerate(edges):
        for j, (c, d) in enumerate(edges):
            if j <= i or j == i + 1 or (i == 0 and j == len(edges) - 1):
                continue
            if _intersects(a, b, c, d):
                return False
    return True


def _segment_inside(a, b, polygon):
    if not _inside(a, polygon) or not _inside(b, polygon):
        return False
    # Split at every boundary intersection and test each open interval. This
    # catches concave exits, including paths through a polygon vertex.
    ts = {0.0, 1.0}
    dx, dy = b[0] - a[0], b[1] - a[1]
    for c, d in zip(polygon, polygon[1:] + polygon[:1], strict=True):
        ex, ey = d[0] - c[0], d[1] - c[1]
        denominator = dx * ey - dy * ex
        if denominator:
            t = ((c[0] - a[0]) * ey - (c[1] - a[1]) * ex) / denominator
            u = ((c[0] - a[0]) * dy - (c[1] - a[1]) * dx) / denominator
            if 0 <= t <= 1 and 0 <= u <= 1:
                ts.add(t)
        else:
            for p in (c, d):
                if _on(a, b, p) and (dx or dy):
                    ts.add((p[0] - a[0]) / dx if dx else (p[1] - a[1]) / dy)
    ordered = sorted(ts)
    return all(
        _inside((a[0] + dx * (s + t) / 2, a[1] + dy * (s + t) / 2), polygon)
        for s, t in zip(ordered, ordered[1:], strict=False)
    )


def route_distance_m(route: RouteProfile) -> float:
    """Great-circle distance between consecutive WGS84 points."""
    route = RouteProfile.model_validate(route.model_dump(mode="python"))
    if route.input_crs != "WGS84":
        raise ValueError("coordinate_conversion_unverified")
    total = 0.0
    for a, b in zip(route.points, route.points[1:], strict=False):
        lat1, lat2 = math.radians(a.latitude), math.radians(b.latitude)
        delta = math.radians(b.longitude - a.longitude)
        h = (
            math.sin((lat2 - lat1) / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin(delta / 2) ** 2
        )
        total += 6371008.8 * 2 * math.asin(math.sqrt(min(1.0, max(0.0, h))))
    return total


def validate_route(route: RouteProfile, school: SchoolProfile) -> list[str]:
    """Return stable rejection reasons, including for mutated/bypassed models."""
    try:
        route = RouteProfile.model_validate(route.model_dump(mode="python"))
        school = SchoolProfile.model_validate(school.model_dump(mode="python"))
    except (ValidationError, ValueError, TypeError, AttributeError):
        return ["invalid_profile"]
    reasons = []
    if route.input_crs != "WGS84":
        reasons.append("coordinate_conversion_unverified")
    if not school.confirmed:
        reasons.append("school_unconfirmed")
    if set(school.rules) != _REQUIRED_RULES:
        reasons.append("rules_incomplete")
    polygon = [_xy(p) for p in school.allowed_region]
    if polygon and polygon[0] == polygon[-1]:
        polygon.pop()
    if not _valid_polygon(polygon):
        reasons.append("invalid_boundary")
    elif route.input_crs == "WGS84" and any(
        not _segment_inside(_xy(a), _xy(b), polygon)
        for a, b in zip(route.points, route.points[1:], strict=False)
    ):
        reasons.append("route_outside_boundary")
    if route.input_crs == "WGS84":
        distance = route_distance_m(route)
        if distance == 0 or distance < school.rules.get("minimum_distance_m", 0):
            reasons.append("distance_below_minimum")
        maximum_speed = school.rules.get("maximum_speed_mps")
        maximum_duration = school.rules.get("maximum_duration_seconds")
        if maximum_speed is not None and maximum_duration is not None:
            if maximum_speed <= 0 or maximum_duration <= 0:
                reasons.append("rules_infeasible")
            elif distance > maximum_speed * maximum_duration:
                reasons.append("duration_exceeds_maximum")
    return reasons
