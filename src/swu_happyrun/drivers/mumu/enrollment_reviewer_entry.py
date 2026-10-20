"""Independent reviewer's explicit pin-publication entry, not an initializer.

Only a separately authorized original-machine reviewer invokes this from its
independently fixed code. A successful return is an observation to inspect and
pin externally, never permission to run a device. The runner module deliberately
does not import this module or its issuer.
"""

from .enrollment_authority import RunnerAnchors
from .enrollment_pin_reviewer import issue_review_pin
from .enrollment_review_pin import ReviewPinResult
from .enrollment_review_pin_records import INDEPENDENT_REVIEWER_ID
from .enrollment_runner import _load_fixed_scope


def issue_fixed_pin(anchors: RunnerAnchors) -> ReviewPinResult:
    """One explicit publication attempt; no initialization, repair or retry."""
    try:
        reviewed = _load_fixed_scope(anchors)
        return issue_review_pin(anchors, reviewed, reviewer_id=INDEPENDENT_REVIEWER_ID)
    except Exception:
        return ReviewPinResult("incomplete", "fixed_reviewer_evidence_mismatch")
