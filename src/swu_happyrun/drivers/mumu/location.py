"""Fail-closed MuMu location boundary pending instance-specific calibration.

No transport is exposed: command success alone is not proof of observed
coordinates. Android 12 reference mappings do not establish Android 15 support.
A later implementation must bind calibration to instance/host/engine versions,
validate requested CRS and compare actual device readings after a test write.
"""

from swu_happyrun.core.models import GeoPoint
from swu_happyrun.drivers.base import DriverError


class MuMuLocation:
    write_count = 0

    def write(self, point: GeoPoint, *, input_crs: str) -> None:
        raise DriverError("coordinate_mapping_unverified")
