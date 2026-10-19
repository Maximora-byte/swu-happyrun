"""Durable S0 jobs and agent observations, using short SQLite transactions."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from swu_happyrun.core.clock import Clock
from swu_happyrun.core.models import JobSpec, JobView
from swu_happyrun.server.errors import ApiError
from swu_happyrun.server.leases import LeaseOperations
from swu_happyrun.server.persistence import initialize


class SqliteJobStore(LeaseOperations):
    def __init__(self, path: Path, clock: Clock):
        self.path = Path(path)
        self.clock = clock
        with self.connection(write=True) as db:
            initialize(db)

    @contextmanager
    def connection(self, *, write: bool = False):
        db = None
        try:
            # Bound each SQLite lock wait below the clients' 5s HTTP timeout.
            # This is not a deadline for the entire request or transaction.
            db = sqlite3.connect(self.path, timeout=1.0, isolation_level=None)
            db.row_factory = sqlite3.Row
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
            view = self._insert_job(db, spec)
            db.execute(
                "INSERT INTO job_requests VALUES (?, ?, ?)", (idempotency_key, request, view.job_id)
            )
            return view, True

    def _insert_job(self, db, spec):
        view = JobView(
            job_id=str(uuid4()),
            run_session_id=None,
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
        db.execute("INSERT INTO runtime(job_id) VALUES (?)", (view.job_id,))
        return view

    def list_jobs(self, limit: int, before: str | None = None) -> tuple[list[JobView], str | None]:
        self.expire()
        with self.connection() as db:
            # Keep cursor lookup and page read in one snapshot under concurrent inserts.
            db.execute("BEGIN")
            parameters = []
            where = ""
            if before is not None:
                cursor = db.execute(
                    "SELECT created_at, job_id FROM jobs WHERE job_id = ?", (before,)
                ).fetchone()
                if cursor is None:
                    raise ApiError(422, "invalid_cursor", "Unknown pagination cursor")
                where = "WHERE (created_at, job_id) < (?, ?) "
                parameters.extend(cursor)
            rows = db.execute(
                "SELECT view_json FROM jobs "
                + where
                + "ORDER BY created_at DESC, job_id DESC LIMIT ?",
                (*parameters, limit + 1),
            ).fetchall()
            items = [JobView.model_validate_json(row[0]) for row in rows[:limit]]
            return items, items[-1].job_id if len(rows) > limit else None

    def get(self, job_id: str) -> JobView | None:
        self.expire()
        with self.connection() as db:
            row = db.execute("SELECT view_json FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            return JobView.model_validate_json(row[0]) if row else None
