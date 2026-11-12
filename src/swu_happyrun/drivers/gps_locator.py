"""Offline/read-only GPS Locator preview. No start, stop or permission commands.

Protocol inspected at 0xfnzero/gps-locator@7845ff8 (see third-party notices).
App-reported flags are not fresh GPS, session ownership or execution capability.
"""

import base64
import json
import math
import os
import re
from pathlib import Path

from swu_happyrun.core.canonical import profile_revision
from swu_happyrun.core.coordinates import normalize_points
from swu_happyrun.core.models import RouteProfile
from swu_happyrun.drivers.command import run_readonly

UPSTREAM_COMMIT = "7845ff8c94fef7d0afd2bcc4fa34ad3575635f29"
PACKAGE = "com.gpsupdater.app"
MAX_DOCUMENT_BYTES = 74_999  # Base64url must remain within upstream's 100,000 limit.


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


def export_route(route: RouteProfile, speed_mps: float) -> dict:
    """Derive deterministic upstream JSON; no upload, device call or file write."""
    route = RouteProfile.model_validate(route.model_dump(mode="python"))
    if route.revision != profile_revision(route):
        raise ValueError("route_revision_mismatch")
    if type(speed_mps) not in (int, float) or not math.isfinite(speed_mps):
        raise ValueError("speed_invalid")
    speed_kph = speed_mps * 3.6
    if not 0.5 <= speed_kph <= 500:
        raise ValueError("speed_out_of_upstream_range")
    points = normalize_points(route)
    if len({(p.latitude, p.longitude) for p in points}) < 2:
        raise ValueError("route_requires_distinct_points")
    document = {
        "id": route.route_id,
        "name": "HappyRun offline preview",
        "speedKph": speed_kph,
        "loop": False,
        "createdAt": 0,
        "waypoints": [
            {
                "id": f"point-{index}",
                "name": f"Point {index + 1}",
                "latitude": point.latitude,
                "longitude": point.longitude,
                "stopDurationSeconds": 0,
            }
            for index, point in enumerate(points)
        ],
    }
    if len(json.dumps(document, separators=(",", ":")).encode()) > MAX_DOCUMENT_BYTES:
        raise ValueError("route_document_too_large")
    return document


def export_file(source: Path, output: Path, speed_mps: float) -> None:
    """Write a new local private file only; never overwrite a source or result."""
    with source.open("rb") as handle:
        raw = handle.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError("route_input_too_large")
    route = RouteProfile.model_validate(json.loads(raw, object_pairs_hook=_unique_keys))
    document = export_route(route, speed_mps)
    # Compact JSON is also the representation checked against the upstream limit.
    data = json.dumps(document, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _valid_status(record):
    if type(record) is not dict:
        return False
    fields = {
        "schemaVersion",
        "applicationId",
        "appVersion",
        "versionCode",
        "debug",
        "tier",
        "deviceId",
        "mockLocationReady",
        "simulationActive",
        "enterprise",
    }
    if set(record) != fields:
        return False
    enterprise = record["enterprise"]
    return (
        type(record["schemaVersion"]) is int
        and record["schemaVersion"] == 1
        and record["applicationId"] == PACKAGE
        and type(record["appVersion"]) is str
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+_-]{0,63}", record["appVersion"]) is not None
        and type(record["versionCode"]) is int
        and record["versionCode"] >= 0
        and type(record["debug"]) is bool
        and record["tier"] in ("free", "pro", "enterprise")
        and type(record["deviceId"]) is str
        and type(record["mockLocationReady"]) is bool
        and type(record["simulationActive"]) is bool
        and type(enterprise) is dict
        and set(enterprise) == {"organization", "expiresAt", "active", "deviceBound"}
        and type(enterprise["organization"]) is str
        and type(enterprise["expiresAt"]) is int
        and enterprise["expiresAt"] >= 0
        and type(enterprise["active"]) is bool
        and type(enterprise["deviceBound"]) is bool
    )


def inspect(adb: Path, serial: str) -> dict:
    """Explicit single-device status query; output excludes identifiers and secrets.

    Broadcast wakes the status receiver but does not start location simulation.
    This function intentionally exposes no generic action/payload escape hatch.
    """
    if (
        type(serial) is not str
        or serial == "all"
        or len(serial) > 256
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:\[\]-]*", serial) is None
    ):
        raise ValueError("invalid_adb_serial")
    raw = run_readonly(
        Path(adb),
        "-s",
        serial,
        "shell",
        "am",
        "broadcast",
        "--receiver-foreground",
        "-n",
        f"{PACKAGE}/.enterprise.EnterpriseControlReceiver",
        "-a",
        f"{PACKAGE}.enterprise.GET_DEVICE_STATUS",
        timeout=5,
    )
    try:
        if len(raw) > 100_000:
            raise ValueError
        matches = re.findall(
            r'^Broadcast completed: result=1, data="([A-Za-z0-9_-]+)"$', raw, re.MULTILINE
        )
        if len(matches) != 1 or raw.count("Broadcast completed:") != 1:
            raise ValueError
        encoded = matches[0]
        decoded = base64.b64decode(
            encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True
        )
        record = json.loads(decoded, object_pairs_hook=_unique_keys)
        if not _valid_status(record):
            raise ValueError
    except (ValueError, TypeError, KeyError, RecursionError):
        raise ValueError("gps_locator_status_invalid") from None
    return {
        "backend": "gps-locator-preview",
        "app_version_reported": record["appVersion"],
        "version_code_reported": record["versionCode"],
        "reported_version_matches_reference": record["appVersion"] == "2.1.0"
        and record["versionCode"] == 5,
        "mock_location_appop_reported": record["mockLocationReady"],
        "simulation_active_reported": record["simulationActive"],
        "execution_enabled": False,
        "fresh_location_verified": False,
        "record_verified": False,
        "reason_code": "device_session_protocol_required",
    }
