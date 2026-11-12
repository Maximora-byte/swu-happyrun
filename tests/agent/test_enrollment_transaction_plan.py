import hashlib
import importlib
import json
import os
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from swu_happyrun.drivers.identity import device_id
from swu_happyrun.drivers.mumu.enrollment_authority import (
    ApprovalNotReady,
    FrozenFile,
    RunnerAnchors,
)
from swu_happyrun.drivers.mumu.instance_attribution import FileIdentity


def module():
    return importlib.import_module("swu_happyrun.drivers.mumu.enrollment_transaction_plan")


def identity(path):
    info = path.stat()
    return [info.st_dev, info.st_ino]


def pin(path):
    return FrozenFile(
        FileIdentity.from_stat(path.stat()), hashlib.sha256(path.read_bytes()).hexdigest()
    )


def publish(root, plan, *, authority_changes=None, raw=None):
    raw = json.dumps(plan).encode() if raw is None else raw
    digest = hashlib.sha256(raw).hexdigest()
    folder = root / "reviews" / digest
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "approved-plan-v2.json"
    path.write_bytes(raw)
    authority = {
        "schema": "authority-v1",
        "epoch": 3,
        "approved_plan_sha256": digest,
        "revoked_plan_sha256": [],
    }
    authority.update(authority_changes or {})
    authority_path = root / "authority-v1.json"
    authority_path.write_text(json.dumps(authority))
    return RunnerAnchors(
        FileIdentity.from_stat(root.stat()),
        FileIdentity.from_stat((root / "admission.lock").stat()),
        pin(authority_path),
        digest,
        pin(path),
        FileIdentity.from_stat(folder.stat()),
    )


def bundle(tmp_path, *, kind="new_enrollment"):
    root = tmp_path / "control-v1"
    root.mkdir()
    (root / "admission.lock").write_bytes(b"0")
    transaction_id = "e" * 64
    state = tmp_path / "state"
    state.mkdir()
    instance = tmp_path / "MuMu-0"
    instance.mkdir()
    journal_parent = tmp_path / "journal"
    journal_parent.mkdir()
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    paths = {
        "host": state / "host-id",
        "manager": instance / "MuMuManager.exe",
        "config": instance / "MuMu-0.nemu",
        "config_previous": instance / "MuMu-0.nemu-prev",
        "journal": journal_parent / "state.sqlite3",
        "receipt": state / "mumu-experiment-registration.json",
    }
    namespace = "11111111-1111-4111-8111-111111111111"
    stable = "22222222-2222-4222-8222-222222222222"
    product = device_id("mumu", f"{os.path.normcase(str(paths['manager']))}:0", host_id=namespace)
    paths["device_lock"] = journal_parent / (
        "device-" + hashlib.sha256(product.encode()).hexdigest() + ".lock"
    )
    paths["host"].write_text(namespace + "\n")
    paths["manager"].write_bytes(b"reviewed-manager")
    for name in ("config", "config_previous"):
        paths[name].write_text(f'<Machine uuid="{stable}" name="MuMu-0"/>')
    if kind == "existing":
        paths["journal"].write_bytes(b"mutable database bytes")
        paths["device_lock"].write_bytes(b"0")
    directories = {
        "admissions": root / "admissions",
        "transactions": root / "transactions",
        "transaction": root / "transactions" / transaction_id,
        "evidence": evidence,
    }
    for path in directories.values():
        path.mkdir(exist_ok=True)
    plan = {
        "schema": "approved-plan-v2",
        "epoch": 3,
        "kind": kind,
        "expires_at": 1000,
        "reviewed_scope_sha256": "a" * 64,
        "manager_version": "6.8.4.0",
        "host_namespace": namespace,
        "stable_instance": stable,
        "device_id": product,
        "instance_index": "0",
        "transaction_id": transaction_id,
        "product_commit": "b" * 40,
        "product_tree": "c" * 40,
        "targets": {
            name: {
                "path": str(path),
                "parent_identity": identity(path.parent),
                "identity": identity(path) if path.exists() else None,
                "sha256": (
                    hashlib.sha256(path.read_bytes()).hexdigest()
                    if path.exists() and name != "journal"
                    else None
                ),
            }
            for name, path in paths.items()
        },
        "directories": {
            name: {"path": str(path), "identity": identity(path)}
            for name, path in directories.items()
        },
    }
    return root, publish(root, plan), plan


@pytest.mark.parametrize("kind", ["new_enrollment", "existing"])
def test_loads_strict_immutable_candidate_inputs_without_granting_execution(tmp_path, kind):
    api = module()
    root, anchors, raw = bundle(tmp_path, kind=kind)
    before = {p: (identity(p), p.read_bytes()) for p in tmp_path.rglob("*") if p.is_file()}
    plan = api.load_transaction_plan(root, anchors, now=10)
    assert plan.kind == kind
    assert plan.transaction_id == raw["transaction_id"]
    assert plan.product_commit == raw["product_commit"]
    assert plan.product_tree == raw["product_tree"]
    assert plan.plan_sha256 == anchors.plan_sha256
    assert plan.evidence_root == Path(raw["directories"]["evidence"]["path"])
    assert plan.evidence_identity == FileIdentity("python_stat", *identity(plan.evidence_root))
    assert len(plan.targets) == 7 and len(plan.directories) == 4
    assert plan.execution_allowed is False
    with pytest.raises(FrozenInstanceError):
        plan.epoch = 0
    api.validate_frozen_inputs(plan)
    assert before == {p: (identity(p), p.read_bytes()) for p in tmp_path.rglob("*") if p.is_file()}


def test_loader_never_reads_target_paths_or_parents_before_conflict_scan(tmp_path, monkeypatch):
    api = module()
    root, anchors, raw = bundle(tmp_path)
    forbidden = {Path(item["path"]) for item in raw["targets"].values()}
    forbidden.update(path.parent for path in tuple(forbidden))
    forbidden.add(Path(raw["directories"]["evidence"]["path"]))
    original = Path.lstat

    def deny_target_access(path, *args, **kwargs):
        assert path not in forbidden, f"premature target access: {path}"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", deny_target_access)
    monkeypatch.setattr(
        Path, "resolve", lambda *args, **kwargs: pytest.fail("parser must not resolve targets")
    )
    assert api.load_transaction_plan(root, anchors, now=10).kind == "new_enrollment"


def test_payload_preflight_is_pure_and_hashes_exact_reviewed_bytes(tmp_path, monkeypatch):
    api = module()
    root, _, raw = bundle(tmp_path)
    payload = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
    monkeypatch.setattr(Path, "lstat", lambda *args, **kwargs: pytest.fail("unexpected I/O"))
    monkeypatch.setattr(Path, "stat", lambda *args, **kwargs: pytest.fail("unexpected I/O"))
    plan = api.parse_plan_payload(root, payload)
    assert plan.plan_sha256 == hashlib.sha256(payload).hexdigest()
    assert plan.execution_allowed is False


def test_identical_pinned_bytes_reuse_only_pure_topology(tmp_path, monkeypatch):
    api = module()
    root, anchors, _ = bundle(tmp_path)
    original = api._topology
    calls = []

    def topology(*args):
        calls.append(args)
        return original(*args)

    monkeypatch.setattr(api, "_topology", topology)
    first = api.load_transaction_plan(root, anchors, now=10)
    assert api.load_transaction_plan(root, anchors, now=11) == first
    assert len(calls) == 1


@pytest.mark.parametrize("change", ["expiry", "revoked", "epoch", "plan_bytes", "root"])
def test_warm_plan_still_rechecks_live_authority_and_pins(tmp_path, change):
    api = module()
    root, anchors, raw = bundle(tmp_path)
    api.load_transaction_plan(root, anchors, now=10)
    now = 10
    if change == "expiry":
        now = 1000
    elif change in {"revoked", "epoch"}:
        updates = (
            {"revoked_plan_sha256": [anchors.plan_sha256]} if change == "revoked" else {"epoch": 4}
        )
        anchors = publish(root, raw, authority_changes=updates)
    elif change == "plan_bytes":
        path = root / "reviews" / anchors.plan_sha256 / "approved-plan-v2.json"
        path.write_bytes(path.read_bytes() + b" ")
    else:
        anchors = replace(anchors, root_identity=FileIdentity("python_stat", 1, 1))
    with pytest.raises(ApprovalNotReady):
        api.load_transaction_plan(root, anchors, now=now)


def test_different_pinned_bytes_are_parsed_again(tmp_path, monkeypatch):
    api = module()
    root, anchors, raw = bundle(tmp_path)
    api.load_transaction_plan(root, anchors, now=10)
    raw["manager_version"] = "6.8.4.1"
    calls = []
    original = api._topology

    def topology(*args):
        calls.append(args)
        return original(*args)

    monkeypatch.setattr(api, "_topology", topology)
    current = api.load_transaction_plan(root, publish(root, raw), now=11)
    assert current.manager_version == "6.8.4.1"
    assert len(calls) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"schema": "approved-plan-v1"},
        {"epoch": True},
        {"epoch": 4},
        {"kind": "ready"},
        {"kind": []},
        {"expires_at": True},
        {"expires_at": float("nan")},
        {"expires_at": float("inf")},
        {"transaction_id": "e" * 63},
        {"product_commit": "B" * 40},
        {"product_tree": "c" * 64},
        {"instance_index": "01"},
        {"instance_index": "10000"},
        {"manager_version": "6.8.4"},
        {"manager_version": "1" * 1024 + ".2.3.4"},
        {"host_namespace": "BAD"},
        {"reviewed_scope_sha256": "wrong"},
        {"extra": 1},
    ],
)
def test_invalid_envelope_rejected(tmp_path, change):
    api = module()
    root, _, raw = bundle(tmp_path)
    raw.update(change)
    with pytest.raises(ApprovalNotReady):
        api.load_transaction_plan(root, publish(root, raw), now=10)


@pytest.mark.parametrize(
    "change",
    [
        {"schema": "bad"},
        {"epoch": True},
        {"epoch": 0},
        {"epoch": 4},
        {"approved_plan_sha256": "0" * 64},
        {"revoked_plan_sha256": ["invalid"]},
        {"revoked_plan_sha256": "invalid"},
        {"unknown": 1},
    ],
)
def test_current_authority_must_match(tmp_path, change):
    api = module()
    root, _, raw = bundle(tmp_path)
    with pytest.raises(ApprovalNotReady):
        api.load_transaction_plan(root, publish(root, raw, authority_changes=change), now=10)


def test_revoked_and_expired_approval_rejected(tmp_path):
    api = module()
    root, anchors, raw = bundle(tmp_path)
    with pytest.raises(ApprovalNotReady):
        api.load_transaction_plan(root, anchors, now=1000)
    revoked = publish(root, raw, authority_changes={"revoked_plan_sha256": [anchors.plan_sha256]})
    with pytest.raises(ApprovalNotReady):
        api.load_transaction_plan(root, revoked, now=10)


@pytest.mark.parametrize("now", [True, None, float("inf"), float("nan")])
def test_invalid_clock_rejected(tmp_path, now):
    api = module()
    root, anchors, _ = bundle(tmp_path)
    with pytest.raises(ApprovalNotReady):
        api.load_transaction_plan(root, anchors, now=now)


@pytest.mark.parametrize("field", ["root_identity", "plan_parent_identity", "authority", "plan"])
def test_wrong_pinned_control_object_rejected(tmp_path, field):
    api = module()
    root, anchors, _ = bundle(tmp_path)
    fake = FileIdentity("python_stat", 1, 1)
    value = fake if field.endswith("identity") else replace(getattr(anchors, field), identity=fake)
    with pytest.raises(ApprovalNotReady):
        api.load_transaction_plan(root, replace(anchors, **{field: value}), now=10)


@pytest.mark.parametrize("name", ["host", "manager", "config", "config_previous", "journal"])
@pytest.mark.parametrize("value", [[True, 1], [1, False], [1, 0], [-1, 1], [1.0, 2], [1]])
def test_target_identity_requires_strict_integers(tmp_path, name, value):
    api = module()
    root, _, raw = bundle(tmp_path, kind="existing")
    raw["targets"][name]["identity"] = value
    with pytest.raises(ApprovalNotReady):
        api.load_transaction_plan(root, publish(root, raw), now=10)


@pytest.mark.parametrize("name", ["admissions", "transactions", "transaction", "evidence"])
def test_directory_identity_requires_strict_integers(tmp_path, name):
    api = module()
    root, _, raw = bundle(tmp_path)
    raw["directories"][name]["identity"] = [True, 1]
    with pytest.raises(ApprovalNotReady):
        api.load_transaction_plan(root, publish(root, raw), now=10)


@pytest.mark.parametrize("name", ["admissions", "transactions", "transaction"])
def test_control_directory_names_are_fixed(tmp_path, name):
    api = module()
    root, _, raw = bundle(tmp_path)
    raw["directories"][name]["path"] = str(tmp_path / "other")
    with pytest.raises(ApprovalNotReady):
        api.load_transaction_plan(root, publish(root, raw), now=10)


@pytest.mark.parametrize("section", ["targets", "directories"])
@pytest.mark.parametrize("action", ["missing", "extra", "nested_extra"])
def test_target_and_directory_sets_are_exact(tmp_path, section, action):
    api = module()
    root, _, raw = bundle(tmp_path)
    name = next(iter(raw[section]))
    if action == "missing":
        del raw[section][name]
    elif action == "extra":
        raw[section]["unexpected"] = raw[section][name]
    else:
        raw[section][name]["extra"] = True
    with pytest.raises(ApprovalNotReady):
        api.load_transaction_plan(root, publish(root, raw), now=10)


@pytest.mark.parametrize("kind", ["new_enrollment", "existing"])
@pytest.mark.parametrize("name", ["journal", "device_lock", "receipt", "host"])
def test_target_presence_and_hash_policy_is_strict(tmp_path, kind, name):
    api = module()
    root, _, raw = bundle(tmp_path, kind=kind)
    item = raw["targets"][name]
    if name == "journal" and kind == "existing":
        item["sha256"] = "a" * 64
    elif item["identity"] is None:
        item["identity"] = [1, 1]
        item["sha256"] = "a" * 64
    else:
        item["identity"] = None
        item["sha256"] = None
    with pytest.raises(ApprovalNotReady):
        api.load_transaction_plan(root, publish(root, raw), now=10)


@pytest.mark.parametrize(
    "text",
    ["relative", "/a/../b", "/a//b", "/a/./b", "//host/share", "/a/\0b", "/" + "x" * 1024],
    ids=["relative", "parent", "double-slash", "dot", "unc", "nul", "oversized"],
)
def test_target_path_must_be_canonical_absolute_and_bounded(tmp_path, text):
    api = module()
    root, _, raw = bundle(tmp_path)
    raw["targets"]["manager"]["path"] = text
    with pytest.raises(ApprovalNotReady):
        api.load_transaction_plan(root, publish(root, raw), now=10)


@pytest.mark.parametrize(
    "change", ["receipt", "lock", "journal_suffix", "config_pair", "duplicate"]
)
def test_derived_target_names_are_not_caller_selectable(tmp_path, change):
    api = module()
    root, _, raw = bundle(tmp_path)
    targets = raw["targets"]
    if change == "receipt":
        targets["receipt"]["path"] = str(tmp_path / "mumu-experiment-registration.json")
    elif change == "lock":
        targets["device_lock"]["path"] = str(tmp_path / "device-wrong.lock")
    elif change == "journal_suffix":
        targets["journal"]["path"] += ".txt"
    elif change == "config_pair":
        targets["config_previous"]["path"] += ".bak"
    else:
        targets["manager"]["path"] = targets["host"]["path"]
    with pytest.raises(ApprovalNotReady):
        api.load_transaction_plan(root, publish(root, raw), now=10)


@pytest.mark.parametrize(
    "collision",
    ["authority", "admission_lock", "admission", "intent", "candidate", "stage", "provenance"],
)
def test_static_targets_cannot_alias_controlled_write_names(tmp_path, collision):
    api = module()
    root, anchors, raw = bundle(tmp_path)
    directory = root / "transactions" / raw["transaction_id"]
    paths = {
        "authority": root / "authority-v1.json",
        "admission_lock": root / "admission.lock",
        "admission": root / "admissions" / (anchors.plan_sha256 + ".json"),
        "intent": directory / "enrollment-intent-v1.json",
        "candidate": directory / "candidate-v1.json",
        "stage": directory / "stage-01.json",
        "provenance": Path(raw["targets"]["journal"]["path"]).parent / "enrollment-v1.json",
    }
    # The admission file hash changes with this mutation, so use the fixed admissions
    # directory itself to exercise the same forbidden control-tree rule.
    raw["targets"]["manager"]["path"] = str(
        root / "admissions" if collision == "admission" else paths[collision]
    )
    with pytest.raises(ApprovalNotReady):
        api.load_transaction_plan(root, publish(root, raw), now=10)


@pytest.mark.parametrize("name", ["host", "manager", "config", "config_previous"])
def test_static_bytes_are_checked_only_at_frozen_input_validation(tmp_path, name):
    api = module()
    root, anchors, raw = bundle(tmp_path)
    Path(raw["targets"][name]["path"]).write_bytes(b"changed")
    plan = api.load_transaction_plan(root, anchors, now=10)
    with pytest.raises(ApprovalNotReady):
        api.validate_frozen_inputs(plan)


@pytest.mark.parametrize("name", ["admissions", "transactions", "transaction", "evidence"])
def test_directory_replacement_rejected_when_frozen_inputs_are_validated(tmp_path, name):
    api = module()
    root, anchors, raw = bundle(tmp_path)
    path = Path(raw["directories"][name]["path"])
    path.rename(path.with_name(path.name + ".old"))
    path.mkdir()
    plan = api.load_transaction_plan(root, anchors, now=10)
    with pytest.raises(ApprovalNotReady):
        api.validate_frozen_inputs(plan)


def test_target_parent_replacement_rejected_when_frozen_inputs_are_validated(tmp_path):
    api = module()
    root, anchors, raw = bundle(tmp_path)
    parent = Path(raw["targets"]["journal"]["path"]).parent
    parent.rename(parent.with_name("old-journal"))
    parent.mkdir()
    plan = api.load_transaction_plan(root, anchors, now=10)
    with pytest.raises(ApprovalNotReady):
        api.validate_frozen_inputs(plan)


@pytest.mark.parametrize("name", ["journal", "receipt", "device_lock"])
def test_frozen_input_validation_does_not_reject_phase_owned_mutable_outputs(tmp_path, name):
    api = module()
    root, anchors, raw = bundle(tmp_path)
    Path(raw["targets"][name]["path"]).write_bytes(b"coordinator must validate this")
    plan = api.load_transaction_plan(root, anchors, now=10)
    api.validate_frozen_inputs(plan)


def test_existing_journal_content_is_not_frozen_or_read(tmp_path):
    api = module()
    root, anchors, raw = bundle(tmp_path, kind="existing")
    Path(raw["targets"]["journal"]["path"]).write_bytes(b"legitimate runtime changes")
    plan = api.load_transaction_plan(root, anchors, now=10)
    api.validate_frozen_inputs(plan)


@pytest.mark.parametrize("change", ["host_namespace", "device_id", "xml_pair", "xml_name"])
def test_frozen_semantic_mapping_must_match_plan(tmp_path, change):
    api = module()
    root, _, raw = bundle(tmp_path)
    if change in {"host_namespace", "device_id"}:
        raw[change] = "44444444-4444-4444-8444-444444444444"
        if change == "device_id":
            old = Path(raw["targets"]["device_lock"]["path"])
            raw["targets"]["device_lock"]["path"] = str(
                old.parent
                / ("device-" + hashlib.sha256(raw[change].encode()).hexdigest() + ".lock")
            )
    else:
        names = ("config_previous",) if change == "xml_pair" else ("config", "config_previous")
        for name in names:
            path = Path(raw["targets"][name]["path"])
            path.write_text(f'<Machine uuid="{raw["stable_instance"]}" name="Wrong-0"/>')
            raw["targets"][name]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    plan = api.load_transaction_plan(root, publish(root, raw), now=10)
    with pytest.raises(ApprovalNotReady):
        api.validate_frozen_inputs(plan)


def test_duplicate_json_keys_are_rejected(tmp_path):
    api = module()
    root, _, raw = bundle(tmp_path)
    duplicate = json.dumps(raw)[:-1] + ',"epoch":3}'
    anchors = publish(root, raw, raw=duplicate.encode())
    with pytest.raises(ApprovalNotReady):
        api.load_transaction_plan(root, anchors, now=10)


@pytest.mark.parametrize("section", ["targets", "directories"])
def test_pure_preflight_rejects_unbounded_path_depth(tmp_path, section):
    api = module()
    root, _, raw = bundle(tmp_path)
    name = "manager" if section == "targets" else "evidence"
    raw[section][name]["path"] = "/" + "/".join(["a"] * 65)
    with pytest.raises(ApprovalNotReady):
        api.parse_plan_payload(root, json.dumps(raw).encode())


@pytest.mark.parametrize("section", ["targets", "directories"])
def test_pure_preflight_rejects_inconsistent_shared_parent_identity(tmp_path, section):
    api = module()
    root, _, raw = bundle(tmp_path)
    if section == "targets":
        raw["targets"]["receipt"]["parent_identity"] = [1, 1]
    else:
        raw["directories"]["evidence"]["path"] = str(Path(raw["targets"]["host"]["path"]).parent)
        raw["directories"]["evidence"]["identity"] = [1, 1]
    with pytest.raises(ApprovalNotReady):
        api.parse_plan_payload(root, json.dumps(raw).encode())


@pytest.mark.parametrize("kind", ["new_enrollment", "existing"])
def test_loader_does_not_inspect_any_actual_mutable_artifact(tmp_path, monkeypatch, kind):
    api = module()
    root, anchors, raw = bundle(tmp_path, kind=kind)
    mutable = {Path(raw["targets"][name]["path"]) for name in ("journal", "receipt", "device_lock")}
    original = Path.lstat

    def deny_mutable_access(path, *args, **kwargs):
        assert path not in mutable, "coordinator owns mutable artifact checks"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", deny_mutable_access)
    plan = api.load_transaction_plan(root, anchors, now=10)
    api.validate_frozen_inputs(plan)


@pytest.mark.parametrize("name", ["host", "manager", "config", "config_previous"])
def test_frozen_validation_rejects_same_bytes_at_replaced_identity(tmp_path, name):
    api = module()
    root, anchors, raw = bundle(tmp_path)
    path = Path(raw["targets"][name]["path"])
    old = path.with_name(path.name + ".old")
    path.rename(old)
    path.write_bytes(old.read_bytes())
    plan = api.load_transaction_plan(root, anchors, now=10)
    with pytest.raises(ApprovalNotReady):
        api.validate_frozen_inputs(plan)


@pytest.mark.skipif(os.name == "nt", reason="symlink creation requires separate Windows permission")
@pytest.mark.parametrize("name", ["host", "manager", "config", "config_previous"])
def test_frozen_validation_rejects_static_symlink_and_hardlink(tmp_path, name):
    api = module()
    root, _, raw = bundle(tmp_path)
    path = Path(raw["targets"][name]["path"])
    old = path.with_name(path.name + ".old")
    path.rename(old)
    path.symlink_to(old)
    raw["targets"][name]["identity"] = identity(path)
    plan = api.load_transaction_plan(root, publish(root, raw), now=10)
    with pytest.raises(ApprovalNotReady):
        api.validate_frozen_inputs(plan)
    path.unlink()
    os.link(old, path)
    plan = api.load_transaction_plan(root, publish(root, raw), now=10)
    with pytest.raises(ApprovalNotReady):
        api.validate_frozen_inputs(plan)


@pytest.mark.parametrize(
    "payload",
    [b"", b"\xff", b"{}", b"null", b"[]" * 40000, b"[" * 1000 + b"]" * 1000],
    ids=["empty", "invalid-utf8", "empty-object", "null", "oversized", "deep-nesting"],
)
def test_malformed_payload_is_sanitized(tmp_path, payload):
    api = module()
    with pytest.raises(ApprovalNotReady, match="^enrollment_approval_not_ready$"):
        api.parse_plan_payload(tmp_path, payload)


@pytest.mark.parametrize(
    "name", ["CON.db", "my journal.db", "数据库.db", ".journal.db", "a" * 126 + ".db"]
)
def test_first_use_journal_name_must_be_publishable_before_any_stage(tmp_path, name):
    api = module()
    root, _, raw = bundle(tmp_path)
    item = raw["targets"]["journal"]
    item["path"] = str(Path(item["path"]).with_name(name))
    with pytest.raises(ApprovalNotReady):
        api.parse_plan_payload(root, json.dumps(raw).encode())


@pytest.mark.parametrize("name", ["my journal.db", "数据库.db", "a" * 180 + ".db"])
def test_existing_journal_is_not_subject_to_new_artifact_filename_restrictions(tmp_path, name):
    api = module()
    root, _, raw = bundle(tmp_path, kind="existing")
    item = raw["targets"]["journal"]
    item["path"] = str(Path(item["path"]).with_name(name))
    plan = api.parse_plan_payload(root, json.dumps(raw).encode())
    assert next(item.path for item in plan.targets if item.name == "journal").name == name


def test_frozen_device_mapping_preserves_original_resolved_manager_identity(tmp_path, monkeypatch):
    api = module()
    root, anchors, raw = bundle(tmp_path)
    manager = Path(raw["targets"]["manager"]["path"])
    plan = api.load_transaction_plan(root, anchors, now=10)
    original = Path.resolve

    def canonical_manager(path, *args, **kwargs):
        # Simulate Windows expanding an existing 8.3 spelling to its long name.
        if path == manager:
            return manager.with_name("CanonicalMuMuManager.exe")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", canonical_manager)
    with pytest.raises(ApprovalNotReady):
        api.validate_frozen_inputs(plan)


@pytest.mark.parametrize("part", ["CON", "NUL.txt", "COM1", "LPT9.log", "ordinary.txt"])
def test_windows_reserved_component_uses_supported_api_when_available(monkeypatch, part):
    plan = module()
    calls = []

    def supported(value):
        calls.append(value)
        return value != "ordinary.txt"

    monkeypatch.setattr(plan.os.path, "isreserved", supported, raising=False)
    monkeypatch.setattr(
        plan.PureWindowsPath,
        "is_reserved",
        lambda _: pytest.fail("deprecated fallback must not run when supported API exists"),
    )
    assert plan._reserved_component(part) == (part != "ordinary.txt")
    assert calls == [part]


@pytest.mark.parametrize(
    "part, expected",
    [("CON", True), ("NUL.txt", True), ("COM1", True), ("LPT9.log", True), ("ordinary.txt", False)],
)
def test_windows_reserved_component_compatibility_fallback(monkeypatch, part, expected):
    plan = module()
    monkeypatch.setattr(plan, "os", SimpleNamespace(path=SimpleNamespace()))
    # This fallback is used only on Python versions predating os.path.isreserved.
    assert plan._reserved_component(part) is expected
