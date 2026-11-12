import json
import os
import subprocess
import sys
from contextlib import contextmanager

import pytest
from test_enrollment_authority import bundle

from swu_happyrun.drivers.mumu import enrollment_admission as admission
from swu_happyrun.drivers.mumu.enrollment_authority import ApprovalNotReady


@pytest.fixture
def approved(tmp_path, monkeypatch):
    root, anchors, plan = bundle(tmp_path)
    (root / "admissions").mkdir()
    monkeypatch.setattr(admission, "resolve_control_root", lambda: root)

    @contextmanager
    def fake_guard(root, anchors):
        yield lambda: None

    monkeypatch.setattr(admission, "_protected_root", fake_guard)

    @contextmanager
    def fake_targets(plan):
        yield

    monkeypatch.setattr(admission, "_protected_targets", fake_targets)
    monkeypatch.setattr(admission.time, "time", lambda: 10)
    return root, anchors, plan


def test_same_lock_is_exclusive_and_no_journal_created(approved):
    root, anchors, _ = approved
    with admission.locked_admission(anchors) as permit:
        assert permit.plan.execution_allowed is False
        with pytest.raises(ApprovalNotReady):
            with admission.locked_admission(anchors):
                pytest.fail("second lock")
        permit.revalidate()
    with pytest.raises(ApprovalNotReady):
        permit.revalidate()
    assert not (root.parent / "journal").exists()


def test_expiry_rechecked_inside_lock(approved, monkeypatch):
    _, anchors, _ = approved
    with admission.locked_admission(anchors) as permit:
        monkeypatch.setattr(admission.time, "time", lambda: 1000)
        with pytest.raises(ApprovalNotReady):
            permit.revalidate()


def test_authority_replacement_during_lock_rejected(approved):
    root, anchors, _ = approved
    with admission.locked_admission(anchors) as permit:
        (root / "authority-v1.json").write_bytes(b"{}")
        with pytest.raises(ApprovalNotReady):
            permit.revalidate()


def test_unexplained_admission_prevents_new_target(approved):
    root, anchors, _ = approved
    (root / "admissions" / "unexpected.json").write_bytes(b"{}")
    with pytest.raises(ApprovalNotReady):
        with admission.locked_admission(anchors):
            pytest.fail("unexplained record")
    assert not (root.parent / "journal").exists()


def test_missing_lock_does_not_create_anything(approved):
    root, anchors, _ = approved
    (root / "admission.lock").unlink()
    before = set(root.rglob("*"))
    with pytest.raises(ApprovalNotReady):
        with admission.locked_admission(anchors):
            pytest.fail("missing original lock")
    assert set(root.rglob("*")) == before


def test_cross_process_fixed_lock_busy(approved):
    root, anchors, _ = approved
    code = """
from pathlib import Path
from swu_happyrun.drivers.mumu.enrollment_admission import _existing_lock
from swu_happyrun.drivers.mumu.instance_attribution import FileIdentity
from swu_happyrun.drivers.mumu.enrollment_authority import ApprovalNotReady
import sys
p=Path(sys.argv[1])
try:
    with _existing_lock(p, FileIdentity.from_stat(p.stat())):
        sys.exit(7)
except ApprovalNotReady:
    sys.exit(0)
"""
    env = {**os.environ, "PYTHONPATH": str(__import__("pathlib").Path("src").absolute())}
    with admission.locked_admission(anchors):
        result = subprocess.run(
            [sys.executable, "-c", code, str(root / "admission.lock")],
            env=env,
            timeout=10,
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr
    result = subprocess.run(
        [sys.executable, "-c", code, str(root / "admission.lock")],
        env=env,
        timeout=10,
        capture_output=True,
    )
    assert result.returncode == 7, result.stderr


def test_record_conflict_rejects_different_plan_before_target_io(approved):
    root, anchors, plan = approved
    targets = plan["targets"]
    record = {
        "schema": "admission-v1",
        "plan_sha256": "f" * 64,
        "host_namespace": plan["host_namespace"],
        "stable_instance": plan["stable_instance"],
        "device_id": plan["device_id"],
        "instance_index": plan["instance_index"],
        "journal": targets["journal"]["path"],
        "receipt": targets["receipt"]["path"],
    }
    (root / "admissions" / ("f" * 64 + ".json")).write_text(json.dumps(record))
    with pytest.raises(ApprovalNotReady):
        with admission.locked_admission(anchors):
            pytest.fail("conflicting approved plan")


def test_closed_original_fd_rejected(approved):
    _, anchors, _ = approved
    with admission.locked_admission(anchors) as permit:
        assert permit.revalidate().execution_allowed is False
    with pytest.raises(ApprovalNotReady):
        permit.revalidate()


@pytest.mark.skipif(os.name != "nt", reason="native Windows local NTFS probe")
def test_native_volume_is_local_ntfs(tmp_path):
    admission._require_local_ntfs(tmp_path)


def test_production_admission_no_linux_fallback(tmp_path, monkeypatch):
    if os.name == "nt":
        pytest.skip("non-Windows fail-closed check")
    root, anchors, _ = bundle(tmp_path)
    monkeypatch.setattr(admission, "resolve_control_root", lambda: root)
    with pytest.raises(ApprovalNotReady):
        with admission.locked_admission(anchors):
            pytest.fail("platform fallback")


def test_security_revalidated_after_lock_and_each_use(approved, monkeypatch):
    _, anchors, _ = approved
    checks = []
    valid = True

    def security_check():
        checks.append(True)
        if not valid:
            raise ApprovalNotReady()

    @contextmanager
    def guarded(root, anchors):
        yield security_check

    monkeypatch.setattr(admission, "_protected_root", guarded)
    with admission.locked_admission(anchors) as permit:
        assert len(checks) == 2
        valid = False
        with pytest.raises(ApprovalNotReady):
            permit.revalidate()
    assert len(checks) == 3


def existing_bundle(approved):
    from test_enrollment_authority import rewrite_bundle

    from swu_happyrun.agent.journal import RunJournal

    root, anchors, plan = approved
    journal = root.parent / "journal"
    receipt = root.parent / "mumu-experiment-registration.json"
    with RunJournal(journal) as db:
        with db.device_lock(plan["device_id"]):
            pass
    receipt.write_bytes(b"frozen receipt")
    for name, path in [("journal", journal), ("receipt", receipt)]:
        plan["targets"][name]["identity"] = [path.stat().st_dev, path.stat().st_ino]
        plan["targets"][name]["sha256"] = (
            None
            if name == "journal"
            else __import__("hashlib").sha256(path.read_bytes()).hexdigest()
        )
    anchors = rewrite_bundle(
        root, anchors, plan_changes={"kind": "existing", "targets": plan["targets"]}
    )
    record = {
        "schema": "admission-v1",
        "plan_sha256": anchors.plan_sha256,
        "host_namespace": plan["host_namespace"],
        "stable_instance": plan["stable_instance"],
        "device_id": plan["device_id"],
        "instance_index": plan["instance_index"],
        "journal": str(journal),
        "receipt": str(receipt),
    }
    (root / "admissions" / (anchors.plan_sha256 + ".json")).write_text(json.dumps(record))
    return root, anchors, plan


def test_account_then_device_then_sqlite_order(approved, monkeypatch):
    import sqlite3

    from swu_happyrun.agent.journal import RunJournal, UnsafeReplay

    root, anchors, plan = existing_bundle(approved)
    connect = sqlite3.connect
    calls = []

    def observed_connect(*args, **kwargs):
        with pytest.raises(ApprovalNotReady):
            with admission.locked_admission(anchors):
                pytest.fail("account not held")
        with pytest.raises(UnsafeReplay):
            with RunJournal.lock_existing(root.parent / "journal", plan["device_id"]):
                pytest.fail("device not held")
        calls.append(True)
        return connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", observed_connect)
    with admission.locked_admission(anchors) as session:
        with session.open_existing_journal() as journal:
            journal.record_intent("fixture", 1, "start")
            journal.record_result("fixture", 1, "start", "uncertain")
            assert session.revalidate().execution_allowed is False
    assert calls == [True]


def test_approval_loss_after_device_lock_prevents_connect(approved, monkeypatch):
    import sqlite3

    from swu_happyrun.agent.journal import RunJournal

    root, anchors, _ = existing_bundle(approved)
    original = RunJournal.lock_existing

    @contextmanager
    def acquire_then_revoke(*args):
        with original(*args) as token:
            (root / "authority-v1.json").write_bytes(b"{}")
            yield token

    monkeypatch.setattr(RunJournal, "lock_existing", acquire_then_revoke)
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: pytest.fail("SQLite before approval"))
    with admission.locked_admission(anchors) as session:
        with pytest.raises(ApprovalNotReady):
            with session.open_existing_journal():
                pytest.fail("invalidated approval")


def test_first_use_session_cannot_open_sqlite(approved, monkeypatch):
    import sqlite3

    _, anchors, _ = approved
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: pytest.fail("new SQLite"))
    with admission.locked_admission(anchors) as session:
        with pytest.raises(ApprovalNotReady):
            with session.open_existing_journal():
                pytest.fail("first-use writer not implemented")


@pytest.mark.parametrize("loss", ["expired", "revoked"])
@pytest.mark.parametrize("operation", ["intent", "result", "stop_ack", "reservation"])
def test_approval_loss_after_open_prevents_mutation(approved, monkeypatch, loss, operation):
    from swu_happyrun.agent.journal import RunJournal

    root, anchors, plan = existing_bundle(approved)
    path = root.parent / "journal"
    with admission.locked_admission(anchors) as session:
        with session.open_existing_journal() as journal:
            before = path.read_bytes()
            if loss == "expired":
                monkeypatch.setattr(admission.time, "time", lambda: plan["expires_at"] + 1)
            else:
                (root / "authority-v1.json").write_bytes(b"{}")
            with pytest.raises(ApprovalNotReady):
                if operation == "intent":
                    journal.record_intent("blocked", 1, "start")
                elif operation == "result":
                    journal.record_result("blocked", 1, "start", "done")
                elif operation == "stop_ack":
                    journal.stop_ack_intent("blocked", 1, 1)
                else:
                    journal.reserve_replay(
                        plan["device_id"], "00000000-0000-0000-0000-000000000002", generation=1
                    )
            assert path.read_bytes() == before
            assert journal.read_replay_reservation(plan["device_id"]) is None
    with RunJournal(path, existing_only=True) as independent:
        assert not independent.has_intent("blocked", "start")
