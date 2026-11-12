"""Synthetic original-machine receipts, never actual user/device identities."""

import hashlib
import json
from pathlib import Path
from uuid import UUID

import pytest

from swu_happyrun.agent.journal import RunJournal
from swu_happyrun.drivers.identity import device_id


def test_existing_journal_never_bootstraps_missing_path(tmp_path):
    path = tmp_path / "absent" / "journal.sqlite"
    with pytest.raises((OSError, RuntimeError)):
        RunJournal(path, existing_only=True, read_only=True)
    assert not path.parent.exists()


def test_readonly_existing_journal_does_not_create_lock(tmp_path):
    path = tmp_path / "journal.sqlite"
    with RunJournal(path):
        pass
    original = path.read_bytes()
    with RunJournal(path, existing_only=True, read_only=True) as journal:
        with pytest.raises((OSError, RuntimeError)):
            with journal.device_lock("synthetic"):
                pytest.fail("missing original lock accepted")
    assert path.read_bytes() == original
    assert sorted(p.name for p in tmp_path.iterdir()) == ["journal.sqlite"]


def test_existing_lock_reuses_normal_contention_and_marker_checks(tmp_path):
    path = tmp_path / "journal.sqlite"
    with RunJournal(path) as ordinary:
        with ordinary.device_lock("synthetic"):
            with RunJournal(path, existing_only=True, read_only=True) as check:
                with pytest.raises(RuntimeError):
                    with check.device_lock("synthetic"):
                        pytest.fail("parallel lock accepted")
        with RunJournal(path, existing_only=True, read_only=True) as check:
            with check.device_lock("synthetic"):
                assert check.read_replay_reservation("synthetic") is None


def subject():
    from swu_happyrun.drivers.mumu import original_registration

    return original_registration


def identity(path):
    value = path.stat()
    return [value.st_dev, value.st_ino]


@pytest.fixture
def receipt(tmp_path, monkeypatch):
    host = tmp_path / "host-id"
    host.write_text("00000000-0000-4000-8000-000000000001\n", encoding="ascii")
    monkeypatch.setenv("SWU_HAPPYRUN_HOST_ID_FILE", str(host))
    manager = tmp_path / "MuMuManager.exe"
    manager.write_bytes(b"synthetic only")
    journal = tmp_path / "original.sqlite"
    import os

    derived = device_id(
        "mumu", f"{os.path.normcase(str(manager.resolve()))}:0", host_id=host.read_text().strip()
    )
    with RunJournal(journal) as j:
        with j.device_lock(derived):
            pass
    lock = tmp_path / ("device-" + hashlib.sha256(derived.encode()).hexdigest() + ".lock")
    private = tmp_path / "private"
    private.mkdir()
    value = dict(
        schema=1,
        stable_instance=str(UUID(int=2)),
        instance_index="0",
        host_id=host.read_text().strip(),
        device_id=derived,
        host_file=dict(path=str(host), identity=identity(host)),
        manager_file=dict(path=str(manager), identity=identity(manager)),
        journal_file=dict(path=str(journal), identity=identity(journal)),
        journal_directory_identity=identity(tmp_path),
        lock_identity=identity(lock),
        evidence_root=str(private),
    )
    registry = tmp_path / "mumu-experiment-registration.json"
    registry.write_text(json.dumps(value))
    return registry, value, lock


def load(receipt):
    path, _, _ = receipt
    return subject().load_original_registration(
        receipt_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        receipt_identity=tuple(identity(path)),
    )


def test_loader_is_readonly_uses_actual_mumu_derivation(receipt):
    registry, value, _ = receipt
    before = {p: p.read_bytes() for p in registry.parent.iterdir() if p.is_file()}
    registered = load(receipt)
    assert registered.device_id == value["device_id"]
    assert registered.stable_instance == value["stable_instance"]
    assert registered.journal == Path(value["journal_file"]["path"])
    with subject().locked_original(registered) as journal:
        assert journal.read_replay_reservation(registered.device_id) is None
    assert all(p.read_bytes() == data for p, data in before.items())
    assert not any(secret in repr(registered) for secret in [str(registry), value["host_id"]])


@pytest.mark.parametrize(
    "change",
    [
        "duplicate",
        "unknown",
        "device",
        "host",
        "index",
        "relative",
        "identity",
        "journal_relocation",
        "oversize",
        "corrupt",
    ],
)
def test_rejects_bad_receipt(receipt, change):
    path, value, _ = receipt
    if change == "duplicate":
        path.write_text(path.read_text()[:-1] + ',"schema":1}')
    elif change == "corrupt":
        path.write_text("not json")
    elif change == "oversize":
        path.write_bytes(b" " * 8193)
    else:
        if change == "unknown":
            value["bootstrap"] = True
        if change == "device":
            value["device_id"] = str(UUID(int=3))
        if change == "host":
            value["host_id"] = str(UUID(int=3))
        if change == "index":
            value["instance_index"] = "00"
        if change == "relative":
            value["journal_file"]["path"] = "original.sqlite"
        if change == "identity":
            value["journal_file"]["identity"][1] += 1
        if change == "journal_relocation":
            old = Path(value["journal_file"]["path"])
            new = old.with_name("replacement.sqlite")
            new.write_bytes(old.read_bytes())
            value["journal_file"]["path"] = str(new)
        path.write_text(json.dumps(value))
    with pytest.raises(subject().RegistrationNotReady):
        load(receipt)


def test_missing_registration_and_host_are_not_created(receipt):
    path, value, _ = receipt
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    file_id = tuple(identity(path))
    path.unlink()
    host = Path(value["host_file"]["path"])
    host.unlink()
    with pytest.raises(subject().RegistrationNotReady):
        subject().load_original_registration(receipt_sha256=expected, receipt_identity=file_id)
    assert not path.exists() and not host.exists()


@pytest.mark.parametrize("which", ["receipt", "host", "journal", "lock", "manager"])
def test_substitution_after_load_is_rejected(receipt, which):
    registered = load(receipt)
    path, value, lock = receipt
    target = dict(
        receipt=path,
        host=Path(value["host_file"]["path"]),
        journal=registered.journal,
        lock=lock,
        manager=Path(value["manager_file"]["path"]),
    )[which]
    moved = target.with_suffix(".replacement")
    moved.write_bytes(target.read_bytes())
    moved.replace(target)
    with pytest.raises(subject().RegistrationNotReady):
        with subject().locked_original(registered):
            pytest.fail("changed original accepted")


def test_marker_and_lock_contention_fail_closed(receipt):
    registration = load(receipt)
    with RunJournal(registration.journal) as ordinary:
        with ordinary.device_lock(registration.device_id):
            with pytest.raises(subject().RegistrationNotReady):
                with subject().locked_original(registration):
                    pytest.fail("contention accepted")
            ordinary.reserve_replay(registration.device_id, str(UUID(int=4)), generation=1)
        with pytest.raises(subject().RegistrationNotReady):
            with subject().locked_original(registration):
                pytest.fail("reservation accepted")


def test_changed_registry_rechecked_under_original_lock(receipt, monkeypatch):
    registration = load(receipt)
    real = RunJournal.device_lock
    from contextlib import contextmanager

    @contextmanager
    def changed(self, device):
        with real(self, device):
            receipt[0].write_text("{}")
            yield

    monkeypatch.setattr(RunJournal, "device_lock", changed)
    with pytest.raises(subject().RegistrationNotReady):
        with subject().locked_original(registration):
            pytest.fail("under-lock change accepted")


def test_symlink_receipt_is_never_followed(receipt):
    path, _, _ = receipt
    other = path.with_name("other.json")
    other.write_bytes(path.read_bytes())
    path.unlink()
    try:
        path.symlink_to(other)
    except OSError:
        pytest.skip("OS does not permit synthetic symlink creation")
    with pytest.raises(subject().RegistrationNotReady):
        load(receipt)


def test_reparse_attribute_is_rejected(receipt, monkeypatch):
    original = Path.lstat

    class Reparse:
        st_mode = 0o100600
        st_file_attributes = 0x400

    def reparse(path):
        return Reparse() if path == receipt[0] else original(path)

    monkeypatch.setattr(Path, "lstat", reparse)
    with pytest.raises(subject().RegistrationNotReady):
        load(receipt)


def test_denied_original_file_is_unknown(receipt, monkeypatch):
    import os

    real = os.open

    def denied(path, *args, **kwargs):
        if path == receipt[0]:
            raise PermissionError("PRIVATE PATH")
        return real(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", denied)
    with pytest.raises(subject().RegistrationNotReady, match="^original_registration_not_ready$"):
        load(receipt)


def test_lifecycle_rechecks_receipt_immediately_before_launch(receipt):
    import sys

    from mumu_experiment_harness import run_synthetic_experiment
    from test_evidence_experiment import Adapter
    from test_experiment_shutdown import Clock

    from swu_happyrun.drivers.mumu.private_evidence import PrivateEvidenceStore

    path, value, _ = receipt
    root = Path(value["evidence_root"])
    if sys.platform == "win32":
        from swu_happyrun.drivers.mumu.windows_private import provision_private_directory

        root.rmdir()
        provision_private_directory(root)
    else:
        root.chmod(0o700)
    registration = load(receipt)

    class Changed(Adapter):
        def check_stopped_registration(self, registration):
            path.write_text("{}")
            return True

    adapter = Changed(registration)
    result = run_synthetic_experiment(
        registration, adapter=adapter, store=PrivateEvidenceStore(root), clock=Clock()
    )
    assert "launch" not in adapter.calls
    assert result["shutdown_status"] == "shutdown_not_attempted"


def test_existing_lock_swap_before_open_rejected(tmp_path, monkeypatch):
    path = tmp_path / "original.sqlite"
    with RunJournal(path) as journal:
        with journal.device_lock("synthetic"):
            pass
    lock = next(tmp_path.glob("*.lock"))
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"0")
    real_open = Path.open

    def swapped(self, *args, **kwargs):
        if self == lock:
            replacement.replace(lock)
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", swapped)
    with RunJournal(path, existing_only=True, read_only=True) as journal:
        with pytest.raises(RuntimeError):
            with journal.device_lock("synthetic"):
                pytest.fail("substituted lock accepted")


def test_readonly_wal_inspection_never_creates_shared_memory(tmp_path):
    import shutil
    import sqlite3

    original = tmp_path / "writer.sqlite"
    with RunJournal(original):
        pass
    writer = sqlite3.connect(original)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("INSERT INTO intents VALUES (?, ?, ?, ?)", ("synthetic", "start", 1, None))
        writer.commit()
        inspection = tmp_path / "inspection"
        inspection.mkdir()
        target = inspection / "original.sqlite"
        shutil.copyfile(original, target)
        shutil.copyfile(str(original) + "-wal", str(target) + "-wal")
        before = {p.name: p.read_bytes() for p in inspection.iterdir()}
        with pytest.raises(RuntimeError):
            with RunJournal(target, existing_only=True, read_only=True):
                pytest.fail("WAL inspection accepted")
        assert {p.name: p.read_bytes() for p in inspection.iterdir()} == before
    finally:
        writer.close()


def test_readonly_is_lock_inspection_not_database_query(tmp_path):
    path = tmp_path / "original.sqlite"
    with RunJournal(path):
        pass
    with RunJournal(path, existing_only=True, read_only=True) as journal:
        with pytest.raises(RuntimeError):
            journal.has_intent("synthetic", "start")
