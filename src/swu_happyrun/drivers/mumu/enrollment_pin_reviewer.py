"""Separate original-machine reviewer-only exclusive ReviewPin publication.

This module is not imported by the initializer, loader, CLI or native factory.
The fixed reviewer ID labels provenance only: it does not prove independence or
create a capability. Publication requires the independently reviewed handoff;
returned exact file observations still need fixed embedding in an external
reviewed runner. No runner, ready state, expiry extension or update is generated.
"""

from __future__ import annotations

import time

from .enrollment_review_pin import (
    ReviewPinAnchors,
    ReviewPinResult,
    _incomplete,
    _locked_evidence,
    _require,
)
from .enrollment_review_pin_records import (
    INDEPENDENT_REVIEWER_ID,
    JournalBinding,
    encode_review_pin,
)
from .enrollment_storage import private_storage


def issue_review_pin(anchors, reviewed_scope, *, reviewer_id) -> ReviewPinResult:
    """One retained attempt, no mkdir, overwrite, adoption, cleanup or retry.

    The original plan expiry is copied exactly, never refreshed. Current expiry,
    authority, all frozen evidence, scope and ACLs are rechecked by storage before
    each mutation while original account/device locks and path guards stay held.
    """
    try:
        _require(type(reviewer_id) is str and reviewer_id == INDEPENDENT_REVIEWER_ID)
        with _locked_evidence(anchors, reviewed_scope) as session:
            snapshot, frozen, _ = session.revalidate()
            journal = snapshot.observations["journal"]
            raw = encode_review_pin(
                session.root,
                anchors,
                session.plan,
                reviewer_id=reviewer_id,
                reviewed_at=time.time(),
                frozen=frozen,
                journal=JournalBinding(journal.path, journal.identity, journal.parent_identity),
            )
            session.revalidate()
            with private_storage(
                session.folder,
                parent_identity=anchors.plan_parent_identity,
                validate_current=session.revalidate,
            ) as storage:
                session.active_storage = storage
                try:
                    staged = storage.stage(
                        "review-pin-v1.json",
                        raw,
                        transaction_id=session.plan.transaction_id,
                    )
                finally:
                    session.active_storage = None
                session.staged = staged
                session.revalidate()
                file = storage.publish(staged)
                _require(file == staged.file)
                session.staged = None
                session.final = ReviewPinAnchors(
                    anchors, file, anchors.plan_parent_identity, reviewer_id
                )
                _, _, record = session.revalidate()
                return ReviewPinResult(
                    "candidate_pinned",
                    "independent_pin_published_runtime_closed",
                    file,
                    anchors.plan_parent_identity,
                    record,
                )
    except Exception:
        return _incomplete()
