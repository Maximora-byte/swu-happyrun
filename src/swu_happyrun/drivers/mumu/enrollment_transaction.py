"""Internal candidate enrollment transaction, never a runtime permission issuer.

Inputs must come from a separately reviewed immutable runner. No CLI, bootstrap,
review-pin issuance, native device command, retry, removal, or recovery writer is
provided. Every retained partial transaction is diagnose-only. Existing history is
adopted as observed *now*, not represented as historically registered.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import sqlite3
import stat
import time
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

from swu_happyrun.agent.journal import RunJournal

from . import windows_private
from .enrollment import resolve_control_root
from .enrollment_admission import _existing_lock, _require_local_ntfs
from .enrollment_authority import ApprovalNotReady, FrozenFile, RunnerAnchors, _chain, _read
from .enrollment_inspection import inspect_enrollment
from .enrollment_phase_scope import require_phase_scope
from .enrollment_review_scope import MAX_REVIEW_SCOPE_BYTES, ReviewedScope, load_review_scope
from .enrollment_storage import StagedFile, private_storage
from .enrollment_transaction_plan import load_transaction_plan, validate_frozen_inputs
from .enrollment_transaction_records import (
    ArtifactObservation,
    TransactionDiagnosis,
    TransactionLayout,
    decode_record,
    diagnose_transaction,
    encode_record,
)
from .instance_attribution import FileIdentity

MAX_JOURNAL_BYTES = 128 * 1024 * 1024


def _require(condition):
    if not condition:
        raise ApprovalNotReady()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _layout(root, plan):
    targets = {target.name: target for target in plan.targets}
    return TransactionLayout(
        root,
        plan.plan_sha256,
        plan.transaction_id,
        targets["journal"].path,
        targets["receipt"].path,
        plan.device_id,
    )


def _directories(plan):
    return {name: (path, identity) for name, path, identity in plan.directories}


def _reviewed(plan, reviewed):
    _require(type(reviewed) is ReviewedScope)
    targets = {target.name: target for target in plan.targets}
    journal = targets["journal"].path
    validated = load_review_scope(
        reviewed.canonical_bytes,
        expected_sha256=plan.reviewed_scope_sha256,
        expected_host_id=plan.host_namespace,
        expected_device_id=plan.device_id,
        expected_journal=journal if plan.kind == "existing" else None,
    )
    inspection = validated.inspection
    sources = inspection.identity_sources
    for name in ("host", "manager"):
        target = targets[name]
        _require(
            sources[name + "_path"] == str(target.path)
            and sources[name + "_identity"] == (target.identity.volume, target.identity.file_index)
        )
    parent = targets["journal"].parent_identity
    _require(
        any(
            item.path == str(journal.parent)
            and item.identity == (parent.volume, parent.file_index)
            and not item.missing
            and not item.errors
            and not item.exclusions
            for item in inspection.roots
        )
    )
    return validated


def _observe(path, role, *, cap=MAX_JOURNAL_BYTES):
    before = _chain(path)
    info = path.lstat()
    _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= cap)
    # Identity first, bounded bytes second, then pinned readback. No SQL is used.
    fd = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0),
    )
    try:
        opened = os.fstat(fd)
        _require(FileIdentity.from_stat(opened) == before[-1][1] and 0 <= opened.st_size <= cap)
        with os.fdopen(fd, "rb", closefd=False) as source:
            raw = source.read(opened.st_size + 1)
        after = os.fstat(fd)
        _require(
            len(raw) == opened.st_size <= cap
            and (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns)
            == (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            and _chain(path) == before
        )
    finally:
        os.close(fd)
    observation = ArtifactObservation(
        role, path, before[-1][1], before[-2][1], len(raw), hashlib.sha256(raw).hexdigest()
    )
    _require(_read(path, FrozenFile(observation.identity, observation.sha256), cap) == raw)
    return observation, raw


def _observe_locked_byte(path, role, fd):
    """Read through the owner handle, never a Windows-conflicting second open."""
    before = _chain(path)
    opened = os.fstat(fd)
    _require(
        FileIdentity.from_stat(opened) == before[-1][1]
        and stat.S_ISREG(opened.st_mode)
        and opened.st_nlink == 1
        and opened.st_size == 1
    )
    position = os.lseek(fd, 0, os.SEEK_CUR)
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        raw = os.read(fd, 2)
    finally:
        os.lseek(fd, position, os.SEEK_SET)
    after = os.fstat(fd)
    _require(
        len(raw) == 1
        and _chain(path) == before
        and (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns)
        == (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    )
    return ArtifactObservation(
        role, path, before[-1][1], before[-2][1], 1, hashlib.sha256(raw).hexdigest()
    ), raw


def _read_observation(observation):
    _require(_chain(observation.path.parent)[-1][1] == observation.parent_identity)
    raw = _read(
        observation.path, FrozenFile(observation.identity, observation.sha256), MAX_JOURNAL_BYTES
    )
    _require(len(raw) == observation.size)
    return raw


def _admission(plan, layout):
    def binding(target):
        identity = target.identity
        return {
            "path": str(target.path),
            "parent_identity": [target.parent_identity.volume, target.parent_identity.file_index],
            "identity": [identity.volume, identity.file_index] if identity is not None else None,
            "sha256": target.sha256,
        }

    return _canonical(
        {
            "schema": "admission-v2",
            "plan_sha256": plan.plan_sha256,
            "transaction_id": plan.transaction_id,
            "host_namespace": plan.host_namespace,
            "stable_instance": plan.stable_instance,
            "device_id": plan.device_id,
            "instance_index": plan.instance_index,
            "journal": str(layout.journal),
            "receipt": str(layout.receipt),
            "targets": {target.name: binding(target) for target in plan.targets},
            "directories": {
                name: {"path": str(path), "identity": [identity.volume, identity.file_index]}
                for name, path, identity in plan.directories
            },
        }
    )


def _intent(plan):
    return _canonical(
        {
            "schema": "enrollment-intent-v1",
            "plan_sha256": plan.plan_sha256,
            "transaction_id": plan.transaction_id,
            "kind": plan.kind,
            "reviewed_scope_sha256": plan.reviewed_scope_sha256,
            "product_commit": plan.product_commit,
            "product_tree": plan.product_tree,
            "execution_allowed": False,
        }
    )


def _provenance(plan, journal):
    return _canonical(
        {
            "schema": "enrollment-provenance-v1",
            "plan_sha256": plan.plan_sha256,
            "transaction_id": plan.transaction_id,
            "adoption": "current_existing_history"
            if plan.kind == "existing"
            else "new_empty_journal",
            "historical_provenance_verified": False,
            "journal": journal.payload(),
            "product_commit": plan.product_commit,
            "product_tree": plan.product_tree,
            "execution_allowed": False,
        }
    )


def _receipt(plan, journal, lock):
    targets = {target.name: target for target in plan.targets}

    def entry(path, identity):
        return {"path": str(path), "identity": [identity.volume, identity.file_index]}

    return _canonical(
        {
            "schema": 1,
            "stable_instance": plan.stable_instance,
            "instance_index": plan.instance_index,
            "host_id": plan.host_namespace,
            "device_id": plan.device_id,
            "host_file": entry(targets["host"].path, targets["host"].identity),
            "manager_file": entry(targets["manager"].path, targets["manager"].identity),
            "journal_file": entry(journal.path, journal.identity),
            "journal_directory_identity": [
                journal.parent_identity.volume,
                journal.parent_identity.file_index,
            ],
            "lock_identity": [lock.identity.volume, lock.identity.file_index],
            "evidence_root": str(plan.evidence_root),
        }
    )


def _candidate(plan, receipt_record_sha256):
    return _canonical(
        {
            "schema": "candidate-v1",
            "status": "candidate_unpinned",
            "plan_sha256": plan.plan_sha256,
            "transaction_id": plan.transaction_id,
            "receipt_record_sha256": receipt_record_sha256,
            "reviewed_scope_sha256": plan.reviewed_scope_sha256,
            "product_commit": plan.product_commit,
            "product_tree": plan.product_tree,
            "execution_allowed": False,
        }
    )


def _names(directory):
    before = _chain(directory)
    _require(stat.S_ISDIR(directory.lstat().st_mode))
    with os.scandir(directory) as entries:
        names = []
        for entry in entries:
            _require(len(names) < 32)
            names.append(entry.name)
    _require(_chain(directory) == before)
    return set(names)


def _control_state(plan, layout):
    """Reject foreign/partial admissions before any journal or SQLite use."""
    _require(_names(layout.root / "transactions") == {plan.transaction_id})
    names = _names(layout.root / "admissions")
    _require(names <= {layout.path("admission").name})
    if names:
        _, raw = _observe(layout.path("admission"), "admission", cap=65536)
        _require(raw == _admission(plan, layout))
    transaction_names = _names(layout.directory)
    return bool(names or transaction_names)


def _control_publications(root, anchors, reviewed):
    """Reviewer publication after scope capture, pinned independently of writer."""
    folder = root / "reviews" / anchors.plan_sha256
    result = {
        folder: (anchors.plan_parent_identity, True),
        folder / "approved-plan-v2.json": (anchors.plan.identity, False),
        root / "authority-v1.json": (anchors.authority.identity, False),
    }
    scope = folder / "reviewed-scope-v1.json"
    if os.path.lexists(scope):
        identity = _chain(scope)[-1][1]
        _require(
            _read(scope, FrozenFile(identity, reviewed.sha256), MAX_REVIEW_SCOPE_BYTES)
            == reviewed.canonical_bytes
        )
        result[scope] = identity, False
    return result


def _require_current_scope(session):
    """Subtract only exact observed own files, never refresh the approved ledger."""
    previous = session.reviewed.inspection
    target = {item.name: item for item in session.plan.targets}
    live = (
        session.active_storage.live_staging_observations
        if session.active_storage is not None
        else ()
    )
    additions = dict(session.control_additions)
    for path in session.created:
        additions[path] = session.owned[path].identity, False
    for staged in session.inflight.values():
        present = [path for path in (staged.path, staged.destination) if os.path.lexists(path)]
        _require(len(present) == 1)
        additions[present[0]] = staged.identity, False
    for item in live:
        _require(item.parent_identity == session.parents[item.path.parent] and item.size >= 0)
        additions[item.path] = item.identity, False
    _require(_names(session.root / "transactions") == {session.plan.transaction_id})
    _require(_names(session.root / "reviews") == {session.plan.plan_sha256})
    for directory in (session.root / "admissions", session.layout.directory):
        _require(_names(directory) == {path.name for path in additions if path.parent == directory})
    root_names = {
        "admission.lock",
        "authority-v1.json",
        "review-layout-v1.json",
        "reviews",
        "admissions",
        "transactions",
    }
    if session.plan.evidence_root.is_relative_to(session.root):
        root_names.add(session.plan.evidence_root.relative_to(session.root).parts[0])
    _require(_names(session.root) <= root_names)
    current = inspect_enrollment(
        previous.scope,
        manager=target["manager"].path,
        instance_index=session.plan.instance_index,
        expected_journal=session.layout.journal if session.plan.kind == "existing" else None,
        _live_staging=live,
    )
    require_phase_scope(session.reviewed, current, additions, live_staging=live)


@contextmanager
def _protected_paths(root, anchors, plan, reviewed):
    """Hold original path guards before account locking; no fallback platform."""
    _require_local_ntfs(root)
    api = windows_private._WinAPI()
    handles = []
    with ExitStack() as stack:
        try:
            targets = [target.path for target in plan.targets]
            directories = _directories(plan)
            private = {
                root: anchors.root_identity,
                root / "reviews" / plan.plan_sha256: anchors.plan_parent_identity,
                **{path: identity for path, identity in directories.values()},
            }
            for name in ("journal", "receipt"):
                target = next(target for target in plan.targets if target.name == name)
                private[target.path.parent] = target.parent_identity
            sid = api.current_sid()
            for directory, identity in private.items():
                _require_local_ntfs(directory)
                stack.enter_context(
                    windows_private.verified_directory(
                        directory, (identity.volume, identity.file_index)
                    )
                )
            paths = targets + [
                root / "admission.lock",
                root / "authority-v1.json",
                root / "reviews" / plan.plan_sha256 / "approved-plan-v2.json",
            ]
            paths += [Path(item.path) for item in reviewed.inspection.roots if not item.missing]
            parents = {parent for path in paths for parent in path.parents}
            for parent in sorted(parents, key=lambda path: len(path.parts)):
                handles.append(api.guard(parent))
            for path in paths:
                if os.path.lexists(path):
                    _chain(path)
                    handle = api.kernel.CreateFileW(str(path), 0x80, 3, None, 3, 0x02200000, None)
                    _require(handle not in (None, ctypes.c_void_p(-1).value))
                    handles.append(handle)

            def security(extra_paths=()):
                _require(api.current_sid() == sid)
                for path in [
                    *private,
                    root / "admission.lock",
                    root / "authority-v1.json",
                    root / "reviews" / plan.plan_sha256 / "approved-plan-v2.json",
                ]:
                    windows_private.validate_sddl(api.security(path), sid, protected=True)
                for path, protected in extra_paths:
                    windows_private.validate_sddl(api.security(path), sid, protected=protected)

            security()
            yield security
        finally:
            for handle in reversed(handles):
                api.kernel.CloseHandle(handle)


class _Session:
    def __init__(self, root, anchors, plan, reviewed, fd, chain, security):
        self.root, self.anchors, self.plan, self.reviewed = root, anchors, plan, reviewed
        self.layout = _layout(root, plan)
        self.fd, self.lock_chain, self.security = fd, chain, security
        self.owned = {}
        self.created = set()
        self.inflight = {}
        self.active_storage = None
        self.control_additions = _control_publications(root, anchors, reviewed)
        self.records = []
        self.artifacts = {}
        self.device_check = None
        self.device_fd = None
        self.live = True
        self.parents = {target.path.parent: target.parent_identity for target in plan.targets}
        self.parents.update({path: identity for _, path, identity in plan.directories})

    def _security(self):
        extras = [(path, path in self.created) for path in self.owned]
        for staged in self.inflight.values():
            extras.extend(
                (path, True) for path in (staged.path, staged.destination) if os.path.lexists(path)
            )
        self.security(tuple(extras))

    def revalidate(self):
        _require(
            self.live
            and FileIdentity.from_stat(os.fstat(self.fd)) == self.anchors.lock_identity
            and _chain(self.root / "admission.lock") == self.lock_chain
        )
        self._security()
        _require(load_transaction_plan(self.root, self.anchors, now=time.time()) == self.plan)
        validate_frozen_inputs(self.plan)
        for observation in self.owned.values():
            if observation.path == self.layout.path("device_lock") and self.device_fd is not None:
                _require(
                    _observe_locked_byte(observation.path, "device_lock", self.device_fd)[0]
                    == observation
                )
            else:
                _read_observation(observation)
        for staged in self.inflight.values():
            _require(type(staged) is StagedFile)
            present = [path for path in (staged.path, staged.destination) if os.path.lexists(path)]
            _require(len(present) == 1)
            _require(_chain(present[0].parent)[-1][1] == self.parents[present[0].parent])
            raw = _read(present[0], staged.file, MAX_JOURNAL_BYTES)
            _require(len(raw) == staged.size)
        for target in self.plan.targets:
            if target.name not in {"journal", "receipt", "device_lock"}:
                continue
            if target.path in self.owned or target.path in self.inflight:
                continue
            if target.identity is None:
                _require(not os.path.lexists(target.path))
            else:
                _require(_chain(target.path)[-1][1] == target.identity)
                info = target.path.lstat()
                _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1)
                if target.name == "device_lock":
                    if self.device_fd is not None:
                        actual, _ = _observe_locked_byte(target.path, "device_lock", self.device_fd)
                        _require(
                            actual.identity == target.identity and actual.sha256 == target.sha256
                        )
                    else:
                        _require(
                            info.st_size == 1
                            and len(
                                _read(target.path, FrozenFile(target.identity, target.sha256), 1)
                            )
                            == 1
                        )
        for path in [
            self.layout.path(role) for role in ("admission", "intent", "provenance", "candidate")
        ] + [self.layout.record_path(index) for index in range(1, 8)]:
            if path not in self.owned and path not in self.inflight:
                _require(not os.path.lexists(path))
        if self.device_check is not None:
            self.device_check()
        _require_current_scope(self)
        self._security()

    def publish(self, path, payload, role):
        self.revalidate()
        parent = self.parents[path.parent]
        with private_storage(
            path.parent, parent_identity=parent, validate_current=self.revalidate
        ) as storage:
            self.active_storage = storage
            try:
                staged = storage.stage(path.name, payload, transaction_id=self.plan.transaction_id)
            finally:
                self.active_storage = None
            self.inflight[path] = staged
            self.revalidate()
            frozen = storage.publish(staged)
            _require(frozen == staged.file)
            observed, actual = _observe(path, role)
            _require(
                actual == payload
                and observed.identity == frozen.identity
                and observed.sha256 == frozen.sha256
                and observed.parent_identity == parent
            )
            self.owned[path] = observed
            self.created.add(path)
            del self.inflight[path]
        self.revalidate()
        return observed

    def record(self, role, observation):
        sequence = len(self.records) + 1
        previous = hashlib.sha256(self.records[-1]).hexdigest() if self.records else None
        raw = encode_record(self.layout, sequence, previous, observation)
        self.publish(self.layout.record_path(sequence), raw, role)
        self.records.append(raw)
        self.artifacts[role] = observation

    def artifact(self, role, payload):
        observation = self.publish(self.layout.path(role), payload, role)
        self.record(role, observation)
        return observation

    def adopt(self, role):
        self.revalidate()
        if role == "device_lock" and self.device_fd is not None:
            observation, _ = _observe_locked_byte(self.layout.path(role), role, self.device_fd)
        else:
            observation, _ = _observe(self.layout.path(role), role)
        self.owned[observation.path] = observation
        self.record(role, observation)
        return observation


def _empty_journal():
    """Initialize only private memory; caller holds the original device lock."""
    db = sqlite3.connect(":memory:", timeout=0)
    try:
        db.execute("PRAGMA synchronous=FULL")
        db.execute(
            "CREATE TABLE intents (job_id TEXT NOT NULL, action TEXT NOT NULL, "
            "fence INTEGER NOT NULL, result TEXT, PRIMARY KEY(job_id, action))"
        )
        db.execute(
            "CREATE TABLE stop_acks (job_id TEXT NOT NULL, fence INTEGER NOT NULL, "
            "revision INTEGER NOT NULL, event_id TEXT NOT NULL, "
            "PRIMARY KEY(job_id, fence, revision))"
        )
        db.commit()
        return db.serialize()
    finally:
        db.close()


def _finish(session, lock):
    plan = session.plan
    if plan.kind == "existing":
        journal = session.adopt("journal")
    else:
        session.revalidate()
        journal = session.artifact("journal", _empty_journal())
    session.artifact("provenance", _provenance(plan, journal))
    session.artifact("receipt", _receipt(plan, journal, lock))
    session.artifact("candidate", _candidate(plan, hashlib.sha256(session.records[-1]).hexdigest()))
    session.revalidate()
    return diagnose_transaction(session.layout, session.records, session.artifacts)


@dataclass(frozen=True, repr=False)
class _EvidenceSnapshot:
    """Observed evidence, never a lock token, independent approval or capability."""

    diagnosis: TransactionDiagnosis
    records: tuple[bytes, ...]
    observations: dict
    record_observations: tuple[ArtifactObservation, ...]


def _evidence_snapshot(plan, layout, *, device_fd=None):
    """Collect semantic evidence without SQLite or mutation.

    A pin caller holds path/account/original-device locks and supplies its owner
    descriptor. Public diagnosis retains its existing read-only behavior.
    """
    _control_state(plan, layout)
    validate_frozen_inputs(plan)
    expected_names = {
        layout.path("intent").name,
        layout.path("candidate").name,
        *(layout.record_path(i).name for i in range(1, 8)),
    }
    _require(_names(layout.directory) <= expected_names)
    records, observations, raw_artifacts, record_files = [], {}, {}, []
    for index in range(1, 8):
        path = layout.record_path(index)
        if os.path.lexists(path):
            _require(index == len(records) + 1)
            observation, raw = _observe(path, "intent", cap=65536)
            records.append(raw)
            record_files.append(observation)
    for role in layout.roles:
        path = layout.path(role)
        if os.path.lexists(path):
            if role == "device_lock" and device_fd is not None:
                observation, raw = _observe_locked_byte(path, role, device_fd)
            else:
                observation, raw = _observe(path, role)
            observations[role], raw_artifacts[role] = observation, raw
    # Original DB/lock alone are not a transaction. They must still be the exact
    # approved objects; no initializer may relabel an unexplained new artifact.
    if (
        not records
        and not _names(layout.directory)
        and not os.path.lexists(layout.path("admission"))
    ):
        originals = {"journal", "device_lock"} if plan.kind == "existing" else set()
        _require(set(observations) == originals)
        for target in plan.targets:
            if target.name in originals:
                _require(observations[target.name].identity == target.identity)
        return _EvidenceSnapshot(
            TransactionDiagnosis("unstarted", "no_transaction_evidence"),
            tuple(records),
            observations,
            tuple(record_files),
        )
    for role, expected in (("admission", _admission(plan, layout)), ("intent", _intent(plan))):
        if role in raw_artifacts:
            _require(raw_artifacts[role] == expected)
    if "device_lock" in raw_artifacts:
        _require(len(raw_artifacts["device_lock"]) == 1)
    recorded = {decode_record(raw)[1].role: decode_record(raw)[1] for raw in records}
    if "provenance" in raw_artifacts:
        _require(raw_artifacts["provenance"] == _provenance(plan, recorded["journal"]))
    if "receipt" in raw_artifacts:
        _require(
            raw_artifacts["receipt"] == _receipt(plan, recorded["journal"], recorded["device_lock"])
        )
    if "candidate" in raw_artifacts:
        _require(
            len(records) >= 6
            and raw_artifacts["candidate"]
            == _candidate(plan, hashlib.sha256(records[5]).hexdigest())
        )
    return _EvidenceSnapshot(
        diagnose_transaction(layout, records, observations),
        tuple(records),
        observations,
        tuple(record_files),
    )


def _evidence_scope(plan, layout, anchors, reviewed, snapshot, *, extra=(), live_staging=()):
    """Recheck original scope, subtracting exact verified evidence only."""
    additions = _control_publications(layout.root, anchors, reviewed)
    additions.update({item.path: (item.identity, False) for item in snapshot.record_observations})
    for role, observation in snapshot.observations.items():
        if plan.kind == "existing" and role in {"device_lock", "journal"}:
            continue
        additions[observation.path] = observation.identity, False
    additions.update({item.path: (item.identity, False) for item in extra})
    targets = {target.name: target for target in plan.targets}
    current = inspect_enrollment(
        reviewed.inspection.scope,
        manager=targets["manager"].path,
        instance_index=plan.instance_index,
        expected_journal=layout.journal if plan.kind == "existing" else None,
        _live_staging=live_staging,
    )
    require_phase_scope(reviewed, current, additions, live_staging=live_staging)


def _diagnose(plan, layout, anchors, reviewed):
    snapshot = _evidence_snapshot(plan, layout)
    if snapshot.diagnosis.status == "candidate_unpinned":
        _evidence_scope(plan, layout, anchors, reviewed, snapshot)
    return snapshot.diagnosis


def diagnose_candidate(
    anchors: RunnerAnchors, reviewed_scope: ReviewedScope
) -> TransactionDiagnosis:
    """Read bounded files only. Never SQLite, lock creation, mkdir, fix or resume."""
    try:
        root = resolve_control_root()
        plan = load_transaction_plan(root, anchors, now=time.time())
        reviewed = _reviewed(plan, reviewed_scope)
        return _diagnose(plan, _layout(root, plan), anchors, reviewed)
    except Exception:
        return TransactionDiagnosis("incomplete", "transaction_evidence_mismatch")


def initialize_candidate(
    anchors: RunnerAnchors, reviewed_scope: ReviewedScope
) -> TransactionDiagnosis:
    """One attempt with held guards → account lock → intent → original device lock.

    The schema1 receipt is the last substantive artifact; immutable completion
    metadata follows it. Completed and partial existing transactions are only read.
    A failure before any object is created cannot manufacture durable evidence of
    the attempt. Retained evidence is never deleted, overwritten or retried.
    """
    session = None
    try:
        root = resolve_control_root()
        plan = load_transaction_plan(root, anchors, now=time.time())
        reviewed = _reviewed(plan, reviewed_scope)
        layout = _layout(root, plan)
        with _protected_paths(root, anchors, plan, reviewed) as security:
            with _existing_lock(root / "admission.lock", anchors.lock_identity) as (fd, chain):
                _require(load_transaction_plan(root, anchors, now=time.time()) == plan)
                if _control_state(plan, layout):
                    return _diagnose(plan, layout, anchors, reviewed)
                session = _Session(root, anchors, plan, reviewed, fd, chain, security)
                session.revalidate()
                session.artifact("admission", _admission(plan, layout))
                session.artifact("intent", _intent(plan))
                if plan.kind == "existing":
                    with RunJournal.lock_existing(layout.journal, plan.device_id) as device:
                        session.device_check = device.validate
                        session.device_fd = device.fd
                        session.revalidate()
                        lock = session.adopt("device_lock")
                        original, _ = _observe(layout.journal, "journal")
                        session.owned[layout.journal] = original
                        session.revalidate()
                        # Constructor only validates existing schemas. No schema
                        # migration, intent alteration or reservation clearing.
                        with RunJournal.open_existing_locked(
                            device, approval_check=session.revalidate
                        ):
                            return _finish(session, lock)
                lock = session.artifact("device_lock", b"0")
                with _existing_lock(lock.path, lock.identity) as (device_fd, device_chain):

                    def device_check():
                        _require(
                            FileIdentity.from_stat(os.fstat(device_fd)) == lock.identity
                            and _chain(lock.path) == device_chain
                        )

                    session.device_check = device_check
                    session.device_fd = device_fd
                    session.revalidate()
                    return _finish(session, lock)
    except Exception:
        return TransactionDiagnosis("incomplete", "transaction_not_complete")
    finally:
        if session is not None:
            session.live = False
