#!/usr/bin/env python3
"""Read-only enrollment inventory from an explicit private JSON manifest.

Run: python scripts/mumu_enrollment_inspect.py --manifest ABSOLUTE_PRIVATE_PATH

Exact schema (no extra fields):
  {"schema": 1, "manager": "absolute manager path", "instance_index": "0",
   "expected_journal": null, "roots": ["absolute known state root"],
   "journal_arguments": [], "working_directories": [], "configuration_sources": [],
   "unchecked_categories": ["historical_launch_arguments", "other_accounts"],
   "declared_complete": false}

All path arrays contain absolute paths. List all effective historical --journal
paths, known working directories and configuration sources, not guessed names.
Missing/uncertain categories stay explicitly unchecked. declared_complete is only
a scope statement, never an approved plan or permission to initialize/execute.
The host path remains the product's existing environment/default identity path;
this manifest cannot supply a host UUID, device UUID, control root or approval pin.
Only a sanitized summary is printed. No output file, SQLite or device command is
created/opened. Exit 0 means inventory completed, NOT ready or accepted execution.
"""

import argparse
import json
import sys
from pathlib import Path

MAX_MANIFEST_BYTES = 65536
_FIELDS = {
    "schema",
    "manager",
    "instance_index",
    "expected_journal",
    "roots",
    "journal_arguments",
    "working_directories",
    "configuration_sources",
    "unchecked_categories",
    "declared_complete",
}
_CATEGORIES = {
    "historical_launch_arguments",
    "historical_configuration_sources",
    "custom_roots_and_other_disks",
    "other_accounts",
    "legacy_writers",
}


class _PrivateArguments(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("arguments_invalid")


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _path(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 1024:
        raise ValueError
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or value.startswith(("//", "\\\\")):
        raise ValueError
    return path


def _paths(value):
    if type(value) is not list or len(value) > 32:
        raise ValueError
    return tuple(_path(item) for item in value)


def main(argv=None):
    parser = _PrivateArguments(description=__doc__, allow_abbrev=False)
    parser.add_argument("--manifest", required=True)
    try:
        args = parser.parse_args(argv)
    except ValueError:
        summary = {
            "status": "unknown",
            "reason_codes": ["arguments_invalid"],
            "launch_allowed": False,
            "runtime_state": "unverified",
        }
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
        from swu_happyrun.drivers.mumu.enrollment_inspection import (
            DiscoveryScope,
            _read,
            inspect_enrollment,
        )

        try:
            raw = _read(_path(args.manifest), MAX_MANIFEST_BYTES)
            value = json.loads(raw, object_pairs_hook=_unique)
            if (
                type(value) is not dict
                or set(value) != _FIELDS
                or type(value["schema"]) is not int
                or value["schema"] != 1
                or type(value["declared_complete"]) is not bool
                or type(value["unchecked_categories"]) is not list
                or len(value["unchecked_categories"]) > len(_CATEGORIES)
                or any(
                    type(item) is not str or item not in _CATEGORIES
                    for item in value["unchecked_categories"]
                )
            ):
                raise ValueError
            scope = DiscoveryScope(
                roots=_paths(value["roots"]),
                journal_arguments=_paths(value["journal_arguments"]),
                working_directories=_paths(value["working_directories"]),
                configuration_sources=_paths(value["configuration_sources"]),
                unchecked_categories=tuple(value["unchecked_categories"]),
                declared_complete=value["declared_complete"],
            )
            result = inspect_enrollment(
                scope,
                manager=_path(value["manager"]),
                instance_index=value["instance_index"],
                expected_journal=(
                    None if value["expected_journal"] is None else _path(value["expected_journal"])
                ),
            )
            summary = result.public_summary()
        except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
            summary = {
                "status": "unknown",
                "reason_codes": ["manifest_invalid"],
                "launch_allowed": False,
                "runtime_state": "unverified",
            }
    print(json.dumps(summary, separators=(",", ":")))
    return 3 if summary["status"] == "unknown" else 0


if __name__ == "__main__":
    raise SystemExit(main())
