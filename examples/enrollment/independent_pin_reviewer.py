"""Separate private reviewer entry. Never import from an initializer or runner.

This example refuses every argument and has no anchors. Publication needs its
own operation-specific authorization and independently fixed original-machine
anchors, not a label saying that somebody reviewed it.
"""

import json
import sys

from swu_happyrun.drivers.mumu.enrollment_authority import RunnerAnchors
from swu_happyrun.drivers.mumu.enrollment_pin_reviewer import issue_fixed_pin

RUNNER_ANCHORS: RunnerAnchors | None = None


def main(arguments):
    result = None
    if not arguments and type(RUNNER_ANCHORS) is RunnerAnchors:
        result = issue_fixed_pin(RUNNER_ANCHORS)
    print(
        json.dumps(
            {
                "status": result.status if result else "incomplete",
                "reason_code": result.reason_code if result else "external_reviewer_not_fixed",
                "execution_allowed": False,
            },
            sort_keys=True,
        )
    )
    return 0 if result and result.status == "candidate_pinned" else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
