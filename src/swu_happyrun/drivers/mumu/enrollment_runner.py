"""Non-executing entry points for an independently fixed external runner.

The caller supplies reviewed, literal anchors from its protected external code.
This module never discovers anchors, imports a caller-selected module, accepts
CLI/environment overrides, issues approval, or upgrades evidence to a native
capability. Constructing an anchors dataclass does not establish independence.

Initialization is an explicit, separately authorized write operation. Diagnosis
and pin inspection do not initialize anything. All paths retain the original
transaction/pin guards and lock ordering, and all results remain runtime-closed.
"""

from __future__ import annotations

import time

from . import enrollment_transaction as transaction
from .enrollment_authority import ApprovalNotReady, FrozenFile, RunnerAnchors, _chain, _read
from .enrollment_review_pin import ReviewPinAnchors, ReviewPinResult, load_review_pin
from .enrollment_review_scope import MAX_REVIEW_SCOPE_BYTES, load_review_scope
from .enrollment_transaction_plan import load_transaction_plan
from .enrollment_transaction_records import TransactionDiagnosis


def _load_fixed_scope(anchors: RunnerAnchors):
    """Load the original ledger using the hash in the independently pinned plan.

    The scope file identity is observed for a single bounded, no-redirect read;
    it is not promoted to a new trust anchor. Its authority comes from the
    original plan's scope digest and the fixed plan-parent identity. The called
    transaction/loader then rechecks evidence under its original locks.
    """
    if type(anchors) is not RunnerAnchors:
        raise ApprovalNotReady()
    root = transaction.resolve_control_root()
    plan = load_transaction_plan(root, anchors, now=time.time())
    folder = root / "reviews" / anchors.plan_sha256
    if _chain(folder)[-1][1] != anchors.plan_parent_identity:
        raise ApprovalNotReady()
    path = folder / "reviewed-scope-v1.json"
    observed = _chain(path)[-1][1]
    raw = _read(
        path,
        FrozenFile(observed, plan.reviewed_scope_sha256),
        cap=MAX_REVIEW_SCOPE_BYTES,
    )
    journal = next(item.path for item in plan.targets if item.name == "journal")
    reviewed = load_review_scope(
        raw,
        expected_sha256=plan.reviewed_scope_sha256,
        expected_host_id=plan.host_namespace,
        expected_device_id=plan.device_id,
        expected_journal=journal if plan.kind == "existing" else None,
    )
    if load_transaction_plan(root, anchors, now=time.time()) != plan:
        raise ApprovalNotReady()
    return reviewed


def initialize_fixed_candidate(anchors: RunnerAnchors) -> TransactionDiagnosis:
    """One explicit initializer call; never provision authority or issue a pin."""
    try:
        reviewed = _load_fixed_scope(anchors)
        return transaction.initialize_candidate(anchors, reviewed)
    except Exception:
        return TransactionDiagnosis("incomplete", "fixed_runner_evidence_mismatch")


def diagnose_fixed_candidate(anchors: RunnerAnchors) -> TransactionDiagnosis:
    """Read-only diagnosis; no retry, repair, initialization or SQLite open."""
    try:
        reviewed = _load_fixed_scope(anchors)
        return transaction.diagnose_candidate(anchors, reviewed)
    except Exception:
        return TransactionDiagnosis("incomplete", "fixed_runner_evidence_mismatch")


def inspect_fixed_pin(anchors: ReviewPinAnchors) -> ReviewPinResult:
    """Verify an independently fixed final pin, never issue or adopt one."""
    try:
        if type(anchors) is not ReviewPinAnchors:
            raise ApprovalNotReady()
        reviewed = _load_fixed_scope(anchors.runner)
        return load_review_pin(anchors, reviewed)
    except Exception:
        return ReviewPinResult("incomplete", "fixed_runner_evidence_mismatch")
