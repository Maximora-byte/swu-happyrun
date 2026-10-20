"""Pinned approval input validation, not an enrollment or execution authority issuer.

RunnerAnchors must come from a separately reviewed, immutable private runner. No
CLI accepts these values. Constructing this type is NOT permission: production
entry gates remain closed. This foundation reads existing reviewer artifacts;
it neither creates a control root nor signs a plan or writes a review pin.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from swu_happyrun.drivers.identity import device_id

from .instance_attribution import FileIdentity, _machine

MAX_APPROVAL_BYTES = 64 * 1024
_TARGETS = frozenset({"host", "manager", "config", "config_previous", "journal", "receipt"})


class ApprovalNotReady(RuntimeError):
    def __init__(self):
        super().__init__("enrollment_approval_not_ready")


def _digest(value):
    if type(value) is not str or re.fullmatch("[0-9a-f]{64}", value) is None:
        raise ApprovalNotReady()
    return value


def _stat_id(path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ApprovalNotReady()
    return FileIdentity.from_stat(info)


def _chain(path):
    if not path.is_absolute() or ".." in path.parts or str(path).startswith(("\\\\", "//")):
        raise ApprovalNotReady()
    if len(path.parts) > 64:
        raise ApprovalNotReady()
    result = []
    for part in [*reversed(path.parents), path]:
        identity = _stat_id(part)
        if part != path and not stat.S_ISDIR(part.lstat().st_mode):
            raise ApprovalNotReady()
        result.append((part, identity))
    return tuple(result)


def _read(path, pin, cap=MAX_APPROVAL_BYTES):
    before = _chain(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > cap:
        raise ApprovalNotReady()
    if before[-1][1] != pin.identity:
        raise ApprovalNotReady()
    fd = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0),
    )
    try:
        opened = os.fstat(fd)
        if FileIdentity.from_stat(opened) != pin.identity or not stat.S_ISREG(opened.st_mode):
            raise ApprovalNotReady()
        with os.fdopen(fd, "rb", closefd=False) as source:
            raw = source.read(cap + 1)
        after = os.fstat(fd)
        if (
            len(raw) > cap
            or _chain(path) != before
            or (opened.st_size, opened.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
            or hashlib.sha256(raw).hexdigest() != _digest(pin.sha256)
        ):
            raise ApprovalNotReady()
        return raw
    finally:
        os.close(fd)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ApprovalNotReady()
        result[key] = value
    return result


def _json(path, pin):
    return json.loads(
        _read(path, pin),
        object_pairs_hook=_unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ApprovalNotReady()),
    )


def _identity(value):
    if type(value) is not list or len(value) != 2:
        raise ApprovalNotReady()
    return FileIdentity("python_stat", *value)


@dataclass(frozen=True, repr=False)
class FrozenFile:
    identity: FileIdentity
    sha256: str

    def __post_init__(self):
        if type(self.identity) is not FileIdentity or self.identity.domain != "python_stat":
            raise ApprovalNotReady()
        _digest(self.sha256)


@dataclass(frozen=True, repr=False)
class RunnerAnchors:
    root_identity: FileIdentity
    lock_identity: FileIdentity
    authority: FrozenFile
    plan_sha256: str
    plan: FrozenFile
    plan_parent_identity: FileIdentity

    def __post_init__(self):
        for identity in (self.root_identity, self.lock_identity, self.plan_parent_identity):
            if type(identity) is not FileIdentity or identity.domain != "python_stat":
                raise ApprovalNotReady()
        if type(self.authority) is not FrozenFile or type(self.plan) is not FrozenFile:
            raise ApprovalNotReady()
        if _digest(self.plan_sha256) != self.plan.sha256:
            raise ApprovalNotReady()


@dataclass(frozen=True, repr=False)
class TargetBinding:
    name: str
    path: Path
    parent_identity: FileIdentity
    identity: FileIdentity | None
    sha256: str | None


@dataclass(frozen=True, repr=False)
class ApprovedPlan:
    """Verified bytes at a point in time, never a reusable action permit."""

    epoch: int
    kind: str
    plan_sha256: str
    host_namespace: str
    stable_instance: str
    device_id: str
    instance_index: str
    reviewed_scope_sha256: str
    manager_version: str
    expires_at: int | float
    targets: tuple[TargetBinding, ...] = field(repr=False)
    execution_allowed: bool = field(default=False, init=False)


def _target(name, value, kind):
    if type(value) is not dict or set(value) != {"path", "parent_identity", "identity", "sha256"}:
        raise ApprovalNotReady()
    text = value["path"]
    if type(text) is not str or not 1 <= len(text) <= 1024:
        raise ApprovalNotReady()
    path = Path(text)
    if str(path) != text or not path.is_absolute() or ".." in path.parts:
        raise ApprovalNotReady()
    parent = _identity(value["parent_identity"])
    if _chain(path.parent)[-1][1] != parent:
        raise ApprovalNotReady()
    missing = name in {"journal", "receipt"} and kind == "new_enrollment"
    if missing:
        if value["identity"] is not None or value["sha256"] is not None or os.path.lexists(path):
            raise ApprovalNotReady()
        return TargetBinding(name, path, parent, None, None)
    identity = _identity(value["identity"])
    if name == "journal":
        # Mutable runtime state is identity-bound, never permanently hash-pinned.
        if value["sha256"] is not None or _chain(path)[-1][1] != identity:
            raise ApprovalNotReady()
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ApprovalNotReady()
    else:
        _read(
            path,
            FrozenFile(identity, value["sha256"]),
            128 * 1024 * 1024 if name == "manager" else 1024 * 1024,
        )
    return TargetBinding(name, path, parent, identity, value["sha256"])


def load_approved_plan(root: Path, anchors: RunnerAnchors, *, now: float) -> ApprovedPlan:
    """Read pinned inputs only; caller must hold fixed admission lock and recheck.

    This parser is intentionally callable for offline review. It does NOT verify
    ACL/NTFS or grant writes, and does not make an incomplete historical inventory
    complete. The admission context adds fixed-root, path protection and lock.
    """
    try:
        if (
            type(anchors) is not RunnerAnchors
            or type(now) not in (int, float)
            or not math.isfinite(now)
        ):
            raise ApprovalNotReady()
        if _chain(root)[-1][1] != anchors.root_identity:
            raise ApprovalNotReady()
        authority = _json(root / "authority-v1.json", anchors.authority)
        if type(authority) is not dict or set(authority) != {
            "schema",
            "epoch",
            "approved_plan_sha256",
            "revoked_plan_sha256",
        }:
            raise ApprovalNotReady()
        revoked = authority["revoked_plan_sha256"]
        if (
            authority["schema"] != "authority-v1"
            or type(authority["epoch"]) is not int
            or authority["epoch"] < 1
            or type(revoked) is not list
            or len(revoked) > 512
            or any(_digest(item) != item for item in revoked)
            or anchors.plan_sha256 in revoked
            or authority["approved_plan_sha256"] != anchors.plan_sha256
        ):
            raise ApprovalNotReady()
        folder = root / "reviews" / anchors.plan_sha256
        if _chain(folder)[-1][1] != anchors.plan_parent_identity:
            raise ApprovalNotReady()
        plan = _json(folder / "approved-plan-v1.json", anchors.plan)
        if type(plan) is not dict or set(plan) != {
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
        }:
            raise ApprovalNotReady()
        expiry = plan["expires_at"]
        if (
            plan["schema"] != "approved-plan-v1"
            or type(plan["epoch"]) is not int
            or plan["epoch"] != authority["epoch"]
            or plan["kind"] not in {"new_enrollment", "existing"}
            or type(expiry) not in (int, float)
            or not math.isfinite(expiry)
            or now >= expiry
            or type(plan["instance_index"]) is not str
            or re.fullmatch("0|[1-9][0-9]{0,3}", plan["instance_index"]) is None
        ):
            raise ApprovalNotReady()
        for name in ("host_namespace", "stable_instance", "device_id"):
            if type(plan[name]) is not str or str(UUID(plan[name])) != plan[name]:
                raise ApprovalNotReady()
        _digest(plan["reviewed_scope_sha256"])
        if (
            type(plan["manager_version"]) is not str
            or re.fullmatch(r"[0-9]+(?:\.[0-9]+){3}", plan["manager_version"]) is None
        ):
            raise ApprovalNotReady()
        if type(plan["targets"]) is not dict or set(plan["targets"]) != _TARGETS:
            raise ApprovalNotReady()
        targets = tuple(
            _target(name, plan["targets"][name], plan["kind"]) for name in sorted(_TARGETS)
        )
        by_name = {item.name: item for item in targets}
        config, previous = by_name["config"], by_name["config_previous"]
        if config.path.suffix != ".nemu" or previous.path != config.path.with_suffix(".nemu-prev"):
            raise ApprovalNotReady()
        static = _machine(
            _read(config.path, FrozenFile(config.identity, config.sha256), 1024 * 1024)
        )
        old = _machine(
            _read(previous.path, FrozenFile(previous.identity, previous.sha256), 1024 * 1024)
        )
        if (
            static != old
            or static[0] != plan["stable_instance"]
            or static[1] != config.path.parent.name
            or not static[1].endswith("-" + plan["instance_index"])
        ):
            raise ApprovalNotReady()
        host = by_name["host"]
        namespace = (
            _read(host.path, FrozenFile(host.identity, host.sha256), 128).decode("ascii").strip()
        )
        if namespace != plan["host_namespace"]:
            raise ApprovalNotReady()
        if by_name["receipt"].path != host.path.with_name("mumu-experiment-registration.json"):
            raise ApprovalNotReady()
        identifier = (
            f"{os.path.normcase(str(by_name['manager'].path.resolve()))}:{plan['instance_index']}"
        )
        if device_id("mumu", identifier, host_id=namespace) != plan["device_id"]:
            raise ApprovalNotReady()
        paths = [os.path.normcase(str(item.path)) for item in targets]
        if len(set(paths)) != len(paths):
            raise ApprovalNotReady()
        return ApprovedPlan(
            plan["epoch"],
            plan["kind"],
            anchors.plan_sha256,
            plan["host_namespace"],
            plan["stable_instance"],
            plan["device_id"],
            plan["instance_index"],
            plan["reviewed_scope_sha256"],
            plan["manager_version"],
            expiry,
            targets,
        )
    except (OSError, ValueError, TypeError, KeyError, RecursionError, ET.ParseError):
        raise ApprovalNotReady() from None
