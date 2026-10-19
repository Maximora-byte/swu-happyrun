"""Offline, operator-attested own-app QA triage. Never a driver or live capture gate."""

import argparse
import json
import re
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

MAX_BYTES = 2 * 1024 * 1024
OWN = "org.happyrun.app"


def classify(data):
    """Classify a private capture manifest; statements are not independently verified.

    A UUID and absence declaration prevent accidental mixing, not a malicious or
    mistaken attestation. All results require local human evidence review. This
    module is deliberately disconnected from capability registration and input.
    """
    code = data.get("dump_exit") if isinstance(data, dict) else None
    if type(code) is not int or not -255 <= code <= 255:
        code = None
    result = {
        "scope": "offline_operator_attested_own_app_qa",
        "independently_verified": False,
        "dump_exit": code,
        "dump_succeeded": False,
        "manual_review_candidate": False,
        "driver_input_permitted": False,
        "record_verified": False,
        "reason": "invalid_manifest",
    }
    if not isinstance(data, dict) or code is None:
        return result
    try:
        capture_id = data["capture_id"]
        fresh = (
            str(uuid.UUID(capture_id)) == capture_id
            and data["file_capture_id"] == capture_id
            and data["absent_before"] is True
        )
    except (KeyError, ValueError, TypeError, AttributeError):
        fresh = False
    if not fresh:
        result["reason"] = "freshness_not_established"
        return result
    before, after = data.get("before"), data.get("after")
    if not isinstance(before, dict) or not isinstance(after, dict):
        result["reason"] = "focus_not_established"
        return result
    required = {
        "package",
        "activity",
        "task_id",
        "display_id",
        "task_count",
        "focused",
        "signature_sha256",
    }
    bound = (
        required <= before.keys()
        and required <= after.keys()
        and all(before[key] == after[key] for key in required)
        and before["package"] == OWN
        and before["activity"] == OWN + ".MainActivity"
        and all(type(snapshot["task_count"]) is int for snapshot in (before, after))
        and before["task_count"] == 1
        and before["focused"] is True
        and after["focused"] is True
        and all(
            type(snapshot[key]) is int and snapshot[key] >= 0
            for snapshot in (before, after)
            for key in ("task_id", "display_id")
        )
        and isinstance(before["signature_sha256"], str)
        and re.fullmatch(r"[0-9a-f]{64}", before["signature_sha256"]) is not None
    )
    if not bound:
        result["reason"] = "focus_or_identity_changed_or_unknown"
        return result
    try:
        path = Path(data["xml_file"])
        if path.is_symlink() or not path.is_file():
            raise ValueError
        with path.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if (
            len(raw) > MAX_BYTES
            or b"\x00" in raw
            or b"<!DOCTYPE" in raw.upper()
            or b"<!ENTITY" in raw.upper()
        ):
            raise ValueError
        # Strict UTF-8 prevents alternate encodings hiding DTD/entity bytes.
        root = ET.fromstring(raw.decode("utf-8"))
        nodes = list(root.iter("node"))
        if root.tag != "hierarchy" or not nodes or any(n.get("package") != OWN for n in nodes):
            raise ValueError
    except (KeyError, TypeError, OSError, ValueError, ET.ParseError):
        result["reason"] = "xml_missing_invalid_or_not_exclusively_own"
        return result
    result["dump_succeeded"] = code == 0
    result["manual_review_candidate"] = code in (0, 139, 135)
    result["reason"] = (
        "operator_attested_dump_zero"
        if code == 0
        else "vendor_dump_nonzero"
        if code in (139, 135)
        else "dump_failed"
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.manifest.is_symlink() or not args.manifest.is_file():
            raise ValueError
        with args.manifest.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        data = json.loads(raw) if len(raw) <= MAX_BYTES else None
    except (OSError, ValueError):
        data = None
    result = classify(data)
    print(json.dumps(result, sort_keys=True))
    # Even an eligible XML with vendor exit139/135 is a failed dump command.
    return 0 if result["dump_succeeded"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
