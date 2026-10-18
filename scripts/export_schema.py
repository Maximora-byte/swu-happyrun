"""Export all v1 wire models. --check fails on missing or changed bytes."""

import argparse
import json
from pathlib import Path

from pydantic.json_schema import models_json_schema

from swu_happyrun.core import models

MODELS = (
    models.JobSpec,
    models.JobView,
    models.AgentHello,
    models.DeviceCapability,
    models.LeaseGrant,
    models.LeaseCommand,
    models.JobEvent,
    models.EvidenceRef,
    models.ScheduleSpec,
    models.GeoPoint,
    models.RouteProfile,
    models.SchoolProfile,
    models.VerificationResult,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "contracts/protocol-v1.schema.json",
    )
    args = parser.parse_args()
    refs, schema = models_json_schema([(model, "validation") for model in MODELS])
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = "SWU HappyRun protocol v1"
    schema["anyOf"] = [refs[(model, "validation")] for model in MODELS]
    data = (json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
    if args.check:
        if not args.output.is_file() or args.output.read_bytes() != data:
            print("Protocol schema is missing or stale; run scripts/export_schema.py")
            return 1
        print("Protocol schema matches shared models")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(data)
        print("Protocol schema exported")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
