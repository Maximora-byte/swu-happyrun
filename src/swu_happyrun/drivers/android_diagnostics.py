"""Standalone Android metadata diagnostics; no MuMu or execution capability claims.

ADB may start its host server implicitly. This module never connects, pairs, changes
settings, requests permission, starts an app, or writes location/sensor data.
"""

import argparse
import json
import re
from pathlib import Path

from swu_happyrun.drivers.adb import AdbClient
from swu_happyrun.drivers.command import ProbeError, run_readonly


def _unknown(reason):
    return {"status": "unknown", "value": None, "reason": reason}


def _observed(value):
    return {"status": "observed", "value": value, "reason": None}


def _failure(raw):
    lower = raw.lower()
    if "permission denial" in lower or "permission denied" in lower or "securityexception" in lower:
        return "permission_denied"
    if "can't find service" in lower or "cannot find service" in lower:
        return "unsupported"
    if not raw.strip():
        return "empty_response"
    return None


def _devices(raw):
    lines = raw.strip().splitlines()
    if not lines or lines[0].strip() != "List of devices attached":
        raise ProbeError("invalid_response")
    result = {}
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split(None, 1)
        if len(parts) != 2 or parts[0] in result:
            raise ProbeError("invalid_response")
        result[parts[0]] = parts[1].strip()
    return result


def collect_report(
    *, adb: Path, serial: str | None = None, package: str | None = None, samples: bool = False
) -> dict:
    """Collect local-only metadata. Explicit serial required even for one device.

    samples opts into transient service dumps. Raw dumps never leave this process;
    only recognized service-header presence is reported. It is not a live sensor
    measurement, a fresh position fix, or application compatibility verification.
    """
    report = {
        "status": "blocked",
        "reason": None,
        "backend": "android",
        "metadata": {},
        "capabilities": [],
        "device_verified": False,
        "record_verified": False,
        "execution": "unsupported_by_candidate",
        "samples": {
            name: {**_unknown("not_requested"), "live_read": "unknown"}
            for name in ("location", "sensorservice")
        },
    }
    # Reuse input validation without running AdbClient.inspect or requiring MuMu.
    try:
        AdbClient(adb, serial if serial is not None else "validation-only", package=package)
    except (ValueError, TypeError):
        report["reason"] = "invalid_arguments"
        return report
    try:
        devices = _devices(run_readonly(adb, "devices"))
    except ProbeError as exc:
        report["reason"] = exc.code
        return report
    reason = None
    if not devices:
        reason = "no_devices"
    elif serial is None:
        reason = "multiple_devices" if len(devices) > 1 else "serial_required"
    elif serial not in devices:
        reason = "device_not_found"
    elif devices[serial] != "device":
        state = devices[serial]
        reason = state if state in {"unauthorized", "offline"} else "unsupported_state"
        if state.startswith("no permissions"):
            reason = "host_permission_denied"
    if reason:
        report["reason"] = reason
        return report

    def query(*args):
        try:
            raw = run_readonly(adb, "-s", serial, "shell", *args).strip()
        except ProbeError as exc:
            return None, exc.code
        return raw, _failure(raw)

    fields = {
        "model": "ro.product.model",
        "abi": "ro.product.cpu.abilist",
        "android_version": "ro.build.version.release",
        "sdk": "ro.build.version.sdk",
    }
    for name, prop in fields.items():
        raw, error = query("getprop", prop)
        value = raw
        if not error:
            if name == "abi":
                value = raw.split(",")
                if not all(re.fullmatch(r"[a-zA-Z0-9_-]{1,32}", item) for item in value):
                    error = "invalid_response"
            elif name in {"sdk", "android_version"}:
                pattern = r"[0-9]{1,3}" if name == "sdk" else r"[0-9]{1,3}(?:\.[0-9]{1,3})*"
                if not re.fullmatch(pattern, raw):
                    error = "invalid_response"
                elif name == "sdk":
                    value = int(raw)
            elif len(raw) > 128 or not raw.isprintable():
                error = "invalid_response"
        report["metadata"][name] = _unknown(error) if error else _observed(value)
    for key in ("app_version", "app_version_code"):
        report["metadata"][key] = _unknown("package_not_requested")
    if package:
        raw, error = query("dumpsys", "package", package)
        if raw and "unable to find package" in raw.lower():
            error = "package_not_found"
        for key, pattern in (
            ("app_version", r"^\s*versionName=([^\r\n]+)"),
            ("app_version_code", r"^\s*versionCode=([0-9]+)(?:\s|$)"),
        ):
            match = re.search(pattern, raw or "", re.MULTILINE) if not error else None
            value = match.group(1).strip() if match else None
            if value and len(value) <= 128 and value.isprintable():
                report["metadata"][key] = _observed(value)
            else:
                report["metadata"][key] = _unknown(error or "unrecognized_output")
    report["status"] = "ok"
    if any(
        item["status"] == "unknown" and item["reason"] != "package_not_requested"
        for item in report["metadata"].values()
    ):
        report["status"] = "partial"
    if samples:
        services, error = query("dumpsys", "-l")
        listed = {line.strip() for line in (services or "").splitlines()}
        recognized = "Currently running services:" in listed
        for service, header in (
            ("location", "Location Manager State:"),
            ("sensorservice", "Sensor List:"),
        ):
            sample_error = error
            if not sample_error and not recognized:
                sample_error = "unrecognized_output"
            if not sample_error and service not in listed:
                sample_error = "unsupported"
            if not sample_error:
                raw, sample_error = query("dumpsys", service)
                if not sample_error and header not in {line.strip() for line in raw.splitlines()}:
                    sample_error = "unrecognized_output"
            sample = _unknown(sample_error) if sample_error else _observed("diagnostic_header")
            report["samples"][service] = {**sample, "live_read": "unknown"}
            if sample_error:
                report["status"] = "partial"
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", type=Path, required=True)
    parser.add_argument("--serial")
    parser.add_argument("--package")
    parser.add_argument("--samples", action="store_true", help="read transient service diagnostics")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = collect_report(
        adb=args.adb, serial=args.serial, package=args.package, samples=args.samples
    )
    print(json.dumps(report, ensure_ascii=True))
    return 0 if report["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
