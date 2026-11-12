"""Pure immutable transaction formats and read-only consistency diagnosis.

These records are not independently trusted approval, a recovery permission, or
proof of filesystem durability. No function here opens a file or advances a stage.
The future coordinator must verify current authority and obtain real observations
under protected paths/account/original-device locks. Candidate completion is never
ready; independent pin and current runtime-state validation remain separate.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from .instance_attribution import FileIdentity

MAX_RECORD_BYTES = 65536
ROLES = ("admission", "intent", "device_lock", "journal", "provenance", "receipt", "candidate")


class RecordInvalid(RuntimeError):
    def __init__(self):
        super().__init__("enrollment_record_invalid")


def _digest(value):
    if type(value) is not str or re.fullmatch("[0-9a-f]{64}", value) is None:
        raise RecordInvalid()
    return value


def _path(value):
    path = Path(value)
    if (
        (isinstance(value, str) and str(path) != value)
        or "\0" in str(path)
        or not path.is_absolute()
        or ".." in path.parts
        or str(path).startswith(("//", "\\\\"))
        or not 1 <= len(str(path)) <= 1024
    ):
        raise RecordInvalid()
    return path


def _identity(value):
    if type(value) is not FileIdentity or value.domain != "python_stat":
        raise RecordInvalid()
    return [value.volume, value.file_index]


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


@dataclass(frozen=True, repr=False)
class TransactionLayout:
    """Deterministic names only; construction does not verify or authorize paths.

    All parents, including transactions/<transaction_id>, must be independently
    provisioned, approved and identity-bound before a future writer may use them.
    """

    root: Path
    plan_sha256: str
    transaction_id: str
    journal: Path
    receipt: Path
    device_id: str
    roles: tuple[str, ...] = field(default=ROLES, init=False)

    def __post_init__(self):
        _digest(self.plan_sha256)
        _digest(self.transaction_id)
        for path in (self.root, self.journal, self.receipt):
            if type(path) is not type(Path()) or _path(path) != path:
                raise RecordInvalid()
        try:
            if str(UUID(self.device_id)) != self.device_id:
                raise RecordInvalid()
        except (ValueError, TypeError, AttributeError):
            raise RecordInvalid() from None
        if self.receipt.name != "mumu-experiment-registration.json":
            raise RecordInvalid()
        paths = {self.path(role) for role in self.roles}
        if len(paths) != len(self.roles):
            raise RecordInvalid()
        reserved = {self.record_path(i) for i in range(1, len(self.roles) + 1)}
        reserved.update({self.root / "admission.lock", self.root / "authority-v1.json"})
        if paths & reserved:
            raise RecordInvalid()

    @property
    def directory(self):
        return self.root / "transactions" / self.transaction_id

    def path(self, role):
        paths = {
            "admission": self.root / "admissions" / (self.plan_sha256 + ".json"),
            "intent": self.directory / "enrollment-intent-v1.json",
            "device_lock": self.journal.parent
            / ("device-" + hashlib.sha256(self.device_id.encode()).hexdigest() + ".lock"),
            "journal": self.journal,
            "provenance": self.journal.parent / "enrollment-v1.json",
            "receipt": self.receipt,
            "candidate": self.directory / "candidate-v1.json",
        }
        if role not in paths:
            raise RecordInvalid()
        return paths[role]

    def record_path(self, sequence):
        if type(sequence) is not int or not 1 <= sequence <= len(self.roles):
            raise RecordInvalid()
        return self.directory / f"stage-{sequence:02d}.json"


@dataclass(frozen=True, repr=False)
class ArtifactObservation:
    role: str
    path: Path
    identity: FileIdentity
    parent_identity: FileIdentity
    size: int
    sha256: str

    def payload(self):
        if self.role not in ROLES or type(self.size) is not int or not 0 <= self.size <= 2**63 - 1:
            raise RecordInvalid()
        return {
            "role": self.role,
            "path": str(_path(self.path)),
            "identity": {"domain": "python_stat", "value": _identity(self.identity)},
            "parent_identity": {"domain": "python_stat", "value": _identity(self.parent_identity)},
            "size": self.size,
            "sha256": _digest(self.sha256),
        }


def encode_record(layout, sequence, previous_sha256, artifact):
    if type(layout) is not TransactionLayout or type(artifact) is not ArtifactObservation:
        raise RecordInvalid()
    layout.record_path(sequence)
    if artifact.role != layout.roles[sequence - 1] or artifact.path != layout.path(artifact.role):
        raise RecordInvalid()
    if sequence == 1:
        if previous_sha256 is not None:
            raise RecordInvalid()
    else:
        _digest(previous_sha256)
    return _canonical(
        {
            "schema": "enrollment-stage-v1",
            "plan_sha256": layout.plan_sha256,
            "transaction_id": layout.transaction_id,
            "sequence": sequence,
            "previous_sha256": previous_sha256,
            "artifact": artifact.payload(),
        }
    )


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RecordInvalid()
        result[key] = value
    return result


def _decode_identity(value):
    if (
        type(value) is not dict
        or set(value) != {"domain", "value"}
        or value["domain"] != "python_stat"
    ):
        raise RecordInvalid()
    if type(value["value"]) is not list or len(value["value"]) != 2:
        raise RecordInvalid()
    return FileIdentity("python_stat", *value["value"])


def decode_record(raw):
    try:
        if type(raw) is not bytes or not 1 <= len(raw) <= MAX_RECORD_BYTES:
            raise RecordInvalid()
        value = json.loads(
            raw,
            object_pairs_hook=_unique,
            parse_constant=lambda _: (_ for _ in ()).throw(RecordInvalid()),
        )
        if type(value) is not dict or set(value) != {
            "schema",
            "plan_sha256",
            "transaction_id",
            "sequence",
            "previous_sha256",
            "artifact",
        }:
            raise RecordInvalid()
        if value["schema"] != "enrollment-stage-v1":
            raise RecordInvalid()
        _digest(value["plan_sha256"])
        _digest(value["transaction_id"])
        seq = value["sequence"]
        if type(seq) is not int or not 1 <= seq <= len(ROLES):
            raise RecordInvalid()
        if seq == 1:
            if value["previous_sha256"] is not None:
                raise RecordInvalid()
        else:
            _digest(value["previous_sha256"])
        art = value["artifact"]
        if type(art) is not dict or set(art) != {
            "role",
            "path",
            "identity",
            "parent_identity",
            "size",
            "sha256",
        }:
            raise RecordInvalid()
        artifact = ArtifactObservation(
            art["role"],
            _path(art["path"]),
            _decode_identity(art["identity"]),
            _decode_identity(art["parent_identity"]),
            art["size"],
            art["sha256"],
        )
        artifact.payload()
        if artifact.role != ROLES[seq - 1] or _canonical(value) != raw:
            raise RecordInvalid()
        return value, artifact
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        raise RecordInvalid() from None


@dataclass(frozen=True)
class TransactionDiagnosis:
    status: str
    reason_code: str
    execution_allowed: bool = field(default=False, init=False)


def diagnose_transaction(layout, records, observations):
    """Compare supplied actual observations without writing, opening or repairing.

    A complete candidate allows the journal's *contents* to change but still
    requires its exact identity/parent/path. This says nothing about unresolved
    intents or runtime readiness. Partial transactions retain initial hash checks.
    """
    try:
        if (
            type(layout) is not TransactionLayout
            or type(records) not in (list, tuple)
            or type(observations) is not dict
            or len(records) > len(ROLES)
        ):
            raise RecordInvalid()
        if not records and not observations:
            return TransactionDiagnosis("unstarted", "no_transaction_evidence")
        expected_roles = layout.roles[: len(records)]
        if set(observations) != set(expected_roles):
            raise RecordInvalid()
        previous = None
        for sequence, raw in enumerate(records, 1):
            value, recorded = decode_record(raw)
            if raw != encode_record(layout, sequence, previous, recorded):
                raise RecordInvalid()
            actual = observations[recorded.role]
            if type(actual) is not ArtifactObservation:
                raise RecordInvalid()
            actual.payload()
            if len(records) == len(ROLES) and recorded.role == "journal":
                if (actual.role, actual.path, actual.identity, actual.parent_identity) != (
                    recorded.role,
                    recorded.path,
                    recorded.identity,
                    recorded.parent_identity,
                ):
                    raise RecordInvalid()
            elif actual != recorded:
                raise RecordInvalid()
            previous = hashlib.sha256(raw).hexdigest()
        if len(records) == len(ROLES):
            return TransactionDiagnosis("candidate_unpinned", "independent_pin_required")
        return TransactionDiagnosis("incomplete", "transaction_not_complete")
    except (RecordInvalid, ValueError, TypeError, KeyError):
        return TransactionDiagnosis("incomplete", "transaction_evidence_mismatch")
