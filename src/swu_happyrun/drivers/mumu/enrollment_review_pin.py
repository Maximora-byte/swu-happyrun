"""Read-only independently anchored ReviewPin inspection; execution stays closed.

Only a separately reviewed immutable external runner can establish trusted pin
bytes and identity. Constructing these dataclasses or supplying callbacks does
not do so. This module never imports the reviewer or writes/repairs any artifact.
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, replace

from swu_happyrun.agent.journal import RunJournal

from . import enrollment_transaction as transaction
from .enrollment_authority import FrozenFile, RunnerAnchors, _chain, _read
from .enrollment_review_pin_records import (
    INDEPENDENT_REVIEWER_ID,
    MAX_REVIEW_PIN_BYTES,
    decode_review_pin,
)
from .enrollment_review_scope import MAX_REVIEW_SCOPE_BYTES
from .enrollment_storage import StagedFile
from .enrollment_transaction_plan import load_transaction_plan
from .instance_attribution import FileIdentity

_require = transaction._require


@dataclass(frozen=True, repr=False)
class ReviewPinAnchors:
    """External runner observations only, not self-issued approval or authority."""

    runner: RunnerAnchors
    file: FrozenFile
    parent_identity: FileIdentity
    reviewer_id: str

    def __post_init__(self):
        _require(type(self.runner) is RunnerAnchors and type(self.file) is FrozenFile)
        _require(
            type(self.parent_identity) is FileIdentity
            and self.parent_identity == self.runner.plan_parent_identity
            and self.reviewer_id == INDEPENDENT_REVIEWER_ID
        )


@dataclass(frozen=True, repr=False)
class ReviewPinResult:
    status: str
    reason_code: str
    file: FrozenFile | None = None
    parent_identity: FileIdentity | None = None
    record: object | None = None
    execution_allowed: bool = field(default=False, init=False)


def _incomplete():
    return ReviewPinResult("incomplete", "independent_pin_evidence_mismatch")


class _PinSession:
    """Live read-only evidence plus exactly owned publication observations."""

    def __init__(self, root, anchors, plan, reviewed, fd, chain, security, device, pinned):
        self.root, self.anchors, self.plan, self.reviewed = root, anchors, plan, reviewed
        self.layout = transaction._layout(root, plan)
        self.fd, self.lock_chain, self.security, self.device = fd, chain, security, device
        self.folder = root / "reviews" / plan.plan_sha256
        self.path = self.folder / "review-pin-v1.json"
        self.stage_path = self.folder / f".review-pin-v1.json.{plan.transaction_id}.staged"
        self.final = pinned
        self.active_storage = None
        self.staged = None
        self.baseline = None
        self.live = True

    def _current_authority(self):
        _require(
            self.live
            and FileIdentity.from_stat(os.fstat(self.fd)) == self.anchors.lock_identity
            and _chain(self.root / "admission.lock") == self.lock_chain
        )
        self.security()
        _require(load_transaction_plan(self.root, self.anchors, now=time.time()) == self.plan)
        transaction._control_state(self.plan, self.layout)
        self.device.validate()

    def _pin_additions(self):
        """Only an external final anchor or this attempt's exact owned stage."""
        live = self.active_storage.live_staging_observations if self.active_storage else ()
        _require(len(live) <= 1)
        extra = []
        if live:
            item = live[0]
            _require(
                self.final is None
                and self.staged is None
                and item.path == self.stage_path
                and item.parent_identity == self.anchors.plan_parent_identity
                and not os.path.lexists(self.path)
            )
            extra.append(item)
        elif self.staged is not None:
            staged = self.staged
            _require(
                self.final is None
                and type(staged) is StagedFile
                and staged.path == self.stage_path
                and staged.destination == self.path
            )
            present = [path for path in (self.path, self.stage_path) if os.path.lexists(path)]
            _require(len(present) == 1)
            observed, raw = transaction._observe(present[0], "intent", cap=MAX_REVIEW_PIN_BYTES)
            _require(
                observed.identity == staged.identity
                and observed.sha256 == staged.sha256
                and observed.size == staged.size
                and observed.parent_identity == self.anchors.plan_parent_identity
            )
            extra.append(observed)
        elif self.final is not None:
            _require(type(self.final) is ReviewPinAnchors and self.final.runner == self.anchors)
            _require(not os.path.lexists(self.stage_path))
            observed, raw = transaction._observe(self.path, "intent", cap=MAX_REVIEW_PIN_BYTES)
            _require(
                observed.identity == self.final.file.identity
                and observed.sha256 == self.final.file.sha256
                and observed.parent_identity == self.final.parent_identity
            )
            extra.append(observed)
        else:
            _require(not os.path.lexists(self.path) and not os.path.lexists(self.stage_path))
        expected = {"approved-plan-v2.json", "reviewed-scope-v1.json"}
        expected.update(item.path.name for item in extra)
        _require(transaction._names(self.folder) == expected)
        _require(transaction._names(self.root / "reviews") == {self.plan.plan_sha256})
        return tuple(extra), live

    def _frozen(self, snapshot):
        frozen = {}
        target = {item.name: item for item in self.plan.targets}
        paths = {
            "authority": self.root / "authority-v1.json",
            "approved_plan": self.folder / "approved-plan-v2.json",
            "reviewed_scope": self.folder / "reviewed-scope-v1.json",
            **{
                name: target[name].path for name in ("host", "manager", "config", "config_previous")
            },
        }
        for role, path in paths.items():
            cap = (
                MAX_REVIEW_SCOPE_BYTES
                if role == "reviewed_scope"
                else transaction.MAX_JOURNAL_BYTES
            )
            observation, raw = transaction._observe(path, role, cap=cap)
            if role == "reviewed_scope":
                _require(raw == self.reviewed.canonical_bytes)
            frozen[role] = observation
        frozen.update(
            {name: item for name, item in snapshot.observations.items() if name != "journal"}
        )
        for index, item in enumerate(snapshot.record_observations, 1):
            frozen[f"stage{index:02d}"] = replace(item, role=f"stage{index:02d}")
        return frozen

    def revalidate(self):
        self._current_authority()
        extra, live = self._pin_additions()
        snapshot = transaction._evidence_snapshot(self.plan, self.layout, device_fd=self.device.fd)
        _require(snapshot.diagnosis.status == "candidate_unpinned")
        frozen = self._frozen(snapshot)
        current = (
            frozen,
            snapshot.observations["journal"].identity,
            snapshot.observations["journal"].parent_identity,
        )
        if self.baseline is not None:
            _require(current == self.baseline)
        self.baseline = current
        protected = {"authority", "approved_plan", "reviewed_scope"}
        protected.update(set(snapshot.observations) - {"journal", "device_lock"})
        protected.update(f"stage{i:02d}" for i in range(1, 8))
        if self.plan.kind == "new_enrollment":
            protected.add("device_lock")
        extras = [(item.path, name in protected) for name, item in frozen.items()]
        extras.append((self.layout.journal, self.plan.kind == "new_enrollment"))
        extras.extend((item.path, True) for item in extra if item not in live)
        self.security(tuple(extras))
        transaction._evidence_scope(
            self.plan,
            self.layout,
            self.anchors,
            self.reviewed,
            snapshot,
            extra=extra,
            live_staging=live,
        )
        record = None
        if self.final is not None:
            raw = _read(self.path, self.final.file, MAX_REVIEW_PIN_BYTES)
            record = decode_review_pin(
                raw,
                root=self.root,
                anchors=self.anchors,
                plan=self.plan,
                expected_reviewer_id=self.final.reviewer_id,
            )
            _require({item.role: item for item in record.frozen} == frozen)
            journal = snapshot.observations["journal"]
            _require(
                (record.journal.path, record.journal.identity, record.journal.parent_identity)
                == (journal.path, journal.identity, journal.parent_identity)
            )
            _require(record.reviewed_at <= time.time() < record.expires_at)
        self.security(tuple(extras))
        self._current_authority()
        return snapshot, frozen, record


@contextmanager
def _locked_evidence(anchors, reviewed_scope, *, pinned=None):
    """Guards → account lock → original device OS lock, no SQLite connection."""
    root = transaction.resolve_control_root()
    plan = load_transaction_plan(root, anchors, now=time.time())
    reviewed = transaction._reviewed(plan, reviewed_scope)
    layout = transaction._layout(root, plan)
    # Reject control conflicts before target byte or metadata access. Only the
    # existing protected-path setup's ancestor guard metadata may precede locks.
    transaction._control_state(plan, layout)
    with transaction._protected_paths(root, anchors, plan, reviewed) as security:
        with transaction._existing_lock(root / "admission.lock", anchors.lock_identity) as (
            fd,
            chain,
        ):
            _require(load_transaction_plan(root, anchors, now=time.time()) == plan)
            transaction._control_state(plan, layout)
            with RunJournal.lock_existing(layout.journal, plan.device_id) as device:
                session = _PinSession(
                    root, anchors, plan, reviewed, fd, chain, security, device, pinned
                )
                try:
                    session.revalidate()
                    yield session
                finally:
                    session.live = False


def load_review_pin(anchors: ReviewPinAnchors, reviewed_scope) -> ReviewPinResult:
    """Verify current full evidence without repair, refresh, renewal or readiness."""
    try:
        _require(type(anchors) is ReviewPinAnchors)
        with _locked_evidence(anchors.runner, reviewed_scope, pinned=anchors) as session:
            _, _, record = session.revalidate()
            return ReviewPinResult(
                "candidate_pinned",
                "independent_pin_verified_runtime_closed",
                anchors.file,
                anchors.parent_identity,
                record,
            )
    except Exception:
        return _incomplete()
