#!/usr/bin/env python3
"""Zero-device preview for the staged isolated-evidence implementation.

No executable adapter is installed. --execute explains the gate and does nothing.
Do not use the older probe-point command as a substitute for this missing gate.
"""

import json
import sys


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    preview = argv in ([], ["--preview"])
    recognized = preview or argv == ["--execute"]
    print(
        json.dumps(
            {
                "status": "preview" if preview else "not_ready",
                "reason_code": "device_adapter_unverified" if recognized else "arguments_invalid",
                "execution_ready": False,
                "gaps": [
                    "stable_registry_adapter",
                    "exact_process_identity_adapter",
                    "windows_private_acl_verification",
                    "independent_device_review",
                ],
                "launch_count": 0,
                "install_count": 0,
                "location_count": 0,
                "shutdown_count": 0,
                "stop_status": "stop_unconfirmed",
                "replay_enabled": False,
            },
            separators=(",", ":"),
        )
    )
    return 0 if preview else 3


if __name__ == "__main__":
    raise SystemExit(main())
