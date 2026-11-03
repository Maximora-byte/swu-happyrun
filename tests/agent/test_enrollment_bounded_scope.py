"""Synthetic v2 coverage evidence, not human history or execution approval."""

import json
from dataclasses import replace

import pytest
from test_enrollment_review_scope import (  # noqa: F401
    build,
    encoded,
    load,
    observation,
)
from test_enrollment_review_scope import (
    observed as observed,
)
from test_enrollment_transaction import synthetic as synthetic  # noqa: F401

from swu_happyrun.drivers.mumu import enrollment_inspection as discovery
from swu_happyrun.drivers.mumu import enrollment_review_scope as ledger


def bounded(observed):
    assert hasattr(discovery, "BoundedDiscoveryScope"), "explicit bounded v2 scope is missing"
    original, manager, host, product = observed
    scope = discovery.BoundedDiscoveryScope(**vars(original))
    for index in range(600):
        (scope.roots[0] / f"ordinary-{index}.txt").write_text("synthetic")
    return scope, manager, host, product


def test_v2_scans_beyond_450_and_pinned_ledger_roundtrips(observed):
    v2 = bounded(observed)
    assert observation(observed).status == "unknown"
    current = observation(v2)
    assert current.status == "first_use_review_required"
    assert sum(root.entry_count for root in current.roots) > 450
    reviewed = build(v2, current)
    payload = json.loads(reviewed.canonical_bytes)
    assert payload["schema"] == "enrollment-review-scope-v2"
    assert payload["scan_policy"] == {
        "page_entries": 450,
        "max_pages": 64,
        "max_depth": 8,
        "max_roots": 32,
    }
    restored = load(v2, reviewed.canonical_bytes)
    assert type(restored.inspection.scope) is discovery.BoundedDiscoveryScope
    ledger.require_matching_reinspection(restored, observation(v2))
    assert restored.execution_allowed is False


def test_v2_cannot_make_unchecked_history_complete(observed):
    v2 = bounded(observed)
    scope = replace(v2[0], unchecked_categories=discovery._UNCHECKED)
    current = observation((scope, *v2[1:]))
    assert current.status == "unknown"
    assert current.unchecked_categories == discovery._UNCHECKED
    assert "historical_scope_incomplete" in current.reasons
    with pytest.raises(ledger.ReviewScopeNotReady):
        build(v2, current)


@pytest.mark.parametrize("change", ["policy", "schema", "count", "unchecked", "missing_policy"])
def test_v2_tampered_ledger_fails_even_with_recomputed_hash(observed, change):
    v2 = bounded(observed)
    payload = json.loads(build(v2).canonical_bytes)
    if change == "policy":
        payload["scan_policy"]["max_pages"] = 100000
    elif change == "schema":
        payload["schema"] = "enrollment-review-scope-v1"
    elif change == "count":
        payload["inspection"]["roots"][0]["entry_count"] = 28800
    elif change == "unchecked":
        payload["inspection"]["scope"]["unchecked_categories"] = ["legacy_writers"]
    else:
        del payload["scan_policy"]
    with pytest.raises(ledger.ReviewScopeNotReady):
        load(v2, encoded(payload))


def test_v2_reinspection_detects_new_candidate_not_only_old_report(observed):
    v2 = bounded(observed)
    reviewed = build(v2)
    (v2[0].roots[0] / "late.sqlite").write_bytes(b"not a database")
    current = observation(v2)
    assert current.status == "unknown"
    with pytest.raises(ledger.ReviewScopeNotReady):
        ledger.require_matching_reinspection(reviewed, current)


@pytest.mark.parametrize("existing", [False, True])
def test_fixed_initializer_and_pin_reinspect_v2_beyond_450(synthetic, monkeypatch, existing):
    assert hasattr(discovery, "BoundedDiscoveryScope"), "explicit bounded v2 scope is missing"
    import test_enrollment_transaction as fixture

    from swu_happyrun.drivers.mumu.enrollment_pin_reviewer import issue_fixed_pin
    from swu_happyrun.drivers.mumu.enrollment_review_pin import ReviewPinAnchors
    from swu_happyrun.drivers.mumu.enrollment_runner import (
        initialize_fixed_candidate,
        inspect_fixed_pin,
    )

    _, _, bundle = synthetic

    def scope(*args, **kwargs):
        result = discovery.BoundedDiscoveryScope(*args, **kwargs)
        for index in range(500):
            (result.roots[0] / f"ordinary-{index}.txt").write_text("synthetic")
        return result

    monkeypatch.setattr(fixture, "DiscoveryScope", scope)
    root, anchors, reviewed, _, _ = bundle(existing=existing, nested=True)
    assert json.loads(reviewed.canonical_bytes)["schema"] == "enrollment-review-scope-v2"
    initialized = initialize_fixed_candidate(anchors)
    assert initialized.status == "candidate_unpinned"
    assert initialized.execution_allowed is False
    issued = issue_fixed_pin(anchors)
    assert issued.status == "candidate_pinned"
    pins = ReviewPinAnchors(anchors, issued.file, issued.parent_identity, "original-machine-codex")
    inspected = inspect_fixed_pin(pins)
    assert inspected.status == "candidate_pinned"
    assert inspected.execution_allowed is False


def test_v2_records_nested_directory_identity():
    assert "directory_identities" in discovery.RootInspection.__dataclass_fields__, (
        "v2 must bind nested directory identities, not just root identity and counts"
    )


def test_v2_reinspection_rejects_replaced_nested_directory(observed):
    v2 = bounded(observed)
    nested = v2[0].roots[0] / "nested"
    nested.mkdir()
    reviewed = build(v2)
    nested.rename(nested.parent.parent / "old-nested")
    nested.mkdir()
    with pytest.raises(ledger.ReviewScopeNotReady):
        ledger.require_matching_reinspection(reviewed, observation(v2))


def test_v2_cross_root_change_fails_closed(observed, monkeypatch):
    v2 = bounded(observed)
    from swu_happyrun.drivers.mumu import enrollment_coverage

    original = enrollment_coverage.scan
    first = []

    def scan(root, *args, **kwargs):
        result = original(root, *args, **kwargs)
        if not first:
            first.append(root)
        elif root == v2[0].roots[0]:
            (first[0] / "late.txt").write_text("late change")
        return result

    monkeypatch.setattr(enrollment_coverage, "scan", scan)
    current = observation(v2)
    assert current.status == "unknown"
    assert "directory_changed" in current.reasons


def test_v2_ledger_rejects_directory_without_scanned_parent(observed):
    v2 = bounded(observed)
    nested = v2[0].roots[0] / "nested"
    nested.mkdir()
    payload = json.loads(build(v2).canonical_bytes)
    root = next(
        item for item in payload["inspection"]["roots"] if item["path"] == str(nested.parent)
    )
    item = next(item for item in root["directory_identities"] if item[0] == str(nested))
    item[0] = str(nested.parent / "unscanned" / "nested")
    with pytest.raises(ledger.ReviewScopeNotReady):
        load(v2, encoded(payload))
