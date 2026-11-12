"""Synthetic read-only evidence checks, never original-machine acceptance."""

import hashlib
import importlib
import json
import os
import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from swu_happyrun.drivers.identity import device_id
from swu_happyrun.drivers.mumu.enrollment_inspection import DiscoveryScope, inspect_enrollment


def api():
    return importlib.import_module("swu_happyrun.drivers.mumu.enrollment_review_scope")


@pytest.fixture
def observed(tmp_path, monkeypatch):
    host_root = tmp_path / "host"
    host_root.mkdir()
    host = host_root / "host-id"
    host.write_text(str(uuid4()), encoding="ascii")
    manager = tmp_path / "manager.exe"
    manager.write_bytes(b"synthetic manager")
    root = tmp_path / "scan"
    root.mkdir()
    config = tmp_path / "history.conf"
    config.write_text("synthetic", encoding="ascii")
    workdir = tmp_path / "old-workdir"
    monkeypatch.setenv("SWU_HAPPYRUN_HOST_ID_FILE", str(host))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    scope = DiscoveryScope(
        roots=(root,),
        working_directories=(workdir,),
        configuration_sources=(config,),
        unchecked_categories=(),
        declared_complete=True,
    )
    namespace = host.read_text()
    product = device_id("mumu", f"{os.path.normcase(str(manager.resolve()))}:0", host_id=namespace)
    return scope, manager, namespace, product


def observation(observed, **kwargs):
    scope, manager, _, _ = observed
    return inspect_enrollment(scope, manager=manager, instance_index="0", **kwargs)


def build(observed, value=None, **kwargs):
    return api().build_review_scope(
        observation(observed, **kwargs) if value is None else value,
        expected_host_id=observed[2],
        expected_device_id=observed[3],
        **kwargs,
    )


def load(observed, raw, **kwargs):
    return api().load_review_scope(
        raw,
        expected_sha256=hashlib.sha256(raw).hexdigest(),
        expected_host_id=observed[2],
        expected_device_id=observed[3],
        **kwargs,
    )


def encoded(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def existing(observed):
    root = observed[0].roots[0]
    journal = root / "history.sqlite"
    with closing(sqlite3.connect(journal)) as database, database:
        database.execute("CREATE TABLE synthetic (id INTEGER)")
    lock = root / f"device-{hashlib.sha256(observed[3].encode()).hexdigest()}.lock"
    lock.write_bytes(b"0")
    return journal


def test_full_private_roundtrip_missing_candidate_roots_and_public_redaction(observed):
    actual = observation(observed)
    assert actual.status == "first_use_review_required"
    reviewed = build(observed, actual)
    assert reviewed.kind == "new_enrollment"
    assert reviewed.inspection == actual
    assert reviewed.sha256 == hashlib.sha256(reviewed.canonical_bytes).hexdigest()
    restored = load(observed, reviewed.canonical_bytes)
    assert restored.inspection == actual
    assert any(root.missing for root in restored.inspection.roots)
    payload = json.loads(reviewed.canonical_bytes)
    assert payload["schema"] == "enrollment-review-scope-v1"
    assert all(root["sources"] for root in payload["inspection"]["roots"])
    assert payload["inspection"]["observed_at"] == actual.observed_at
    private = str(observed[0].roots[0].parent)
    assert private not in repr(reviewed)
    assert private not in str(reviewed.public_summary())
    assert observed[2] not in str(reviewed.public_summary())
    assert observed[3] not in str(reviewed.public_summary())
    assert reviewed.public_summary()["launch_allowed"] is False


def test_existing_mapping_is_explicit_and_preserves_declared_history(observed):
    journal = existing(observed)
    scope = replace(observed[0], journal_arguments=(journal, journal))
    fixture = (scope, *observed[1:])
    actual = observation(fixture, expected_journal=journal)
    assert actual.status == "existing"
    reviewed = build(fixture, actual, expected_journal=journal)
    assert reviewed.kind == "existing"
    assert reviewed.inspection == actual
    assert load(fixture, reviewed.canonical_bytes, expected_journal=journal).inspection == actual
    with pytest.raises(api().ReviewScopeNotReady):
        build(fixture, actual)
    with pytest.raises(api().ReviewScopeNotReady):
        load(fixture, reviewed.canonical_bytes)


def test_timestamp_only_reinspection_matches_but_original_timestamp_is_retained(observed):
    actual = observation(observed)
    reviewed = build(observed, actual)
    later = replace(observation(observed), observed_at="2030-01-01T00:00:00+00:00")
    assert later.observed_at != actual.observed_at
    api().require_matching_reinspection(reviewed, later)
    assert reviewed.inspection.observed_at == actual.observed_at
    (observed[0].roots[0] / "new-file").write_bytes(b"new evidence")
    with pytest.raises(api().ReviewScopeNotReady):
        api().require_matching_reinspection(reviewed, observation(observed))


def test_full_ledger_digest_cannot_be_replaced_by_summary_digest(observed):
    reviewed = build(observed)
    with pytest.raises(api().ReviewScopeNotReady):
        api().load_review_scope(
            reviewed.canonical_bytes,
            expected_sha256=hashlib.sha256(encoded(reviewed.public_summary())).hexdigest(),
            expected_host_id=observed[2],
            expected_device_id=observed[3],
        )


@pytest.mark.parametrize("field", ["expected_host_id", "expected_device_id"])
def test_independent_identity_binding_rejects_wrong_expected_identity(observed, field):
    args = {"expected_host_id": observed[2], "expected_device_id": observed[3]}
    args[field] = str(uuid4())
    with pytest.raises(api().ReviewScopeNotReady):
        api().build_review_scope(observation(observed), **args)


@pytest.mark.parametrize(
    "forgery",
    ["unchecked", "incomplete", "root_error", "exclusion", "root_omitted", "fake_identity"],
)
def test_success_status_cannot_hide_incomplete_or_unchecked_evidence(observed, forgery):
    actual = observation(observed)
    if forgery == "unchecked":
        actual = replace(actual, unchecked_categories=("other_accounts",))
    elif forgery == "incomplete":
        actual = replace(actual, scope=replace(actual.scope, declared_complete=False))
    elif forgery in {"root_error", "exclusion"}:
        first = actual.roots[0]
        first = replace(
            first,
            **(
                {"errors": ("root_access_denied",)}
                if forgery == "root_error"
                else {"exclusions": (first.path,)}
            ),
        )
        actual = replace(actual, roots=(first, *actual.roots[1:]))
    elif forgery == "root_omitted":
        actual = replace(actual, roots=actual.roots[:-1])
    else:
        actual = replace(actual, device_id=str(uuid4()))
    with pytest.raises(api().ReviewScopeNotReady):
        build(observed, actual)


def test_missing_declared_historical_journal_cannot_be_relabelled_firstuse(observed):
    missing = observed[0].roots[0] / "missing.custom"
    fixture = (replace(observed[0], journal_arguments=(missing,)), *observed[1:])
    actual = observation(fixture)
    assert actual.status == "unknown"
    assert actual.declared_journals[0].status == "missing"
    with pytest.raises(api().ReviewScopeNotReady):
        build(fixture, actual)
    forged = replace(actual, status="first_use_review_required", reasons=())
    with pytest.raises(api().ReviewScopeNotReady):
        build(fixture, forged)
    with pytest.raises(api().ReviewScopeNotReady):
        build(fixture, replace(forged, declared_journals=()))


def test_over_budget_actual_inspector_result_cannot_be_approved(observed):
    for number in range(450):
        (observed[0].roots[0] / f"item-{number}").write_bytes(b"fixture")
    actual = observation(observed)
    assert actual.status == "unknown"
    with pytest.raises(api().ReviewScopeNotReady):
        build(observed, actual)
    forged = replace(actual, status="first_use_review_required", reasons=())
    with pytest.raises(api().ReviewScopeNotReady):
        build(observed, forged)


def test_two_histories_never_approve_even_with_forged_success(observed):
    journal = existing(observed)
    other = journal.with_name("other.sqlite")
    other.write_bytes(journal.read_bytes())
    actual = observation(observed, expected_journal=journal)
    assert actual.status == "unknown"
    for value in (actual, replace(actual, status="existing", reasons=())):
        with pytest.raises(api().ReviewScopeNotReady):
            build(observed, value, expected_journal=journal)


@pytest.mark.parametrize(
    "tamper",
    [
        "extra",
        "root_extra",
        "omitted_root",
        "duplicate_root",
        "sources",
        "count",
        "missing",
        "identity",
        "declared",
        "status",
        "launch",
        "runtime",
        "timestamp",
    ],
)
def test_loader_semantically_rejects_forged_payload(observed, tamper):
    payload = json.loads(build(observed).canonical_bytes)
    value = payload["inspection"]
    if tamper == "extra":
        payload["approval"] = True
    elif tamper == "root_extra":
        value["roots"][0]["reviewed"] = True
    elif tamper == "omitted_root":
        value["roots"].pop()
    elif tamper == "duplicate_root":
        value["roots"].append(value["roots"][0])
    elif tamper == "sources":
        value["roots"][0]["sources"] = []
    elif tamper == "count":
        value["roots"][0]["entry_count"] = True
    elif tamper == "missing":
        value["roots"][0]["missing"] = True
    elif tamper == "identity":
        value["identity_sources"]["host_identity_domain"] = "win32_file_id"
    elif tamper == "declared":
        value["scope"]["journal_arguments"] = [str(observed[0].roots[0] / "lost.sqlite")]
    elif tamper == "status":
        value["status"] = "existing"
    elif tamper == "launch":
        value["launch_allowed"] = True
    elif tamper == "runtime":
        value["runtime_state"] = "verified"
    else:
        value["observed_at"] = "not-a-time"
    with pytest.raises(api().ReviewScopeNotReady):
        load(observed, encoded(payload))


@pytest.mark.parametrize(
    "invalid",
    ["duplicate", "nan", "oversized", "deep"],
    ids=["duplicate", "nan", "oversized", "deep"],
)
def test_strict_json_and_bounded_structure(observed, invalid):
    raw = build(observed).canonical_bytes
    if invalid == "duplicate":
        raw = raw.replace(b'"schema":', b'"schema":"enrollment-review-scope-v1","schema":', 1)
    elif invalid == "nan":
        raw = raw.replace(b'"entry_count":1', b'"entry_count":NaN', 1)
        assert b"NaN" in raw
    elif invalid == "oversized":
        raw = b" " * (api().MAX_REVIEW_SCOPE_BYTES + 1)
    else:
        raw = b"[" * 2000 + b"]" * 2000
    with pytest.raises(api().ReviewScopeNotReady):
        load(observed, raw)


def test_scope_builder_is_read_only_and_copies_mutable_input(observed, monkeypatch):
    actual = observation(observed)
    monkeypatch.setattr(sqlite3, "connect", lambda *args, **kwargs: pytest.fail("SQLite opened"))
    monkeypatch.setattr(Path, "write_bytes", lambda *args, **kwargs: pytest.fail("file written"))
    monkeypatch.setattr(os, "open", lambda *args, **kwargs: pytest.fail("file opened"))
    reviewed = build(observed, actual)
    original = reviewed.canonical_bytes
    actual.identity_sources["host_path"] = "/changed"
    reviewed.inspection.identity_sources["host_path"] = "/also-changed"
    assert reviewed.canonical_bytes == original
    assert load(observed, original).canonical_bytes == original


def test_explicit_unknown_filename_second_history_cannot_hide_behind_selected_db(observed):
    journal = existing(observed)
    hidden = journal.with_name("historical-run-without-extension")
    hidden.write_bytes(journal.read_bytes())
    fixture = (replace(observed[0], journal_arguments=(journal, hidden)), *observed[1:])
    actual = observation(fixture, expected_journal=journal)
    assert actual.status == "unknown"
    assert len(actual.declared_journals) == 2
    with pytest.raises(api().ReviewScopeNotReady):
        build(fixture, replace(actual, status="existing", reasons=()), expected_journal=journal)


@pytest.mark.parametrize("incomplete", ["depth", "roots", "config", "unchecked"])
def test_actual_inspector_incomplete_scope_is_rejected(observed, incomplete):
    fixture = observed
    if incomplete == "depth":
        (observed[0].roots[0] / "a/b/c/d/e").mkdir(parents=True)
    elif incomplete == "roots":
        roots = tuple(observed[0].roots[0] / str(index) for index in range(33))
        fixture = (replace(observed[0], roots=roots), *observed[1:])
    elif incomplete == "config":
        observed[0].configuration_sources[0].unlink()
    else:
        fixture = (replace(observed[0], unchecked_categories=("other_accounts",)), *observed[1:])
    actual = observation(fixture)
    assert actual.status == "unknown"
    with pytest.raises(api().ReviewScopeNotReady):
        build(fixture, actual)


def test_missing_root_becoming_present_is_changed_scope(observed):
    reviewed = build(observed)
    (observed[0].working_directories[0] / "local").mkdir(parents=True)
    later = observation(observed)
    assert later.status == "first_use_review_required"
    with pytest.raises(api().ReviewScopeNotReady):
        api().require_matching_reinspection(reviewed, later)


def test_existing_mutable_sql_contents_are_not_permanently_hash_pinned(observed):
    journal = existing(observed)
    reviewed = build(observed, expected_journal=journal)
    with closing(sqlite3.connect(journal)) as database, database:
        database.execute("INSERT INTO synthetic VALUES (1)")
    api().require_matching_reinspection(reviewed, observation(observed, expected_journal=journal))


def test_reinspection_never_trusts_constructed_wrapper(observed):
    payload = json.loads(build(observed).canonical_bytes)
    payload["inspection"]["roots"][0]["entry_count"] = -1
    forged = api().ReviewedScope(encoded(payload))
    with pytest.raises(api().ReviewScopeNotReady):
        api().require_matching_reinspection(forged, observation(observed))


def test_reinspection_checks_size_before_json_decode(observed, monkeypatch):
    forged = api().ReviewedScope(b" " * (api().MAX_REVIEW_SCOPE_BYTES + 1))
    monkeypatch.setattr(api().json, "loads", lambda *a, **k: pytest.fail("unbounded JSON decoded"))
    with pytest.raises(api().ReviewScopeNotReady):
        api().require_matching_reinspection(forged, observation(observed))
