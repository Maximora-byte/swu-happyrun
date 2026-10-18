"""Read-only inventory: python -m swu_happyrun.drivers.mumu.discovery --json."""

import argparse
import json
import os
import re
import sys
from pathlib import Path

from swu_happyrun.drivers.adb import AdbClient
from swu_happyrun.drivers.command import ProbeError
from swu_happyrun.drivers.mumu.manager import MuMuInstance, MuMuManager


def _registered_installations() -> list[tuple[Path, str | None]]:
    installations = []
    if sys.platform == "win32":
        import winreg

        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                try:
                    with winreg.OpenKey(
                        hive,
                        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                        0,
                        winreg.KEY_READ | view,
                    ) as base:
                        for i in range(winreg.QueryInfoKey(base)[0]):
                            try:
                                with winreg.OpenKey(base, winreg.EnumKey(base, i)) as key:
                                    name = winreg.QueryValueEx(key, "DisplayName")[0]
                                    if isinstance(name, str) and "mumu" in name.lower():
                                        location = winreg.QueryValueEx(key, "InstallLocation")[0]
                                        if isinstance(location, str) and location:
                                            try:
                                                version = winreg.QueryValueEx(
                                                    key, "DisplayVersion"
                                                )[0]
                                            except OSError:
                                                version = None
                                            if not isinstance(version, str) or not re.fullmatch(
                                                r"[0-9]+(?:\.[0-9]+)+", version
                                            ):
                                                version = None
                                            installations.append((Path(location), version))
                            except OSError:
                                continue
                except OSError:
                    continue
    return installations


def _system_roots() -> list[Path]:
    roots = [
        Path(os.environ[key]) / "Netease" / "MuMu"
        for key in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)")
        if os.environ.get(key)
    ]
    return roots + [root for root, _ in _registered_installations()]


def discover_installations(
    *, roots: list[Path] | None = None, include_system: bool = True
) -> list[Path]:
    candidates = list(roots or []) + (_system_roots() if include_system else [])
    found = set()
    for root in candidates:
        for relative in ("nx_main/MuMuManager.exe", "MuMuManager.exe", "shell/MuMuManager.exe"):
            candidate = root / relative
            if candidate.is_file():
                found.add(candidate.resolve())
    return sorted(found, key=str)


def select_instance(instances: list[MuMuInstance], index: str | None) -> MuMuInstance:
    if index is None:
        if len(instances) != 1:
            raise ValueError("instance_selection_required")
        return instances[0]
    for instance in instances:
        if instance.index == index:
            return instance
    raise ValueError("instance_not_found")


def host_version(path: Path) -> str | None:
    """Use matching installed-product metadata, not the manager's internal file version."""
    target = path.resolve()
    for root, version in _registered_installations():
        root = root.resolve()
        candidates = (
            root / "nx_main/MuMuManager.exe",
            root / "MuMuManager.exe",
            root / "shell/MuMuManager.exe",
        )
        if target in candidates:
            return version
    return None


def collect_report(
    *,
    manager: Path | None = None,
    index: str | None = None,
    adb: Path | None = None,
    serial: str | None = None,
    package: str | None = None,
) -> dict:
    report = dict(
        protocol_version=1,
        scope="read_only_inventory",
        status="needs_attention",
        reason_code=None,
        host_check="not_tested",
        device_check="not_tested",
        host_version=None,
        instances=[],
        selected_device=None,
        capabilities=[],
    )
    try:
        if manager is None:
            installations = discover_installations()
            if not installations:
                raise ProbeError("mumu_not_found")
            if len(installations) != 1:
                raise ProbeError("installation_selection_required")
            manager = installations[0]
        client = MuMuManager(manager)
        instances = client.inspect("all" if index is None else index)
        report["host_check"] = "host_verified"
        report["host_version"] = host_version(manager)
        report["instances"] = [
            dict(
                index=i.index,
                android_version=i.android_version,
                android_started=i.android_started,
                process_started=i.process_started,
            )
            for i in instances
        ]
        selected = select_instance(instances, index)
        report["selected_device"] = client.capability(selected).model_dump(mode="json")
        if not selected.android_started:
            raise ProbeError("android_not_started")
        if adb is None or serial is None:
            raise ProbeError("adb_selection_required")
        observed = AdbClient(adb, serial, package=package).inspect()
        # Keep the MuMu identity; a generic ADB identity is not automatically the same device.
        # Until that mapping is verified in L1, expose the ADB observation separately.
        report["adb_observation"] = observed.model_dump(mode="json")
        report["device_check"] = "adb_observed_identity_unverified"
        report["status"] = "ok"
        report["reason_code"] = "execution_capabilities_not_tested"
    except ProbeError as error:
        report["reason_code"] = error.code
    except ValueError as error:
        allowed = {
            "instance_selection_required",
            "instance_not_found",
            "invalid_instance_index",
            "invalid_adb_serial",
            "invalid_package",
        }
        report["reason_code"] = str(error) if str(error) in allowed else "invalid_response"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit structured JSON")
    parser.add_argument("--manager", type=Path)
    parser.add_argument("--index", help="explicit instance index (required for multiple instances)")
    parser.add_argument("--adb", type=Path)
    parser.add_argument("--serial", help="explicit authorized ADB serial")
    parser.add_argument("--package", help="optional exact app package for version lookup")
    args = parser.parse_args()
    report = collect_report(
        manager=args.manager,
        index=args.index,
        adb=args.adb,
        serial=args.serial,
        package=args.package,
    )
    # ensure_ascii keeps valid output on Windows consoles with non-UTF-8 code pages.
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
