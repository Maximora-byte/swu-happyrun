"""Private, bounded static observations; never a process or execution capability.

No MuMu commands are run. XML UUID, product device ID, Android binding and
PID/creation time are separate identity domains. File identity describes the
opened file, not the image loaded into a process. Results must stay private.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

MAX_CONFIG_BYTES = 1024 * 1024
MAX_MANAGER_BYTES = 128 * 1024 * 1024
MAX_PATH_COMPONENTS = 64
MAX_INSTANCES = 128


@dataclass(frozen=True)
class FileIdentity:
    domain: str
    volume: int = field(repr=False)
    file_index: int = field(repr=False)

    def __post_init__(self):
        if (
            self.domain not in {"python_stat", "win32_legacy_ntfs"}
            or type(self.volume) is not int
            or self.volume < 0
            or type(self.file_index) is not int
            or self.file_index <= 0
        ):
            raise ValueError("file_identity_invalid")
        if self.domain == "win32_legacy_ntfs" and (
            self.volume >= 2**32 or self.file_index >= 2**64
        ):
            raise ValueError("file_identity_invalid")

    @classmethod
    def from_stat(cls, info):
        return cls("python_stat", info.st_dev, info.st_ino)


@dataclass(frozen=True)
class FileProvenance:
    path: Path = field(repr=False)
    identity: FileIdentity = field(repr=False)
    sha256: str = field(repr=False)
    size: int


@dataclass(frozen=True, repr=False)
class StaticInstance:
    stable_instance: str
    instance_index: str
    name: str
    directory: Path
    config: FileProvenance
    previous: FileProvenance
    manager: FileProvenance
    manager_version: str


@dataclass(frozen=True)
class StaticInstanceInspection:
    status: str
    code: str
    instance: StaticInstance | None = field(default=None, repr=False)


@dataclass(frozen=True)
class ProcessAttribution:
    status: str
    code: str
    # No attributed PID/Android/device identity is fabricated from static XML.


def _chain(path):
    if not path.is_absolute() or ".." in path.parts or len(path.parts) > MAX_PATH_COMPONENTS:
        raise ValueError
    if str(path).startswith(("//", "\\\\")):
        raise ValueError
    result = []
    for part in [*reversed(path.parents), path]:
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError
        if part != path and not stat.S_ISDIR(info.st_mode):
            raise ValueError
        result.append((part, FileIdentity.from_stat(info)))
    return tuple(result)


def _read(path, cap):
    chain = _chain(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or FileIdentity.from_stat(info) != chain[-1][1]:
        raise ValueError
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        identity = FileIdentity.from_stat(before)
        if identity != chain[-1][1] or not stat.S_ISREG(before.st_mode) or before.st_size > cap:
            raise ValueError
        with os.fdopen(fd, "rb", closefd=False) as source:
            raw = source.read(cap + 1)
        after = os.fstat(fd)
        if len(raw) > cap or len(raw) != before.st_size or _chain(path) != chain:
            raise ValueError
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise ValueError
        return raw, FileProvenance(path, identity, hashlib.sha256(raw).hexdigest(), len(raw))
    finally:
        os.close(fd)


def _machine(raw):
    # Reject DTD/entities before parsing, including UTF-16/32 declarations.
    # Native observed .nemu input is UTF-8; unsupported encodings fail closed.
    text = raw.decode("utf-8-sig")
    if "\x00" in text or "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError
    root = ET.fromstring(text)
    machines = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "Machine"]
    if len(machines) != 1:
        raise ValueError
    node = machines[0]
    raw_uuid, name = node.attrib.get("uuid"), node.attrib.get("name")
    if not isinstance(raw_uuid, str) or not isinstance(name, str) or not 1 <= len(name) <= 200:
        raise ValueError
    value = UUID(raw_uuid)
    if value.int == 0:
        raise ValueError
    return str(value), name


def inspect_static_instance(
    config_path, *, instance_index, manager_path, manager_version, expected=None
):
    """Inspect supplied files only; no discovery, host bootstrap or PID lookup.

    manager_version is caller-provided provenance, NOT independently detected
    by this function. A known snapshot proves only these static bytes at this
    observation; it cannot authorize registration, launch, shutdown or replay.
    """
    try:
        if not isinstance(instance_index, str) or not re.fullmatch(
            r"0|[1-9][0-9]{0,8}", instance_index
        ):
            raise ValueError
        if not isinstance(manager_version, str) or not re.fullmatch(
            r"[0-9]+(?:\.[0-9]+){3}", manager_version
        ):
            raise ValueError
        path = Path(config_path)
        if path.suffix != ".nemu":
            raise ValueError
        raw, config = _read(path, MAX_CONFIG_BYTES)
        previous_raw, previous = _read(path.with_suffix(".nemu-prev"), MAX_CONFIG_BYTES)
        _, manager = _read(Path(manager_path), MAX_MANAGER_BYTES)
        stable, name = _machine(raw)
        if _machine(previous_raw) != (stable, name) or name != path.parent.name:
            raise ValueError
        # The caller supplies index from reviewed provenance; do not infer it
        # solely from a filename. The observed directory suffix must agree.
        if not name.endswith("-" + instance_index):
            raise ValueError
        value = StaticInstance(
            stable, instance_index, name, path.parent, config, previous, manager, manager_version
        )
        if expected is not None and (
            not isinstance(expected, StaticInstance)
            or compare_static_instances([value], previous=[expected]).status != "known"
        ):
            raise ValueError
        return StaticInstanceInspection("known", "static_observation_only", value)
    except (OSError, ValueError, TypeError, UnicodeError, ET.ParseError, OverflowError):
        return StaticInstanceInspection("unknown", "static_identity_unavailable")


def compare_static_instances(instances, *, previous=()):
    """Reject ambiguous/changed static mappings; never migrate a device ID."""
    try:
        if not isinstance(instances, (tuple, list)) or not 1 <= len(instances) <= MAX_INSTANCES:
            raise ValueError
        if not isinstance(previous, (tuple, list)) or len(previous) > MAX_INSTANCES:
            raise ValueError
        seen_uuid, seen_index, seen_path = set(), set(), set()
        for item in instances:
            if not isinstance(item, StaticInstance):
                raise ValueError
            key = (item.manager.identity, item.instance_index)
            if (
                item.stable_instance in seen_uuid
                or key in seen_index
                or item.config.identity in seen_path
            ):
                raise ValueError
            seen_uuid.add(item.stable_instance)
            seen_index.add(key)
            seen_path.add(item.config.identity)
            for old in previous:
                if not isinstance(old, StaticInstance):
                    raise ValueError
                same_slot = old.instance_index == item.instance_index
                same_uuid = old.stable_instance == item.stable_instance
                if same_slot or same_uuid:
                    if (
                        not same_slot
                        or not same_uuid
                        or old.directory != item.directory
                        or old.manager != item.manager
                        or old.name != item.name
                        or old.config != item.config
                        or old.previous != item.previous
                        or old.manager_version != item.manager_version
                    ):
                        raise ValueError
        return StaticInstanceInspection("known", "static_observation_only")
    except (ValueError, TypeError, AttributeError):
        return StaticInstanceInspection("unknown", "static_mapping_conflict")


def attribute_processes(static, snapshot, *, previous=None):
    """No observed configuration→PID bridge exists in helper IPC v1.

    Even complete enumeration and a matching image name/path cannot establish
    ownership. An absent PID is not exit evidence; reused PIDs are conflicts.
    This function performs no OS query and grants no shutdown permission.
    """
    if not isinstance(static, StaticInstanceInspection) or static.status != "known":
        return ProcessAttribution("unknown", "static_identity_unavailable")
    try:
        current = {}
        for fact in snapshot.processes:
            if fact.pid in current:
                return ProcessAttribution("conflict", "duplicate_pid")
            current[fact.pid] = fact.creation_time_100ns
        if previous is not None:
            for old in previous.processes:
                now = current.get(old.pid)
                if now is not None and old.creation_time_100ns is not None:
                    if now != old.creation_time_100ns:
                        return ProcessAttribution("conflict", "pid_reused")
    except (AttributeError, TypeError):
        return ProcessAttribution("unknown", "process_facts_unavailable")
    return ProcessAttribution("unknown", "configuration_process_link_unavailable")
