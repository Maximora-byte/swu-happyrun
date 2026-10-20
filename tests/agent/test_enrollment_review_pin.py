"""Synthetic independent-pin checks, never Windows/device acceptance."""

import importlib
import importlib.util
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest
from test_enrollment_transaction import TX, identity, pin
from test_enrollment_transaction import synthetic as synthetic  # noqa: F401

from swu_happyrun.agent.journal import RunJournal
from swu_happyrun.drivers.base import DriverError
from swu_happyrun.drivers.mumu.enrollment import require_native_enrollment
from swu_happyrun.drivers.mumu.instance_attribution import FileIdentity

REVIEWER = "original-machine-codex"


def modules():
    names = ["enrollment_review_pin", "enrollment_pin_reviewer"]
    for name in names:
        assert importlib.util.find_spec("swu_happyrun.drivers.mumu." + name), name + " missing"
    return tuple(importlib.import_module("swu_happyrun.drivers.mumu." + n) for n in names)


def complete(synthetic):
    transaction, state, bundle = synthetic
    root, anchors, reviewed, plan, paths = bundle(nested=True)
    assert transaction.initialize_candidate(anchors, reviewed).status == "candidate_unpinned"
    return transaction, state, root, anchors, reviewed, plan, paths


def issue(synthetic):
    result = complete(synthetic)
    loader, reviewer = modules()
    transaction, state, root, anchors, reviewed, plan, paths = result
    publication = reviewer.issue_review_pin(anchors, reviewed, reviewer_id=REVIEWER)
    assert publication.status == "candidate_pinned"
    assert publication.execution_allowed is False
    pinned = loader.ReviewPinAnchors(
        anchors, publication.file, publication.parent_identity, REVIEWER
    )
    return (*result, loader, reviewer, publication, pinned)


def test_pin_modules_exist():
    modules()


@pytest.mark.parametrize("existing", [False, True])
def test_issue_and_read_pin_readonly_never_ready(synthetic, monkeypatch, existing):
    transaction, state, bundle = synthetic
    root, anchors, reviewed, plan, paths = bundle(existing=existing, nested=True)
    assert transaction.initialize_candidate(anchors, reviewed).status == "candidate_unpinned"
    loader, reviewer = modules()
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: pytest.fail("pin SQLite"))
    monkeypatch.setattr(Path, "mkdir", lambda *a, **k: pytest.fail("pin mkdir"))
    publication = reviewer.issue_review_pin(anchors, reviewed, reviewer_id=REVIEWER)
    assert publication.status == "candidate_pinned"
    assert publication.execution_allowed is False
    file = root / "reviews" / anchors.plan_sha256 / "review-pin-v1.json"
    assert publication.file == pin(file)
    pinned = loader.ReviewPinAnchors(
        anchors, publication.file, publication.parent_identity, REVIEWER
    )
    before = {
        p: (identity(p), p.read_bytes())
        for p in paths["journal"].parent.parent.rglob("*")
        if p.is_file()
    }
    events = len(state["events"])
    result = loader.load_review_pin(pinned, reviewed)
    assert result.status == "candidate_pinned"
    assert result.execution_allowed is False
    assert result.record.expires_at == plan["expires_at"]
    assert len(state["events"]) == events
    assert before == {
        p: (identity(p), p.read_bytes())
        for p in paths["journal"].parent.parent.rglob("*")
        if p.is_file()
    }
    for value in (result, publication, pinned, anchors, result.record, True, {"approved": True}):
        with pytest.raises(DriverError, match="enrollment_execution_not_ready"):
            require_native_enrollment(value)


def test_journal_intent_and_result_changes_preserve_pin_not_ready(synthetic):
    (
        transaction,
        state,
        root,
        anchors,
        reviewed,
        plan,
        paths,
        loader,
        reviewer,
        publication,
        pinned,
    ) = issue(synthetic)
    before = (root / "transactions" / TX / "stage-04.json").read_bytes()
    with RunJournal(paths["journal"]) as db:
        with db.device_lock(plan["device_id"]):
            db.record_intent("later", 1, "start")
            db.record_result("later", 1, "start", "confirmed")
    result = loader.load_review_pin(pinned, reviewed)
    assert result.status == "candidate_pinned"
    assert result.execution_allowed is False
    assert (root / "transactions" / TX / "stage-04.json").read_bytes() == before
    record = json.loads(result.record.canonical_bytes)
    assert set(record["journal"]) == {"path", "identity", "parent_identity"}


def test_any_tampered_stage_rejects_without_repair(synthetic):
    (
        transaction,
        state,
        root,
        anchors,
        reviewed,
        plan,
        paths,
        loader,
        reviewer,
        publication,
        pinned,
    ) = issue(synthetic)
    events = len(state["events"])
    for stage in range(1, 8):
        assert loader.load_review_pin(pinned, reviewed).status == "candidate_pinned", stage
        file = root / "transactions" / TX / f"stage-{stage:02d}.json"
        original = file.read_bytes()
        file.write_bytes(original + b" ")
        assert loader.load_review_pin(pinned, reviewed).status == "incomplete", stage
        assert file.read_bytes() == original + b" "
        file.write_bytes(original)
    assert len(state["events"]) == events


def test_existing_pin_cannot_be_reissued_or_initializer_adopted(synthetic):
    (
        transaction,
        state,
        root,
        anchors,
        reviewed,
        plan,
        paths,
        loader,
        reviewer,
        publication,
        pinned,
    ) = issue(synthetic)
    before = {
        p: (identity(p), p.read_bytes())
        for p in paths["journal"].parent.parent.rglob("*")
        if p.is_file()
    }
    events = len(state["events"])
    assert reviewer.issue_review_pin(anchors, reviewed, reviewer_id=REVIEWER).status == "incomplete"
    assert transaction.initialize_candidate(anchors, reviewed).status == "incomplete"
    assert len(state["events"]) == events
    assert before == {
        p: (identity(p), p.read_bytes())
        for p in paths["journal"].parent.parent.rglob("*")
        if p.is_file()
    }


@pytest.mark.parametrize("event", ["create", "write", "fsync", "flush", "move"])
def test_publish_failure_retains_pin_attempt_without_repair(synthetic, event):
    transaction, state, root, anchors, reviewed, plan, paths = complete(synthetic)
    loader, reviewer = modules()
    state["fault"] = event
    assert reviewer.issue_review_pin(anchors, reviewed, reviewer_id=REVIEWER).status == "incomplete"
    assert state["events"][-1] == event
    if event == "create":
        return  # No persisted attempt exists when CREATE_NEW itself failed.
    before = {
        p: (identity(p), p.read_bytes())
        for p in paths["journal"].parent.parent.rglob("*")
        if p.is_file()
    }
    events = len(state["events"])
    state["fault"] = None
    assert reviewer.issue_review_pin(anchors, reviewed, reviewer_id=REVIEWER).status == "incomplete"
    assert len(state["events"]) == events
    assert before == {
        p: (identity(p), p.read_bytes())
        for p in paths["journal"].parent.parent.rglob("*")
        if p.is_file()
    }


@pytest.mark.parametrize("halt", ["expiry", "revocation"])
@pytest.mark.parametrize("event", ["create", "write", "fsync", "flush", "move"])
def test_authority_at_each_pin_mutation_stops_immediately(synthetic, event, halt):
    transaction, state, root, anchors, reviewed, plan, paths = complete(synthetic)
    loader, reviewer = modules()
    start = len(state["events"])

    def change(name):
        if name == event:
            if halt == "expiry":
                state["now"] = 1000
            else:
                authority = root / "authority-v1.json"
                original = json.loads(authority.read_bytes())
                original["revoked_plan_sha256"] = [anchors.plan_sha256]
                authority.write_text(json.dumps(original), encoding="utf-8")

    state["after"] = change
    assert reviewer.issue_review_pin(anchors, reviewed, reviewer_id=REVIEWER).status == "incomplete"
    assert state["events"][start:][-1] == event


def test_old_pin_remains_valid_until_exact_expiry(synthetic):
    (
        transaction,
        state,
        root,
        anchors,
        reviewed,
        plan,
        paths,
        loader,
        reviewer,
        publication,
        pinned,
    ) = issue(synthetic)
    state["now"] = 999.999
    assert loader.load_review_pin(pinned, reviewed).status == "candidate_pinned"
    state["now"] = 1000
    assert loader.load_review_pin(pinned, reviewed).status == "incomplete"


def test_authority_change_revokes_pin(synthetic):
    (
        transaction,
        state,
        root,
        anchors,
        reviewed,
        plan,
        paths,
        loader,
        reviewer,
        publication,
        pinned,
    ) = issue(synthetic)
    authority = root / "authority-v1.json"
    data = json.loads(authority.read_bytes())
    data["revoked_plan_sha256"] = [anchors.plan_sha256]
    authority.write_text(json.dumps(data))
    assert loader.load_review_pin(pinned, reviewed).status == "incomplete"


@pytest.mark.parametrize("operation", ["issue", "load"])
def test_original_device_byte_uses_owner_fd_no_second_handle(synthetic, monkeypatch, operation):
    import swu_happyrun.agent.journal as journal_module

    if operation == "load":
        (
            transaction,
            state,
            root,
            anchors,
            reviewed,
            plan,
            paths,
            loader,
            reviewer,
            publication,
            pinned,
        ) = issue(synthetic)
    else:
        transaction, state, root, anchors, reviewed, plan, paths = complete(synthetic)
        loader, reviewer = modules()
    original = os.open

    def no_second_handle(path, flags, *args, **kwargs):
        if Path(path) == paths["device_lock"] and any(
            token.fd is not None and token.lock_path == paths["device_lock"]
            for token in journal_module._ACTIVE_ORIGINAL_LOCKS
        ):
            pytest.fail("second handle read of held device lock")
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", no_second_handle)
    result = (
        loader.load_review_pin(pinned, reviewed)
        if operation == "load"
        else reviewer.issue_review_pin(anchors, reviewed, reviewer_id=REVIEWER)
    )
    assert result.status == "candidate_pinned"


@pytest.mark.parametrize("lock", ["account", "device"])
@pytest.mark.parametrize("operation", ["issue", "load"])
def test_lock_conflict_has_zero_sqlite_storage_mkdir_or_native(
    synthetic, monkeypatch, lock, operation
):
    from swu_happyrun.drivers import command
    from swu_happyrun.drivers.mumu.enrollment_admission import _existing_lock

    if operation == "load":
        (
            transaction,
            state,
            root,
            anchors,
            reviewed,
            plan,
            paths,
            loader,
            reviewer,
            publication,
            pinned,
        ) = issue(synthetic)
    else:
        transaction, state, root, anchors, reviewed, plan, paths = complete(synthetic)
        loader, reviewer = modules()
    events = len(state["events"])

    def forbidden(*args, **kwargs):
        pytest.fail("lock conflict reached mutation")

    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(Path, "mkdir", forbidden)
    monkeypatch.setattr(command, "run_readonly", forbidden)
    monkeypatch.setattr(command, "_run_bounded_bytes", forbidden)
    lock_path = root / "admission.lock" if lock == "account" else paths["device_lock"]
    with _existing_lock(lock_path, FileIdentity.from_stat(lock_path.stat())):
        result = (
            loader.load_review_pin(pinned, reviewed)
            if operation == "load"
            else reviewer.issue_review_pin(anchors, reviewed, reviewer_id=REVIEWER)
        )
    assert result.status == "incomplete"
    assert len(state["events"]) == events


@pytest.mark.parametrize("conflict", ["admission", "transaction"])
def test_control_conflict_rejected_before_journal_access(synthetic, monkeypatch, conflict):
    transaction, state, root, anchors, reviewed, plan, paths = complete(synthetic)
    loader, reviewer = modules()
    if conflict == "admission":
        (root / "admissions" / ("f" * 64 + ".json")).write_bytes(b"foreign")
    else:
        (root / "transactions" / "foreign").mkdir()
    original = os.open

    def guarded(path, flags, *args, **kwargs):
        if Path(path) in {paths["journal"], paths["device_lock"]}:
            pytest.fail("conflict touched journal")
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", guarded)
    events = len(state["events"])
    assert reviewer.issue_review_pin(anchors, reviewed, reviewer_id=REVIEWER).status == "incomplete"
    assert len(state["events"]) == events


@pytest.mark.parametrize("boundary", ["account", "device"])
def test_expiry_while_acquiring_locks_rejected_before_publication(synthetic, monkeypatch, boundary):
    transaction, state, root, anchors, reviewed, plan, paths = complete(synthetic)
    loader, reviewer = modules()
    original = transaction._existing_lock if boundary == "account" else RunJournal.lock_existing

    @contextmanager
    def delayed(*args, **kwargs):
        with original(*args, **kwargs) as result:
            state["now"] = plan["expires_at"]
            yield result

    if boundary == "account":
        monkeypatch.setattr(transaction, "_existing_lock", delayed)
    else:
        monkeypatch.setattr(RunJournal, "lock_existing", delayed)
    events = len(state["events"])
    assert reviewer.issue_review_pin(anchors, reviewed, reviewer_id=REVIEWER).status == "incomplete"
    assert len(state["events"]) == events


def test_owned_live_pin_stage_is_scanned_without_second_stat(synthetic, monkeypatch):
    transaction, state, root, anchors, reviewed, plan, paths = complete(synthetic)
    loader, reviewer = modules()
    stage = root / "reviews" / anchors.plan_sha256 / f".review-pin-v1.json.{TX}.staged"
    original = os.scandir
    original_open = os.open
    original_close = os.close
    held = set()

    def opened(path, flags, *args, **kwargs):
        if Path(path) == stage and held:
            pytest.fail("opened live share-zero pin stage")
        fd = original_open(path, flags, *args, **kwargs)
        if Path(path) == stage and flags & os.O_CREAT:
            held.add(fd)
        return fd

    def closed(fd):
        held.discard(fd)
        return original_close(fd)

    @contextmanager
    def scan(path):
        with original(path) as entries:

            class Entry:
                def __init__(self, entry):
                    self.entry, self.name, self.path = entry, entry.name, entry.path

                def stat(self, **kwargs):
                    if self.path == str(stage) and held:
                        pytest.fail("stat of live share-zero pin stage")
                    return self.entry.stat(**kwargs)

            yield (Entry(entry) for entry in entries)

    monkeypatch.setattr(os, "open", opened)
    monkeypatch.setattr(os, "close", closed)
    monkeypatch.setattr(os, "scandir", scan)
    assert (
        reviewer.issue_review_pin(anchors, reviewed, reviewer_id=REVIEWER).status
        == "candidate_pinned"
    )


def test_every_frozen_and_mutable_file_requires_same_identity(synthetic):
    (
        transaction,
        state,
        root,
        anchors,
        reviewed,
        plan,
        paths,
        loader,
        reviewer,
        publication,
        pinned,
    ) = issue(synthetic)
    parked = paths["journal"].parent.parent / "parked-original"
    evidence = {item.role: item.path for item in publication.record.frozen}
    evidence["journal"] = paths["journal"]
    evidence["pin"] = root / "reviews" / anchors.plan_sha256 / "review-pin-v1.json"
    for role, file in evidence.items():
        assert loader.load_review_pin(pinned, reviewed).status == "candidate_pinned", role
        original = file.read_bytes()
        original_identity = identity(file)
        file.rename(parked)
        file.write_bytes(original)
        assert identity(file) != original_identity, role
        assert loader.load_review_pin(pinned, reviewed).status == "incomplete", role
        file.unlink()
        parked.rename(file)
        assert identity(file) == original_identity, role
    assert loader.load_review_pin(pinned, reviewed).status == "candidate_pinned"


def test_pin_parent_replacement_rejected_even_with_identical_contents(synthetic):
    (
        transaction,
        state,
        root,
        anchors,
        reviewed,
        plan,
        paths,
        loader,
        reviewer,
        publication,
        pinned,
    ) = issue(synthetic)
    folder = root / "reviews" / anchors.plan_sha256
    old = folder.with_name("old-review")
    folder.rename(old)
    folder.mkdir()
    for file in old.iterdir():
        (folder / file.name).write_bytes(file.read_bytes())
    assert loader.load_review_pin(pinned, reviewed).status == "incomplete"


def test_untrusted_pin_anchor_types_and_unknown_reviewer_rejected(synthetic):
    transaction, state, root, anchors, reviewed, plan, paths = complete(synthetic)
    loader, reviewer = modules()
    events = len(state["events"])
    for value in (True, {}, anchors, object(), {"file": "approved"}):
        assert loader.load_review_pin(value, reviewed).status == "incomplete"
    assert (
        reviewer.issue_review_pin(anchors, reviewed, reviewer_id="fake-reviewer").status
        == "incomplete"
    )
    assert len(state["events"]) == events


def test_reviewer_module_is_not_imported_by_other_entrypoints():
    import ast

    package = Path(__file__).parents[2] / "src" / "swu_happyrun"
    for file in package.rglob("*.py"):
        if file.name == "enrollment_pin_reviewer.py":
            continue
        for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                assert "enrollment_pin_reviewer" not in (node.module or "")
                assert all(alias.name != "enrollment_pin_reviewer" for alias in node.names)
            elif isinstance(node, ast.Import):
                assert all("enrollment_pin_reviewer" not in alias.name for alias in node.names)


def test_all_frozen_current_acls_are_checked_without_mutation(synthetic, monkeypatch):
    (
        transaction,
        state,
        root,
        anchors,
        reviewed,
        plan,
        paths,
        loader,
        reviewer,
        publication,
        pinned,
    ) = issue(synthetic)
    denied = set()

    @contextmanager
    def guards(*args):
        def security(extra_paths=()):
            if denied & {path for path, protected in extra_paths}:
                raise ValueError("synthetic current ACL rejection")

        yield security

    monkeypatch.setattr(transaction, "_protected_paths", guards)
    events = len(state["events"])
    files = [(item.role, item.path) for item in publication.record.frozen]
    files += [
        ("journal", paths["journal"]),
        ("pin", root / "reviews" / anchors.plan_sha256 / "review-pin-v1.json"),
    ]
    for role, path in files:
        denied.clear()
        assert loader.load_review_pin(pinned, reviewed).status == "candidate_pinned", role
        denied.add(path)
        assert loader.load_review_pin(pinned, reviewed).status == "incomplete", role
    assert len(state["events"]) == events


def test_unowned_file_during_pin_write_is_not_whitelisted(synthetic):
    transaction, state, root, anchors, reviewed, plan, paths = complete(synthetic)
    loader, reviewer = modules()
    start = len(state["events"])
    foreign = root / "reviews" / anchors.plan_sha256 / "review-pin-v2.json"

    def inject(event):
        if event == "write":
            foreign.write_bytes(b"unreviewed")

    state["after"] = inject
    assert reviewer.issue_review_pin(anchors, reviewed, reviewer_id=REVIEWER).status == "incomplete"
    assert state["events"][start:] == ["create", "write"]
    assert foreign.read_bytes() == b"unreviewed"


def test_initial_expiry_prevents_any_pin_mutation(synthetic):
    transaction, state, root, anchors, reviewed, plan, paths = complete(synthetic)
    loader, reviewer = modules()
    events = len(state["events"])
    state["now"] = plan["expires_at"]
    assert reviewer.issue_review_pin(anchors, reviewed, reviewer_id=REVIEWER).status == "incomplete"
    assert len(state["events"]) == events


def test_uncertain_final_pin_is_retained_and_never_adopted(synthetic):
    transaction, state, root, anchors, reviewed, plan, paths = complete(synthetic)
    loader, reviewer = modules()
    file = root / "reviews" / anchors.plan_sha256 / "review-pin-v1.json"
    replacement = paths["journal"].parent.parent / "changed-pin-object"

    def replace_after_publication(event):
        if event == "move":
            replacement.write_bytes(file.read_bytes())
            os.replace(replacement, file)

    state["after"] = replace_after_publication
    result = reviewer.issue_review_pin(anchors, reviewed, reviewer_id=REVIEWER)
    assert result.status == "incomplete"
    assert result.file is None
    before = identity(file), file.read_bytes()
    events = len(state["events"])
    state["after"] = None
    assert reviewer.issue_review_pin(anchors, reviewed, reviewer_id=REVIEWER).status == "incomplete"
    assert (identity(file), file.read_bytes()) == before
    assert len(state["events"]) == events
