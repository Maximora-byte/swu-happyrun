"""Durable S0 jobs and agent observations, using short SQLite transactions."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from swu_happyrun.core.clock import Clock
from swu_happyrun.core.models import AgentHello, JobSpec, JobView
from swu_happyrun.server.errors import ApiError


class SqliteJobStore:
    def __init__(self, path: Path, clock: Clock):
        self.path = Path(path)
        self.clock = clock
        with self.connection(write=True) as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValueError("Unsupported database schema version")
            db.execute(
                "CREATE TABLE IF NOT EXISTS jobs (job_id TEXT PRIMARY KEY, "
                "view_json TEXT NOT NULL, created_at TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS job_requests (idempotency_key TEXT PRIMARY KEY, "
                "request_json TEXT NOT NULL, job_id TEXT NOT NULL REFERENCES jobs(job_id))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS agents (agent_id TEXT PRIMARY KEY, "
                "hello_json TEXT NOT NULL, received_at TEXT NOT NULL)"
            )
            db.execute("PRAGMA user_version = 1")

    @contextmanager
    def connection(self, *, write: bool = False):
        db = None
        try:
            db = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
            db.execute("PRAGMA foreign_keys = ON")
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if write:
                db.commit()
        except sqlite3.OperationalError as exc:
            if db is not None:
                db.rollback()
            if getattr(exc, "sqlite_errorcode", 0) & 0xFF in {
                sqlite3.SQLITE_BUSY,
                sqlite3.SQLITE_LOCKED,
            }:
                raise ApiError(503, "database_busy", "Temporarily unavailable", True) from None
            raise ApiError(503, "storage_unavailable", "Storage unavailable", True) from None
        except BaseException:
            if db is not None:
                db.rollback()
            raise
        finally:
            if db is not None:
                db.close()

    def create(self, spec: JobSpec, idempotency_key: str) -> tuple[JobView, bool]:
        if not idempotency_key or not idempotency_key.strip() or len(idempotency_key) > 256:
            raise ApiError(422, "invalid_input", "Idempotency-Key must contain 1 to 256 characters")
        request = json.dumps(spec.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        with self.connection(write=True) as db:
            previous = db.execute(
                "SELECT request_json, view_json FROM job_requests JOIN jobs USING(job_id) "
                "WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if previous:
                if previous[0] != request:
                    raise ApiError(
                        409, "idempotency_conflict", "Key already used for another request"
                    )
                return JobView.model_validate_json(previous[1]), False
            view = JobView(
                job_id=str(uuid4()),
                spec=spec,
                state="queued",
                revision=0,
                desired_state="run",
                fence=0,
                agent_id=None,
                reason_code=None,
                resume_phase=None,
                recovery_action=None,
            )
            db.execute(
                "INSERT INTO jobs VALUES (?, ?, ?)",
                (view.job_id, view.model_dump_json(), self.clock.utcnow().isoformat()),
            )
            db.execute(
                "INSERT INTO job_requests VALUES (?, ?, ?)", (idempotency_key, request, view.job_id)
            )
            return view, True

    def get(self, job_id: str) -> JobView | None:
        with self.connection() as db:
            row = db.execute("SELECT view_json FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            return JobView.model_validate_json(row[0]) if row else None

    def observe_agent(self, hello: AgentHello) -> None:
        with self.connection(write=True) as db:
            db.execute(
                "INSERT INTO agents VALUES (?, ?, ?) ON CONFLICT(agent_id) DO UPDATE "
                "SET hello_json=excluded.hello_json, received_at=excluded.received_at",
                (hello.agent_id, hello.model_dump_json(), self.clock.utcnow().isoformat()),
            )
