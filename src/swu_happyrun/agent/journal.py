"""Durable, token-free intent journal and process-scoped device exclusion."""

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4


class UnsafeReplay(RuntimeError):
    """An action may already have happened, or a device is already owned."""


class RunJournal:
    def __init__(self, path: Path):
        self._device_owners = {}
        self._replay_reservations = {}
        self.path = Path(path)
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

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self._db.close()

    def has_intent(self, job_id: str, action: str) -> bool:
        return (
            self._db.execute(
                "SELECT 1 FROM intents WHERE job_id=? AND action=?", (job_id, action)
            ).fetchone()
            is not None
        )

    def record_intent(self, job_id: str, fence: int, action: str) -> None:
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
        with lock_path.open("a+b") as handle:
            # Windows byte locks also prohibit reads; inspect metadata only.
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
