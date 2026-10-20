"""Strict private discovery ledgers, not an approval or execution authority.

The digest covers the entire original observation, including its timestamp.
Fresh reinspection comparison ignores only that timestamp. It compares recorded
inventory facts, not arbitrary file contents: the inspector does not hash SQL or
historical configuration files. Independently pinned immutable approval targets
and locked runtime SQL validation remain necessary. A valid ledger cannot prove
that a human's historical scope declaration was truthful or complete; a private
reviewed runner must supply the expected digest and require fresh inspection.

All parsing and comparison here is pure: no files, SQLite, locks, device calls,
or approval artifacts are opened or written. Raw paths occur only in the private
canonical bytes and reconstructed inspection; repr/public_summary are sanitized.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from swu_happyrun.drivers.identity import device_id

from .enrollment_inspection import (
    MAX_SCAN_DEPTH,
    MAX_SCAN_ENTRIES,
    MAX_SCAN_ROOTS,
    BoundedDiscoveryScope,
    DeclaredJournalInspection,
    DiscoveryScope,
    EnrollmentInspection,
    RootInspection,
)

MAX_REVIEW_SCOPE_BYTES = 2 * 1024 * 1024
_SCHEMA = "enrollment-review-scope-v1"
_SCHEMA_V2 = "enrollment-review-scope-v2"
# Literal, versioned policy: neither a caller budget nor a trusted resume cursor.
_POLICY_V2 = {"page_entries": 450, "max_pages": 64, "max_depth": 8, "max_roots": 32}

_SOURCE_KEYS = {
    "host_path",
    "host_override",
    "default_host_path",
    "LOCALAPPDATA",
    "XDG_CONFIG_HOME",
    "manager_path",
    "instance_index",
    "host_identity_domain",
    "host_identity",
    "manager_identity",
}
_ROOT_KEYS = {
    "path",
    "identity_domain",
    "identity",
    "entry_count",
    "file_count",
    "exclusions",
    "errors",
    "candidate_journals",
    "state_artifacts",
    "missing",
    "sources",
}
_SCOPE_KEYS = {
    "roots",
    "journal_arguments",
    "working_directories",
    "configuration_sources",
    "unchecked_categories",
    "declared_complete",
}
_INSPECTION_KEYS = {
    "status",
    "reasons",
    "roots",
    "identity_sources",
    "scope",
    "observed_at",
    "unchecked_categories",
    "host_id",
    "device_id",
    "runtime_state",
    "launch_allowed",
    "declared_journals",
}


class ReviewScopeNotReady(RuntimeError):
    def __init__(self):
        super().__init__("enrollment_review_scope_not_ready")


def _require(condition):
    if not condition:
        raise ReviewScopeNotReady()


def _keys(value, keys):
    _require(type(value) is dict and set(value) == keys)


def _path(value):
    _require(type(value) is str and 1 <= len(value) <= 1024 and "\x00" not in value)
    path = Path(value)
    _require(
        str(path) == value
        and path.is_absolute()
        and ".." not in path.parts
        and not value.startswith(("//", "\\\\"))
        and len(path.parts) <= 64
    )
    return path


def _identity(value, *, optional=False):
    if value is None and optional:
        return None
    _require(type(value) is list and len(value) == 2)
    _require(type(value[0]) is int and value[0] >= 0)
    _require(type(value[1]) is int and value[1] > 0)
    return tuple(value)


def _uuid(value):
    _require(type(value) is str and len(value) == 36 and str(UUID(value)) == value)
    return value


def _list(value, limit=MAX_SCAN_ROOTS):
    _require(type(value) is list and len(value) <= limit)
    return value


def _paths(value, limit=MAX_SCAN_ROOTS):
    return tuple(_path(item) for item in _list(value, limit))


def _empty(value):
    _require(type(value) is list and not value)


def _digest(value):
    _require(type(value) is str and re.fullmatch("[0-9a-f]{64}", value) is not None)
    return value


def _canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def _constant(_):
    raise ReviewScopeNotReady()


def _bounded(value, *, v2=False):
    pending, count = [(value, 0)], 0
    while pending:
        node, depth = pending.pop()
        count += 1
        _require(count <= (262144 if v2 else 8192) and depth <= (10 if v2 else 8))
        if type(node) is dict:
            _require(len(node) <= 32 and all(type(key) is str and len(key) <= 64 for key in node))
            pending.extend((item, depth + 1) for item in node.values())
        elif type(node) is list:
            _require(len(node) <= (28800 if v2 else MAX_SCAN_ENTRIES))
            pending.extend((item, depth + 1) for item in node)
        else:
            _require(node is None or type(node) in (str, int, bool))
            if type(node) is str:
                _require(len(node) <= 1024)


def _root_sources(scope, sources, journal):
    result = {}

    def add(path, label):
        result.setdefault(str(path), []).append(label)

    add(_path(sources["host_path"]).parent, "host_parent")
    add(_path(sources["default_host_path"]).parent, "default_state_root")
    for index, path in enumerate(scope["roots"]):
        add(_path(path), f"roots[{index}]")
    for index, path in enumerate(scope["journal_arguments"]):
        add(_path(path).parent, f"journal_arguments[{index}]")
    for index, path in enumerate(scope["working_directories"]):
        add(_path(path) / "local", f"working_directories[{index}]")
    if journal is not None:
        add(_path(journal).parent, "expected_journal_parent")
    return result


def _validate(payload, expected_host_id, expected_device_id, expected_journal):
    """Structural checks precede semantic derivation; no asserted success is trusted."""
    v2 = type(payload) is dict and payload.get("schema") == _SCHEMA_V2
    _bounded(payload, v2=v2)
    _keys(
        payload,
        {"schema", "kind", "expected_journal", "inspection"} | ({"scan_policy"} if v2 else set()),
    )
    _require(payload["schema"] == (_SCHEMA_V2 if v2 else _SCHEMA))
    if v2:
        _keys(payload["scan_policy"], set(_POLICY_V2))
        _require(all(type(value) is int for value in payload["scan_policy"].values()))
        _require(payload["scan_policy"] == _POLICY_V2)
    max_entries = 28800 if v2 else MAX_SCAN_ENTRIES
    max_depth = 8 if v2 else MAX_SCAN_DEPTH
    _require(payload["expected_journal"] == expected_journal)
    if expected_journal is not None:
        _path(expected_journal)
    value = payload["inspection"]
    _keys(value, _INSPECTION_KEYS)
    scope = value["scope"]
    _keys(scope, _SCOPE_KEYS)
    for name in ("roots", "journal_arguments", "working_directories", "configuration_sources"):
        _paths(scope[name])
    _require(scope["declared_complete"] is True)
    _empty(scope["unchecked_categories"])
    _empty(value["unchecked_categories"])
    _empty(value["reasons"])
    _require(value["runtime_state"] == "unverified" and value["launch_allowed"] is False)
    observed = value["observed_at"]
    _require(type(observed) is str and 20 <= len(observed) <= 40)
    parsed = datetime.fromisoformat(observed)
    _require(parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0))
    host = _uuid(value["host_id"])
    product = _uuid(value["device_id"])
    _require(host == _uuid(expected_host_id) and product == _uuid(expected_device_id))
    sources = value["identity_sources"]
    _keys(sources, _SOURCE_KEYS)
    host_path = _path(sources["host_path"])
    default_host_path = _path(sources["default_host_path"])
    manager = _path(sources["manager_path"])
    for name in ("host_override", "LOCALAPPDATA", "XDG_CONFIG_HOME"):
        if sources[name] is not None:
            _path(sources[name])
    if sources["host_override"] is not None:
        _require(host_path == _path(sources["host_override"]))
    else:
        _require(host_path == default_host_path)
    _require(
        default_host_path.name == "host-id" and default_host_path.parent.name == "swu-happyrun"
    )
    environment_root = sources["LOCALAPPDATA" if os.name == "nt" else "XDG_CONFIG_HOME"]
    if environment_root is not None:
        _require(default_host_path == _path(environment_root) / "swu-happyrun" / "host-id")
    _require(sources["host_identity_domain"] == "python_stat")
    _identity(sources["host_identity"])
    _identity(sources["manager_identity"])
    index = sources["instance_index"]
    _require(type(index) is str and re.fullmatch("0|[1-9][0-9]{0,8}", index) is not None)
    identifier = f"{os.path.normcase(str(manager))}:{index}"
    _require(device_id("mumu", identifier, host_id=host) == product)
    expected_roots = _root_sources(scope, sources, expected_journal)
    _require(1 <= len(expected_roots) <= MAX_SCAN_ROOTS)
    roots = _list(value["roots"])
    _require(
        [item.get("path") if type(item) is dict else None for item in roots] == list(expected_roots)
    )
    count = 0
    identities = set()
    candidates, artifacts = set(), set()
    for root in roots:
        _keys(root, _ROOT_KEYS | ({"directory_identities"} if v2 else set()))
        path = _path(root["path"])
        _require(root["sources"] == expected_roots[root["path"]])
        _require(root["identity_domain"] == "python_stat")
        identity = _identity(root["identity"], optional=True)
        _require(type(root["missing"]) is bool)
        _empty(root["errors"])
        _empty(root["exclusions"])
        entries, files = root["entry_count"], root["file_count"]
        _require(
            type(entries) is int and type(files) is int and 0 <= files <= entries < max_entries
        )
        count += entries
        _require(count < max_entries)
        if v2:
            directories = _list(root["directory_identities"], max_entries)
            seen_paths, seen_ids = set(), set()
            for directory in directories:
                _require(type(directory) is list and len(directory) == 2)
                directory_path = _path(directory[0])
                directory_identity = _identity(directory[1])
                _require(len(directory_path.relative_to(path).parts) <= max_depth)
                _require(directory_path not in seen_paths and directory_identity not in seen_ids)
                seen_paths.add(directory_path)
                seen_ids.add(directory_identity)
            _require([item[0] for item in directories] == sorted(str(item) for item in seen_paths))
            _require(len(directories) == (0 if root["missing"] else entries - files + 1))
            if not root["missing"]:
                _require([str(path), root["identity"]] in directories)
            _require(all(item == path or item.parent in seen_paths for item in seen_paths))

        journals = _paths(root["candidate_journals"], max_entries)
        states = _paths(root["state_artifacts"], max_entries)
        _require(len(set(journals)) == len(journals) and len(set(states)) == len(states))
        _require(len(set(journals) | set(states)) <= files)
        for item in (*journals, *states):
            if v2:
                _require(item.parent in seen_paths)
            relative = item.relative_to(path)
            _require(1 <= len(relative.parts) <= max_depth + 1)
        _require(
            all(item.name.lower().endswith((".sqlite", ".sqlite3", ".db")) for item in journals)
        )
        _require(
            all(
                item.name.lower().startswith(("device-", "replay-", "enrollment-"))
                or item.name.lower().endswith(("-wal", "-shm", "-journal"))
                or item.name.lower() == "mumu-experiment-registration.json"
                for item in states
            )
        )
        if root["missing"]:
            _require(identity is None and entries == files == 0 and not journals and not states)
            _require(path != host_path.parent)
        else:
            _require(identity is not None and identity not in identities)
            identities.add(identity)
        candidates.update(str(item) for item in journals)
        artifacts.update(str(item) for item in states)
    declarations = _list(value["declared_journals"])
    declared_paths = list(dict.fromkeys(scope["journal_arguments"]))
    _require(
        [item.get("path") if type(item) is dict else None for item in declarations]
        == declared_paths
    )
    declared_identities = set()
    for declaration in declarations:
        _keys(declaration, {"path", "status", "identity", "identity_domain", "errors"})
        path = _path(declaration["path"])
        _require(
            declaration["status"] == "present" and declaration["identity_domain"] == "python_stat"
        )
        identity = _identity(declaration["identity"])
        _require(identity not in declared_identities)
        declared_identities.add(identity)
        _empty(declaration["errors"])
        containing = next(item for item in roots if item["path"] == str(path.parent))
        _require(not containing["missing"] and containing["file_count"] > 0)
        candidates.add(str(path))
    if candidates:
        _require(expected_journal is not None and candidates == {expected_journal})
        expected_lock = str(
            Path(expected_journal).parent
            / f"device-{hashlib.sha256(product.encode()).hexdigest()}.lock"
        )
        _require(artifacts == {expected_lock})
        derived_kind, derived_status = "existing", "existing"
    else:
        _require(expected_journal is None and not declarations and not artifacts)
        derived_kind, derived_status = "new_enrollment", "first_use_review_required"
    _require(payload["kind"] == derived_kind and value["status"] == derived_status)


def _serialize(inspection, expected_journal):
    _require(
        type(inspection) is EnrollmentInspection
        and type(inspection.scope) in (DiscoveryScope, BoundedDiscoveryScope)
    )
    v2 = type(inspection.scope) is BoundedDiscoveryScope
    scope = inspection.scope
    declaration = {
        "roots": [str(path) for path in scope.roots],
        "journal_arguments": [str(path) for path in scope.journal_arguments],
        "working_directories": [str(path) for path in scope.working_directories],
        "configuration_sources": [str(path) for path in scope.configuration_sources],
        "unchecked_categories": list(scope.unchecked_categories),
        "declared_complete": scope.declared_complete,
    }
    # The round trip detaches nested mutable data supplied by the caller.
    sources = json.loads(_canonical(inspection.identity_sources))
    expected_roots = _root_sources(declaration, sources, expected_journal)
    roots = []
    for root in inspection.roots:
        _require(type(root) is RootInspection)
        roots.append(
            {
                "path": root.path,
                "identity_domain": root.identity_domain,
                "identity": list(root.identity) if root.identity is not None else None,
                "entry_count": root.entry_count,
                "file_count": root.file_count,
                "exclusions": list(root.exclusions),
                "errors": list(root.errors),
                "candidate_journals": list(root.candidate_journals),
                "state_artifacts": list(root.state_artifacts),
                "missing": root.missing,
                "sources": expected_roots.get(root.path, []),
                **(
                    {
                        "directory_identities": [
                            [path, list(identity)] for path, identity in root.directory_identities
                        ]
                    }
                    if v2
                    else {}
                ),
            }
        )
    journals = []
    for item in inspection.declared_journals:
        _require(type(item) is DeclaredJournalInspection)
        journals.append(
            {
                "path": item.path,
                "status": item.status,
                "identity": list(item.identity) if item.identity is not None else None,
                "identity_domain": item.identity_domain,
                "errors": list(item.errors),
            }
        )
    return {
        "schema": _SCHEMA_V2 if v2 else _SCHEMA,
        **({"scan_policy": dict(_POLICY_V2)} if v2 else {}),
        "kind": "existing" if expected_journal is not None else "new_enrollment",
        "expected_journal": expected_journal,
        "inspection": {
            "status": inspection.status,
            "reasons": list(inspection.reasons),
            "roots": roots,
            "identity_sources": sources,
            "scope": declaration,
            "observed_at": inspection.observed_at,
            "unchecked_categories": list(inspection.unchecked_categories),
            "host_id": inspection.host_id,
            "device_id": inspection.device_id,
            "runtime_state": inspection.runtime_state,
            "launch_allowed": inspection.launch_allowed,
            "declared_journals": journals,
        },
    }


def _inspection(payload):
    value = payload["inspection"]
    scope = value["scope"]
    sources = value["identity_sources"]
    for name in ("host_identity", "manager_identity"):
        sources[name] = tuple(sources[name])
    return EnrollmentInspection(
        status=value["status"],
        reasons=tuple(value["reasons"]),
        roots=tuple(
            RootInspection(
                path=root["path"],
                identity_domain=root["identity_domain"],
                identity=tuple(root["identity"]) if root["identity"] is not None else None,
                entry_count=root["entry_count"],
                file_count=root["file_count"],
                exclusions=tuple(root["exclusions"]),
                errors=tuple(root["errors"]),
                candidate_journals=tuple(root["candidate_journals"]),
                state_artifacts=tuple(root["state_artifacts"]),
                missing=root["missing"],
                directory_identities=tuple(
                    (item[0], tuple(item[1])) for item in root.get("directory_identities", [])
                ),
            )
            for root in value["roots"]
        ),
        identity_sources=sources,
        scope=(BoundedDiscoveryScope if payload["schema"] == _SCHEMA_V2 else DiscoveryScope)(
            roots=tuple(Path(path) for path in scope["roots"]),
            journal_arguments=tuple(Path(path) for path in scope["journal_arguments"]),
            working_directories=tuple(Path(path) for path in scope["working_directories"]),
            configuration_sources=tuple(Path(path) for path in scope["configuration_sources"]),
            unchecked_categories=tuple(scope["unchecked_categories"]),
            declared_complete=scope["declared_complete"],
        ),
        observed_at=value["observed_at"],
        unchecked_categories=tuple(value["unchecked_categories"]),
        host_id=value["host_id"],
        device_id=value["device_id"],
        runtime_state=value["runtime_state"],
        launch_allowed=value["launch_allowed"],
        declared_journals=tuple(
            DeclaredJournalInspection(
                path=item["path"],
                status=item["status"],
                identity=tuple(item["identity"]) if item["identity"] is not None else None,
                identity_domain=item["identity_domain"],
                errors=tuple(item["errors"]),
            )
            for item in value["declared_journals"]
        ),
    )


@dataclass(frozen=True, repr=False)
class ReviewedScope:
    """Detached private evidence; constructing this object grants no authority."""

    canonical_bytes: bytes = field(repr=False)
    execution_allowed: bool = field(default=False, init=False)

    @property
    def sha256(self):
        return hashlib.sha256(self.canonical_bytes).hexdigest()

    @property
    def kind(self):
        return json.loads(self.canonical_bytes)["kind"]

    @property
    def inspection(self):
        return _inspection(json.loads(self.canonical_bytes))

    def public_summary(self):
        return {**self.inspection.public_summary(), "kind": self.kind, "execution_allowed": False}


def build_review_scope(
    inspection: EnrollmentInspection,
    *,
    expected_host_id: str,
    expected_device_id: str,
    expected_journal: Path | None = None,
) -> ReviewedScope:
    """Validate and serialize actual inspector evidence without issuing approval."""
    try:
        _require(expected_journal is None or isinstance(expected_journal, Path))
        journal = str(expected_journal) if expected_journal is not None else None
        payload = _serialize(inspection, journal)
        _validate(payload, expected_host_id, expected_device_id, journal)
        raw = _canonical(payload)
        _require(len(raw) <= MAX_REVIEW_SCOPE_BYTES)
        return ReviewedScope(raw)
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, StopIteration):
        raise ReviewScopeNotReady() from None


def load_review_scope(
    raw: bytes,
    *,
    expected_sha256: str,
    expected_host_id: str,
    expected_device_id: str,
    expected_journal: Path | None = None,
) -> ReviewedScope:
    """Load canonical full-ledger bytes against an independently trusted plan pin."""
    try:
        _require(type(raw) is bytes and 1 <= len(raw) <= MAX_REVIEW_SCOPE_BYTES)
        _require(hashlib.sha256(raw).hexdigest() == _digest(expected_sha256))
        _require(expected_journal is None or isinstance(expected_journal, Path))
        journal = str(expected_journal) if expected_journal is not None else None
        payload = json.loads(raw, object_pairs_hook=_unique, parse_constant=_constant)
        _validate(payload, expected_host_id, expected_device_id, journal)
        _require(_canonical(payload) == raw)
        return ReviewedScope(raw)
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, StopIteration):
        raise ReviewScopeNotReady() from None


def require_matching_reinspection(
    reviewed: ReviewedScope, inspection: EnrollmentInspection
) -> None:
    """Require a fresh actual inspection; only its observation timestamp may differ.

    The caller must rerun inspect_enrollment with the ledger's original scope,
    manager, instance index and selected journal, under the appropriate admission
    protections. Reusing the old dataclass is not reinspection or authorization.
    """
    try:
        _require(type(reviewed) is ReviewedScope)
        _require(
            type(reviewed.canonical_bytes) is bytes
            and 1 <= len(reviewed.canonical_bytes) <= MAX_REVIEW_SCOPE_BYTES
        )
        previous = json.loads(
            reviewed.canonical_bytes, object_pairs_hook=_unique, parse_constant=_constant
        )
        _bounded(previous, v2=previous.get("schema") == _SCHEMA_V2)
        original = previous["inspection"]
        journal = previous["expected_journal"]
        load_review_scope(
            reviewed.canonical_bytes,
            expected_sha256=reviewed.sha256,
            expected_host_id=original["host_id"],
            expected_device_id=original["device_id"],
            expected_journal=Path(journal) if journal is not None else None,
        )
        current = build_review_scope(
            inspection,
            expected_host_id=original["host_id"],
            expected_device_id=original["device_id"],
            expected_journal=Path(journal) if journal is not None else None,
        )
        latest = json.loads(current.canonical_bytes)
        latest["inspection"]["observed_at"] = original["observed_at"]
        _require(latest == previous)
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, StopIteration):
        raise ReviewScopeNotReady() from None
