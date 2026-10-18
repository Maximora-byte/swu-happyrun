"""Read-only, explicitly addressed ADB queries. No connect/start/install commands."""

import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from swu_happyrun.core.models import DeviceCapability
from swu_happyrun.drivers.command import ProbeError, run_readonly


class AdbClient:
    def __init__(self, path: Path, serial: str, *, package: str | None = None):
        if not isinstance(serial, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.:\[\]-]*", serial
        ):
            raise ValueError("invalid_adb_serial")
        if package is not None and not re.fullmatch(
            r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+", package
        ):
            raise ValueError("invalid_package")
        self.path, self.serial, self.package = Path(path), serial, package

    def _query(self, *args: str) -> str:
        return run_readonly(self.path, "-s", self.serial, *args).strip()

    def inspect(self) -> DeviceCapability:
        if self._query("get-state") != "device":
            raise ProbeError("adb_not_ready")
        version = self._query("shell", "getprop", "ro.build.version.release")
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", version):
            raise ProbeError("invalid_response")
        app_version = None
        if self.package:
            raw = self._query("shell", "dumpsys", "package", self.package)
            match = re.search(r"^\s*versionName=([^\r\n]+)", raw, re.MULTILINE)
            if match:
                app_version = match.group(1).strip() or None
        return DeviceCapability(
            device_id=str(uuid5(NAMESPACE_URL, f"adb:{self.serial}")),
            backend="android",
            app_version=app_version,
            capabilities=[],
            observed_at=datetime.now(UTC),
        )
