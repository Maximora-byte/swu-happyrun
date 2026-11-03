"""Live fixed-pin storage context, not an independently trusted native issuer.

The opaque objects bind validation to this process, held locks and original SQL
connection. They do not authenticate Python code, the external runner or a PID.
Production execution stays closed. The separate original-scope operation can
only retain uncertainty for an already-owned reservation, never stop a device,
kill a PID, clear a reservation, acknowledge stop or create another run.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import time
import weakref
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Event, get_ident

from swu_happyrun.agent.journal import RunJournal, _original_chain, _original_read

from .enrollment import require_native_enrollment
from .enrollment_authority import ApprovalNotReady, _chain, _unique
from .enrollment_review_pin import ReviewPinAnchors, _locked_evidence
from .enrollment_runner import _load_fixed_scope
from .enrollment_transaction import MAX_JOURNAL_BYTES, _require
from .instance_attribution import FileIdentity

MAX_RUNTIME_ROWS = 4096
RETENTION_SECONDS = 2.0
MAX_ORIGINAL_SCOPE_SECONDS = 45.0
_CONTEXTS = weakref.WeakKeyDictionary()
_CLEANUPS = weakref.WeakKeyDictionary()


@dataclass(frozen=True)
class RuntimeObservation:
    status: str
    intent_count: int
    unresolved_intent_count: int
    stop_ack_intent_count: int
    execution_allowed: bool = field(default=False, init=False)


@dataclass(frozen=True)
class RetentionResult:
    status: str
    native_cleanup_allowed: bool = field(default=False, init=False)


class _Opaque:
    __slots__ = ("__weakref__",)

    def __new__(cls):
        raise TypeError("runtime_objects_are_resolver_owned")

    def __reduce_ex__(self, protocol):
        raise TypeError("runtime_objects_are_process_local")


class RuntimeContext(_Opaque):
    """Only live registry membership binds this observation to original locks.

    No raw journal, callback installer, native factory or start method is exposed.
    A successful observation is not independent approval or process ownership.
    """

    __slots__ = ()

    @property
    def sealed(self) -> bool:
        return _state(self).sealed.is_set()

    def inspect(self) -> RuntimeObservation:
        state = _state(self)
        try:
            _require(not state.sealed.is_set())
            state.session.revalidate()
            rows, acknowledgments = _sql_snapshot(state.journal)
            state.session.revalidate()
            # Neither a confirmed start/upload nor stop-ack intent proves exit.
            # Every retained start stays conservatively unresolved here.
            unresolved = sum(
                action == "start" or result != "confirmed" for _, action, _, result in rows
            )
            return RuntimeObservation(
                "unresolved" if unresolved else "observed_runtime_closed",
                len(rows),
                unresolved,
                len(acknowledgments),
            )
        except Exception:
            state.seal()
            raise ApprovalNotReady() from None

    def require_execution(self) -> None:
        # A live object, success status, supplied bool or pin is not independent
        # trust. No PID/configuration bridge exists, so do not weaken this gate.
        require_native_enrollment(self)


class OriginalScopeCleanup(_Opaque):
    """Uncertainty-retention only, NOT native shutdown/stop/release authority."""

    __slots__ = ()

    def retain_uncertain(self) -> RetentionResult:
        cleanup = _CLEANUPS.get(self)
        _require(type(self) is OriginalScopeCleanup and cleanup is not None)
        _require(cleanup.state.live and cleanup.state.owner == get_ident())
        cleanup.state.sealed.set()  # Irreversible, even if every following check fails.
        if cleanup.result is not None:
            # Historical one-attempt result, not a fresh ownership validation.
            return cleanup.result
        cleanup.deadline = min(cleanup.original_deadline, time.monotonic() + RETENTION_SECONDS)
        cleanup.result = RetentionResult("retention_unconfirmed")
        descriptor = None
        try:
            cleanup.validate()
            value = dict(cleanup.marker, status="uncertain")
            if value == cleanup.marker:
                cleanup.result = RetentionResult("uncertainty_retained")
                return cleanup.result
            raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
            _require(len(raw) <= 4096)
            descriptor = os.open(
                cleanup.path,
                os.O_RDWR
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_NONBLOCK", 0)
                | getattr(os, "O_BINARY", 0),
            )
            cleanup.validate()

            def original_descriptor():
                cleanup.validate_storage()
                info = os.fstat(descriptor)
                _require(
                    (info.st_dev, info.st_ino) == cleanup.marker_chain[-1][1:3]
                    and info.st_nlink == 1
                    and _original_chain(cleanup.path) == cleanup.marker_chain
                )

            # Never rename or publish a newly discovered staging path. A partial
            # write can leave an invalid marker, which blocks all new producers;
            # it cannot release occupancy or become proof of a stopped device.
            written = 0
            while written < len(raw):
                original_descriptor()
                count = os.write(descriptor, raw[written:])
                _require(count > 0)
                written += count
            original_descriptor()
            os.ftruncate(descriptor, len(raw))
            original_descriptor()
            os.fsync(descriptor)
            original_descriptor()
            _require(_original_read(cleanup.path, 4096) == raw)
            cleanup.permit.marker = value
            cleanup.marker = value
            cleanup.validate()
            cleanup.result = RetentionResult("uncertainty_retained")
        except BaseException:
            # Cleanup interruption is an unconfirmed result, not permission to
            # retry or release. Preserve the original object even if a partial write made its
            # contents invalid. Never delete, replace or automatically retry it.
            pass
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except BaseException:
                    # A close outcome can be uncertain; do not retry or mask the
                    # original context exception with cleanup failure.
                    cleanup.result = RetentionResult("retention_unconfirmed")
        if time.monotonic() >= cleanup.deadline:
            cleanup.result = RetentionResult("retention_unconfirmed")
        return cleanup.result


class _RuntimeState:
    def __init__(self, session, journal):
        self.session, self.journal = session, journal
        self.live, self.owner = True, get_ident()
        self.sealed = Event()
        self.cleanup = None

    def seal(self):
        self.sealed.set()
        if self.cleanup is not None:
            self.cleanup.retain_uncertain()


def _state(context):
    _require(type(context) is RuntimeContext)
    state = _CONTEXTS.get(context)
    _require(state is not None and state.live and state.owner == get_ident())
    return state


def _header(journal):
    raw = _original_read(journal.path, MAX_JOURNAL_BYTES)
    _require(
        len(raw) >= 100
        and raw[:16] == b"SQLite format 3\x00"
        and raw[18:20] == b"\x01\x01"
        and not any(os.path.lexists(str(journal.path) + x) for x in ("-wal", "-shm", "-journal"))
    )


def _sql_snapshot(journal):
    """Current bounded SQL, not a frozen journal digest or a stop receipt."""
    journal._preopen_token.validate(check_marker=False)
    _header(journal)
    db = journal._db
    ticks = 0

    def bounded():
        nonlocal ticks
        ticks += 1
        return ticks > 1000

    _require(not db.in_transaction)
    db.set_progress_handler(bounded, 1000)
    try:
        db.execute("BEGIN")
        objects = db.execute("SELECT type, name FROM sqlite_master").fetchmany(8)
        _require(
            set(objects)
            == {
                ("table", "intents"),
                ("table", "stop_acks"),
                ("index", "sqlite_autoindex_intents_1"),
                ("index", "sqlite_autoindex_stop_acks_1"),
            }
        )
        for table, expected in (
            (
                "intents",
                (
                    ("job_id", "TEXT", 1, 1),
                    ("action", "TEXT", 1, 2),
                    ("fence", "INTEGER", 1, 0),
                    ("result", "TEXT", 0, 0),
                ),
            ),
            (
                "stop_acks",
                (
                    ("job_id", "TEXT", 1, 1),
                    ("fence", "INTEGER", 1, 2),
                    ("revision", "INTEGER", 1, 3),
                    ("event_id", "TEXT", 1, 0),
                ),
            ),
        ):
            columns = db.execute("PRAGMA table_info(" + table + ")").fetchall()
            _require(tuple((row[1], row[2], row[3], row[5]) for row in columns) == expected)
        _require(db.execute("PRAGMA quick_check(1)").fetchall() == [("ok",)])
        rows = db.execute("SELECT job_id, action, fence, result FROM intents").fetchmany(
            MAX_RUNTIME_ROWS + 1
        )
        acknowledgments = db.execute(
            "SELECT job_id, fence, revision, event_id FROM stop_acks"
        ).fetchmany(MAX_RUNTIME_ROWS + 1)
        _require(len(rows) <= MAX_RUNTIME_ROWS and len(acknowledgments) <= MAX_RUNTIME_ROWS)
        for job, action, fence, result in rows:
            _require(
                type(job) is str
                and 0 < len(job) <= 256
                and action in {"start", "upload"}
                and type(fence) is int
                and fence >= 0
                and result in {None, "confirmed", "uncertain"}
            )
        for job, fence, revision, event in acknowledgments:
            _require(
                type(job) is str
                and 0 < len(job) <= 256
                and type(fence) is int
                and fence >= 0
                and type(revision) is int
                and revision >= 0
                and type(event) is str
                and 0 < len(event) <= 256
            )
        _header(journal)
        journal._preopen_token.validate(check_marker=False)
        return tuple(rows), tuple(acknowledgments)
    except sqlite3.Error:
        raise ApprovalNotReady() from None
    finally:
        db.set_progress_handler(None, 0)
        db.rollback()


class _CleanupState:
    def __init__(self, state, permit, deadline):
        self.state, self.permit = state, permit
        self.original_deadline = deadline
        self.marker = dict(permit.marker)
        self.path = state.journal._reservation_path(permit.device_id)
        self.marker_chain = _original_chain(self.path)
        self.deadline, self.result = None, None

    def validate_storage(self):
        state, session, journal = self.state, self.state.session, self.state.journal
        _require(state.live and session.live and state.owner == get_ident())
        _require(self.deadline is None or time.monotonic() < self.deadline)
        _require(
            FileIdentity.from_stat(os.fstat(session.fd)) == session.anchors.lock_identity
            and _chain(session.root / "admission.lock") == session.lock_chain
            and journal._preopen_token is session.device
            and journal._device_owners.get(self.permit.device_id) is session.device
            and journal._replay_reservations.get(self.permit.device_id) is self.permit
            and self.permit.device_id == session.plan.device_id
            and self.permit.marker == self.marker
            and self.marker["status"] in {"active", "uncertain"}
        )
        session.device.validate(check_marker=False)
        session.security(
            ((journal.path, False), (session.device.lock_path, False), (self.path, False))
        )
        rows, _ = _sql_snapshot(journal)
        _require(
            any(
                job == self.marker["session_id"]
                and action == "start"
                and fence == self.marker["generation"]
                for job, action, fence, _ in rows
            )
        )
        _require(self.deadline is None or time.monotonic() < self.deadline)

    def validate(self):
        self.validate_storage()
        _require(_original_chain(self.path) == self.marker_chain)
        raw = _original_read(self.path, 4096)
        _require(json.loads(raw, object_pairs_hook=_unique) == self.marker)
        _require(self.deadline is None or time.monotonic() < self.deadline)


def _bind_original_scope(context, *, deadline: float):
    """Internal already-started binding; never starts, grants native trust or stops.

    The future issuer must pass its already-established absolute scope deadline;
    a caller-supplied time is not itself scope authentication or a fresh budget.
    No production start issuer calls this yet. Synthetic tests exercise the real
    transition with an exact owned permit under the resolver's original locks.
    """
    state = _state(context)
    now = time.monotonic()
    _require(
        type(deadline) in (int, float)
        and now < deadline <= now + MAX_ORIGINAL_SCOPE_SECONDS
        and math.isfinite(deadline)
    )
    _require(not state.sealed.is_set() and state.cleanup is None)
    permit = state.journal._replay_reservations.get(state.session.plan.device_id)
    _require(permit is not None and permit.journal is state.journal and not permit.recovery_only)
    cleanup_state = _CleanupState(state, permit, deadline)
    cleanup_state.validate()
    cleanup = object.__new__(OriginalScopeCleanup)
    _CLEANUPS[cleanup] = cleanup_state
    state.cleanup = cleanup
    return cleanup


@contextmanager
def resolve_fixed_runtime(anchors: ReviewPinAnchors):
    """Retain original guards and locks; existing SQL only, no bootstrap or write.

    Constructed anchors do not prove their independent origin. This resolver
    verifies their current storage facts but deliberately cannot issue execution.
    """
    _require(type(anchors) is ReviewPinAnchors)
    reviewed = _load_fixed_scope(anchors.runner)
    with _locked_evidence(anchors.runner, reviewed, pinned=anchors) as session:
        # This header-only inspection opens no SQL and rejects WAL/sidecars before
        # the existing connection could create SQLite auxiliary state.
        with RunJournal(session.layout.journal, read_only=True):
            pass
        session.revalidate()
        with RunJournal.open_existing_locked(
            session.device, approval_check=session.revalidate
        ) as journal:
            context = object.__new__(RuntimeContext)
            state = _RuntimeState(session, journal)
            _CONTEXTS[context] = state
            try:
                context.inspect()
                yield context
            finally:
                try:
                    state.seal()  # Before closing SQL or releasing either original lock.
                finally:
                    state.live = False
                    if state.cleanup is not None:
                        _CLEANUPS.pop(state.cleanup, None)
                    _CONTEXTS.pop(context, None)
