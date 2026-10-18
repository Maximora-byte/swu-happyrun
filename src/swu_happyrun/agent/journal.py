"""Durable, token-free intent journal and process-scoped device exclusion."""

import hashlib
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


class UnsafeReplay(RuntimeError):
    """An action may already have happened, or a device is already owned."""


class RunJournal:
    def __init__(self, path: Path):
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
        # Same private journal directory must be used by all agents for a host.
        name = hashlib.sha256(device_id.encode()).hexdigest()
        lock_path = self.path.parent / f"device-{name}.lock"
        with lock_path.open("a+b") as handle:
            handle.seek(0)
            if not handle.read(1):
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
                yield
            finally:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
