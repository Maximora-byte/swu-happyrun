"""Pure argument preparation for observed MuMu 6.8.4.0 / API35 help.

No executor, readback, stop command, physical transport or capability activation.
Argument validity does not establish CRS, gyro units, or device-side semantics.
Source: issues/7#issuecomment-6263450120; design: PR61 in this repository.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal
from math import isfinite

from swu_happyrun.drivers.base import DriverError


def _number(value: float) -> str:
    # Strict built-in numbers only: no bool, string coercion or arbitrary __str__.
    if type(value) not in (int, float):
        raise DriverError("command_value_invalid")
    try:
        finite = isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise DriverError("command_value_invalid")
    # Fixed decimal spelling avoids assuming support for scientific notation.
    return format(Decimal(str(value)), "f")


@dataclass(frozen=True)
class MuMu684Commands:
    """Offline preparation only; consume argv with shell=False in a future executor.

    Executable selection is deliberately absent. The instance is private, and
    returned arguments (including sample values) must not be publicly logged.
    This object is not binding evidence and does not replace R1 freshness checks.
    """

    host_version: str
    android_api: int
    instance_index: str = field(repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.host_version) is not str
            or self.host_version != "6.8.4.0"
            or type(self.android_api) is not int
            or self.android_api != 35
        ):
            raise DriverError("transport_version_unverified")
        if (
            type(self.instance_index) is not str
            or not 1 <= len(self.instance_index) <= 128
            or re.fullmatch(r"[0-9]+", self.instance_index) is None
        ):
            raise DriverError("instance_index_invalid")

    @property
    def capabilities(self) -> tuple[()]:
        return ()

    def location(self, *, longitude: float, latitude: float) -> tuple[str, ...]:
        """Encode raw vendor arguments without assigning a CRS or converting it."""
        lon, lat = _number(longitude), _number(latitude)
        if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
            raise DriverError("command_value_invalid")
        return (
            "control",
            "--vmindex",
            self.instance_index,
            "tool",
            "location",
            "--longitude",
            lon,
            "--latitude",
            lat,
        )

    def gyro(self, *, x: float, y: float, z: float) -> tuple[str, ...]:
        """Preserve vendor axis order; no units, range, timing or step-count claim."""
        return (
            "control",
            "--vmindex",
            self.instance_index,
            "tool",
            "gyro",
            "--gyro_x",
            _number(x),
            "--gyro_y",
            _number(y),
            "--gyro_z",
            _number(z),
        )

    def require_physical_transport(self, channel: str) -> None:
        """Always fail closed. There is no caller-supplied evidence/boolean bypass.

        Both channels lack verified independent readback and stop/queue semantics;
        location also lacks CRS, gyro lacks units/axes/timing. Preparing arguments
        cannot fill these gaps. Real support requires reviewed implementation.
        """
        if type(channel) is not str or channel not in ("location", "gyro"):
            raise DriverError("channel_invalid")
        raise DriverError("physical_transport_unverified")
