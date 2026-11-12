import hashlib
import json
import os
from dataclasses import replace

import pytest

from swu_happyrun.drivers.mumu.enrollment_authority import (
    ApprovalNotReady,
    FrozenFile,
    RunnerAnchors,
    load_approved_plan,
)
from swu_happyrun.drivers.mumu.instance_attribution import FileIdentity


def pin(path):
    return FrozenFile(
        FileIdentity.from_stat(path.stat()), hashlib.sha256(path.read_bytes()).hexdigest()
    )


def bundle(tmp_path):
    root = tmp_path / "control-v1"
    root.mkdir()
    (root / "admission.lock").write_bytes(b"0")
    plan = {
        "schema": "approved-plan-v1",
        "epoch": 3,
        "kind": "new_enrollment",
        "expires_at": 1000,
        "reviewed_scope_sha256": "a" * 64,
        "host_namespace": "11111111-1111-4111-8111-111111111111",
        "stable_instance": "22222222-2222-4222-8222-222222222222",
        "device_id": "33333333-3333-4333-8333-333333333333",
        "instance_index": "0",
        "targets": {},
        "manager_version": "6.8.4.0",
    }
    config_dir = tmp_path / "MuMu-0"
    config_dir.mkdir()
    for name in ["host", "manager", "config", "config_previous", "journal", "receipt"]:
        p = tmp_path / ("mumu-experiment-registration.json" if name == "receipt" else name)
        if name in {"config", "config_previous"}:
            p = config_dir / ("MuMu-0.nemu" if name == "config" else "MuMu-0.nemu-prev")
        if name not in {"journal", "receipt"}:
            p.write_bytes(
                (plan["host_namespace"] + "\n").encode() if name == "host" else name.encode()
            )
        if name in {"config", "config_previous"}:
            p.write_text(f'<Machine uuid="{plan["stable_instance"]}" name="MuMu-0"/>')
        plan["targets"][name] = {
            "path": str(p),
            "parent_identity": [p.parent.stat().st_dev, p.parent.stat().st_ino],
            "identity": [p.stat().st_dev, p.stat().st_ino] if p.exists() else None,
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None,
        }
    import os

    from swu_happyrun.drivers.identity import device_id

    plan["device_id"] = device_id(
        "mumu", f"{os.path.normcase(str(tmp_path / 'manager'))}:0", host_id=plan["host_namespace"]
    )
    raw = json.dumps(plan).encode()
    digest = hashlib.sha256(raw).hexdigest()
    folder = root / "reviews" / digest
    folder.mkdir(parents=True)
    path = folder / "approved-plan-v1.json"
    path.write_bytes(raw)
    authority = root / "authority-v1.json"
    authority.write_text(
        json.dumps(
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
        pin(path),
        FileIdentity.from_stat(folder.stat()),
    )
    return root, anchors, plan


def test_read_plan_has_no_writes_and_does_not_grant_execution(tmp_path):
    root, anchors, _ = bundle(tmp_path)
    before = {p: (p.stat().st_ino, p.read_bytes()) for p in tmp_path.rglob("*") if p.is_file()}
    value = load_approved_plan(root, anchors, now=10)
    assert value.epoch == 3
    assert value.execution_allowed is False
    assert before == {
        p: (p.stat().st_ino, p.read_bytes()) for p in tmp_path.rglob("*") if p.is_file()
    }


@pytest.mark.parametrize(
    "change", ["expired", "authority_hash", "authority_id", "plan_id", "parent_id"]
)
def test_invalid_pin_or_expiry_rejected(tmp_path, change):
    root, anchors, _ = bundle(tmp_path)
    if change == "expired":
        now = 1000
    else:
        now = 10
        key = "authority" if change.startswith("authority") else "plan"
        if change.endswith("hash"):
            anchors = replace(anchors, **{key: replace(getattr(anchors, key), sha256="0" * 64)})
        elif change == "parent_id":
            anchors = replace(anchors, plan_parent_identity=FileIdentity("python_stat", 1, 1))
        else:
            anchors = replace(
                anchors,
                **{key: replace(getattr(anchors, key), identity=FileIdentity("python_stat", 1, 1))},
            )
    with pytest.raises(ApprovalNotReady):
        load_approved_plan(root, anchors, now=now)


def test_target_replacement_and_missing_are_not_approved(tmp_path):
    root, anchors, _ = bundle(tmp_path)
    host = tmp_path / "host"
    host.unlink()
    host.write_bytes(b"other")
    with pytest.raises(ApprovalNotReady):
        load_approved_plan(root, anchors, now=10)


def test_future_target_must_remain_absent(tmp_path):
    root, anchors, _ = bundle(tmp_path)
    (tmp_path / "journal").write_bytes(b"unexpected")
    with pytest.raises(ApprovalNotReady):
        load_approved_plan(root, anchors, now=10)


def test_old_valid_approval_not_rejected_by_age(tmp_path):
    root, anchors, _ = bundle(tmp_path)
    assert load_approved_plan(root, anchors, now=999).epoch == 3


def rewrite_bundle(root, anchors, *, authority_changes=None, plan_changes=None):
    old = root / "reviews" / anchors.plan_sha256 / "approved-plan-v1.json"
    plan = json.loads(old.read_bytes())
    if plan_changes:
        plan.update(plan_changes)
    raw = json.dumps(plan).encode()
    digest = hashlib.sha256(raw).hexdigest()
    folder = root / "reviews" / digest
    folder.mkdir(exist_ok=True)
    path = folder / "approved-plan-v1.json"
    path.write_bytes(raw)
    auth = json.loads((root / "authority-v1.json").read_bytes())
    auth["approved_plan_sha256"] = digest
    if authority_changes:
        auth.update(authority_changes)
    (root / "authority-v1.json").write_text(json.dumps(auth))
    return replace(
        anchors,
        authority=pin(root / "authority-v1.json"),
        plan_sha256=digest,
        plan=pin(path),
        plan_parent_identity=FileIdentity.from_stat(folder.stat()),
    )


@pytest.mark.parametrize(
    "change",
    [
        {"schema": "other"},
        {"epoch": True},
        {"epoch": 0},
        {"epoch": 4},
        {"approved_plan_sha256": "0" * 64},
        {"unknown": True},
        {"revoked_plan_sha256": ["invalid"]},
    ],
)
def test_invalid_current_authority_rejected(tmp_path, change):
    root, anchors, _ = bundle(tmp_path)
    anchors = rewrite_bundle(root, anchors, authority_changes=change)
    with pytest.raises(ApprovalNotReady):
        load_approved_plan(root, anchors, now=10)


def test_revocation_rejects_even_pinned_plan(tmp_path):
    root, anchors, _ = bundle(tmp_path)
    anchors = rewrite_bundle(
        root, anchors, authority_changes={"revoked_plan_sha256": [anchors.plan_sha256]}
    )
    with pytest.raises(ApprovalNotReady):
        load_approved_plan(root, anchors, now=10)


@pytest.mark.parametrize(
    "change",
    [
        {"schema": "other"},
        {"epoch": True},
        {"kind": "ready"},
        {"expires_at": float("nan")},
        {"instance_index": "01"},
        {"reviewed_scope_sha256": "wrong"},
        {"extra": 1},
    ],
)
def test_invalid_plan_rejected(tmp_path, change):
    root, anchors, _ = bundle(tmp_path)
    anchors = rewrite_bundle(root, anchors, plan_changes=change)
    with pytest.raises(ApprovalNotReady):
        load_approved_plan(root, anchors, now=10)


def test_same_bytes_replaced_inode_rejected(tmp_path):
    root, anchors, _ = bundle(tmp_path)
    source = root / "authority-v1.json"
    backup = root / "replacement"
    backup.write_bytes(source.read_bytes())
    backup.replace(source)
    with pytest.raises(ApprovalNotReady):
        load_approved_plan(root, anchors, now=10)


def test_untrusted_anchor_cannot_enable_native(tmp_path):
    from swu_happyrun.drivers.base import DriverError
    from swu_happyrun.drivers.mumu.enrollment import require_native_enrollment

    root, anchors, _ = bundle(tmp_path)
    candidate = load_approved_plan(root, anchors, now=10)
    with pytest.raises(DriverError, match="enrollment_execution_not_ready"):
        require_native_enrollment(candidate)


def test_mutable_existing_journal_uses_identity_not_full_hash(tmp_path):
    root, anchors, plan = bundle(tmp_path)
    journal = tmp_path / "journal"
    receipt = tmp_path / "mumu-experiment-registration.json"
    journal.write_bytes(b"initial mutable state")
    receipt.write_bytes(b"frozen receipt")
    for name, path in [("journal", journal), ("receipt", receipt)]:
        plan["targets"][name]["identity"] = [path.stat().st_dev, path.stat().st_ino]
        plan["targets"][name]["sha256"] = (
            None if name == "journal" else hashlib.sha256(path.read_bytes()).hexdigest()
        )
    anchors = rewrite_bundle(
        root, anchors, plan_changes={"kind": "existing", "targets": plan["targets"]}
    )
    first = load_approved_plan(root, anchors, now=10)
    journal.write_bytes(b"new intent and result")
    assert load_approved_plan(root, anchors, now=11) == first
    replacement = tmp_path / "new-database"
    replacement.write_bytes(journal.read_bytes())
    replacement.replace(journal)
    with pytest.raises(ApprovalNotReady):
        load_approved_plan(root, anchors, now=12)


def test_cross_domain_anchor_cannot_compare_equal(tmp_path):
    root, anchors, _ = bundle(tmp_path)
    original = anchors.root_identity
    with pytest.raises(ApprovalNotReady):
        replace(
            anchors,
            root_identity=FileIdentity(
                "win32_legacy_ntfs", original.volume % 2**32, original.file_index
            ),
        )


def test_approval_reader_rejects_fifo_before_open(tmp_path, monkeypatch):
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO not supported")
    root, anchors, _ = bundle(tmp_path)
    path = root / "authority-v1.json"
    path.unlink()
    os.mkfifo(path)

    def forbidden(*args, **kwargs):
        pytest.fail("opened FIFO")

    monkeypatch.setattr(os, "open", forbidden)
    with pytest.raises(ApprovalNotReady):
        load_approved_plan(root, anchors, now=10)
