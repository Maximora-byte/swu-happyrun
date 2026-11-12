"""Explicit offline normalization to WGS84; never a device-calibration claim.

Formula adaptations: EdmundMad0309/budao-lepao-runner, MIT, commit
53715ec80b3c5f0f99ef963e6cf5ed7be1a31e25, src/lepao/geo.py.
See THIRD_PARTY_NOTICES.md and docs/coordinate-conversion.md for limitations.
"""

import math

from swu_happyrun.core.models import GeoPoint, RouteProfile

_A = 6378245.0
_EE = 0.00669342162296594323
_X_PI = math.pi * 3000.0 / 180.0


def _require_domain(longitude: float, latitude: float) -> None:
    # Mathematical envelope from upstream, NOT a national jurisdiction polygon.
    if not (73.66 < longitude < 135.05 and 3.86 < latitude < 53.55):
        raise ValueError("coordinate_outside_conversion_domain")


def _latitude_delta(x: float, y: float) -> float:
    result = -100 + 2 * x + 3 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    result += (20 * math.sin(6 * x * math.pi) + 20 * math.sin(2 * x * math.pi)) * 2 / 3
    result += (20 * math.sin(y * math.pi) + 40 * math.sin(y / 3 * math.pi)) * 2 / 3
    result += (160 * math.sin(y / 12 * math.pi) + 320 * math.sin(y * math.pi / 30)) * 2 / 3
    return result


def _longitude_delta(x: float, y: float) -> float:
    result = 300 + x + 2 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    result += (20 * math.sin(6 * x * math.pi) + 20 * math.sin(2 * x * math.pi)) * 2 / 3
    result += (20 * math.sin(x * math.pi) + 40 * math.sin(x / 3 * math.pi)) * 2 / 3
    result += (150 * math.sin(x / 12 * math.pi) + 300 * math.sin(x / 30 * math.pi)) * 2 / 3
    return result


def _forward_gcj(longitude: float, latitude: float) -> tuple[float, float]:
    _require_domain(longitude, latitude)
    dlat = _latitude_delta(longitude - 105, latitude - 35)
    dlon = _longitude_delta(longitude - 105, latitude - 35)
    radlat = math.radians(latitude)
    magic = 1 - _EE * math.sin(radlat) ** 2
    root = math.sqrt(magic)
    dlat = dlat * 180 / ((_A * (1 - _EE)) / (magic * root) * math.pi)
    dlon = dlon * 180 / (_A / root * math.cos(radlat) * math.pi)
    return longitude + dlon, latitude + dlat


def _inverse_gcj(longitude: float, latitude: float) -> tuple[float, float]:
    lon, lat = longitude, latitude
    for _ in range(8):
        forward_lon, forward_lat = _forward_gcj(lon, lat)
        dx, dy = longitude - forward_lon, latitude - forward_lat
        # The tolerance is a numerical residual, not physical accuracy.
        if max(abs(dx), abs(dy)) <= 1e-11:
            return lon, lat
        lon, lat = lon + dx, lat + dy
    raise ValueError("coordinate_conversion_not_converged")


def to_wgs84(*, longitude: float, latitude: float, source_crs: str) -> GeoPoint:
    """Convert explicit angular degrees; reject unknown CRS, types and domain.

    Non-WGS84 inputs must be known by the caller to actually use that CRS.
    The domain rectangle cannot detect mislabeled overseas/HK/Macao/Taiwan data.
    BD09 means angular BD-09, never projected BD-09MC (meters).
    """
    if source_crs not in ("WGS84", "GCJ02", "BD09"):
        raise ValueError("unknown_coordinate_system")
    for value in (longitude, latitude):
        if type(value) not in (int, float):
            raise ValueError("invalid_coordinate")
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError("invalid_coordinate")
    if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
        raise ValueError("invalid_coordinate")
    if source_crs == "WGS84":
        return GeoPoint(longitude=longitude, latitude=latitude)
    _require_domain(longitude, latitude)
    if source_crs == "BD09":
        x, y = longitude - 0.0065, latitude - 0.006
        radius = math.hypot(x, y) - 0.00002 * math.sin(y * _X_PI)
        angle = math.atan2(y, x) - 0.000003 * math.cos(x * _X_PI)
        longitude, latitude = radius * math.cos(angle), radius * math.sin(angle)
        _require_domain(longitude, latitude)
    longitude, latitude = _inverse_gcj(longitude, latitude)
    _require_domain(longitude, latitude)
    return GeoPoint(longitude=longitude, latitude=latitude)


def normalize_points(route: RouteProfile) -> tuple[GeoPoint, ...]:
    """Return detached WGS84 points, leaving source CRS, content and hash intact.

    Callers must verify source revision before use. These are derived points,
    not a replacement RouteProfile with a stale content revision.
    """
    route = RouteProfile.model_validate(route.model_dump(mode="python"))
    return tuple(
        to_wgs84(longitude=p.longitude, latitude=p.latitude, source_crs=route.input_crs)
        for p in route.points
    )
