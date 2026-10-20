"""Synthetic local filesystem exercise; no native/device acceptance claimed."""

import hashlib
import importlib
import importlib.util
import json
import os
import sqlite3
from contextlib import closing, contextmanager

import pytest

from swu_happyrun.agent.journal import RunJournal
from swu_happyrun.drivers.identity import device_id
from swu_happyrun.drivers.mumu import enrollment_storage as storage
from swu_happyrun.drivers.mumu.enrollment_authority import FrozenFile, RunnerAnchors
from swu_happyrun.drivers.mumu.enrollment_inspection import DiscoveryScope, inspect_enrollment
from swu_happyrun.drivers.mumu.enrollment_review_scope import build_review_scope
from swu_happyrun.drivers.mumu.instance_attribution import FileIdentity

MODULE = "swu_happyrun.drivers.mumu.enrollment_transaction"
SID = "S-1-5-21-1-2-3-1001"
TX = "a" * 64


def module():
    assert importlib.util.find_spec(MODULE) is not None, "candidate transaction is missing"
    return importlib.import_module(MODULE)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def identity(path):
    return [path.stat().st_dev, path.stat().st_ino]


def pin(path):
    return FrozenFile(
        FileIdentity.from_stat(path.stat()), hashlib.sha256(path.read_bytes()).hexdigest()
    )


def create_bundle(tmp_path, monkeypatch, existing=False, nested=False):
    state = tmp_path / "state" / "swu-happyrun"
    state.mkdir(parents=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(state.parent))
    monkeypatch.setenv("LOCALAPPDATA", str(state.parent))
    monkeypatch.delenv("SWU_HAPPYRUN_HOST_ID_FILE", raising=False)
    host = state / "host-id"
    host_id = "11111111-1111-4111-8111-111111111111"
    host.write_text(host_id + "\n")
    manager = tmp_path / "manager.exe"
    manager.write_bytes(b"synthetic manager")
    config_dir = tmp_path / "MuMu-0"
    config_dir.mkdir()
    config = config_dir / "MuMu-0.nemu"
    previous = config_dir / "MuMu-0.nemu-prev"
    stable = "22222222-2222-4222-8222-222222222222"
    for path in (config, previous):
        path.write_text(f'<Machine uuid="{stable}" name="MuMu-0"/>')
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir()
    journal = journal_dir / "runs.sqlite"
    product = device_id("mumu", f"{os.path.normcase(str(manager))}:0", host_id=host_id)
    lock = journal_dir / ("device-" + hashlib.sha256(product.encode()).hexdigest() + ".lock")
    if existing:
        with RunJournal(journal) as db:
            with db.device_lock(product):
                db.record_intent("historic-job", 7, "start")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    root = (state if nested else tmp_path) / "control-v1"
    root.mkdir()
    (root / "admission.lock").write_bytes(b"0")
    (root / "reviews").mkdir()
    for path in (root / "admissions", root / "transactions", root / "transactions" / TX):
        path.mkdir()
    scope = DiscoveryScope(
        (journal_dir,),
        (journal,) if existing else (),
        unchecked_categories=(),
        declared_complete=True,
    )
    reviewed = build_review_scope(
        inspect_enrollment(
            scope,
            manager=manager,
            instance_index="0",
            expected_journal=journal if existing else None,
        ),
        expected_host_id=host_id,
        expected_device_id=product,
        expected_journal=journal if existing else None,
    )
    paths = {
        "host": host,
        "manager": manager,
        "config": config,
        "config_previous": previous,
        "journal": journal,
        "device_lock": lock,
        "receipt": state / "mumu-experiment-registration.json",
    }
    targets = {}
    for name, path in paths.items():
        targets[name] = {
            "path": str(path),
            "parent_identity": identity(path.parent),
            "identity": identity(path) if path.exists() else None,
            "sha256": pin(path).sha256 if path.exists() and name != "journal" else None,
        }
    plan = {
        "schema": "approved-plan-v2",
        "epoch": 3,
        "kind": "existing" if existing else "new_enrollment",
        "expires_at": 1000,
        "reviewed_scope_sha256": reviewed.sha256,
        "manager_version": "6.8.4.0",
        "host_namespace": host_id,
        "stable_instance": stable,
        "device_id": product,
        "instance_index": "0",
        "targets": targets,
        "transaction_id": TX,
        "product_commit": "b" * 40,
        "product_tree": "c" * 40,
        "directories": {
            name: {"path": str(path), "identity": identity(path)}
            for name, path in {
                "admissions": root / "admissions",
                "transactions": root / "transactions",
                "transaction": root / "transactions" / TX,
                "evidence": evidence,
            }.items()
        },
    }
    raw = canonical(plan)
    digest = hashlib.sha256(raw).hexdigest()
    folder = root / "reviews" / digest
    folder.mkdir(parents=True)
    plan_path = folder / "approved-plan-v2.json"
    plan_path.write_bytes(raw)
    if nested:
        (folder / "reviewed-scope-v1.json").write_bytes(reviewed.canonical_bytes)
    authority = root / "authority-v1.json"
    authority.write_bytes(
        canonical(
            {
                "schema": "authority-v1",
                "epoch": 3,
                "approved_plan_sha256": digest,
                "revoked_plan_sha256": [],
            }
        )
    )
    anchors = RunnerAnchors(
        FileIdentity.from_stat(root.stat()),
        FileIdentity.from_stat((root / "admission.lock").stat()),
        pin(authority),
        digest,
        pin(plan_path),
        FileIdentity.from_stat(folder.stat()),
    )
    return root, anchors, reviewed, plan, paths


@pytest.fixture
def synthetic(tmp_path, monkeypatch):
    transaction = module()
    state = {"fault": None, "after": None, "events": [], "now": 10}
    monkeypatch.setattr(transaction.time, "time", lambda: state["now"])

    class API:
        def current_sid(self):
            return SID

        def security(self, path):
            return f"O:{SID}D:P(A;;FA;;;{SID})"

    class IO:
        def __init__(self, api, sid):
            assert sid == SID

        def event(self, name, action):
            state["events"].append(name)
            if state["fault"] == name:
                raise OSError("injected before operation")
            result = action()
            if state["after"]:
                state["after"](name)
            return result

        def create(self, path):
            return self.event(
                "create",
                lambda: os.open(
                    path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600
                ),
            )

        def write(self, fd, data):
            return self.event("write", lambda: os.write(fd, data))

        def fsync(self, fd):
            return self.event("fsync", lambda: os.fsync(fd))

        def flush(self, fd):
            return self.event("flush", lambda: os.fsync(fd))

        def close(self, fd):
            os.close(fd)

        def open_read(self, path):
            return os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))

        def check_fd(self, fd):
            assert os.fstat(fd).st_nlink == 1

        def check_path(self, fd, path):
            assert FileIdentity.from_stat(os.fstat(fd)) == FileIdentity.from_stat(path.stat())

        def move(self, source, destination):
            def action():
                os.link(source, destination)
                source.unlink()

            return self.event("move", action)

    @contextmanager
    def guard(path, expected):
        assert tuple(identity(path)) == expected
        yield API(), SID, expected

    @contextmanager
    def protected(*args):
        yield lambda *args: None

    monkeypatch.setattr(storage, "_NativeIO", IO)
    monkeypatch.setattr(storage, "_require_local_ntfs", lambda _: None)
    monkeypatch.setattr(storage.windows_private, "verified_directory", guard)
    monkeypatch.setattr(transaction, "_protected_paths", protected)

    def bundle(existing=False, nested=False):
        result = create_bundle(tmp_path, monkeypatch, existing, nested)
        monkeypatch.setattr(transaction, "resolve_control_root", lambda: result[0])
        return result

    return transaction, state, bundle


def test_candidate_transaction_api_exists():
    assert callable(module().initialize_candidate)


def test_first_use_completes_candidate_but_never_ready(synthetic):
    transaction, state, bundle = synthetic
    root, anchors, reviewed, plan, paths = bundle()
    result = transaction.initialize_candidate(anchors, reviewed)
    assert result.status == "candidate_unpinned"
    assert result.execution_allowed is False
    assert all(
        (root / "transactions" / TX / f"stage-{index:02d}.json").is_file() for index in range(1, 8)
    )
    receipt = json.loads(paths["receipt"].read_bytes())
    assert receipt["schema"] == 1
    assert receipt["journal_file"]["identity"] == identity(paths["journal"])
    assert receipt["lock_identity"] == identity(paths["device_lock"])
    assert receipt["evidence_root"] == plan["directories"]["evidence"]["path"]
    with closing(sqlite3.connect(paths["journal"])) as db:
        assert db.execute("SELECT COUNT(*) FROM intents").fetchone() == (0,)
        assert db.execute("SELECT COUNT(*) FROM stop_acks").fetchone() == (0,)


def test_completed_repeat_is_readonly_no_sqlite(synthetic, monkeypatch):
    transaction, state, bundle = synthetic
    root, anchors, reviewed, _, _ = bundle()
    assert transaction.initialize_candidate(anchors, reviewed).status == "candidate_unpinned"
    before = {p: (identity(p), p.read_bytes()) for p in root.parent.rglob("*") if p.is_file()}
    events = len(state["events"])
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: pytest.fail("repeat SQLite"))
    assert transaction.initialize_candidate(anchors, reviewed).status == "candidate_unpinned"
    assert len(state["events"]) == events
    assert before == {
        p: (identity(p), p.read_bytes()) for p in root.parent.rglob("*") if p.is_file()
    }


def test_existing_without_receipt_adopts_current_preserves_database(synthetic):
    transaction, _, bundle = synthetic
    _, anchors, reviewed, _, paths = bundle(existing=True)
    before = {
        name: (identity(paths[name]), paths[name].read_bytes())
        for name in ("journal", "device_lock")
    }
    assert transaction.initialize_candidate(anchors, reviewed).status == "candidate_unpinned"
    assert before == {name: (identity(paths[name]), paths[name].read_bytes()) for name in before}
    provenance = json.loads((paths["journal"].parent / "enrollment-v1.json").read_bytes())
    assert provenance["adoption"] == "current_existing_history"
    assert provenance["historical_provenance_verified"] is False


@pytest.mark.parametrize("fault", ["create", "write", "fsync", "flush", "move"])
def test_storage_failure_retains_incomplete_and_never_retries(synthetic, fault):
    transaction, state, bundle = synthetic
    root, anchors, reviewed, _, _ = bundle()
    state["fault"] = fault
    result = transaction.initialize_candidate(anchors, reviewed)
    assert result.status == "incomplete"
    before = {p: (identity(p), p.read_bytes()) for p in root.parent.rglob("*") if p.is_file()}
    assert state["events"].count(fault) == 1
    state["fault"] = None
    if fault == "create":
        # The first CREATE_NEW failed before any object existed. Do not invent
        # a durable failure marker or automatically retry this attempt.
        assert transaction.diagnose_candidate(anchors, reviewed).status == "unstarted"
        return
    assert transaction.initialize_candidate(anchors, reviewed).status == "incomplete"
    assert before == {
        p: (identity(p), p.read_bytes()) for p in root.parent.rglob("*") if p.is_file()
    }


def test_foreign_admission_blocks_before_sqlite_or_storage(synthetic, monkeypatch):
    transaction, state, bundle = synthetic
    root, anchors, reviewed, _, paths = bundle()
    (root / "admissions" / ("f" * 64 + ".json")).write_bytes(b"{}")
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: pytest.fail("foreign SQLite"))
    assert transaction.initialize_candidate(anchors, reviewed).status == "incomplete"
    assert state["events"] == []
    assert list(paths["journal"].parent.iterdir()) == []


@pytest.mark.parametrize("existing", [False, True])
def test_original_device_and_account_locks_precede_every_sqlite_connect(
    synthetic, monkeypatch, existing
):
    from swu_happyrun.drivers.mumu.enrollment_admission import _existing_lock
    from swu_happyrun.drivers.mumu.enrollment_authority import ApprovalNotReady

    transaction, _, bundle = synthetic
    root, anchors, reviewed, _, paths = bundle(existing=existing)
    original = sqlite3.connect
    calls = []

    def connect(*args, **kwargs):
        for path in (root / "admission.lock", paths["device_lock"]):
            with pytest.raises(ApprovalNotReady):
                with _existing_lock(path, FileIdentity.from_stat(path.stat())):
                    pytest.fail("lock not held")
        calls.append(args[0])
        return original(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    assert transaction.initialize_candidate(anchors, reviewed).status == "candidate_unpinned"
    assert len(calls) == 1
    if not existing:
        assert calls == [":memory:"]


def test_expiry_between_stage_mutations_retains_evidence(synthetic):
    transaction, state, bundle = synthetic
    root, anchors, reviewed, _, paths = bundle()

    def expire(name):
        if name == "write":
            state["now"] = 1000

    state["after"] = expire
    assert transaction.initialize_candidate(anchors, reviewed).status == "incomplete"
    assert not paths["journal"].exists()
    assert list((root / "admissions").iterdir())


@pytest.mark.parametrize("missing", ["stage-03.json", "candidate-v1.json"])
def test_diagnosis_missing_stage_or_candidate_never_repairs(synthetic, monkeypatch, missing):
    transaction, _, bundle = synthetic
    root, anchors, reviewed, _, paths = bundle()
    assert transaction.initialize_candidate(anchors, reviewed).status == "candidate_unpinned"
    (root / "transactions" / TX / missing).unlink()
    assert paths["receipt"].exists()
    before = {p: p.read_bytes() for p in root.parent.rglob("*") if p.is_file()}
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: pytest.fail("diagnostic SQLite"))
    assert transaction.diagnose_candidate(anchors, reviewed).status == "incomplete"
    assert transaction.initialize_candidate(anchors, reviewed).status == "incomplete"
    assert before == {p: p.read_bytes() for p in root.parent.rglob("*") if p.is_file()}


def test_unreviewed_first_use_journal_root_rejected_before_writes(synthetic, monkeypatch):
    transaction, state, bundle = synthetic
    _, anchors, reviewed, _, paths = bundle()
    # A fresh, unreviewed state artifact appears after review. The old approved
    # inventory must not become a declaration of current emptiness.
    (paths["journal"].parent / "orphan.db").write_bytes(b"unknown history")
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: pytest.fail("changed scope SQLite"))
    assert transaction.initialize_candidate(anchors, reviewed).status == "incomplete"
    assert state["events"] == []


def test_same_content_postpublication_identity_replacement_is_incomplete(synthetic):
    transaction, state, bundle = synthetic
    root, anchors, reviewed, _, _ = bundle()
    admission = root / "admissions" / (anchors.plan_sha256 + ".json")

    def replace(name):
        if name == "move" and admission.exists():
            state["after"] = None
            old = admission.read_bytes()
            replacement = admission.with_name("replacement")
            replacement.write_bytes(old)
            os.replace(replacement, admission)

    state["after"] = replace
    assert transaction.initialize_candidate(anchors, reviewed).status == "incomplete"
    assert admission.exists()
    assert transaction.initialize_candidate(anchors, reviewed).status == "incomplete"
    assert not (root / "transactions" / TX / "stage-01.json").exists()


@pytest.mark.parametrize("boundary", range(1, 15))
def test_each_publication_failure_keeps_immutable_prefix(synthetic, boundary):
    transaction, state, bundle = synthetic
    root, anchors, reviewed, _, _ = bundle()
    count = 0

    def fault(name):
        nonlocal count
        if name == "flush":
            count += 1
            if count == boundary:
                state["fault"] = "move"

    state["after"] = fault
    assert transaction.initialize_candidate(anchors, reviewed).status == "incomplete"
    assert count == boundary
    before = {p: (identity(p), p.read_bytes()) for p in root.parent.rglob("*") if p.is_file()}
    state["fault"] = state["after"] = None
    events = len(state["events"])
    assert transaction.initialize_candidate(anchors, reviewed).status == "incomplete"
    assert len(state["events"]) == events
    assert before == {
        p: (identity(p), p.read_bytes()) for p in root.parent.rglob("*") if p.is_file()
    }


@pytest.mark.parametrize("boundary", [1, 2, 3, 4, 5, 6, 7, 12, 13, 14])
def test_expiry_after_each_phase_never_completes(synthetic, boundary):
    transaction, state, bundle = synthetic
    _, anchors, reviewed, _, _ = bundle()
    count = 0

    def expire(name):
        nonlocal count
        if name == "move":
            count += 1
            if count == boundary:
                state["now"] = 1000

    state["after"] = expire
    assert transaction.initialize_candidate(anchors, reviewed).status == "incomplete"
    assert count == boundary


def test_existing_sqlite_side_effect_is_detected_against_original_bytes(synthetic, monkeypatch):
    transaction, _, bundle = synthetic
    _, anchors, reviewed, _, paths = bundle(existing=True)
    original = sqlite3.connect

    def connect(*args, **kwargs):
        db = original(*args, **kwargs)
        db.execute("INSERT INTO intents VALUES ('unexpected', 'start', 99, NULL)")
        db.commit()
        return db

    monkeypatch.setattr(sqlite3, "connect", connect)
    assert transaction.initialize_candidate(anchors, reviewed).status == "incomplete"
    assert not paths["receipt"].exists()


def test_complete_candidate_diagnosis_allows_changed_journal_bytes_not_identity(synthetic):
    transaction, _, bundle = synthetic
    _, anchors, reviewed, _, paths = bundle()
    assert transaction.initialize_candidate(anchors, reviewed).status == "candidate_unpinned"
    with closing(sqlite3.connect(paths["journal"])) as db:
        db.execute("INSERT INTO intents VALUES ('later', 'start', 1, NULL)")
        db.commit()
    assert transaction.diagnose_candidate(anchors, reviewed).status == "candidate_unpinned"
    replacement = paths["journal"].with_name("replacement")
    replacement.write_bytes(paths["journal"].read_bytes())
    os.replace(replacement, paths["journal"])
    assert transaction.diagnose_candidate(anchors, reviewed).status == "incomplete"


@pytest.mark.parametrize("existing", [False, True])
def test_locked_device_byte_is_never_read_through_another_handle(synthetic, monkeypatch, existing):
    import swu_happyrun.agent.journal as journal_module

    transaction, _, bundle = synthetic
    _, anchors, reviewed, _, paths = bundle(existing=existing)
    original_open = os.open
    original_lock = transaction._existing_lock
    held = set()

    @contextmanager
    def locked(path, identity):
        with original_lock(path, identity) as result:
            held.add(path)
            try:
                yield result
            finally:
                held.remove(path)

    def guarded_open(path, flags, *args, **kwargs):
        active = any(
            token.fd is not None and token.lock_path == paths["device_lock"]
            for token in journal_module._ACTIVE_ORIGINAL_LOCKS
        )
        if path == paths["device_lock"] and (path in held or active):
            pytest.fail("second-handle read of a Windows-locked byte")
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(transaction, "_existing_lock", locked)
    monkeypatch.setattr(os, "open", guarded_open)
    assert transaction.initialize_candidate(anchors, reviewed).status == "candidate_unpinned"


def repin_bundle(root, anchors, plan):
    raw = canonical(plan)
    digest = hashlib.sha256(raw).hexdigest()
    folder = root / "reviews" / digest
    folder.mkdir()
    target = folder / "approved-plan-v2.json"
    target.write_bytes(raw)
    authority = root / "authority-v1.json"
    authority.write_bytes(
        canonical(
            {
                "schema": "authority-v1",
                "epoch": 3,
                "approved_plan_sha256": digest,
                "revoked_plan_sha256": [],
            }
        )
    )
    return RunnerAnchors(
        anchors.root_identity,
        anchors.lock_identity,
        pin(authority),
        digest,
        pin(target),
        FileIdentity.from_stat(folder.stat()),
    )


def test_first_use_target_cannot_escape_reviewed_roots(synthetic, monkeypatch):
    transaction, state, bundle = synthetic
    root, anchors, reviewed, plan, paths = bundle()
    unreviewed = root.parent / "unreviewed"
    unreviewed.mkdir()
    (unreviewed / "historic.sqlite").write_bytes(b"unknown")
    for role in ("journal", "device_lock"):
        plan["targets"][role]["path"] = str(unreviewed / paths[role].name)
        plan["targets"][role]["parent_identity"] = identity(unreviewed)
    anchors = repin_bundle(root, anchors, plan)
    monkeypatch.setattr(
        transaction, "_protected_paths", lambda *a: pytest.fail("unreviewed parent reached guards")
    )
    assert transaction.initialize_candidate(anchors, reviewed).status == "incomplete"
    assert state["events"] == []


@pytest.mark.parametrize("name", ["foreign.db", "replay-foreign.json", "unexpected.txt"])
@pytest.mark.parametrize("existing", [False, True])
def test_phase_scope_rejects_unowned_new_files(synthetic, name, existing):
    transaction, state, bundle = synthetic
    _, anchors, reviewed, _, paths = bundle(existing=existing)

    def inject(event):
        if event == "move":
            state["after"] = None
            (paths["journal"].parent / name).write_bytes(b"unknown change")

    state["after"] = inject
    assert transaction.initialize_candidate(anchors, reviewed).status == "incomplete"
    assert not paths["receipt"].exists()


def test_already_published_artifact_acl_is_revalidated(synthetic, monkeypatch):
    transaction, state, bundle = synthetic
    root, anchors, reviewed, _, paths = bundle()
    invalid = root / "admissions" / (anchors.plan_sha256 + ".json")
    changed = False

    @contextmanager
    def guards(*args):
        def security(extra_paths=()):
            if changed and any(path == invalid for path, protected in extra_paths):
                raise ValueError("synthetic changed artifact ACL")

        yield security

    def alter(event):
        nonlocal changed
        if event == "move":
            changed = True

    state["after"] = alter
    monkeypatch.setattr(transaction, "_protected_paths", guards)
    assert transaction.initialize_candidate(anchors, reviewed).status == "incomplete"
    assert not paths["receipt"].exists()


@pytest.mark.parametrize("existing", [False, True])
def test_real_control_root_nested_under_default_state_scope(synthetic, existing):
    transaction, _, bundle = synthetic
    root, anchors, reviewed, _, paths = bundle(existing=existing, nested=True)
    assert root.parent == paths["host"].parent
    assert transaction.initialize_candidate(anchors, reviewed).status == "candidate_unpinned"
    assert transaction.initialize_candidate(anchors, reviewed).status == "candidate_unpinned"


def test_completed_diagnosis_rejects_later_foreign_history_readonly(synthetic, monkeypatch):
    transaction, _, bundle = synthetic
    _, anchors, reviewed, _, paths = bundle()
    assert transaction.initialize_candidate(anchors, reviewed).status == "candidate_unpinned"
    (paths["journal"].parent / "foreign.db").write_bytes(b"unreviewed")
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: pytest.fail("diagnostic SQL"))
    assert transaction.diagnose_candidate(anchors, reviewed).status == "incomplete"


def test_live_stage_scan_uses_exact_fd_metadata_not_second_stat(tmp_path, monkeypatch):
    from swu_happyrun.drivers.mumu.enrollment_phase_scope import require_phase_scope
    from swu_happyrun.drivers.mumu.enrollment_storage import LiveStagingObservation

    _, _, reviewed, _, paths = create_bundle(tmp_path, monkeypatch)
    stage = paths["journal"].parent / (".private." + TX + ".staged")
    fd = os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    try:
        original = os.scandir

        @contextmanager
        def exclusive_scan(path):
            with original(path) as entries:

                class Entry:
                    def __init__(self, entry):
                        self.entry, self.name, self.path = entry, entry.name, entry.path

                    def stat(self, **kwargs):
                        if self.path == str(stage):
                            raise PermissionError("synthetic share=0 second metadata handle")
                        return self.entry.stat(**kwargs)

                yield (Entry(entry) for entry in entries)

        monkeypatch.setattr(os, "scandir", exclusive_scan)
        live = LiveStagingObservation(
            stage,
            FileIdentity.from_stat(os.fstat(fd)),
            FileIdentity.from_stat(stage.parent.stat()),
            0,
        )
        arguments = {"manager": paths["manager"], "instance_index": "0"}
        assert inspect_enrollment(reviewed.inspection.scope, **arguments).status == "unknown"
        current = inspect_enrollment(reviewed.inspection.scope, **arguments, _live_staging=(live,))
        require_phase_scope(
            reviewed, current, {stage: (live.identity, False)}, live_staging=(live,)
        )
    finally:
        os.close(fd)


def test_synthetic_byte_io_preserves_binary_journal_on_windows(synthetic, monkeypatch):
    """Model CRT text translation, even on Linux, without replacing storage logic."""
    transaction, _, bundle = synthetic
    _, anchors, reviewed, _, _ = bundle()
    native_binary = getattr(os, "O_BINARY", 0)
    marker = native_binary or 0x40000000
    original_open, original_write, original_read = os.open, os.write, os.read
    modes = {}

    def opened(path, flags, *args, **kwargs):
        # Underlying descriptors stay binary; emulate only the requested mode.
        fd = original_open(path, (flags & ~marker) | native_binary, *args, **kwargs)
        modes[fd] = bool(flags & marker)
        return fd

    def written(fd, data):
        raw = bytes(data)
        if not modes.get(fd, True):
            original_write(fd, raw.replace(b"\n", b"\r\n"))
            return len(raw)
        return original_write(fd, raw)

    def read(fd, count):
        raw = original_read(fd, count)
        return raw if modes.get(fd, True) else raw.replace(b"\r\n", b"\n")

    monkeypatch.setattr(os, "O_BINARY", marker, raising=False)
    monkeypatch.setattr(os, "open", opened)
    monkeypatch.setattr(os, "write", written)
    monkeypatch.setattr(os, "read", read)
    assert transaction.initialize_candidate(anchors, reviewed).status == "candidate_unpinned"
