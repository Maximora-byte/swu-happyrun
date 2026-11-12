"""Read-only explicit-instance metadata sampler. Stdout is a fixed redacted summary.

No URL, arbitrary command, session, token, UI dump, install, input or location API.
Existing ADB can implicitly start its host daemon. No connect/pair is requested.
Raw output may be saved only underneath this checkout's local directory.
"""

import argparse
import importlib.util
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from swu_happyrun.drivers.adb import AdbClient
from swu_happyrun.drivers.command import ProbeError
from swu_happyrun.drivers.mumu.manager import MuMuManager

ROOT = Path(__file__).resolve().parents[1]


def write_private(path: Path, data: dict, *, root: Path = ROOT) -> None:
    """Create a new private file only; never overwrite or follow a symlink."""
    root = root.resolve()
    path = Path(path).absolute()
    local = root / "local"
    try:
        relative = path.relative_to(local)
        if not relative.parts or any(part in {".", ".."} for part in relative.parts):
            raise ValueError
        current = root
        for part in ("local", *relative.parts):
            current = current / part
            if current.is_symlink():
                raise ValueError
        if not path.resolve().is_relative_to(local.resolve()):
            raise ValueError
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(data, output, ensure_ascii=True, indent=2)
            output.write("\n")
    except (OSError, ValueError):
        raise ProbeError("private_output_rejected") from None


def collect_context(
    *,
    manager: Path,
    adb: Path,
    instance_index: str | None,
    serial: str | None,
    package: str | None,
    private_output: Path | None = None,
) -> dict:
    report = {
        "status": "blocked",
        "reason": "selection_required",
        "missing": [],
        "scope": "read_only_metadata",
        "capabilities": [],
        "writes": 0,
        "device_verified": False,
        "record_verified": False,
    }
    selections = {"instance_index": instance_index, "adb_serial": serial, "package": package}
    report["missing"] = [key for key, value in selections.items() if not value]
    if report["missing"]:
        return report
    try:
        if not isinstance(instance_index, str) or not re.fullmatch(r"[0-9]+", instance_index):
            raise ValueError
        AdbClient(adb, serial, package=package)
        instances = MuMuManager(manager).inspect(instance_index)
        if (
            len(instances) != 1
            or not instances[0].android_started
            or not instances[0].process_started
        ):
            raise ProbeError("instance_not_ready")
        observed = AdbClient(adb, serial, package=package).inspect()
        # Reuse the existing bounded read-only adapters. Do not duplicate their
        # parsers or retain unrelated package dump contents (which may be private).
        selected = instances[0]
        private = {
            "selection": selections,
            "observation_id": str(uuid4()),
            "observed_at": datetime.now(UTC).isoformat(),
            "manager_observation": {
                "index": selected.index,
                "android_version": selected.android_version,
                "probe_id": selected.probe_id,
                "observed_at": selected.observed_at.isoformat(),
            },
            "adb_observation": observed.model_dump(mode="json"),
        }
        # This sampler cannot infer an alias mapping, boot identity, or display/task.
        # Do not turn successful subprocesses or unrelated UUIDs into a binding.
        report["reason"] = "binding_evidence_required"
        report["missing"] = [
            "current_alias_mapping",
            "host_version",
            "engine_version",
            "boot_id",
            "display_task_observation",
        ]
        if observed.app_version is None:
            report["missing"].append("app_version")
        if private_output is not None:
            write_private(private_output, private)
        report["metadata_collected"] = True
    except ProbeError as exc:
        report["reason"] = exc.code
    except (TypeError, ValueError):
        report["reason"] = "invalid_arguments"
    return report


def validate_display_replay(
    raw: str,
    *,
    code: int,
    observation_id: str,
    display_id: int,
    task_id: int,
    signature_sha256: str,
) -> bool:
    """Reuse Task5's pure receipt parser; never invoke its instrumentation main.

    A valid replay proves only that the bundle matches these supplied expectations.
    The caller must independently establish freshness, mapping and provenance.
    """
    spec = importlib.util.spec_from_file_location(
        "mumu_display_observation", ROOT / "scripts/check_mumu_observation.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.accepted(raw, code, observation_id, display_id, task_id, signature_sha256)


class _SafeParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse normally echoes unknown argument values, including accidental secrets.
        super().error("invalid or missing arguments; use --help")


def main(argv=None):
    parser = _SafeParser(description=__doc__)
    parser.add_argument("--manager", required=True, type=Path)
    parser.add_argument("--adb", required=True, type=Path)
    parser.add_argument("--instance", required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--package", required=True)
    parser.add_argument("--private-output", type=Path)
    args = parser.parse_args(argv)
    report = collect_context(
        manager=args.manager,
        adb=args.adb,
        instance_index=args.instance,
        serial=args.serial,
        package=args.package,
        private_output=args.private_output,
    )
    print(json.dumps(report, ensure_ascii=True))
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    sys.exit(main())
