"""Durable, token-free intent journal and process-scoped device exclusion."""

import hashlib
import json
import os
import sqlite3
import stat
import weakref
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4


class UnsafeReplay(RuntimeError):
    """An action may already have happened, or a device is already owned."""


class RunJournal:
    def __init__(self, path: Path, *, existing_only: bool = False, read_only: bool = False):
        self._device_owners = {}
        self._replay_reservations = {}
        self.path = Path(path)
        self._existing_only = existing_only or read_only
        self._read_only = read_only
        if read_only:
            # Inspection is deliberately lock/reservation-only: even SQLite
            # mode=ro can CREATE a WAL -shm file. Do not open SQLite at all.
            self._db = None
            try:
                with self.path.open("rb") as source:
                    header = source.read(100)
                if (
                    len(header) != 100
                    or header[:16] != b"SQLite format 3\x00"
                    or header[18:20] != b"\x01\x01"
                    or any(
                        os.path.lexists(str(self.path) + suffix)
                        for suffix in ("-wal", "-shm", "-journal")
                    )
                ):
                    raise UnsafeReplay("original_journal_unavailable")
            except OSError:
                raise UnsafeReplay("original_journal_unavailable") from None
            return
        if self._existing_only:
            # No directory, database, schema or original lock bootstrapping.
            try:
                self._db = sqlite3.connect(
                    self.path.absolute().as_uri() + "?mode=rw",
                    uri=True,
                    timeout=0,
                )
                self._db.execute("SELECT job_id, action, fence, result FROM intents LIMIT 0")
                self._db.execute("SELECT job_id, fence, revision, event_id FROM stop_acks LIMIT 0")
            except sqlite3.Error:
                if hasattr(self, "_db"):
                    self._db.close()
                raise UnsafeReplay("original_journal_unavailable") from None
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, timeout=5)
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("""CREATE TABLE IF NOT EXISTS intents (
            job_id TEXT NOT NULL, action TEXT NOT NULL, fence INTEGER NOT NULL,
            result TEXT, PRIMARY KEY(job_id, action))""")
        self._db.execute("""CREATE TABLE IF NOT EXISTS stop_acks (
            job_id TEXT NOT NULL, fence INTEGER NOT NULL, revision INTEGER NOT NULL,
            event_id TEXT NOT NULL, PRIMARY KEY(job_id, fence, revision))""")
        self._db.commit()

    @classmethod
    @contextmanager
    def lock_existing(cls, path: Path, device_id: str):
        """Hold the original device OS lock before a possible RW SQLite open.

        This is storage exclusion, NOT authority to initialize or run a device.
        The MuMu caller must hold its independent account admission lock first.
        No directory, lock, database, or reservation is created here.
        """
        token = _ExistingDeviceLock(path, device_id)
        with token.hold():
            yield token

    @classmethod
    @contextmanager
    def open_existing_locked(cls, token, *, approval_check=None):
        """Open once under a live original lock; never lock its byte twice."""
        if type(token) is not _ExistingDeviceLock or token not in _ACTIVE_ORIGINAL_LOCKS:
            raise UnsafeReplay("original_lock_required")
        if approval_check is not None:
            approval_check()
        token.validate()
        if token.opened:
            raise UnsafeReplay("original_lock_already_used")
        token.opened = True
        journal = cls(token.path, existing_only=True)
        token.journal = journal
        journal._approval_check = approval_check
        journal._preopen_token = token
        journal._device_owners[token.device_id] = token
        try:
            token.validate()
            yield journal
        finally:
            journal.close()
            journal._device_owners.clear()
            journal._replay_reservations.clear()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        if self._db is not None:
            self._db.close()

    def _require_database(self):
        approval_check = getattr(self, "_approval_check", None)
        if approval_check is not None:
            approval_check()
        token = getattr(self, "_preopen_token", None)
        if token is not None:
            token.validate(check_marker=False)
        if self._read_only:
            raise UnsafeReplay("original_lock_inspection_only")

    def has_intent(self, job_id: str, action: str) -> bool:
        self._require_database()
        return (
            self._db.execute(
                "SELECT 1 FROM intents WHERE job_id=? AND action=?", (job_id, action)
            ).fetchone()
            is not None
        )

    def record_intent(self, job_id: str, fence: int, action: str) -> None:
        self._require_database()
        if action not in {"start", "upload"} or type(fence) is not int or fence < 0:
            raise ValueError("invalid intent")
        try:
            with self._db:
                self._db.execute(
                    "INSERT INTO intents VALUES (?, ?, ?, NULL)", (job_id, action, fence)
                )
        except sqlite3.IntegrityError:
            raise UnsafeReplay("action already attempted; recovery required") from None

    def record_result(self, job_id: str, fence: int, action: str, result: str) -> None:
        self._require_database()
        if action not in {"start", "upload"} or result not in {"confirmed", "uncertain"}:
            raise ValueError("invalid action result")
        with self._db:
            changed = self._db.execute(
                "UPDATE intents SET result=? WHERE job_id=? AND action=? AND fence=?",
                (result, job_id, action, fence),
            ).rowcount
            if changed != 1:
                raise UnsafeReplay("intent or fence mismatch")

    def stop_ack_intent(self, job_id: str, fence: int, revision: int) -> str:
        self._require_database()
        with self._db:
            self._db.execute(
                "INSERT OR IGNORE INTO stop_acks VALUES (?, ?, ?, ?)",
                (job_id, fence, revision, str(uuid4())),
            )
            return self._db.execute(
                "SELECT event_id FROM stop_acks WHERE job_id=? AND fence=? AND revision=?",
                (job_id, fence, revision),
            ).fetchone()[0]

    @contextmanager
    def device_lock(self, device_id: str):
        """All producers reject a prior unresolved local playback reservation."""
        with self._device_lock(device_id, recovery=False):
            yield

    @contextmanager
    def replay_recovery_lock(self, device_id: str):
        """Internal stop-only scope; no caller-provided bypass token is accepted.

        The yielded opaque capability can only mark this exact reservation
        uncertain/stopped. It cannot verify a write or create an active intent.
        """
        with self._device_lock(device_id, recovery=True) as permit:
            yield permit

    @contextmanager
    def _device_lock(self, device_id: str, *, recovery: bool):
        # Same private journal directory must be used by all agents for a host.
        name = hashlib.sha256(device_id.encode()).hexdigest()
        lock_path = self.path.parent / f"device-{name}.lock"
        if self._existing_only:
            import stat

            info = lock_path.lstat()
            if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise UnsafeReplay("original_lock_invalid")
        with lock_path.open("r+b" if self._existing_only else "a+b") as handle:
            if self._existing_only:
                opened = os.fstat(handle.fileno())
                if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                    raise UnsafeReplay("original_lock_changed")
            # Windows byte locks also prohibit reads; inspect metadata only.
            if self._existing_only and os.fstat(handle.fileno()).st_size != 1:
                raise UnsafeReplay("original_lock_invalid")
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise UnsafeReplay("device already locked") from None
            try:
                if self._existing_only:
                    current = lock_path.lstat()
                    if (
                        (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino)
                        or not stat.S_ISREG(current.st_mode)
                        or getattr(current, "st_file_attributes", 0) & 0x400
                    ):
                        raise UnsafeReplay("original_lock_changed")
                if device_id in self._device_owners:
                    raise UnsafeReplay("device already locked")
                self._device_owners[device_id] = object()
                marker = self.read_replay_reservation(device_id)
                if recovery:
                    if marker is None or marker["status"] == "stopped":
                        raise UnsafeReplay("replay recovery not needed")
                    permit = _ReplayReservation(self, device_id, marker, recovery_only=True)
                    self._replay_reservations[device_id] = permit
                else:
                    if marker is not None and marker["status"] != "stopped":
                        raise UnsafeReplay("replay_recovery_requires_stop")
                    permit = None
                yield permit
            finally:
                self._device_owners.pop(device_id, None)
                self._replay_reservations.pop(device_id, None)
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _reservation_path(self, device_id):
        digest = hashlib.sha256(device_id.encode()).hexdigest()
        return self.path.parent / f"replay-{digest}.json"

    def read_replay_reservation(self, device_id):
        """Read strictly only after the shared device OS lock is held."""
        if device_id not in self._device_owners:
            raise UnsafeReplay("device lock required")
        path = self._reservation_path(device_id)

        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError
                result[key] = value
            return result

        try:
            # lstat also sees a dangling symlink, unlike exists().
            import stat

            try:
                metadata = path.lstat()
            except FileNotFoundError:
                return None
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 4096:
                raise ValueError
            value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
            if (
                type(value) is not dict
                or set(value)
                != {
                    "schema",
                    "owner",
                    "device_digest",
                    "session_id",
                    "status",
                    "generation",
                    "probe_pending",
                }
                or type(value["schema"]) is not int
                or value["schema"] != 1
                or value["owner"] != "local_virtual_replay"
                or value["device_digest"] != hashlib.sha256(device_id.encode()).hexdigest()
                or value["status"] not in {"active", "stopped", "uncertain"}
                or not isinstance(value["session_id"], str)
                or str(UUID(value["session_id"])) != value["session_id"]
                or type(value["generation"]) is not int
                or value["generation"] < 1
                or type(value["probe_pending"]) is not bool
                or (value["status"] == "stopped" and value["probe_pending"])
            ):
                raise ValueError
            return value
        except (OSError, ValueError, TypeError, AttributeError):
            raise UnsafeReplay("replay_journal_invalid") from None

    def reserve_replay(self, device_id, session_id, *, generation):
        if device_id not in self._device_owners or device_id in self._replay_reservations:
            raise UnsafeReplay("device reservation owner required")
        current = self.read_replay_reservation(device_id)
        if current is not None and current["status"] != "stopped":
            raise UnsafeReplay("replay_recovery_requires_stop")
        if (
            not isinstance(session_id, str)
            or str(UUID(session_id)) != session_id
            or type(generation) is not int
            or generation != 1
        ):
            raise ValueError("invalid replay reservation")
        value = {
            "schema": 1,
            "owner": "local_virtual_replay",
            "device_digest": hashlib.sha256(device_id.encode()).hexdigest(),
            "session_id": session_id,
            "status": "active",
            "generation": generation,
            "probe_pending": False,
        }
        self._write_reservation(device_id, value)
        permit = _ReplayReservation(self, device_id, value, recovery_only=False)
        self._replay_reservations[device_id] = permit
        return permit

    def _check_reservation_permit(self, permit):
        if (
            not isinstance(permit, _ReplayReservation)
            or permit.journal is not self
            or permit.device_id not in self._device_owners
            or self._replay_reservations.get(permit.device_id) is not permit
            or self.read_replay_reservation(permit.device_id) != permit.marker
        ):
            raise UnsafeReplay("device reservation owner mismatch")

    def verify_replay(self, permit, *, generation):
        self._check_reservation_permit(permit)
        if (
            permit.recovery_only
            or permit.marker["status"] != "active"
            or permit.marker["generation"] != generation
        ):
            raise UnsafeReplay("replay write forbidden")

    def update_replay(self, permit, *, generation, status, probe_pending=None):
        self._check_reservation_permit(permit)
        if probe_pending is None:
            probe_pending = permit.marker["probe_pending"]
        if (
            status not in {"active", "stopped", "uncertain"}
            or type(generation) is not int
            or generation not in {permit.marker["generation"], permit.marker["generation"] + 1}
            or type(probe_pending) is not bool
            or (permit.recovery_only and status == "active")
            or (permit.recovery_only and permit.marker["probe_pending"] and not probe_pending)
            or (status == "stopped" and probe_pending)
        ):
            raise UnsafeReplay("replay reservation transition forbidden")
        value = dict(
            permit.marker, generation=generation, status=status, probe_pending=probe_pending
        )
        self._write_reservation(permit.device_id, value)
        permit.marker = value

    def _write_reservation(self, device_id, value):
        self._require_database()
        if self._read_only:
            raise UnsafeReplay("original_journal_read_only")
        path = self._reservation_path(device_id)
        temporary = path.with_suffix(".tmp-" + str(uuid4()))
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                json.dump(value, handle, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            if os.name != "nt":
                descriptor = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        finally:
            temporary.unlink(missing_ok=True)


class _ReplayReservation:
    """Process-local identity capability; serialized strings cannot stand in for it."""

    def __init__(self, journal, device_id, marker, *, recovery_only):
        self.journal = journal
        self.device_id = device_id
        self.marker = marker
        self.recovery_only = recovery_only


_ACTIVE_ORIGINAL_LOCKS = weakref.WeakSet()


def _original_chain(path, *, directory=False):
    """Snapshot same-domain identities without resolving away a symlink."""
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise UnsafeReplay("original_path_invalid")
    result = []
    try:
        for item in (*reversed(path.parents), path):
            info = item.lstat()
            expected = stat.S_ISDIR if item != path or directory else stat.S_ISREG
            if (
                not expected(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & 0x400
                or (item == path and not directory and info.st_nlink != 1)
            ):
                raise UnsafeReplay("original_path_invalid")
            result.append((str(item), info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)))
    except OSError:
        raise UnsafeReplay("original_path_unavailable") from None
    return tuple(result)


def _original_read(path, limit):
    chain = _original_chain(path)
    descriptor = None
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_BINARY", 0),
        )
        info = os.fstat(descriptor)
        if (info.st_dev, info.st_ino) != chain[-1][1:3] or info.st_size > limit:
            raise UnsafeReplay("original_file_invalid")
        data = os.read(descriptor, limit + 1)
        if len(data) > limit or _original_chain(path) != chain:
            raise UnsafeReplay("original_file_changed")
        return data
    except OSError:
        raise UnsafeReplay("original_file_unavailable") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


class _ExistingDeviceLock:
    """Only registered live instances can be used; never serialize this object."""

    def __init__(self, path, device_id):
        if not isinstance(device_id, str) or not device_id or len(device_id) > 256:
            raise UnsafeReplay("original_device_invalid")
        self.path = Path(path).absolute()
        self.device_id = device_id
        digest = hashlib.sha256(device_id.encode()).hexdigest()
        self.lock_path = self.path.parent / f"device-{digest}.lock"
        self.marker_path = self.path.parent / f"replay-{digest}.json"
        self.journal_chain = _original_chain(self.path)
        self.lock_chain = _original_chain(self.lock_path)
        self.fd = None
        self.opened = False
        self.journal = None

    def _marker(self):
        try:
            self.marker_path.lstat()
        except FileNotFoundError:
            return
        except OSError:
            raise UnsafeReplay("replay_journal_invalid") from None
        data = _original_read(self.marker_path, 4096)

        # Reuse the schema parser without reopening the file: the private
        # temporary inspector has no database or mutable storage privileges.
        def unique(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError
                value[key] = item
            return value

        try:
            value = json.loads(data.decode("utf-8"), object_pairs_hook=unique)
            if (
                type(value) is not dict
                or set(value)
                != {
                    "schema",
                    "owner",
                    "device_digest",
                    "session_id",
                    "status",
                    "generation",
                    "probe_pending",
                }
                or type(value["schema"]) is not int
                or value["schema"] != 1
                or value["owner"] != "local_virtual_replay"
                or value["device_digest"] != hashlib.sha256(self.device_id.encode()).hexdigest()
                or value["status"] not in {"active", "stopped", "uncertain"}
                or not isinstance(value["session_id"], str)
                or str(UUID(value["session_id"])) != value["session_id"]
                or type(value["generation"]) is not int
                or value["generation"] < 1
                or type(value["probe_pending"]) is not bool
                or (value["status"] == "stopped" and value["probe_pending"])
            ):
                raise ValueError
        except (ValueError, TypeError, KeyError, AttributeError):
            raise UnsafeReplay("replay_journal_invalid") from None
        if value["status"] != "stopped":
            raise UnsafeReplay("replay_recovery_requires_stop")

    def validate(self, *, check_marker=True):
        if self not in _ACTIVE_ORIGINAL_LOCKS or self.fd is None:
            raise UnsafeReplay("original_lock_required")
        try:
            info = os.fstat(self.fd)
            if (
                (info.st_dev, info.st_ino) != self.lock_chain[-1][1:3]
                or info.st_size != 1
                or _original_chain(self.path) != self.journal_chain
                or _original_chain(self.lock_path) != self.lock_chain
            ):
                raise UnsafeReplay("original_path_changed")
        except OSError:
            raise UnsafeReplay("original_lock_unavailable") from None
        if check_marker:
            self._marker()

    @contextmanager
    def hold(self):
        locked = False
        try:
            self.fd = os.open(
                self.lock_path,
                os.O_RDWR
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_NONBLOCK", 0)
                | getattr(os, "O_BINARY", 0),
            )
            info = os.fstat(self.fd)
            if (info.st_dev, info.st_ino) != self.lock_chain[-1][1:3] or info.st_size != 1:
                raise UnsafeReplay("original_lock_invalid")
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
            _ACTIVE_ORIGINAL_LOCKS.add(self)
            self.validate()
            yield self
        except OSError:
            raise UnsafeReplay("original_lock_unavailable") from None
        finally:
            try:
                if self.journal is not None:
                    self.journal.close()
                    self.journal._device_owners.clear()
                    self.journal._replay_reservations.clear()
            finally:
                _ACTIVE_ORIGINAL_LOCKS.discard(self)
                if self.fd is not None:
                    try:
                        if locked:
                            if os.name == "nt":
                                import msvcrt

                                os.lseek(self.fd, 0, os.SEEK_SET)
                                msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
                            else:
                                import fcntl

                                fcntl.flock(self.fd, fcntl.LOCK_UN)
                    finally:
                        os.close(self.fd)
                        self.fd = None
