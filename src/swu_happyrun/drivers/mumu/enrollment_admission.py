"""Existing fixed account lock and approval revalidation, without enrollment writes.

The independent review tool must provision anchors and private control objects.
This module never bootstraps missing state. A locked admission is not a native
execution capability; require_native_enrollment still rejects every candidate.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import stat
import time
from contextlib import contextmanager

from swu_happyrun.agent.journal import RunJournal

from . import windows_private
from .enrollment import resolve_control_root
from .enrollment_authority import (
    ApprovalNotReady,
    RunnerAnchors,
    _chain,
    _digest,
    _unique,
    load_approved_plan,
)
from .instance_attribution import FileIdentity


def _require_local_ntfs(root):
    if os.name != "nt":
        raise ApprovalNotReady()
    from ctypes import wintypes

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.GetVolumePathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    api.GetVolumePathNameW.restype = wintypes.BOOL
    api.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    api.GetDriveTypeW.restype = wintypes.UINT
    api.GetVolumeInformationW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPWSTR,
        wintypes.DWORD,
    ]
    api.GetVolumeInformationW.restype = wintypes.BOOL
    volume = ctypes.create_unicode_buffer(1024)
    filesystem = ctypes.create_unicode_buffer(64)
    if (
        not api.GetVolumePathNameW(str(root), volume, len(volume))
        or api.GetDriveTypeW(volume.value) != 3  # DRIVE_FIXED, no network/removable media
        or not api.GetVolumeInformationW(
            volume.value, None, 0, None, None, None, filesystem, len(filesystem)
        )
        or filesystem.value != "NTFS"
    ):
        raise ApprovalNotReady()


@contextmanager
def _protected_root(root, anchors):
    try:
        _require_local_ntfs(root)
        identity = (anchors.root_identity.volume, anchors.root_identity.file_index)
        with windows_private.verified_directory(root, identity) as (api, sid, _):
            # Freeze ancestor and reviewer directory names for the whole lock scope.
            with windows_private.verified_directory(root / "reviews"):
                with windows_private.verified_directory(root / "reviews" / anchors.plan_sha256):
                    with windows_private.verified_directory(root / "admissions"):

                        def recheck_security():
                            for path in (
                                root,
                                root / "reviews",
                                root / "reviews" / anchors.plan_sha256,
                                root / "admissions",
                                root / "admission.lock",
                                root / "authority-v1.json",
                                root / "reviews" / anchors.plan_sha256 / "approved-plan-v1.json",
                            ):
                                windows_private.validate_sddl(
                                    api.security(path), sid, protected=True
                                )

                        recheck_security()
                        yield recheck_security

    except windows_private.WindowsPrivacyError:
        raise ApprovalNotReady() from None


@contextmanager
def _protected_targets(plan):
    """Hold no-delete-sharing parent/file handles before taking account lock."""
    if os.name != "nt":
        raise ApprovalNotReady()
    api = windows_private._WinAPI()
    handles = []
    try:
        paths = [item.path for item in plan.targets]
        if plan.kind == "existing":
            journal = next(item.path for item in plan.targets if item.name == "journal")
            name = hashlib.sha256(plan.device_id.encode()).hexdigest()
            paths.append(journal.parent / f"device-{name}.lock")
        parents = {parent for path in paths for parent in path.parents}
        for parent in sorted(parents, key=lambda p: len(p.parts)):
            handles.append(api.guard(parent))
        for path in paths:
            if not os.path.lexists(path):
                continue
            _chain(path)
            handle = api.kernel.CreateFileW(str(path), 0x80, 3, None, 3, 0x00200000, None)
            if handle in (None, ctypes.c_void_p(-1).value):
                raise ApprovalNotReady()
            handles.append(handle)
        yield
    except windows_private.WindowsPrivacyError:
        raise ApprovalNotReady() from None
    finally:
        for handle in reversed(handles):
            api.kernel.CloseHandle(handle)


@contextmanager
def _existing_lock(path, expected):
    """One-byte OS lock of an existing exact object; never O_CREAT or truncate."""
    fd = None
    locked = False
    try:
        chain = _chain(path)
        info = path.lstat()
        if (
            chain[-1][1] != expected
            or not stat.S_ISREG(info.st_mode)
            or info.st_size != 1
            or info.st_nlink != 1
        ):
            raise ApprovalNotReady()
        fd = os.open(
            path,
            os.O_RDWR
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
        )
        opened = os.fstat(fd)
        if (
            FileIdentity.from_stat(opened) != expected
            or opened.st_size != 1
            or not stat.S_ISREG(opened.st_mode)
            or _chain(path) != chain
        ):
            raise ApprovalNotReady()
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        locked = True
        if _chain(path) != chain:
            raise ApprovalNotReady()
        yield fd, chain
    except OSError:
        raise ApprovalNotReady() from None
    finally:
        if fd is not None:
            if locked:
                if os.name == "nt":
                    import msvcrt

                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


def _records(root, plan):
    """Complete bounded record set; unknown, duplicate or conflicting objects reject.

    First version has one fixed schema1 receipt and one selected instance. Any
    other plan is a conflict, including a different UUID/namespace/journal root.
    This conservative capacity rule cannot be bypassed by changing the plan path.
    """
    directory = root / "admissions"
    before = _chain(directory)
    if not stat.S_ISDIR(directory.lstat().st_mode):
        raise ApprovalNotReady()
    records = []
    with os.scandir(directory) as entries:
        for entry in entries:
            if len(records) >= 1:
                raise ApprovalNotReady()
            path = directory / entry.name
            info = path.lstat()
            if (
                entry.name != plan.plan_sha256 + ".json"
                or not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_size > 8192
            ):
                raise ApprovalNotReady()
            chain = _chain(path)
            fd = os.open(
                path,
                os.O_RDONLY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_NONBLOCK", 0)
                | getattr(os, "O_BINARY", 0),
            )
            try:
                opened = os.fstat(fd)
                if FileIdentity.from_stat(opened) != chain[-1][1]:
                    raise ApprovalNotReady()
                raw = os.read(fd, 8193)
                if len(raw) > 8192 or _chain(path) != chain:
                    raise ApprovalNotReady()
            finally:
                os.close(fd)
            record = json.loads(raw, object_pairs_hook=_unique)
            expected = {
                "schema": "admission-v1",
                "plan_sha256": plan.plan_sha256,
                "host_namespace": plan.host_namespace,
                "stable_instance": plan.stable_instance,
                "device_id": plan.device_id,
                "instance_index": plan.instance_index,
                "journal": str(next(t.path for t in plan.targets if t.name == "journal")),
                "receipt": str(next(t.path for t in plan.targets if t.name == "receipt")),
            }
            if record != expected:
                raise ApprovalNotReady()
            records.append(chain[-1][1])
    if _chain(directory) != before or (plan.kind == "existing" and not records):
        raise ApprovalNotReady()
    return tuple(records)


class _AdmissionSession:
    def __init__(self, root, anchors, fd, chain, security_check):
        self._root, self._anchors, self._fd, self._chain = root, anchors, fd, chain
        self._security_check = security_check
        self._active = True
        self.plan = None
        self._records = None

    def revalidate(self):
        if not self._active:
            raise ApprovalNotReady()
        if (
            FileIdentity.from_stat(os.fstat(self._fd)) != self._anchors.lock_identity
            or _chain(self._root / "admission.lock") != self._chain
        ):
            raise ApprovalNotReady()
        self._security_check()
        current = load_approved_plan(self._root, self._anchors, now=time.time())
        records = _records(self._root, current)
        self._security_check()
        if self.plan is not None and (current != self.plan or records != self._records):
            raise ApprovalNotReady()
        self.plan, self._records = current, records
        return current

    @contextmanager
    def open_existing_journal(self):
        """Foundation ordering only, not ready-state derivation or launch permission.

        Frozen approval facts are checked again after original-device acquisition.
        Existing journal contents may change legally while its identity stays
        fixed. No recovery/init/schema migration is attempted by this interface.
        """
        plan = self.revalidate()
        if plan.kind != "existing":
            raise ApprovalNotReady()
        target = next(item for item in plan.targets if item.name == "journal")
        with RunJournal.lock_existing(target.path, plan.device_id) as device_lock:
            self.revalidate()
            with RunJournal.open_existing_locked(
                device_lock, approval_check=self.revalidate
            ) as journal:
                yield journal


@contextmanager
def locked_admission(anchors: RunnerAnchors):
    """Existing objects only, fixed root, account lock then current approval read.

    This foundation can open an existing journal under both locks, with live
    approval checks on journal access; it cannot initialize or publish enrollment
    state, launch a device, or authorize execution. A future coordinator needs
    distinct bounded cleanup authority for a run that already started. New-plan
    validation is pre-write only: publishing any target invalidates that snapshot.
    """
    session = None
    try:
        if type(anchors) is not RunnerAnchors:
            raise ApprovalNotReady()
        _digest(anchors.plan_sha256)
        root = resolve_control_root()
        with _protected_root(root, anchors) as security_check:
            observed = load_approved_plan(root, anchors, now=time.time())
            with _protected_targets(observed):
                with _existing_lock(root / "admission.lock", anchors.lock_identity) as (fd, chain):
                    session = _AdmissionSession(root, anchors, fd, chain, security_check)
                    session.revalidate()
                    yield session
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        raise ApprovalNotReady() from None
    finally:
        if session is not None:
            session._active = False
