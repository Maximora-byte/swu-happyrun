#!/usr/bin/env python3
"""Read explicit static MuMu files, emit only a sanitized non-execution summary.

No MuMu/ADB/process query, host identity creation, registration or output file.
Known means a static observation only. Supplied version is not vendor-attested.
"""

import argparse
import json
import sys
from pathlib import Path


class _PrivateArguments(argparse.ArgumentParser):
    def error(self, message):
        # argparse's ordinary errors can include private paths/argument values.
        raise ValueError("arguments_invalid")


def main(argv=None):
    parser = _PrivateArguments(description=__doc__, allow_abbrev=False)
    parser.add_argument("--config", required=True)
    parser.add_argument("--index", required=True)
    parser.add_argument("--manager", required=True)
    parser.add_argument("--manager-version", required=True)
    try:
        args = parser.parse_args(argv)
    except ValueError:
        status, code = "unknown", "arguments_invalid"
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
        from swu_happyrun.drivers.mumu.instance_attribution import inspect_static_instance

        result = inspect_static_instance(
            args.config,
            instance_index=args.index,
            manager_path=args.manager,
            manager_version=args.manager_version,
        )
        status, code = result.status, result.code
    print(
        json.dumps(
            {
                "status": status,
                "reason_code": code,
                "execution_ready": False,
                "attribution_status": "unknown",
            },
            separators=(",", ":"),
        )
    )
    return 0 if status == "known" else 3


if __name__ == "__main__":
    raise SystemExit(main())
