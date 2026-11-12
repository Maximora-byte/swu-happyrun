"""Synthetic local storage checks; no device commands or sensitive fixtures."""

import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from swu_happyrun.drivers.mumu import private_evidence as evidence


@pytest.fixture
def private_root(tmp_path):
    if os.name != "posix":
        pytest.skip("POSIX storage; Windows fails closed until DACL verification exists")
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    return root


def test_private_bytes_are_exclusive_and_durable(private_root, monkeypatch):
    synced = []
    real_fsync = os.fsync

    def fsync(fd):
        synced.append(os.fstat(fd).st_mode)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fsync)
    store = evidence.PrivateEvidenceStore(private_root)
    assert store.root == private_root
    store.put_once("command.stdout.bin", b"\xff\x00synthetic")
    assert (private_root / "command.stdout.bin").read_bytes() == b"\xff\x00synthetic"
    assert (private_root / "command.stdout.bin").stat().st_mode & 0o777 == 0o600
    assert len(synced) == 2
    with pytest.raises(evidence.PrivateEvidenceError, match="^evidence_exists$"):
        store.put_once("command.stdout.bin", b"replacement")


@pytest.mark.parametrize(
    "name",
    ["../outside", "/absolute", "anything.bin", "launch.intent", "CON", "command.json/child"],
)
def test_only_fixed_evidence_names_allowed(private_root, name):
    with pytest.raises(evidence.PrivateEvidenceError, match="^evidence_name_invalid$"):
        evidence.PrivateEvidenceStore(private_root).put_once(name, b"x")
    assert list(private_root.iterdir()) == []


def test_size_bound_before_creating_file(private_root):
    with pytest.raises(evidence.PrivateEvidenceError, match="^evidence_size_invalid$"):
        evidence.PrivateEvidenceStore(private_root).put_once(
            "command.stdout.bin", b"x" * (3 * 1024 * 1024 + 1)
        )
    assert list(private_root.iterdir()) == []


@pytest.mark.parametrize("action", ["launch", "location", "shutdown"])
def test_intent_persists_across_store_restart(private_root, action):
    evidence.PrivateEvidenceStore(private_root).claim_intent(action)
    with pytest.raises(evidence.PrivateEvidenceError, match="^intent_exists$"):
        evidence.PrivateEvidenceStore(private_root).claim_intent(action)


def test_unknown_intent_rejected(private_root):
    with pytest.raises(evidence.PrivateEvidenceError, match="^intent_action_invalid$"):
        evidence.PrivateEvidenceStore(private_root).claim_intent("all")


def test_contenders_only_one_claims(private_root):
    def claim(_):
        try:
            evidence.PrivateEvidenceStore(private_root).claim_intent("location")
            return True
        except evidence.PrivateEvidenceError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(claim, range(16))) == 1


def test_fsync_failure_retains_intent_and_redacts_error(private_root, monkeypatch):
    def fail(fd):
        raise OSError("sensitive path and raw bytes")

    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", fail)
        with pytest.raises(evidence.PrivateEvidenceError) as caught:
            evidence.PrivateEvidenceStore(private_root).claim_intent("shutdown")
        assert caught.value.code == "private_write_failed"
        assert str(caught.value) == "private_write_failed"
        assert caught.value.__suppress_context__
    with pytest.raises(evidence.PrivateEvidenceError, match="^intent_exists$"):
        evidence.PrivateEvidenceStore(private_root).claim_intent("shutdown")


def test_preexisting_empty_intent_is_not_retryable(private_root):
    (private_root / "launch.intent").touch(mode=0o600)
    with pytest.raises(evidence.PrivateEvidenceError, match="^intent_exists$"):
        evidence.PrivateEvidenceStore(private_root).claim_intent("launch")


@pytest.mark.skipif(os.name != "posix", reason="POSIX error classification")
def test_missing_root_not_created(tmp_path):
    with pytest.raises(evidence.PrivateEvidenceError, match="^private_directory_invalid$"):
        evidence.PrivateEvidenceStore(tmp_path / "missing")
    assert not (tmp_path / "missing").exists()


def test_nonprivate_root_not_chmodded(private_root):
    private_root.chmod(0o755)
    with pytest.raises(evidence.PrivateEvidenceError, match="^private_permissions_invalid$"):
        evidence.PrivateEvidenceStore(private_root)
    assert private_root.stat().st_mode & 0o777 == 0o755


def test_symlink_root_and_ancestor_rejected(private_root, tmp_path):
    alias = tmp_path / "alias"
    alias.symlink_to(private_root, target_is_directory=True)
    with pytest.raises(evidence.PrivateEvidenceError):
        evidence.PrivateEvidenceStore(alias)
    child = private_root / "child"
    child.mkdir(mode=0o700)
    with pytest.raises(evidence.PrivateEvidenceError):
        evidence.PrivateEvidenceStore(alias / "child")


def test_world_writable_ancestor_rejected(private_root):
    private_root.parent.chmod(0o777)
    with pytest.raises(evidence.PrivateEvidenceError, match="^private_ancestor_unsafe$"):
        evidence.PrivateEvidenceStore(private_root)


def test_symlink_file_never_followed(private_root, tmp_path):
    outside = tmp_path / "outside"
    outside.write_bytes(b"unchanged")
    (private_root / "command.json").symlink_to(outside)
    with pytest.raises(evidence.PrivateEvidenceError, match="^evidence_exists$"):
        evidence.PrivateEvidenceStore(private_root).put_once("command.json", b"new")
    assert outside.read_bytes() == b"unchanged"


def test_root_replacement_refused(private_root):
    store = evidence.PrivateEvidenceStore(private_root)
    private_root.rename(private_root.with_name("old"))
    private_root.mkdir(mode=0o700)
    with pytest.raises(evidence.PrivateEvidenceError, match="^private_directory_changed$"):
        store.claim_intent("launch")


def test_windows_never_assumes_chmod_is_acl(tmp_path, monkeypatch):
    monkeypatch.setattr(evidence, "_PLATFORM", "nt")

    def fail_native_verification(root):
        raise evidence.windows_private.WindowsPrivacyError("private_acl_unverified")

    monkeypatch.setattr(evidence.windows_private, "verify_directory", fail_native_verification)
    with pytest.raises(evidence.PrivateEvidenceError, match="^private_acl_unverified$"):
        evidence.PrivateEvidenceStore(tmp_path)


def test_symlink_parent_dotdot_not_normalized_away(private_root, tmp_path):
    alias = tmp_path / "alias"
    alias.symlink_to(private_root, target_is_directory=True)
    with pytest.raises(evidence.PrivateEvidenceError, match="^private_directory_invalid$"):
        evidence.PrivateEvidenceStore(alias / ".." / "private")


def test_close_error_never_exposes_os_error(private_root, monkeypatch):
    real_close = os.close

    def fail(fd):
        real_close(fd)
        raise OSError("sensitive filename")

    with monkeypatch.context() as patch:
        patch.setattr(os, "close", fail)
        with pytest.raises(evidence.PrivateEvidenceError) as caught:
            evidence.PrivateEvidenceStore(private_root)
        assert "sensitive" not in str(caught.value)


def test_partial_write_failure_keeps_intent(private_root, monkeypatch):
    store = evidence.PrivateEvidenceStore(private_root)
    real_write = os.write
    calls = 0

    def write(fd, data):
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_write(fd, data[:1])
        raise OSError("synthetic interruption")

    with monkeypatch.context() as patch:
        patch.setattr(os, "write", write)
        with pytest.raises(evidence.PrivateEvidenceError, match="^private_write_failed$"):
            store.claim_intent("location")
    assert (private_root / "location.intent").read_bytes() == b"a"
    with pytest.raises(evidence.PrivateEvidenceError, match="^intent_exists$"):
        evidence.PrivateEvidenceStore(private_root).claim_intent("location")


def test_directory_fsync_failure_not_success(private_root, monkeypatch):
    real_fsync = os.fsync
    calls = 0

    def fsync(fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic parent sync failure")
        real_fsync(fd)

    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", fsync)
        with pytest.raises(evidence.PrivateEvidenceError, match="^private_write_failed$"):
            evidence.PrivateEvidenceStore(private_root).claim_intent("shutdown")
    with pytest.raises(evidence.PrivateEvidenceError, match="^intent_exists$"):
        evidence.PrivateEvidenceStore(private_root).claim_intent("shutdown")


def test_directory_permissions_rechecked_for_each_write(private_root):
    store = evidence.PrivateEvidenceStore(private_root)
    private_root.chmod(0o755)
    with pytest.raises(evidence.PrivateEvidenceError, match="^private_permissions_invalid$"):
        store.claim_intent("launch")
