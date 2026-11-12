"""Own-APK private readback entry point; never injects or grants Android permissions."""

import argparse
import json
import os
import stat
from dataclasses import asdict
from pathlib import Path

from swu_happyrun.drivers.command import ProbeError
from swu_happyrun.drivers.mumu.binding import resolve_binding
from swu_happyrun.drivers.mumu.own_probe import OwnProbe


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise ProbeError("arguments_invalid")


def _checked_path(path: Path) -> Path:
    path = path.absolute()
    for parent in reversed(path.parents):
        entry = parent.lstat()
        if not stat.S_ISDIR(entry.st_mode) or stat.S_ISLNK(entry.st_mode):
            raise ProbeError("private_path_invalid")
        if getattr(entry, "st_file_attributes", 0) & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
        ):
            raise ProbeError("private_path_invalid")
    return path


def read_private(path: Path, *, limit: int) -> bytes:
    path = _checked_path(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
        raise ProbeError("private_input_invalid")
    if getattr(before, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
        raise ProbeError("private_path_invalid")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
            before.st_dev,
            before.st_ino,
        ):
            raise ProbeError("private_input_invalid")
        value = stream.read(limit + 1)
    if len(value) > limit:
        raise ProbeError("private_input_invalid")
    _checked_path(path)
    return value


def write_private(path: Path, value: str) -> None:
    path = _checked_path(path)
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600
    )
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        _checked_path(path)
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ProbeError("private_output_invalid")
        stream.write(value)


def main(argv=None):
    parser = SafeParser(description=__doc__)
    parser.add_argument("--adb", type=Path)
    parser.add_argument("--binding", type=Path, help="Fresh local binding observation JSON")
    parser.add_argument("--channel", choices=("location", "gravity"), required=True)
    parser.add_argument("--duration-ms", type=int, default=1000)
    parser.add_argument("--observe-own-channel", action="store_true")
    parser.add_argument("--isolated-no-personal-data", action="store_true")
    parser.add_argument(
        "--private-output", type=Path, help="Optional new local file; never publish"
    )
    try:
        args = parser.parse_args(argv)
        if not 1 <= args.duration_ms <= 5000:
            raise ProbeError("observation_budget_invalid")
        if not args.observe_own_channel:
            print(json.dumps({"status": "not_run_opt_in_required", "channel": args.channel}))
            return 0
        if not args.isolated_no_personal_data or args.adb is None or args.binding is None:
            raise ProbeError("observation_authorization_missing")

        def observation():
            return json.loads(read_private(args.binding, limit=16384).decode("utf-8"))

        value = observation()
        binding = resolve_binding(
            instance_index=value["instance_index"],
            adb_serial=value["adb_serial"],
            observation=value,
        )

        def check():
            # A boot recheck is an actual device read, not a host-supplied echo.
            binding.assert_current(observation())
            boot = probe._command(("shell", "cat", "/proc/sys/kernel/random/boot_id"), timeout=5)
            if boot.decode("ascii", errors="strict").strip() != binding.boot_id:
                raise ProbeError("binding_changed")

        probe = OwnProbe(args.adb, binding, binding_check=check, authorization_check=lambda: None)
        samples = probe.sample(args.channel, duration_ms=args.duration_ms)
        if args.private_output is not None:
            write_private(
                args.private_output,
                json.dumps(
                    {
                        "schema": 1,
                        "binding_digest": binding.identity_digest,
                        "boot_id": binding.boot_id,
                        "samples": [asdict(sample) for sample in samples],
                    }
                ),
            )
        print(json.dumps(probe.public_report(args.channel, samples)))
        return 0
    except ProbeError as error:
        # Probe errors are internal constants. No argv, subprocess output or local paths.
        result = {"status": "blocked", "reason": error.code}
        if error.primary_code is not None:
            result["primary_reason"] = error.primary_code
        print(json.dumps(result))
        return 2
    except (OSError, ValueError, KeyError, TypeError, UnicodeError):
        print(json.dumps({"status": "blocked", "reason": "private_input_or_output_invalid"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
