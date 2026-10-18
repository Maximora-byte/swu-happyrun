"""Parse the observed MuMuManager info --vmindex response conservatively."""

import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from swu_happyrun.core.models import DeviceCapability
from swu_happyrun.drivers.command import ProbeError, run_readonly


@dataclass(frozen=True)
class MuMuInstance:
    index: str
    android_version: str
    android_started: bool
    process_started: bool


class MuMuManager:
    def __init__(self, path: Path):
        self.path = Path(path)

    def inspect(self, index: str) -> list[MuMuInstance]:
        if not isinstance(index, str) or not re.fullmatch(r"all|[0-9]+", index):
            raise ValueError("invalid_instance_index")
        raw = run_readonly(self.path, "info", "--vmindex", index)
        try:
            data = json.loads(raw.lstrip("\ufeff"))
        except ValueError:
            raise ProbeError("invalid_response") from None
        if not isinstance(data, dict):
            raise ProbeError("invalid_response")
        if index != "all" and "index" in data:
            data = {index: data}
        result = []
        for key, item in data.items():
            if not re.fullmatch(r"[0-9]+", key) or not isinstance(item, dict):
                raise ProbeError("invalid_response")
            if type(item.get("error_code")) is not int or item["error_code"] != 0:
                raise ProbeError("instance_error")
            if (
                str(item.get("index")) != key
                or (index != "all" and key != index)
                or not isinstance(item.get("android_version"), str)
                or not item["android_version"].strip()
                or type(item.get("is_android_started")) is not bool
                or type(item.get("is_process_started")) is not bool
            ):
                raise ProbeError("invalid_response")
            result.append(
                MuMuInstance(
                    key,
                    item["android_version"],
                    item["is_android_started"],
                    item["is_process_started"],
                )
            )
        return result

    def capability(self, instance: MuMuInstance) -> DeviceCapability:
        identity = f"mumu:{os.path.normcase(str(self.path.resolve()))}:{instance.index}"
        return DeviceCapability(
            device_id=str(uuid5(NAMESPACE_URL, identity)),
            backend="mumu",
            app_version=None,
            capabilities=[],
            observed_at=datetime.now(UTC),
        )

    def info(self, index: str) -> list[DeviceCapability]:
        return [self.capability(instance) for instance in self.inspect(index)]
