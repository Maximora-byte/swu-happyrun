"""Exclusive private enrollment artifacts, not an enrollment/execution permit.

Only existing, identity-pinned Windows local-NTFS directories are accepted. The
caller supplies current authority validation under its account admission lock;
a callback or a successful write alone does not issue an execution capability.

Creation uses the existing CREATE_NEW/explicit-owner-DACL boundary. Publication
uses MoveFileExW with WRITE_THROUGH but never REPLACE_EXISTING or COPY_ALLOWED.
An error can leave the staging or final name present. No path is deleted, adopted,
repaired, or retried, including after an apparently successful OS operation whose
flush/readback failed. Power-loss behavior still requires native acceptance.

Native contracts:
https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-movefileexw
https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-flushfilebuffers
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import re
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from . import windows_private
from .enrollment_admission import _require_local_ntfs
from .enrollment_authority import FrozenFile, _chain
from .instance_attribution import FileIdentity

MAX_STORAGE_BYTES = 16 * 1024 * 1024
WRITE_CHUNK_BYTES = 64 * 1024
_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(10)),
    *(f"LPT{i}" for i in range(10)),
}


class StorageIncomplete(RuntimeError):
    """Sanitized incomplete outcome; uncertain never means safe to retry."""

    def __init__(self, phase: str, *, uncertain: bool):
        super().__init__("enrollment_storage_incomplete")
        self.phase = phase
        self.uncertain = uncertain


@dataclass(frozen=True, repr=False)
class StagedFile:
    """Observation only; publish accepts the exact object issued by this session."""

    path: Path
    destination: Path
    identity: FileIdentity
    sha256: str
    size: int

    @property
    def file(self) -> FrozenFile:
        return FrozenFile(self.identity, self.sha256)


@dataclass(frozen=True, repr=False)
class LiveStagingObservation:
    """Current owned-handle metadata, not complete bytes, a hash or authority."""

    path: Path
    identity: FileIdentity
    parent_identity: FileIdentity
    size: int
    file_type: str = "regular"


class _NativeIO:
    """Native boundaries are replaced only in tests, never by a runtime fallback."""

    def __init__(self, api, sid):
        from ctypes import wintypes

        self.api, self.sid = api, sid
        api._bind(api.kernel, "FlushFileBuffers", [wintypes.HANDLE], wintypes.BOOL)
        api._bind(
            api.kernel,
            "GetFinalPathNameByHandleW",
            [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD],
            wintypes.DWORD,
        )
        api._bind(
            api.kernel,
            "MoveFileExW",
            [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD],
            wintypes.BOOL,
        )

    def create(self, path):
        return self.api.create_private_file(path, self.sid)

    @staticmethod
    def write(fd, data):
        return os.write(fd, data)

    @staticmethod
    def fsync(fd):
        os.fsync(fd)

    def flush(self, fd):
        import msvcrt

        self.api._require(self.api.kernel.FlushFileBuffers(msvcrt.get_osfhandle(fd)))

    @staticmethod
    def close(fd):
        os.close(fd)

    def check_fd(self, fd):
        import msvcrt

        handle = msvcrt.get_osfhandle(fd)
        self.api._require(self.api.kernel.GetFileType(handle) == 1)
        windows_private.validate_sddl(self.api.security_handle(handle), self.sid, protected=True)

    def check_path(self, fd, path):
        import msvcrt

        # Query the owned handle, never reopen/stat a CREATE_NEW share=0 path.
        name = ctypes.create_unicode_buffer(32768)
        length = self.api.kernel.GetFinalPathNameByHandleW(
            msvcrt.get_osfhandle(fd), name, len(name), 0
        )
        self.api._require(0 < length < len(name))
        actual = name.value
        if actual.startswith("\\\\?\\"):
            actual = actual[4:]
        self.api._require(os.path.normcase(actual) == os.path.normcase(str(path)))

    def open_read(self, path):
        import msvcrt

        # READ_CONTROL + GENERIC_READ. No share-write or share-delete: this exact
        # object stays stable until readback finishes. Close before path rename.
        handle = self.api.kernel.CreateFileW(str(path), 0x80020000, 1, None, 3, 0x00200080, None)
        self.api._require(handle not in {None, ctypes.c_void_p(-1).value})
        try:
            self.api._require(self.api.kernel.GetFileType(handle) == 1)
            windows_private.validate_sddl(
                self.api.security_handle(handle), self.sid, protected=True
            )
            fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
            handle = None
            return fd
        finally:
            if handle is not None:
                self.api.kernel.CloseHandle(handle)

    def move(self, source, destination):
        # MOVEFILE_WRITE_THROUGH only; no replacement, cross-volume copy, reboot
        # scheduling or alternate publication route. One native attempt exactly.
        self.api._require(self.api.kernel.MoveFileExW(str(source), str(destination), 8))


def _filename(value):
    if (
        type(value) is not str
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value) is None
        or value.endswith(".")
        or value.split(".")[0].upper() in _RESERVED
    ):
        raise ValueError("invalid_storage_name")
    return value


def _regular(info, identity):
    if (
        not stat.S_ISREG(info.st_mode)
        or getattr(info, "st_file_attributes", 0) & 0x400
        or info.st_nlink != 1
        or not 0 <= info.st_size <= MAX_STORAGE_BYTES
        or FileIdentity.from_stat(info) != identity
    ):
        raise ValueError("storage_identity_changed")


def _stage_fields(staged):
    return staged.path, staged.destination, staged.identity, staged.sha256, staged.size


def _signature(info):
    return info.st_size, info.st_mtime_ns, info.st_ctime_ns


class _PrivateStorage:
    def __init__(self, parent, identity, api, sid, validate_current):
        self._parent = parent
        self._identity = identity
        self._chain = _chain(parent)
        self._api, self._sid = api, sid
        self._validate_current = validate_current
        self._io = _NativeIO(api, sid)
        self._live = True
        self._live_stage: tuple[int, Path, FileIdentity] | None = None
        self._issued: dict[int, tuple[StagedFile, tuple]] = {}
        self._attempted: set[str] = set()
        self._phase = "guard"
        self._uncertain = False
        self._before()

    def _before(self):
        if not self._live:
            raise StorageIncomplete("closed", uncertain=self._uncertain)
        self._validate_current()
        self._check_parent()

    def _check_parent(self):
        if (
            self._api.current_sid() != self._sid
            or _chain(self._parent) != self._chain
            or self._chain[-1][1] != self._identity
        ):
            raise ValueError("storage_parent_changed")
        windows_private.validate_sddl(self._api.security(self._parent), self._sid, protected=True)

    @property
    def live_staging_observations(self) -> tuple[LiveStagingObservation, ...]:
        """Observe only this session's currently open exclusive staging handle.

        Callable from validate_current without recursion. Metadata is collected
        anew from the owned fd; the handle name is checked without path reopen.
        Published/closed stages are deliberately absent, never inferred complete.
        """
        try:
            if not self._live:
                raise StorageIncomplete("closed", uncertain=self._uncertain)
            self._check_parent()
            if self._live_stage is None:
                return ()
            fd, path, identity = self._live_stage
            before = os.fstat(fd)
            _regular(before, identity)
            self._io.check_fd(fd)
            self._io.check_path(fd, path)
            after = os.fstat(fd)
            _regular(after, identity)
            if _signature(before) != _signature(after):
                raise ValueError("storage_observation_changed")
            return (LiveStagingObservation(path, identity, self._identity, after.st_size),)
        except Exception:
            raise self._fail() from None

    def _mutation(self, phase, action, *, fd=None, identity=None):
        self._phase = phase
        self._before()
        if fd is not None:
            self._io.check_fd(fd)
            _regular(os.fstat(fd), identity)
            if self._live_stage is not None:
                self._io.check_path(fd, self._live_stage[1])
        self._uncertain = True
        return action()

    def _readback(self, path, pin, size):
        self._phase = "readback"
        before = _chain(path)
        if before[-1][1] != pin.identity:
            raise ValueError("storage_identity_changed")
        fd = self._io.open_read(path)
        try:
            self._io.check_fd(fd)
            opened = os.fstat(fd)
            _regular(opened, pin.identity)
            digest, count = hashlib.sha256(), 0
            while count <= MAX_STORAGE_BYTES:
                chunk = os.read(fd, min(WRITE_CHUNK_BYTES, MAX_STORAGE_BYTES + 1 - count))
                if not chunk:
                    break
                count += len(chunk)
                digest.update(chunk)
            after = os.fstat(fd)
            self._io.check_fd(fd)
            _regular(after, pin.identity)
            if (
                count != size
                or digest.hexdigest() != pin.sha256
                or _signature(opened) != _signature(after)
                or _chain(path) != before
            ):
                raise ValueError("storage_readback_changed")
        finally:
            self._io.close(fd)

    def _fail(self):
        self._live = False
        self._issued.clear()
        self._live_stage = None
        return StorageIncomplete(self._phase, uncertain=self._uncertain)

    def stage(self, destination_name: str, payload: bytes, *, transaction_id: str) -> StagedFile:
        """Create one deterministic stage; a failed attempt cannot be resumed."""
        fd = None
        try:
            if not self._live:
                raise StorageIncomplete("closed", uncertain=self._uncertain)
            self._phase = "validate"
            name = _filename(destination_name)
            if (
                type(payload) is not bytes
                or len(payload) > MAX_STORAGE_BYTES
                or type(transaction_id) is not str
                or re.fullmatch("[0-9a-f]{64}", transaction_id) is None
                or name.casefold() in self._attempted
            ):
                raise ValueError("storage_input_invalid")
            self._attempted.add(name.casefold())
            self._before()
            path = self._parent / f".{name}.{transaction_id}.staged"
            destination = self._parent / name
            if os.path.lexists(destination):
                raise ValueError("storage_destination_exists")
            fd = self._mutation("create", lambda: self._io.create(path))
            opened = os.fstat(fd)
            identity = FileIdentity.from_stat(opened)
            _regular(opened, identity)
            if opened.st_size != 0:
                raise ValueError("storage_new_file_invalid")
            self._io.check_fd(fd)
            self._io.check_path(fd, path)
            self._live_stage = (fd, path, identity)
            offset = 0
            while offset < len(payload):
                chunk = payload[offset : offset + WRITE_CHUNK_BYTES]
                written = self._mutation(
                    "write", lambda chunk=chunk: self._io.write(fd, chunk), fd=fd, identity=identity
                )
                if type(written) is not int or not 0 < written <= len(chunk):
                    raise ValueError("storage_write_incomplete")
                offset += written
            self._mutation("fsync", lambda: self._io.fsync(fd), fd=fd, identity=identity)
            self._mutation("flush", lambda: self._io.flush(fd), fd=fd, identity=identity)
            self._phase = "close"
            self._live_stage = None
            closing, fd = fd, None  # No retry of a close with uncertain ownership.
            self._io.close(closing)
            staged = StagedFile(
                path, destination, identity, hashlib.sha256(payload).hexdigest(), len(payload)
            )
            self._readback(path, staged.file, staged.size)
            self._issued[id(staged)] = (staged, _stage_fields(staged))
            return staged
        except BaseException as error:
            incomplete = self._fail()
            if isinstance(error, Exception):
                raise incomplete from None
            raise
        finally:
            self._live_stage = None
            if fd is not None:
                try:
                    self._io.close(fd)
                except Exception:
                    self._live = False

    def publish(self, staged: StagedFile) -> FrozenFile:
        """One no-overwrite move with exact identity/hash readback; never retry."""
        try:
            if not self._live:
                raise StorageIncomplete("closed", uncertain=self._uncertain)
            self._phase = "validate"
            issued = self._issued.pop(id(staged), None)
            if (
                type(staged) is not StagedFile
                or issued is None
                or issued[0] is not staged
                or issued[1] != _stage_fields(staged)
            ):
                raise ValueError("storage_stage_not_owned")
            self._before()
            if staged.path.parent != self._parent or staged.destination.parent != self._parent:
                raise ValueError("storage_directory_changed")
            self._readback(staged.path, staged.file, staged.size)
            self._phase = "move"
            self._before()
            # Recheck after current-authority validation, immediately before the
            # only rename. Same-content object replacement is not the same file.
            if _chain(staged.path)[-1][1] != staged.identity or os.path.lexists(staged.destination):
                raise ValueError("storage_publication_changed")
            self._uncertain = True
            self._io.move(staged.path, staged.destination)
            self._phase = "readback"
            self._before()
            self._readback(staged.destination, staged.file, staged.size)
            if os.path.lexists(staged.path):
                raise ValueError("storage_source_remains")
            return staged.file
        except BaseException as error:
            incomplete = self._fail()
            if isinstance(error, Exception):
                raise incomplete from None
            raise


@contextmanager
def private_storage(
    parent: Path,
    *,
    parent_identity: FileIdentity,
    validate_current: Callable[[], object],
) -> Iterator[_PrivateStorage]:
    """Hold private existing parent/ancestor guards for the whole storage session.

    No directory is created. Pins must come from the caller's independently
    verified transaction, and validate_current must verify its still-held current
    admission authority. Never use this primitive as a standalone approval issuer.
    """
    session = None
    try:
        if (
            not isinstance(parent, Path)
            or type(parent_identity) is not FileIdentity
            or parent_identity.domain != "python_stat"
            or not callable(validate_current)
        ):
            raise ValueError("storage_guard_invalid")
        _require_local_ntfs(parent)
        identity = parent_identity.volume, parent_identity.file_index
        with windows_private.verified_directory(parent, identity) as (api, sid, _):
            session = _PrivateStorage(parent, parent_identity, api, sid, validate_current)
            yield session
    except StorageIncomplete:
        raise
    except Exception:
        raise StorageIncomplete(
            "guard", uncertain=session is not None and session._uncertain
        ) from None
    finally:
        if session is not None:
            session._live = False
            session._issued.clear()
            session._live_stage = None
