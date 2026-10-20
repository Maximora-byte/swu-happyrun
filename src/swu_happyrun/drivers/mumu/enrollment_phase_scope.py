"""Read-only exact-owned-file adjustment of an independently approved ledger.

This is not an approval issuer. Callers must establish the authority and ownership
of every addition before using this consistency check. In particular a filename,
caller boolean, or new scan does not establish transaction ownership.
"""

import stat
from dataclasses import replace
from pathlib import Path

from .enrollment_authority import ApprovalNotReady, _chain
from .enrollment_review_scope import require_matching_reinspection
from .instance_attribution import FileIdentity


def _require(condition):
    if not condition:
        raise ApprovalNotReady()


def require_phase_scope(reviewed, current, additions, *, live_staging=()):
    """Check fresh evidence after subtracting exact observed owned additions.

    additions maps paths to (python-stat identity, is_directory). The directory
    flag is an object-kind observation, never an authorization or bypass flag.
    All source/declaration/error/exclusion facts and adjusted counts must match.
    """
    _require(type(additions) is dict and len(additions) <= 64)
    for path, value in additions.items():
        _require(
            isinstance(path, Path)
            and type(value) is tuple
            and len(value) == 2
            and type(value[0]) is FileIdentity
            and type(value[1]) is bool
        )
    previous = reviewed.inspection
    live = {item.path: item for item in live_staging}
    _require(len(live) == len(live_staging))
    for path, (identity, directory) in additions.items():
        if path in live:
            item = live[path]
            _require(not directory and item.identity == identity and item.file_type == "regular")
            _require(_chain(path.parent)[-1][1] == item.parent_identity)
        else:
            _require(_chain(path)[-1][1] == identity)
            _require(
                stat.S_ISDIR(path.lstat().st_mode)
                if directory
                else stat.S_ISREG(path.lstat().st_mode)
            )
    # These are scanner derivations caused only by the exact owned output set.
    # All underlying roots/counts/artifact names must normalize to the original
    # ledger before any reason or status can be normalized.
    _require(
        set(current.reasons)
        <= {
            "orphan_state_artifacts",
            "state_artifacts_require_review",
            "journal_mapping_unverified",
        }
    )
    roots = []
    for root in current.roots:
        base = Path(root.path)
        changes = {
            path: value
            for path, value in additions.items()
            if path != base and path.is_relative_to(base)
        }
        roots.append(
            replace(
                root,
                entry_count=root.entry_count - len(changes),
                file_count=root.file_count
                - sum(not directory for _, directory in changes.values()),
                candidate_journals=tuple(
                    path for path in root.candidate_journals if Path(path) not in changes
                ),
                state_artifacts=tuple(
                    path for path in root.state_artifacts if Path(path) not in changes
                ),
            )
        )
    normalized = replace(current, roots=tuple(roots), reasons=(), status=previous.status)
    require_matching_reinspection(reviewed, normalized)
