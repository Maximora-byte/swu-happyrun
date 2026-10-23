"""Pinned v2 transaction inputs, without target access during authority loading.

Parsing is deliberately separate from frozen-input inspection. The coordinator
must reject conflicts before touching any journal parent, then hold protected
paths and the account lock before validating frozen inputs. Mutable artifacts
belong to its phase-aware checks, not to this loader. No function here provisions
directories, writes approvals, opens SQLite or grants an execution capability.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PureWindowsPath
from uuid import UUID

from swu_happyrun.drivers.identity import device_id

from .enrollment_authority import (
    MAX_APPROVAL_BYTES,
    ApprovalNotReady,
    ApprovedPlan,
    FrozenFile,
    RunnerAnchors,
    TargetBinding,
    _chain,
    _digest,
    _json,
    _read,
    _unique,
)
from .enrollment_storage import _filename
from .enrollment_transaction_records import TransactionLayout
from .instance_attribution import FileIdentity, _machine

_TARGETS = frozenset(
    {"host", "manager", "config", "config_previous", "journal", "receipt", "device_lock"}
)
_DIRECTORIES = frozenset({"admissions", "transactions", "transaction", "evidence"})
_STATIC = frozenset({"host", "manager", "config", "config_previous"})
_FIELDS = frozenset(
    {
        "schema",
        "epoch",
        "kind",
        "expires_at",
        "reviewed_scope_sha256",
        "manager_version",
        "host_namespace",
        "stable_instance",
        "device_id",
        "instance_index",
        "targets",
        "transaction_id",
        "product_commit",
        "product_tree",
        "directories",
    }
)


def _require(condition):
    if not condition:
        raise ApprovalNotReady()


def _keys(value, expected):
    _require(type(value) is dict and set(value) == expected)


def _reserved_component(part):
    # Python 3.13 deprecates PurePath.is_reserved; do not produce millions of
    # warnings while repeatedly revalidating a pinned Windows transaction.
    checker = getattr(os.path, "isreserved", None)
    if checker is not None:
        return checker(part)
    return PureWindowsPath(part).is_reserved()


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
    # Windows aliases, streams and noncanonical trailing-dot/space names are not
    # valid private transaction paths. On POSIX these are literal characters.
    if os.name == "nt":
        for part in path.parts[1:]:
            _require(
                not part.endswith((".", " "))
                and not any(character in part for character in '<>:"|?*')
                and not _reserved_component(part)
            )
    return path


def _identity(value):
    _require(type(value) is list and len(value) == 2)
    _require(type(value[0]) is int and value[0] >= 0)
    _require(type(value[1]) is int and value[1] > 0)
    return FileIdentity("python_stat", *value)


def _uuid(value):
    _require(type(value) is str and len(value) == 36 and str(UUID(value)) == value)
    return value


def _git_object(value):
    _require(type(value) is str and re.fullmatch("[0-9a-f]{40}", value) is not None)
    return value


def _key(path):
    return os.path.normcase(str(path))


def _within(path, directory):
    return _key(path) == _key(directory) or _key(directory) in {
        _key(parent) for parent in path.parents
    }


@dataclass(frozen=True, repr=False)
class ApprovedTransactionPlan(ApprovedPlan):
    """Frozen reviewed facts, never proof of authority or mutable-stage ownership."""

    transaction_id: str
    product_commit: str
    product_tree: str
    directories: tuple[tuple[str, Path, FileIdentity], ...]

    @property
    def evidence_root(self) -> Path:
        return next(path for name, path, _ in self.directories if name == "evidence")

    @property
    def evidence_identity(self) -> FileIdentity:
        return next(identity for name, _, identity in self.directories if name == "evidence")


def _target(name, value, kind):
    _keys(value, {"path", "parent_identity", "identity", "sha256"})
    path, parent = _path(value["path"]), _identity(value["parent_identity"])
    absent = name == "receipt" or (kind == "new_enrollment" and name in {"journal", "device_lock"})
    if absent:
        _require(value["identity"] is None and value["sha256"] is None)
        return TargetBinding(name, path, parent, None, None)
    identity = _identity(value["identity"])
    if name == "journal":
        _require(value["sha256"] is None)
    else:
        _digest(value["sha256"])
    return TargetBinding(name, path, parent, identity, value["sha256"])


def _topology(root, plan):
    """Only lexical comparisons: never resolve, stat or inspect a target parent."""
    targets = {item.name: item for item in plan.targets}
    directories = {name: path for name, path, _ in plan.directories}
    expected = {
        "admissions": root / "admissions",
        "transactions": root / "transactions",
        "transaction": root / "transactions" / plan.transaction_id,
    }
    _require(all(directories[name] == path for name, path in expected.items()))
    _require(len({_key(path) for path in directories.values()}) == len(directories))
    config, previous = targets["config"].path, targets["config_previous"].path
    journal, receipt = targets["journal"].path, targets["receipt"].path
    _require(config.suffix == ".nemu" and previous == config.with_suffix(".nemu-prev"))
    _require(journal.suffix.lower() in {".db", ".sqlite", ".sqlite3"})
    _require(receipt == targets["host"].path.with_name("mumu-experiment-registration.json"))
    layout = TransactionLayout(
        root, plan.plan_sha256, plan.transaction_id, journal, receipt, plan.device_id
    )
    _require(targets["device_lock"].path == layout.path("device_lock"))
    _require(len({_key(item.path) for item in plan.targets}) == len(plan.targets))

    # Control-root ownership is not reusable as a target destination. This also
    # excludes a supplied target at an ancestor of a required control directory.
    for target in plan.targets:
        _require(not _within(target.path, root) and not _within(root, target.path))

    writes = {layout.path(role) for role in layout.roles}
    writes.update(layout.record_path(i) for i in range(1, len(layout.roles) + 1))
    _require(len({_key(path) for path in writes}) == len(layout.roles) * 2)
    publications = writes.copy()
    if plan.kind == "existing":
        publications -= {journal, targets["device_lock"].path}
    for path in publications:
        _filename(path.name)
    stage_paths = {
        path.with_name(f".{path.name}.{plan.transaction_id}.staged") for path in publications
    }
    # Verify derived names are bounded too, before any storage backend sees them.
    for path in writes | stage_paths:
        _path(str(path))
        _require(len(path.name) <= 255)
    controls = writes | stage_paths | {root / "admission.lock", root / "authority-v1.json"}
    static = [targets[name].path for name in _STATIC]
    _require(not {_key(path) for path in static} & {_key(path) for path in controls})
    _require(not {_key(path) for path in writes} & {_key(path) for path in stage_paths})
    for target in plan.targets:
        _require(
            all(
                _key(target.path) == _key(write)
                or not _within(target.path, write)
                and not _within(write, target.path)
                for write in writes
            )
        )
    for directory in directories.values():
        _require(all(not _within(directory, path) for path in controls))
    evidence = directories["evidence"]
    _require(
        not _within(evidence, root / "admissions")
        and not _within(evidence, root / "transactions")
        and not _within(evidence, root / "reviews")
        and not _within(root, evidence)
    )
    # A single lexical parent cannot simultaneously have two approved identities.
    parent_ids = {}
    for path, identity in (
        *((item.path.parent, item.parent_identity) for item in plan.targets),
        *((path, identity) for _, path, identity in plan.directories),
    ):
        key = _key(path)
        _require(key not in parent_ids or parent_ids[key] == identity)
        parent_ids[key] = identity


def parse_plan_payload(root: Path, raw: bytes) -> ApprovedTransactionPlan:
    """Pure strict preflight; the exact supplied bytes determine the plan digest.

    This does not establish current authority, expiry, filesystem identities,
    target absence, ACLs, NTFS or reviewed-scope completeness.
    """
    try:
        _require(type(root) is type(Path()) and _path(str(root)) == root)
        _require(type(raw) is bytes and 1 <= len(raw) <= MAX_APPROVAL_BYTES)
        value = json.loads(
            raw,
            object_pairs_hook=_unique,
            parse_constant=lambda _: (_ for _ in ()).throw(ApprovalNotReady()),
        )
        _keys(value, _FIELDS)
        expiry = value["expires_at"]
        _require(
            value["schema"] == "approved-plan-v2"
            and type(value["epoch"]) is int
            and value["epoch"] >= 1
            and type(value["kind"]) is str
            and value["kind"] in {"new_enrollment", "existing"}
            and type(expiry) in (int, float)
            and math.isfinite(expiry)
            and type(value["instance_index"]) is str
            and re.fullmatch("0|[1-9][0-9]{0,3}", value["instance_index"]) is not None
            and type(value["manager_version"]) is str
            and len(value["manager_version"]) <= 64
            and re.fullmatch(r"[0-9]+(?:\.[0-9]+){3}", value["manager_version"]) is not None
        )
        _keys(value["targets"], _TARGETS)
        targets = tuple(
            _target(name, value["targets"][name], value["kind"]) for name in sorted(_TARGETS)
        )
        _keys(value["directories"], _DIRECTORIES)
        directories = []
        for name in sorted(_DIRECTORIES):
            item = value["directories"][name]
            _keys(item, {"path", "identity"})
            directories.append((name, _path(item["path"]), _identity(item["identity"])))
        plan = ApprovedTransactionPlan(
            epoch=value["epoch"],
            kind=value["kind"],
            plan_sha256=hashlib.sha256(raw).hexdigest(),
            host_namespace=_uuid(value["host_namespace"]),
            stable_instance=_uuid(value["stable_instance"]),
            device_id=_uuid(value["device_id"]),
            instance_index=value["instance_index"],
            reviewed_scope_sha256=_digest(value["reviewed_scope_sha256"]),
            manager_version=value["manager_version"],
            expires_at=expiry,
            targets=targets,
            transaction_id=_digest(value["transaction_id"]),
            product_commit=_git_object(value["product_commit"]),
            product_tree=_git_object(value["product_tree"]),
            directories=tuple(directories),
        )
        _topology(root, plan)
        return plan
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError):
        raise ApprovalNotReady() from None


@lru_cache(maxsize=8)
def _parse_pinned_payload(root: Path, raw: bytes) -> ApprovedTransactionPlan:
    """Reuse only pure parsing of exact bytes; never cache live authorization.

    Results contain frozen dataclasses/tuples/Paths. The loader still rereads and
    pins both files, checks their ancestry, current revocation/epoch and expiry
    on every call. Frozen-input and phase validation remain fresh separately.
    """
    return parse_plan_payload(root, raw)


def load_transaction_plan(
    root: Path, anchors: RunnerAnchors, *, now: float
) -> ApprovedTransactionPlan:
    """Revalidate trusted authority and pinned bytes without opening target paths."""
    try:
        _require(type(root) is type(Path()) and _path(str(root)) == root)
        _require(type(anchors) is RunnerAnchors)
        _require(type(now) in (int, float) and math.isfinite(now))
        _require(_chain(root)[-1][1] == anchors.root_identity)
        _require(stat.S_ISDIR(root.lstat().st_mode))
        authority = _json(root / "authority-v1.json", anchors.authority)
        _keys(authority, {"schema", "epoch", "approved_plan_sha256", "revoked_plan_sha256"})
        revoked = authority["revoked_plan_sha256"]
        _require(
            authority["schema"] == "authority-v1"
            and type(authority["epoch"]) is int
            and authority["epoch"] >= 1
            and type(revoked) is list
            and len(revoked) <= 512
            and all(_digest(item) == item for item in revoked)
            and anchors.plan_sha256 not in revoked
            and authority["approved_plan_sha256"] == anchors.plan_sha256
        )
        folder = root / "reviews" / anchors.plan_sha256
        _require(_chain(folder)[-1][1] == anchors.plan_parent_identity)
        _require(stat.S_ISDIR(folder.lstat().st_mode))
        raw = _read(folder / "approved-plan-v2.json", anchors.plan)
        plan = _parse_pinned_payload(root, raw)
        _require(
            plan.plan_sha256 == anchors.plan_sha256
            and plan.epoch == authority["epoch"]
            and now < plan.expires_at
        )
        return plan
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        RecursionError,
        OverflowError,
    ):
        raise ApprovalNotReady() from None


def validate_frozen_inputs(plan: ApprovedTransactionPlan) -> None:
    """Inspect only frozen inputs under caller-held account/path protections.

    Target parents and all approved directories are checked here. Journal, lock
    and receipt identity/content/existence checks remain phase-specific, including
    the existing lock's exact one-byte contents, and belong to the coordinator.
    """
    try:
        _require(type(plan) is ApprovedTransactionPlan)
        for _, path, identity in plan.directories:
            _require(_chain(path)[-1][1] == identity and stat.S_ISDIR(path.lstat().st_mode))
        for target in plan.targets:
            parent = target.path.parent
            _require(
                _chain(parent)[-1][1] == target.parent_identity
                and stat.S_ISDIR(parent.lstat().st_mode)
            )
        targets = {item.name: item for item in plan.targets}
        contents = {}
        for name in sorted(_STATIC):
            item = targets[name]
            contents[name] = _read(
                item.path,
                FrozenFile(item.identity, item.sha256),
                128 * 1024 * 1024 if name == "manager" else 1024 * 1024,
            )
        current, previous = _machine(contents["config"]), _machine(contents["config_previous"])
        _require(
            current == previous
            and current[0] == plan.stable_instance
            and current[1] == targets["config"].path.parent.name
            and current[1].endswith("-" + plan.instance_index)
        )
        _require(len(contents["host"]) <= 128)
        namespace = contents["host"].decode("ascii").strip()
        _require(namespace == plan.host_namespace)
        # Preserve the original inspector/v1 mapping, including native Windows
        # canonical-name expansion. Only this locked validation phase may resolve
        # a target; authority loading and payload preflight never do so.
        identifier = (
            f"{os.path.normcase(str(targets['manager'].path.resolve()))}:{plan.instance_index}"
        )
        _require(device_id("mumu", identifier, host_id=namespace) == plan.device_id)
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        RecursionError,
        ET.ParseError,
    ):
        raise ApprovalNotReady() from None
