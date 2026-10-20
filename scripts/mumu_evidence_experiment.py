#!/usr/bin/env python3
"""Zero-device preview for the staged isolated-evidence implementation.

No executable adapter is installed. --execute explains the gate and does nothing.
--process-facts is separate explicit read-only host enumeration; output is counts only.
Do not use the older probe-point command as a substitute for this missing gate.
"""

import json
import sys


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["--process-facts"]:
        # Explicit read-only helper, not the zero-process preview or execution.
        import time
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
        from swu_happyrun.drivers.mumu.windows_process_facts import query_process_facts

        snapshot = query_process_facts(time.monotonic() + 5.0)
        print(
            json.dumps(
                {
                    "status": snapshot.status,
                    "reason_code": snapshot.code,
                    "process_count": len(snapshot.processes),
                    "cleanup_confirmed": snapshot.cleanup_confirmed,
                    "execution_ready": False,
                    "replay_enabled": False,
                },
                separators=(",", ":"),
            )
        )
        return 0 if snapshot.status == "complete" else 3
    preview = argv in ([], ["--preview"])
    recognized = preview or argv == ["--execute"]
    print(
        json.dumps(
            {
                "status": "preview" if preview else "not_ready",
                "reason_code": "device_adapter_unverified" if recognized else "arguments_invalid",
                "execution_ready": False,
                "gaps": [
                    "reviewed_original_registration",
                    "mumu_process_attribution_adapter",
                    "verified_lifecycle_commands",
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
