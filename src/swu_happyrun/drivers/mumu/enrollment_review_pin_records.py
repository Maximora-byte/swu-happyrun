"""Bounded, canonical independent-review records, with no filesystem access.

An encoded record, a decoded dataclass, or a reviewer name is not authority. The
issuer and loader must separately establish current independently reviewed runner
anchors, protected file observations, and the original locks. Nothing here proves
reviewer independence, product identity, durability, or current runtime readiness.
The journal is identity-only: its mutable contents are never permanently pinned.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .enrollment_authority import ApprovalNotReady, RunnerAnchors, TargetBinding
from .enrollment_transaction_plan import ApprovedTransactionPlan, _reserved_component, _topology
from .enrollment_transaction_records import ArtifactObservation, RecordInvalid, TransactionLayout
from .instance_attribution import FileIdentity

MAX_REVIEW_PIN_BYTES = 64 * 1024
# Fixed role label only: a matching string is never evidence of independent issuance.
INDEPENDENT_REVIEWER_ID = "original-machine-codex"
FROZEN_ROLES = (
    "authority",
    "approved_plan",
    "reviewed_scope",
    "host",
    "manager",
    "config",
    "config_previous",
    "admission",
    "intent",
    "device_lock",
    "provenance",
    "receipt",
    "candidate",
    *(f"stage{sequence:02d}" for sequence in range(1, 8)),
)
_FIELDS = {
    "schema",
    "epoch",
    "plan_sha256",
    "transaction_id",
    "candidate_sha256",
    "reviewed_scope_sha256",
    "product_commit",
    "product_tree",
    "reviewer_id",
    "reviewed_at",
    "expires_at",
    "execution_allowed",
    "root_identity",
    "lock_identity",
    "review_parent_identity",
    "frozen",
    "journal",
}
_STATIC_ROLES = {"host", "manager", "config", "config_previous"}
_TARGET_ROLES = _STATIC_ROLES | {"journal", "receipt", "device_lock"}
_DIRECTORY_ROLES = {"admissions", "transactions", "transaction", "evidence"}
_ARTIFACT_FIELDS = {"role", "path", "identity", "parent_identity", "size", "sha256"}
_JOURNAL_FIELDS = {"path", "identity", "parent_identity"}


class ReviewPinInvalid(RuntimeError):
    def __init__(self):
        super().__init__("enrollment_review_pin_invalid")


def _require(condition):
    if not condition:
        raise ReviewPinInvalid()


def _keys(value, fields):
    _require(type(value) is dict and set(value) == fields)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _digest(value, length=64):
    _require(type(value) is str and re.fullmatch(f"[0-9a-f]{{{length}}}", value) is not None)
    return value


def _path(value):
    _require(type(value) is str and 1 <= len(value) <= 1024 and "\0" not in value)
    path = Path(value)
    _require(
        str(path) == value
        and path.is_absolute()
        and ".." not in path.parts
        and not value.startswith(("//", "\\\\"))
        and len(path.parts) <= 64
    )
    if os.name == "nt":
        for part in path.parts[1:]:
            _require(
                not part.endswith((".", " "))
                and not any(character in part for character in '<>:"|?*')
                and not _reserved_component(part)
            )
    return path


def _identity_payload(identity):
    _require(type(identity) is FileIdentity and identity.domain == "python_stat")
    # python_stat indexes can be 128-bit on modern Windows; legacy NTFS limits
    # do not apply. The enclosing canonical record remains strictly byte-bounded.
    _require(
        type(identity.volume) is int
        and identity.volume >= 0
        and type(identity.file_index) is int
        and identity.file_index > 0
    )
    return {"domain": "python_stat", "value": [identity.volume, identity.file_index]}


def _identity(value):
    _keys(value, {"domain", "value"})
    _require(value["domain"] == "python_stat")
    pair = value["value"]
    _require(type(pair) is list and len(pair) == 2)
    result = FileIdentity("python_stat", *pair)
    _identity_payload(result)
    return result


def _number(value):
    _require(type(value) is int or (type(value) is float and math.isfinite(value)))
    return value


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def _constant(_):
    raise ReviewPinInvalid()


def _bounded(value):
    pending, count = [(value, 0)], 0
    while pending:
        node, depth = pending.pop()
        count += 1
        _require(count <= 1024 and depth <= 8)
        if type(node) is dict:
            _require(len(node) <= 32 and all(type(k) is str and len(k) <= 64 for k in node))
            pending.extend((item, depth + 1) for item in node.values())
        elif type(node) is list:
            _require(len(node) <= 32)
            pending.extend((item, depth + 1) for item in node)
        elif type(node) is str:
            _require(len(node) <= 1024)
        else:
            _require(node is None or type(node) in (int, float, bool))
            if type(node) in (int, float):
                _number(node)


@dataclass(frozen=True, repr=False)
class JournalBinding:
    """Mutable journal identity only; construction grants no access or authority."""

    path: Path
    identity: FileIdentity
    parent_identity: FileIdentity


@dataclass(frozen=True, repr=False)
class ReviewPinRecord:
    """Detached private evidence, never an execution or reusable review permit."""

    canonical_bytes: bytes = field(repr=False)
    reviewer_id: str
    reviewed_at: int | float
    expires_at: int | float
    frozen: tuple[ArtifactObservation, ...] = field(repr=False)
    journal: JournalBinding = field(repr=False)
    execution_allowed: bool = field(default=False, init=False)

    @property
    def sha256(self):
        return hashlib.sha256(self.canonical_bytes).hexdigest()


def _trusted(root, anchors, plan):
    """Validate and derive lexical destinations, never stat or resolve a path."""
    _require(type(root) is type(Path()) and _path(str(root)) == root)
    _require(type(anchors) is RunnerAnchors and type(plan) is ApprovedTransactionPlan)
    _require(type(plan.epoch) is int and 1 <= plan.epoch <= 2**63 - 1)
    _require(plan.kind in {"new_enrollment", "existing"} and plan.execution_allowed is False)
    _require(_digest(plan.plan_sha256) == anchors.plan_sha256 == anchors.plan.sha256)
    _digest(plan.transaction_id)
    _digest(plan.reviewed_scope_sha256)
    _digest(plan.product_commit, 40)
    _digest(plan.product_tree, 40)
    _number(plan.expires_at)
    for item in (anchors.root_identity, anchors.lock_identity, anchors.plan_parent_identity):
        _identity_payload(item)
    for item in (anchors.authority, anchors.plan):
        _identity_payload(item.identity)
        _digest(item.sha256)
    _require(type(plan.targets) is tuple and len(plan.targets) == len(_TARGET_ROLES))
    _require(all(type(item) is TargetBinding for item in plan.targets))
    targets = {item.name: item for item in plan.targets}
    _keys(targets, _TARGET_ROLES)
    _require(type(plan.directories) is tuple and len(plan.directories) == len(_DIRECTORY_ROLES))
    directories = {}
    for item in plan.directories:
        _require(type(item) is tuple and len(item) == 3)
        name, path, identity = item
        _require(name not in directories)
        _require(type(path) is type(Path()) and _path(str(path)) == path)
        _identity_payload(identity)
        directories[name] = path, identity
    _keys(directories, _DIRECTORY_ROLES)
    for target in targets.values():
        _require(type(target.path) is type(Path()) and _path(str(target.path)) == target.path)
        _identity_payload(target.parent_identity)
        if target.identity is not None:
            _identity_payload(target.identity)
        if target.sha256 is not None:
            _digest(target.sha256)
        if target.name in _STATIC_ROLES:
            _require(target.identity is not None and target.sha256 is not None)
        elif target.name == "receipt" or plan.kind == "new_enrollment":
            _require(target.identity is None and target.sha256 is None)
        else:
            _require(target.identity is not None)
            _require((target.sha256 is None) == (target.name == "journal"))
    _topology(root, plan)
    layout = TransactionLayout(
        root,
        plan.plan_sha256,
        plan.transaction_id,
        targets["journal"].path,
        targets["receipt"].path,
        plan.device_id,
    )
    review = root / "reviews" / plan.plan_sha256
    expected = {
        "authority": (root / "authority-v1.json", anchors.root_identity),
        "approved_plan": (review / "approved-plan-v2.json", anchors.plan_parent_identity),
        "reviewed_scope": (review / "reviewed-scope-v1.json", anchors.plan_parent_identity),
        **{name: (targets[name].path, targets[name].parent_identity) for name in _STATIC_ROLES},
        "admission": (layout.path("admission"), directories["admissions"][1]),
        "intent": (layout.path("intent"), directories["transaction"][1]),
        "device_lock": (layout.path("device_lock"), targets["device_lock"].parent_identity),
        "provenance": (layout.path("provenance"), targets["journal"].parent_identity),
        "receipt": (layout.path("receipt"), targets["receipt"].parent_identity),
        "candidate": (layout.path("candidate"), directories["transaction"][1]),
        **{
            f"stage{n:02d}": (layout.record_path(n), directories["transaction"][1])
            for n in range(1, 8)
        },
    }
    _require(len({os.path.normcase(str(path)) for path, _ in expected.values()}) == len(expected))
    for path, parent in expected.values():
        _path(str(path))
        _identity_payload(parent)
    return targets, expected


def _artifact_payload(observation):
    # ArtifactObservation.payload() intentionally only accepts transaction roles.
    # This distinct format validates its own exact role vocabulary instead.
    _require(type(observation) is ArtifactObservation and observation.role in FROZEN_ROLES)
    _require(type(observation.path) is type(Path()))
    _require(type(observation.size) is int and 0 <= observation.size <= 2**63 - 1)
    return {
        "role": observation.role,
        "path": str(_path(str(observation.path))),
        "identity": _identity_payload(observation.identity),
        "parent_identity": _identity_payload(observation.parent_identity),
        "size": observation.size,
        "sha256": _digest(observation.sha256),
    }


def _validate(value, root, anchors, plan, expected_reviewer_id):
    _bounded(value)
    _keys(value, _FIELDS)
    targets, expected = _trusted(root, anchors, plan)
    _require(expected_reviewer_id == INDEPENDENT_REVIEWER_ID)
    _require(type(expected_reviewer_id) is str and value["reviewer_id"] == expected_reviewer_id)
    _require(value["schema"] == "review-pin-v1" and value["execution_allowed"] is False)
    for name in (
        "epoch",
        "plan_sha256",
        "transaction_id",
        "reviewed_scope_sha256",
        "product_commit",
        "product_tree",
        "expires_at",
    ):
        trusted = getattr(plan, name)
        _require(
            type(value[name]) is type(trusted)
            and value[name] == trusted
            and _canonical(value[name]) == _canonical(trusted)
        )
    _require(_number(value["reviewed_at"]) < _number(value["expires_at"]))
    for name, trusted in (
        ("root_identity", anchors.root_identity),
        ("lock_identity", anchors.lock_identity),
        ("review_parent_identity", anchors.plan_parent_identity),
    ):
        _require(_identity(value[name]) == trusted)
    _keys(value["frozen"], set(FROZEN_ROLES))
    frozen = []
    for role in FROZEN_ROLES:
        item = value["frozen"][role]
        _keys(item, _ARTIFACT_FIELDS)
        observation = ArtifactObservation(
            item["role"],
            _path(item["path"]),
            _identity(item["identity"]),
            _identity(item["parent_identity"]),
            item["size"],
            item["sha256"],
        )
        _artifact_payload(observation)
        _require(observation.role == role)
        _require((observation.path, observation.parent_identity) == expected[role])
        if role in {"authority", "approved_plan"}:
            binding = anchors.authority if role == "authority" else anchors.plan
            _require(
                (observation.identity, observation.sha256) == (binding.identity, binding.sha256)
            )
        elif role in _STATIC_ROLES or (role == "device_lock" and plan.kind == "existing"):
            binding = targets[role]
            _require(
                (observation.identity, observation.sha256) == (binding.identity, binding.sha256)
            )
        elif role == "reviewed_scope":
            _require(observation.sha256 == plan.reviewed_scope_sha256)
        frozen.append(observation)
    _require(_digest(value["candidate_sha256"]) == value["frozen"]["candidate"]["sha256"])
    item = value["journal"]
    _keys(item, _JOURNAL_FIELDS)
    journal = JournalBinding(
        _path(item["path"]), _identity(item["identity"]), _identity(item["parent_identity"])
    )
    target = targets["journal"]
    _require((journal.path, journal.parent_identity) == (target.path, target.parent_identity))
    if plan.kind == "existing":
        _require(journal.identity == target.identity)
    file_ids = [item.identity for item in frozen] + [journal.identity, anchors.lock_identity]
    _require(len(set(file_ids)) == len(file_ids))
    _require(not set(file_ids) & {anchors.root_identity, anchors.plan_parent_identity})
    return tuple(frozen), journal


def encode_review_pin(root, anchors, plan, *, reviewer_id, reviewed_at, frozen, journal):
    """Serialize actual supplied evidence; no authority is issued or files accessed."""
    try:
        _keys(frozen, set(FROZEN_ROLES))
        _require(type(journal) is JournalBinding and type(journal.path) is type(Path()))
        value = {
            "schema": "review-pin-v1",
            "epoch": plan.epoch,
            "plan_sha256": plan.plan_sha256,
            "transaction_id": plan.transaction_id,
            "candidate_sha256": frozen["candidate"].sha256,
            "reviewed_scope_sha256": plan.reviewed_scope_sha256,
            "product_commit": plan.product_commit,
            "product_tree": plan.product_tree,
            "reviewer_id": reviewer_id,
            "reviewed_at": reviewed_at,
            "expires_at": plan.expires_at,
            "execution_allowed": False,
            "root_identity": _identity_payload(anchors.root_identity),
            "lock_identity": _identity_payload(anchors.lock_identity),
            "review_parent_identity": _identity_payload(anchors.plan_parent_identity),
            "frozen": {role: _artifact_payload(frozen[role]) for role in FROZEN_ROLES},
            "journal": {
                "path": str(_path(str(journal.path))),
                "identity": _identity_payload(journal.identity),
                "parent_identity": _identity_payload(journal.parent_identity),
            },
        }
        _validate(value, root, anchors, plan, reviewer_id)
        raw = _canonical(value)
        _require(1 <= len(raw) <= MAX_REVIEW_PIN_BYTES)
        return raw
    except (
        ApprovalNotReady,
        RecordInvalid,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        RecursionError,
        OverflowError,
    ):
        raise ReviewPinInvalid() from None


def decode_review_pin(raw, *, root, anchors, plan, expected_reviewer_id):
    """Parse exact bounded bytes against trusted inputs, without opening any path.

    Fresh authority, expiry against the current clock, protected byte/identity
    observations and runtime state must still be established by the caller.
    """
    try:
        _require(type(raw) is bytes and 1 <= len(raw) <= MAX_REVIEW_PIN_BYTES)
        value = json.loads(raw, object_pairs_hook=_unique, parse_constant=_constant)
        frozen, journal = _validate(value, root, anchors, plan, expected_reviewer_id)
        _require(_canonical(value) == raw)
        return ReviewPinRecord(
            raw, value["reviewer_id"], value["reviewed_at"], value["expires_at"], frozen, journal
        )
    except (
        ApprovalNotReady,
        RecordInvalid,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        RecursionError,
        OverflowError,
    ):
        raise ReviewPinInvalid() from None
