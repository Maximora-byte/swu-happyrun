"""Read-only, pinned original-machine receipt, never registration/bootstrap.

A reviewed adapter must supply the receipt digest AND file identity from independent
original-machine evidence. A receipt's own claims are not proof of provenance or
MuMu ownership. No adapter or receipt writer is installed by this module.
"""

import hashlib
import json
import os
import re
import stat
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from swu_happyrun.agent.journal import RunJournal, UnsafeReplay
from swu_happyrun.drivers.identity import _namespace_path, device_id
from swu_happyrun.drivers.mumu.evidence_experiment import Registration

MAX_RECEIPT_BYTES = 8192


class RegistrationNotReady(RuntimeError):
    def __init__(self):
        super().__init__("original_registration_not_ready")


def _identity(info):
    return info.st_dev, info.st_ino


def _path(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 1024:
        raise ValueError
    path = Path(value)
    if (
        not path.is_absolute()
        or ".." in path.parts
        or str(path) != value
        or value.startswith(("\\\\", "//"))
    ):
        raise ValueError
    return path


def _file_id(value):
    if (
        type(value) not in (list, tuple)
        or len(value) != 2
        or any(type(item) is not int or item < 0 for item in value)
        or value[1] == 0
    ):
        raise ValueError
    return tuple(value)


def _chain(path):
    result = []
    for part in [*reversed(path.parents), path]:
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError
        if part != path and not stat.S_ISDIR(info.st_mode):
            raise ValueError
        result.append((part, _identity(info)))
    return tuple(result)


def _existing(path, expected, *, directory=False):
    chain = _chain(path)
    info = path.lstat()
    if _identity(info) != _file_id(expected):
        raise ValueError
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise ValueError
    return chain


def _read(path, expected, cap):
    before = _existing(path, expected)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if _identity(info) != expected or not stat.S_ISREG(info.st_mode) or info.st_size > cap:
            raise ValueError
        with os.fdopen(fd, "rb", closefd=False) as stream:
            result = stream.read(cap + 1)
        if len(result) > cap or _existing(path, expected) != before:
            raise ValueError
        final = os.fstat(fd)
        if (info.st_size, info.st_mtime_ns) != (final.st_size, final.st_mtime_ns):
            raise ValueError
        return result
    finally:
        os.close(fd)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


@dataclass(frozen=True, repr=False)
class OriginalRegistration(Registration):
    """Private validated snapshot. Revalidate under the original shared lock."""

    _receipt_sha256: str = field(repr=False)
    _receipt_identity: tuple[int, int] = field(repr=False)
    _paths: tuple = field(repr=False)
    _source: Path = field(repr=False)

    def revalidate(self):
        current = load_original_registration(
            receipt_sha256=self._receipt_sha256, receipt_identity=self._receipt_identity
        )
        if current != self:
            raise RegistrationNotReady()


def load_original_registration(*, receipt_sha256: str, receipt_identity: tuple[int, int]):
    """Read fixed sibling receipt using independently reviewed private anchors.

    Existing identity._namespace_path is authoritative, including its original
    environment override. Never call load_host_id: it creates missing identities.
    No CLI device/journal/path overrides and no writer/migration are provided.
    """
    try:
        if not isinstance(receipt_sha256, str) or not re.fullmatch("[0-9a-f]{64}", receipt_sha256):
            raise ValueError
        receipt_identity = _file_id(receipt_identity)
        host = _path(str(_namespace_path()))
        source = host.with_name("mumu-experiment-registration.json")
        raw = _read(source, receipt_identity, MAX_RECEIPT_BYTES)
        if hashlib.sha256(raw).hexdigest() != receipt_sha256:
            raise ValueError
        value = json.loads(raw, object_pairs_hook=_unique)
        if (
            type(value) is not dict
            or set(value)
            != {
                "schema",
                "stable_instance",
                "instance_index",
                "host_id",
                "device_id",
                "host_file",
                "manager_file",
                "journal_file",
                "journal_directory_identity",
                "lock_identity",
                "evidence_root",
            }
            or type(value["schema"]) is not int
            or value["schema"] != 1
        ):
            raise ValueError
        for key in ("stable_instance", "host_id", "device_id"):
            if not isinstance(value[key], str) or str(UUID(value[key])) != value[key]:
                raise ValueError
        index = value["instance_index"]
        if not isinstance(index, str) or not re.fullmatch("0|[1-9][0-9]{0,8}", index):
            raise ValueError
        paths = [(source, receipt_identity)]
        for key in ("host_file", "manager_file", "journal_file"):
            entry = value[key]
            if type(entry) is not dict or set(entry) != {"path", "identity"}:
                raise ValueError
            path, file_id = _path(entry["path"]), _file_id(entry["identity"])
            _existing(path, file_id)
            paths.append((path, file_id))
        _, host_entry, manager, journal = paths
        if host_entry[0] != host:
            raise ValueError
        host_value = _read(*host_entry, 128).decode("ascii").strip()
        if host_value != value["host_id"]:
            raise ValueError
        # This is the actual MuMuManager.capability identity contract, not vendor UUID.
        identifier = f"{os.path.normcase(str(manager[0].resolve()))}:{index}"
        if device_id("mumu", identifier, host_id=host_value) != value["device_id"]:
            raise ValueError
        directory_id = _file_id(value["journal_directory_identity"])
        _existing(journal[0].parent, directory_id, directory=True)
        lock = journal[0].parent / (
            "device-" + hashlib.sha256(value["device_id"].encode()).hexdigest() + ".lock"
        )
        lock_id = _file_id(value["lock_identity"])
        _existing(lock, lock_id)
        if lock.stat().st_size != 1:
            raise ValueError
        paths.append((lock, lock_id))
        evidence = _path(value["evidence_root"])
        _chain(evidence)
        # Store full ancestor identities as well as original files. Revalidation
        # detects same-file relocation, ancestor substitution and changed resolver.
        snapshot = tuple((path, file_id, _chain(path)) for path, file_id in paths)
        return OriginalRegistration(
            value["stable_instance"],
            value["device_id"],
            journal[0],
            evidence,
            receipt_sha256,
            receipt_identity,
            snapshot,
            source,
        )
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        raise RegistrationNotReady() from None


@contextmanager
def original_paths(registration):
    """Guard Windows ancestors against rename; check every original identity again.

    POSIX read-only evidence tests detect substitution at each boundary, not a
    claim of protection against a hostile same-user process or administrator.
    """
    handles = []
    api = None
    try:
        if not isinstance(registration, OriginalRegistration):
            raise RegistrationNotReady()
        registration.revalidate()
        if os.name == "nt":
            from swu_happyrun.drivers.mumu.windows_private import _WinAPI

            api = _WinAPI()
            parents = {p for path, _, _ in registration._paths for p in path.parents}
            for parent in sorted(parents, key=lambda p: len(p.parts)):
                handles.append(api.guard(parent))
            for path, _, _ in registration._paths:
                # FILE_READ_ATTRIBUTES, share read/write but never share delete.
                handle = api.kernel.CreateFileW(str(path), 0x80, 3, None, 3, 0x00200000, None)
                import ctypes

                if handle in (None, ctypes.c_void_p(-1).value):
                    raise RegistrationNotReady()
                handles.append(handle)
        registration.revalidate()
        yield
    except (OSError, ValueError, UnsafeReplay):
        raise RegistrationNotReady() from None
    finally:
        if api is not None:
            for handle in reversed(handles):
                api.kernel.CloseHandle(handle)


@contextmanager
def locked_original(registration):
    """Zero-mutation preflight using the ORIGINAL lock/reservation parser.

    This is inspection, not an execution permit. Future launch must retain this
    same exclusion continuously, with another recheck immediately before launch.
    """
    try:
        with original_paths(registration):
            with RunJournal(registration.journal, existing_only=True, read_only=True) as journal:
                with journal.device_lock(registration.device_id):
                    registration.revalidate()
                    yield journal
    except (OSError, ValueError, UnsafeReplay):
        raise RegistrationNotReady() from None
