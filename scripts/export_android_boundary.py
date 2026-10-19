"""Export Android local-only reference vectors from existing shared contracts.

This fixture is not a wire-client implementation. Structural state edges are
necessary conditions only: no vector grants a lease, ownership, recovery,
physical capability, or evidence of accepted app records.
"""

import argparse
import hashlib
import json
from pathlib import Path

from swu_happyrun.core.models import VerificationResult
from swu_happyrun.core.states import JobState, transition_allowed

ROOT = Path(__file__).resolve().parents[1]


def boundary() -> dict:
    return {
        "fixture_version": 1,
        "source_schema_sha256": hashlib.sha256(
            (ROOT / "contracts/protocol-v1.schema.json").read_bytes()
        ).hexdigest(),
        "scope": "android_local_simulation_reference_only",
        "wire_protocol_client": False,
        "structural_edges_are_authorization": False,
        "simulation_structural_edges": [
            [source.value, target.value]
            for source in JobState
            for target in JobState
            if transition_allowed(source, target, "simulation")
        ],
        "simulation_completion": JobState.COMPLETED.value,
        "simulation_verification": VerificationResult(
            status="unknown", evidence=[], reason_code="simulation_only"
        ).model_dump(mode="json"),
        "verified_execution_capabilities": [],
        "record_verified": False,
        "notice": (
            "A local simulation is not a server AGENT client or a physical app adapter. "
            "Environment facts, installed packages, su files and permissions do not "
            "establish execution capabilities or accepted records."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "contracts/android-local-boundary-v1.json"
    )
    args = parser.parse_args()
    content = (json.dumps(boundary(), indent=2, sort_keys=True) + "\n").encode()
    if args.check:
        if not args.output.is_file() or args.output.read_bytes() != content:
            print("Android reference fixture is missing or stale")
            return 1
        print("Android reference fixture matches shared contracts")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(content)
        print("Android reference fixture exported")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
