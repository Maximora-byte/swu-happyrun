"""Local evidence binding. This is neither a device identity merge nor execution authority.

Callers must obtain the observation from a trusted, current local review. Accepting
this structure does not authenticate its provenance, grant capabilities, or replace
an execution guard. Never publish the binding or its stable fingerprint.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from swu_happyrun.drivers.command import ProbeError

MAX_AGE_SECONDS = 30
_FIELDS = {
    "instance_index",
    "adb_serial",
    "host_version",
    "engine_version",
    "app_version",
    "package",
    "display_id",
    "task_id",
    "boot_id",
    "observation_id",
    "observed_at",
    "mapping_source",
    "mapped_instance_index",
    "mapped_adb_serial",
    "observed_display_id",
    "observed_task_id",
    "matching_task_count",
}


@dataclass(frozen=True)
class MumuBinding:
    instance_index: str
    adb_serial: str
    host_version: str
    engine_version: str
    app_version: str
    package: str
    display_id: int
    task_id: int
    boot_id: str
    observation_id: str
    observed_at: datetime
    digest: str

    @property
    def capabilities(self) -> tuple:
        return ()

    @property
    def identity_digest(self) -> str:
        """Stable local context, distinct from the original observation digest.

        Calibration may anchor to digest; fresh guard observations compare this
        identity without rewriting that original calibration evidence.
        """
        identity = {
            key: getattr(self, key)
            for key in self.__dataclass_fields__
            if key not in {"observed_at", "observation_id", "digest"}
        }
        return hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def assert_current(self, observation: dict, *, now: datetime | None = None) -> None:
        current = resolve_binding(
            instance_index=self.instance_index,
            adb_serial=self.adb_serial,
            observation=observation,
            now=now,
        )
        if current.identity_digest != self.identity_digest:
            raise ProbeError("binding_changed")


def resolve_binding(
    *, instance_index: str, adb_serial: str, observation: dict, now: datetime | None = None
) -> MumuBinding:
    """Validate a bounded local evidence snapshot; fail closed on missing/extra fields."""
    if not isinstance(observation, dict) or set(observation) != _FIELDS:
        raise ProbeError("binding_fields_invalid")
    value = dict(observation)
    patterns = {
        "instance_index": r"[0-9]+",
        "mapped_instance_index": r"[0-9]+",
        "adb_serial": r"[A-Za-z0-9][A-Za-z0-9_.:\[\]-]*",
        "mapped_adb_serial": r"[A-Za-z0-9][A-Za-z0-9_.:\[\]-]*",
        "package": r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+",
        "host_version": r"[0-9]+(?:\.[0-9]+)*",
        "engine_version": r"[0-9]+(?:\.[0-9]+)*",
        "app_version": r"[0-9][A-Za-z0-9_.+-]*",
        "boot_id": r"[A-Za-z0-9-]+",
    }
    for key, pattern in patterns.items():
        if (
            not isinstance(value[key], str)
            or len(value[key]) > 128
            or not re.fullmatch(pattern, value[key])
        ):
            raise ProbeError("binding_fields_invalid")
    for key in (
        "display_id",
        "task_id",
        "observed_display_id",
        "observed_task_id",
        "matching_task_count",
    ):
        if type(value[key]) is not int or not 0 <= value[key] <= 2**31 - 1:
            raise ProbeError("binding_fields_invalid")
    try:
        if str(UUID(value["observation_id"])) != value["observation_id"]:
            raise ValueError
        observed_at = datetime.fromisoformat(value["observed_at"])
        now = datetime.now(UTC) if now is None else now
        if observed_at.tzinfo is None or now.tzinfo is None:
            raise ValueError
        age = (now - observed_at).total_seconds()
    except (ValueError, TypeError, AttributeError):
        raise ProbeError("binding_fields_invalid") from None
    if not 0 <= age <= MAX_AGE_SECONDS:
        raise ProbeError("binding_stale")
    if (
        value["instance_index"] != instance_index
        or value["mapped_instance_index"] != instance_index
        or value["adb_serial"] != adb_serial
        or value["mapped_adb_serial"] != adb_serial
        or value["mapping_source"] != "local_review"
        or value["display_id"] != value["observed_display_id"]
        or value["task_id"] != value["observed_task_id"]
        or value["matching_task_count"] != 1
    ):
        raise ProbeError("binding_mismatch")
    value["observed_at"] = observed_at.astimezone(UTC).isoformat()
    digest = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    fields = {
        key: value[key]
        for key in MumuBinding.__dataclass_fields__
        if key not in {"digest", "observed_at"}
    }
    return MumuBinding(**fields, observed_at=observed_at, digest=digest)
