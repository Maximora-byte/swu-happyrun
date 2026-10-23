"""Version-pinned BD09 input hypothesis; two-point GPS calibration is mandatory.

On local MuMu 6.8.4.0/API35, one raw-point GPS observation matched BD09 ->
WGS84 within 0.54m, versus >900m for the other supported interpretations.
This does not grant capability: every session verifies two separated route
points, and every trajectory write needs independent fresh WGS84 readback.

Formula family/attribution: core.coordinates and THIRD_PARTY_NOTICES.md.
"""

import math

from swu_happyrun.core.coordinates import _forward_gcj
from swu_happyrun.core.models import GeoPoint

VENDOR_CRS = "BD09"


def vendor_point(wgs84: GeoPoint) -> GeoPoint:
    longitude, latitude = _forward_gcj(wgs84.longitude, wgs84.latitude)
    x_pi = math.pi * 3000.0 / 180.0
    radius = math.hypot(longitude, latitude) + 0.00002 * math.sin(latitude * x_pi)
    angle = math.atan2(latitude, longitude) + 0.000003 * math.cos(longitude * x_pi)
    return GeoPoint(
        longitude=radius * math.cos(angle) + 0.0065, latitude=radius * math.sin(angle) + 0.006
    )
