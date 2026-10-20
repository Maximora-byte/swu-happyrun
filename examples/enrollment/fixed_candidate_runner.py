"""Copy to a private reviewed external location; never fill from CLI/environment.

See docs/qa/2026-10-20-fixed-enrollment-entry.md. These unset anchors intentionally
make the distributed example unusable for initialization. Only an independently
reviewed private copy may embed original-machine observations. Keep that copy and
its anchors out of Git, and independently fix its code/package before invocation.
"""

import json
import sys

from swu_happyrun.drivers.mumu.enrollment_authority import RunnerAnchors
from swu_happyrun.drivers.mumu.enrollment_review_pin import ReviewPinAnchors
from swu_happyrun.drivers.mumu.enrollment_runner import (
    diagnose_fixed_candidate,
    initialize_fixed_candidate,
    inspect_fixed_pin,
)

# Change these only in the independently reviewed private external copy.
# The operation is fixed in code; arguments never select a write operation.
OPERATION = "diagnose"
RUNNER_ANCHORS: RunnerAnchors | None = None
PIN_ANCHORS: ReviewPinAnchors | None = None


def main(arguments):
    result = None
    if not arguments:
        if OPERATION == "inspect_pin" and type(PIN_ANCHORS) is ReviewPinAnchors:
            result = inspect_fixed_pin(PIN_ANCHORS)
        elif type(RUNNER_ANCHORS) is RunnerAnchors:
            if OPERATION == "diagnose":
                result = diagnose_fixed_candidate(RUNNER_ANCHORS)
            elif OPERATION == "initialize":
                result = initialize_fixed_candidate(RUNNER_ANCHORS)
    # Never print records, anchors, file paths, UUIDs, exception text or raw JSON.
    summary = {
        "status": result.status if result else "incomplete",
        "reason_code": result.reason_code if result else "external_runner_not_fixed",
        "execution_allowed": False,
    }
    print(json.dumps(summary, sort_keys=True))
    return 0 if result and result.status in {"candidate_unpinned", "candidate_pinned"} else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
