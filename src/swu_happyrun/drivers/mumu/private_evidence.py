"""Fail-closed private, bounded evidence for the isolated experiment only.

Windows uses native protected-DACL verification, not POSIX chmod. Native Windows
acceptance remains separate from synthetic tests. The
caller provisions the directory; this module never creates it or changes permissions.
An interrupted exclusive write is never removed: its presence prohibits a repeat.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from . import windows_private

_PLATFORM = os.name
MAX_EVIDENCE_BYTES = 3 * 1024 * 1024
_EVIDENCE_NAMES = frozenset(
    {
        "command.stdout.bin",
        "command.stderr.bin",
        "command.json",
        "observation.json",
        "shutdown.json",
        "report.json",
    }
)
_ACTIONS = frozenset({"launch", "location", "shutdown"})


class PrivateEvidenceError(RuntimeError):
    """Only fixed reason codes, never paths, output bytes or exception reprs."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class PrivateEvidenceStore:
    """Exclusive local evidence, not an instance lock or journal replacement.

    Ancestors must be owned by the current user or root and not writable by others;
    root-owned sticky directories (such as /tmp) are allowed. Every component is
    opened relative to its validated parent with O_NOFOLLOW. The final directory
    must belong to the current user and have exactly mode 0700. Same-user/root
    tampering and storage hardware that lies about fsync are outside this boundary.
    """

    def __init__(self, root: Path):
        # Do not resolve: resolving would silently accept symlink ancestors.
        if ".." in root.parts:
            raise PrivateEvidenceError("private_directory_invalid")
        self.root = Path(os.path.abspath(root))
        if _PLATFORM == "nt":
            try:
                self._identity = windows_private.verify_directory(self.root)
                return
            except windows_private.WindowsPrivacyError as error:
                raise PrivateEvidenceError(str(error)) from None
        if _PLATFORM != "posix":
            raise PrivateEvidenceError("private_acl_unverified")
        fd = self._open_directory()
        try:
            info = os.fstat(fd)
            self._identity = (info.st_dev, info.st_ino)
        except OSError:
            raise PrivateEvidenceError("private_directory_invalid") from None
        finally:
            _close(fd)

    def _open_directory(self) -> int:
        fd: int | None = None
        try:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
            fd = os.open(self.root.anchor, flags)
            components = self.root.parts[1:]
            for component in components:
                parent = os.fstat(fd)
                sticky_root = parent.st_uid == 0 and bool(parent.st_mode & stat.S_ISVTX)
                if parent.st_uid not in {0, os.geteuid()} or (
                    parent.st_mode & 0o022 and not sticky_root
                ):
                    raise PrivateEvidenceError("private_ancestor_unsafe")
                child = os.open(component, flags, dir_fd=fd)
                old_fd, fd = fd, child
                _close(old_fd)
            info = os.fstat(fd)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise PrivateEvidenceError("private_permissions_invalid")
            identity = getattr(self, "_identity", None)
            if identity is not None and identity != (info.st_dev, info.st_ino):
                raise PrivateEvidenceError("private_directory_changed")
            result, fd = fd, None
            return result
        except OSError:
            raise PrivateEvidenceError("private_directory_invalid") from None
        finally:
            if fd is not None:
                _close(fd)

    def put_once(self, name: str, data: bytes) -> None:
        """Store one fixed evidence artifact, never overwrite or retry."""
        if not isinstance(name, str) or name not in _EVIDENCE_NAMES:
            raise PrivateEvidenceError("evidence_name_invalid")
        if not isinstance(data, bytes) or len(data) > MAX_EVIDENCE_BYTES:
            raise PrivateEvidenceError("evidence_size_invalid")
        self._write_once(name, data, "evidence_exists")

    def claim_intent(self, action: str) -> None:
        """Persist an irreversible attempt marker before the caller acts."""
        if not isinstance(action, str) or action not in _ACTIONS:
            raise PrivateEvidenceError("intent_action_invalid")
        self._write_once(action + ".intent", b"attempt_reserved_v1\n", "intent_exists")

    def _write_once(self, name: str, data: bytes, exists_code: str) -> None:
        if _PLATFORM == "nt":
            self._write_windows_once(name, data, exists_code)
            return
        directory = self._open_directory()
        fd: int | None = None
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
            try:
                fd = os.open(name, flags, 0o600, dir_fd=directory)
            except FileExistsError:
                raise PrivateEvidenceError(exists_code) from None
            # Unbuffered writes need no userspace flush; fsync commits bytes before
            # the parent entry is synced. Short writes never become silent success.
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("short_write")
                view = view[written:]
            os.fsync(fd)
            completed_fd, fd = fd, None
            _close(completed_fd)
            os.fsync(directory)
        except OSError:
            raise PrivateEvidenceError("private_write_failed") from None
        finally:
            if fd is not None:
                _close(fd)
            _close(directory)

    def _write_windows_once(self, name: str, data: bytes, exists_code: str) -> None:
        fd = None
        try:
            with windows_private.verified_directory(self.root, self._identity) as (api, sid, _):
                path = self.root / name
                try:
                    fd = os.open(
                        path,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
                        0o600,
                    )
                except FileExistsError:
                    raise PrivateEvidenceError(exists_code) from None
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise PrivateEvidenceError("private_file_invalid")
                # Inherit only the already-verified protected current-user DACL.
                # Verify the resulting file ACL before writing any private bytes.
                windows_private.validate_sddl(api.security(path), sid, protected=False)
                view = memoryview(data)
                while view:
                    written = os.write(fd, view)
                    if written <= 0:
                        raise OSError("short_write")
                    view = view[written:]
                os.fsync(fd)
                completed_fd, fd = fd, None
                _close(completed_fd)
                # Windows has no portable directory-fsync equivalent. The file is
                # flushed; its permanent intent is additionally gated by journal.
        except windows_private.WindowsPrivacyError as error:
            raise PrivateEvidenceError(str(error)) from None
        except OSError:
            raise PrivateEvidenceError("private_write_failed") from None
        finally:
            if fd is not None:
                _close(fd)


def _close(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        raise PrivateEvidenceError("private_close_failed") from None
