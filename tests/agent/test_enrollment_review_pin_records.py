"""Pure synthetic pin records are neither review authority nor runtime readiness."""

import hashlib
import importlib
import json
import math
import os
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from swu_happyrun.drivers.mumu.enrollment_authority import FrozenFile, RunnerAnchors
from swu_happyrun.drivers.mumu.enrollment_transaction_plan import parse_plan_payload
from swu_happyrun.drivers.mumu.enrollment_transaction_records import (
    ArtifactObservation,
    TransactionLayout,
)
from swu_happyrun.drivers.mumu.instance_attribution import FileIdentity

MODULE = "swu_happyrun.drivers.mumu.enrollment_review_pin_records"
REVIEWER = "original-machine-codex"
HOST_ID = "11111111-1111-4111-8111-111111111111"
OTHER_REVIEWER = "22222222-2222-4222-8222-222222222222"
ROLES = (
    "authority",
    "approved_plan",
    "reviewed_scope",
    "host",
    "manager",
    "config",
    "config_previous",
    "admission",
    "intent",
    "device_lock",
    "provenance",
    "receipt",
    "candidate",
    *(f"stage{n:02d}" for n in range(1, 8)),
)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def identity(number):
    return FileIdentity("python_stat", 1, number)


@pytest.fixture
def bundle(tmp_path):
    root = tmp_path / "control-v1"
    tx = "a" * 64
    device = "33333333-3333-4333-8333-333333333333"
    state = tmp_path / "state"
    paths = {
        "host": state / "host-id",
        "manager": tmp_path / "MuMu" / "manager.exe",
        "config": tmp_path / "MuMu" / "machine.nemu",
        "config_previous": tmp_path / "MuMu" / "machine.nemu-prev",
        "journal": tmp_path / "journal" / "runs.sqlite",
        "receipt": state / "mumu-experiment-registration.json",
        "device_lock": tmp_path
        / "journal"
        / f"device-{hashlib.sha256(device.encode()).hexdigest()}.lock",
    }
    parent_numbers = {state: 100, tmp_path / "MuMu": 101, tmp_path / "journal": 102}
    targets = {}
    for n, (name, path) in enumerate(paths.items(), 10):
        absent = name in {"journal", "receipt", "device_lock"}
        targets[name] = {
            "path": str(path),
            "identity": None if absent else [1, n],
            "parent_identity": [1, parent_numbers[path.parent]],
            "sha256": None if absent else hashlib.sha256(name.encode()).hexdigest(),
        }
    payload = {
        "schema": "approved-plan-v2",
        "epoch": 3,
        "kind": "new_enrollment",
        "expires_at": 1000,
        "reviewed_scope_sha256": "d" * 64,
        "manager_version": "6.8.4.0",
        "host_namespace": HOST_ID,
        "stable_instance": OTHER_REVIEWER,
        "device_id": device,
        "instance_index": "0",
        "targets": targets,
        "transaction_id": tx,
        "product_commit": "b" * 40,
        "product_tree": "c" * 40,
        "directories": {
            name: {"path": str(path), "identity": [1, number]}
            for name, path, number in (
                ("admissions", root / "admissions", 200),
                ("transactions", root / "transactions", 201),
                ("transaction", root / "transactions" / tx, 202),
                ("evidence", tmp_path / "evidence", 203),
            )
        },
    }
    raw = canonical(payload)
    plan = parse_plan_payload(root, raw)
    anchors = RunnerAnchors(
        identity(300),
        identity(301),
        FrozenFile(identity(302), "e" * 64),
        plan.plan_sha256,
        FrozenFile(identity(303), plan.plan_sha256),
        identity(304),
    )
    layout = TransactionLayout(
        root, plan.plan_sha256, tx, paths["journal"], paths["receipt"], device
    )
    review = root / "reviews" / plan.plan_sha256
    frozen = {}
    for n, role in enumerate(ROLES, 400):
        if role == "authority":
            path, parent, object_id, digest = (
                root / "authority-v1.json",
                anchors.root_identity,
                anchors.authority.identity,
                anchors.authority.sha256,
            )
        elif role == "approved_plan":
            path, parent, object_id, digest = (
                review / "approved-plan-v2.json",
                anchors.plan_parent_identity,
                anchors.plan.identity,
                plan.plan_sha256,
            )
        elif role == "reviewed_scope":
            path, parent, object_id, digest = (
                review / "reviewed-scope-v1.json",
                anchors.plan_parent_identity,
                identity(n),
                plan.reviewed_scope_sha256,
            )
        elif role in {"host", "manager", "config", "config_previous"}:
            target = next(item for item in plan.targets if item.name == role)
            path, parent, object_id, digest = (
                target.path,
                target.parent_identity,
                target.identity,
                target.sha256,
            )
        else:
            path = (
                layout.record_path(int(role[5:])) if role.startswith("stage") else layout.path(role)
            )
            parent = (
                identity(202)
                if path.parent == layout.directory
                else identity(200)
                if role == "admission"
                else identity(parent_numbers[path.parent])
            )
            object_id, digest = identity(n), hashlib.sha256(role.encode()).hexdigest()
        frozen[role] = ArtifactObservation(role, path, object_id, parent, n, digest)
    return root, anchors, plan, frozen, (paths["journal"], identity(500), identity(102))


def encode(bundle, **changes):
    module = importlib.import_module(MODULE)
    root, anchors, plan, frozen, journal = bundle
    args = {
        "reviewer_id": REVIEWER,
        "reviewed_at": 123.5,
        "frozen": frozen,
        "journal": module.JournalBinding(*journal),
    }
    args.update(changes)
    return module.encode_review_pin(root, anchors, plan, **args)


def decode(bundle, raw, **changes):
    module = importlib.import_module(MODULE)
    root, anchors, plan, _, _ = bundle
    args = {"root": root, "anchors": anchors, "plan": plan, "expected_reviewer_id": REVIEWER}
    args.update(changes)
    return module.decode_review_pin(raw, **args)


def test_round_trip_fixed_roles_immutable_and_no_execution_permission(bundle):
    module = importlib.import_module(MODULE)
    raw = encode(bundle)
    result = decode(bundle, raw)
    assert result.canonical_bytes == raw
    assert result.sha256 == hashlib.sha256(raw).hexdigest()
    assert result.reviewer_id == REVIEWER
    assert result.reviewed_at == 123.5
    assert result.expires_at == 1000
    assert result.execution_allowed is False
    assert tuple(item.role for item in result.frozen) == ROLES == module.FROZEN_ROLES
    assert result.frozen == tuple(bundle[3].values())
    assert result.journal == module.JournalBinding(*bundle[4])
    with pytest.raises(FrozenInstanceError):
        result.reviewer_id = OTHER_REVIEWER
    value = json.loads(raw)
    assert set(value["journal"]) == {"path", "identity", "parent_identity"}
    assert value["candidate_sha256"] == bundle[3]["candidate"].sha256
    assert "ready" not in raw.decode()
    assert raw == canonical(value)


def test_encode_decode_are_pure_and_never_follow_attacker_paths(bundle, monkeypatch):
    module = importlib.import_module(MODULE)

    def forbidden(*args, **kwargs):
        pytest.fail("record parser attempted filesystem access")

    for name in ("open", "stat", "lstat", "resolve", "exists", "is_file", "is_dir", "read_bytes"):
        monkeypatch.setattr(Path, name, forbidden)
    monkeypatch.setattr(os, "open", forbidden)
    raw = encode(bundle)
    decode(bundle, raw)
    value = json.loads(raw)
    value["frozen"]["candidate"]["path"] = "/untrusted/arbitrary/path"
    with pytest.raises(module.ReviewPinInvalid):
        decode(bundle, canonical(value))


@pytest.mark.parametrize(
    "field,bad",
    [
        ("schema", "review-pin-v2"),
        ("epoch", True),
        ("epoch", 4),
        ("plan_sha256", "0" * 64),
        ("transaction_id", "0" * 64),
        ("candidate_sha256", "0" * 64),
        ("reviewed_scope_sha256", "0" * 64),
        ("product_commit", "0" * 40),
        ("product_tree", "0" * 40),
        ("reviewer_id", OTHER_REVIEWER),
        ("reviewer_id", REVIEWER.upper().replace("1", "A", 1)),
        ("reviewed_at", True),
        ("reviewed_at", "123"),
        ("reviewed_at", 1000),
        ("expires_at", 1001),
        ("expires_at", 1000.0),
        ("execution_allowed", True),
        ("execution_allowed", 0),
    ],
    ids=[
        "schema",
        "epoch_bool",
        "epoch_changed",
        "plan_digest",
        "transaction_digest",
        "candidate_digest",
        "scope_digest",
        "product_commit",
        "product_tree",
        "reviewer_other",
        "reviewer_noncanonical",
        "review_time_bool",
        "review_time_string",
        "review_time_expired",
        "expiry_changed",
        "expiry_type_changed",
        "execution_true",
        "execution_integer",
    ],
)
def test_reject_changed_trusted_or_strict_metadata(bundle, field, bad):
    module = importlib.import_module(MODULE)
    value = json.loads(encode(bundle))
    value[field] = bad
    with pytest.raises(module.ReviewPinInvalid):
        decode(bundle, canonical(value))


@pytest.mark.parametrize("field", ["root_identity", "lock_identity", "review_parent_identity"])
def test_reject_replaced_control_identities(bundle, field):
    module = importlib.import_module(MODULE)
    value = json.loads(encode(bundle))
    value[field]["value"][1] += 1
    with pytest.raises(module.ReviewPinInvalid):
        decode(bundle, canonical(value))


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("field", ["path", "parent_identity"])
def test_every_frozen_role_path_and_parent_is_trusted_derivation(bundle, role, field):
    module = importlib.import_module(MODULE)
    value = json.loads(encode(bundle))
    value["frozen"][role][field] = (
        "/arbitrary" if field == "path" else {"domain": "python_stat", "value": [1, 9999]}
    )
    with pytest.raises(module.ReviewPinInvalid):
        decode(bundle, canonical(value))


@pytest.mark.parametrize(
    "role", ["authority", "approved_plan", "host", "manager", "config", "config_previous"]
)
@pytest.mark.parametrize("field", ["identity", "sha256"])
def test_preexisting_frozen_hashes_and_identities_must_match_trust(bundle, role, field):
    module = importlib.import_module(MODULE)
    value = json.loads(encode(bundle))
    value["frozen"][role][field] = (
        "0" * 64 if field == "sha256" else {"domain": "python_stat", "value": [1, 9999]}
    )
    with pytest.raises(module.ReviewPinInvalid):
        decode(bundle, canonical(value))


@pytest.mark.parametrize(
    "change",
    [
        "extra",
        "missing",
        "journal_frozen",
        "renamed_role",
        "size_bool",
        "size_negative",
        "hash_upper",
        "identity_bool",
        "identity_zero",
        "identity_domain",
        "identity_extra",
        "parent_extra",
        "journal_hash",
        "journal_size",
        "journal_path",
        "journal_parent",
        "nested_extra",
        "top_extra",
        "scope_hash",
    ],
)
def test_exact_keys_roles_identities_and_journal_identity_only(bundle, change):
    module = importlib.import_module(MODULE)
    value = json.loads(encode(bundle))
    candidate = value["frozen"]["candidate"]
    if change == "extra":
        value["frozen"]["extra"] = candidate.copy()
    elif change == "missing":
        del value["frozen"]["stage07"]
    elif change == "journal_frozen":
        value["frozen"]["journal"] = candidate.copy()
    elif change == "renamed_role":
        candidate["role"] = "intent"
    elif change == "size_bool":
        candidate["size"] = True
    elif change == "size_negative":
        candidate["size"] = -1
    elif change == "hash_upper":
        candidate["sha256"] = "A" * 64
    elif change == "identity_bool":
        candidate["identity"]["value"][0] = True
    elif change == "identity_zero":
        candidate["identity"]["value"][1] = 0
    elif change == "identity_domain":
        candidate["identity"]["domain"] = "win32_legacy_ntfs"
    elif change == "identity_extra":
        candidate["identity"]["extra"] = 1
    elif change == "parent_extra":
        candidate["parent_identity"]["extra"] = 1
    elif change == "journal_hash":
        value["journal"]["sha256"] = "a" * 64
    elif change == "journal_size":
        value["journal"]["size"] = 1
    elif change == "journal_path":
        value["journal"]["path"] = "/untrusted/journal.sqlite"
    elif change == "journal_parent":
        value["journal"]["parent_identity"]["value"][1] = 9999
    elif change == "nested_extra":
        candidate["extra"] = 1
    elif change == "top_extra":
        value["extra"] = 1
    else:
        value["frozen"]["reviewed_scope"]["sha256"] = "f" * 64
    with pytest.raises(module.ReviewPinInvalid):
        decode(bundle, canonical(value))


@pytest.mark.parametrize(
    "change",
    [
        "whitespace",
        "duplicate",
        "nested_duplicate",
        "nan",
        "inf",
        "overflow",
        "unicode",
        "oversized",
        "deep",
        "huge_number",
        "not_bytes",
    ],
)
def test_bounded_canonical_parser_rejects_adversarial_encodings(bundle, change):
    module = importlib.import_module(MODULE)
    raw = encode(bundle)
    if change == "whitespace":
        raw += b"\n"
    elif change == "duplicate":
        raw = raw.replace(b"{", b'{"schema":"review-pin-v1",', 1)
    elif change == "nested_duplicate":
        raw = raw.replace(
            b'"domain":"python_stat"', b'"domain":"python_stat","domain":"python_stat"', 1
        )
    elif change in {"nan", "inf", "overflow"}:
        raw = raw.replace(
            b'"reviewed_at":123.5',
            b'"reviewed_at":' + {"nan": b"NaN", "inf": b"Infinity", "overflow": b"1e999"}[change],
        )
    elif change == "unicode":
        raw = b"\xff"
    elif change == "oversized":
        raw = b" " * (module.MAX_REVIEW_PIN_BYTES + 1)
    elif change == "deep":
        raw = b"[" * 1000 + b"0" + b"]" * 1000
    elif change == "huge_number":
        raw = b'{"epoch":' + b"9" * 5000 + b"}"
    else:
        raw = raw.decode()
    with pytest.raises(module.ReviewPinInvalid):
        decode(bundle, raw)


@pytest.mark.parametrize(
    "bad",
    [True, math.nan, math.inf, -math.inf, "123", None, 1000],
    ids=["bool", "nan", "infinity", "negative_infinity", "string", "null", "expired"],
)
def test_encoder_also_validates_review_timestamp(bundle, bad):
    module = importlib.import_module(MODULE)
    with pytest.raises(module.ReviewPinInvalid):
        encode(bundle, reviewed_at=bad)


def test_expected_reviewer_is_external_not_self_attested(bundle):
    module = importlib.import_module(MODULE)
    raw = encode(bundle)
    with pytest.raises(module.ReviewPinInvalid):
        decode(bundle, raw, expected_reviewer_id=OTHER_REVIEWER)


def test_existing_journal_and_device_lock_preserve_approved_identities(bundle):
    module = importlib.import_module(MODULE)
    root, anchors, plan, frozen, journal = bundle
    targets = tuple(
        replace(item, identity=identity(900))
        if item.name == "journal"
        else replace(
            item, identity=frozen["device_lock"].identity, sha256=frozen["device_lock"].sha256
        )
        if item.name == "device_lock"
        else item
        for item in plan.targets
    )
    existing = replace(plan, kind="existing", targets=targets)
    bundle = root, anchors, existing, frozen, (journal[0], identity(900), journal[2])
    decode(bundle, encode(bundle))
    with pytest.raises(module.ReviewPinInvalid):
        encode(bundle, journal=module.JournalBinding(*journal))
    frozen = dict(frozen)
    frozen["device_lock"] = replace(frozen["device_lock"], identity=identity(901))
    with pytest.raises(module.ReviewPinInvalid):
        encode(bundle, frozen=frozen)


def test_python_stat_preserves_128_bit_windows_file_indexes(bundle):
    root, anchors, plan, frozen, journal = bundle
    large_identity = FileIdentity("python_stat", 1, 2**127 + 123)
    frozen = dict(frozen)
    frozen["candidate"] = replace(frozen["candidate"], identity=large_identity)
    bundle = root, anchors, plan, frozen, journal
    result = decode(bundle, encode(bundle))
    assert (
        next(item for item in result.frozen if item.role == "candidate").identity == large_identity
    )
    assert result.execution_allowed is False


def test_expiry_preserves_exact_plan_numeric_representation(bundle):
    module = importlib.import_module(MODULE)
    root, anchors, plan, frozen, journal = bundle
    bundle = root, anchors, replace(plan, expires_at=-0.0), frozen, journal
    raw = encode(bundle, reviewed_at=-1)
    value = json.loads(raw)
    assert math.copysign(1, value["expires_at"]) == -1
    value["expires_at"] = 0.0
    with pytest.raises(module.ReviewPinInvalid):
        decode(bundle, canonical(value))


@pytest.mark.parametrize("role", ["candidate", "stage01", "reviewed_scope"])
def test_frozen_objects_cannot_alias_other_files(bundle, role):
    module = importlib.import_module(MODULE)
    root, anchors, plan, frozen, journal = bundle
    frozen = dict(frozen)
    frozen[role] = replace(frozen[role], identity=frozen["intent"].identity)
    with pytest.raises(module.ReviewPinInvalid):
        encode((root, anchors, plan, frozen, journal))


def test_parser_detaches_immutable_observations_from_encoder_inputs(bundle):
    root, anchors, plan, frozen, journal = bundle
    frozen = dict(frozen)
    raw = encode((root, anchors, plan, frozen, journal))
    result = decode(bundle, raw)
    original = result.frozen
    frozen["candidate"] = replace(frozen["candidate"], size=1)
    frozen.clear()
    assert result.frozen == original
    assert result.canonical_bytes == raw
    assert str(bundle[0]) not in repr(result)


@pytest.mark.parametrize("bad", ["", "initializer", "codex", "original-machine-codex "])
def test_encoder_cannot_assert_arbitrary_reviewer_role(bundle, bad):
    module = importlib.import_module(MODULE)
    with pytest.raises(module.ReviewPinInvalid):
        encode(bundle, reviewer_id=bad)


def test_windows_paths_prefer_supported_reserved_name_api(monkeypatch):
    from pathlib import PureWindowsPath
    from types import SimpleNamespace

    module = importlib.import_module(MODULE)
    checked = []

    def supported_checker(part):
        checked.append(part)
        return part == "CON"

    def deprecated_fallback(_):
        pytest.fail("supported reserved-name API was bypassed for deprecated fallback")

    monkeypatch.setattr(os.path, "isreserved", supported_checker, raising=False)
    monkeypatch.setattr(PureWindowsPath, "is_reserved", deprecated_fallback)
    # Exercise only lexical Windows parsing without changing the process platform
    # or constructing a filesystem WindowsPath on Linux.
    monkeypatch.setattr(module, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(module, "Path", PureWindowsPath)
    assert module._path(r"C:\safe\record.json") == PureWindowsPath(r"C:\safe\record.json")
    assert checked == ["safe", "record.json"]
    with pytest.raises(module.ReviewPinInvalid):
        module._path(r"C:\safe\CON")
    assert checked[-1] == "CON"


@pytest.mark.filterwarnings("ignore:.*is_reserved.*:DeprecationWarning")
@pytest.mark.parametrize(
    "name,reserved", [("CON", True), ("LPT9.txt", True), ("record.json", False)]
)
def test_reserved_name_fallback_preserves_older_python_semantics(monkeypatch, name, reserved):
    from types import SimpleNamespace

    module = importlib.import_module(MODULE)
    plan_module = importlib.import_module("swu_happyrun.drivers.mumu.enrollment_transaction_plan")
    # PureWindowsPath.is_reserved itself uses ntpath.isreserved on Python 3.13;
    # hide the supported entry point only from the helper, not from pathlib.
    monkeypatch.setattr(plan_module, "os", SimpleNamespace(path=SimpleNamespace()))
    assert module._reserved_component(name) is reserved
