from uuid import uuid4

import pytest

from swu_happyrun.agent.journal import RunJournal, UnsafeReplay


def test_start_intent_survives_reopen_and_blocks_new_fence(tmp_path):
    path = tmp_path / "runs.sqlite"
    job = str(uuid4())
    with RunJournal(path) as journal:
        journal.record_intent(job, 1, "start")
    with RunJournal(path) as journal:
        assert journal.has_intent(job, "start")
        with pytest.raises(UnsafeReplay):
            journal.record_intent(job, 2, "start")


def test_upload_intent_is_at_most_once_even_after_result(tmp_path):
    with RunJournal(tmp_path / "runs.sqlite") as journal:
        journal.record_intent("job", 1, "upload")
        journal.record_result("job", 1, "upload", "uncertain")
        with pytest.raises(UnsafeReplay):
            journal.record_intent("job", 1, "upload")


def test_journal_rejects_arbitrary_text_and_tokens(tmp_path):
    with RunJournal(tmp_path / "runs.sqlite") as journal:
        with pytest.raises(ValueError):
            journal.record_intent("job", 1, "Bearer secret")
        with pytest.raises(ValueError):
            journal.record_result("job", 1, "start", "secret token")


def test_device_lock_excludes_second_journal(tmp_path):
    with RunJournal(tmp_path / "runs.sqlite") as first:
        with RunJournal(tmp_path / "runs.sqlite") as second:
            with first.device_lock("device"):
                with pytest.raises(UnsafeReplay):
                    with second.device_lock("device"):
                        pass
            with second.device_lock("device"):
                pass


def test_stop_ack_identity_survives_reopen(tmp_path):
    path = tmp_path / "runs.sqlite"
    with RunJournal(path) as journal:
        first = journal.stop_ack_intent("job", 3, 7)
    with RunJournal(path) as journal:
        assert journal.stop_ack_intent("job", 3, 7) == first
        assert journal.stop_ack_intent("job", 4, 9) != first


def test_lock_initialization_never_reads_a_mandatory_locked_byte(tmp_path, monkeypatch):
    from pathlib import Path

    original = Path.open

    class MandatoryReadGuard:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.handle.close()

        def __getattr__(self, name):
            return getattr(self.handle, name)

        def read(self, *args):
            raise PermissionError("Windows denies reads of a locked byte")

    def guarded_open(path, *args, **kwargs):
        handle = original(path, *args, **kwargs)
        return MandatoryReadGuard(handle) if path.suffix == ".lock" else handle

    monkeypatch.setattr(Path, "open", guarded_open)
    with RunJournal(tmp_path / "runs.sqlite") as first:
        with RunJournal(tmp_path / "runs.sqlite") as second:
            with first.device_lock("device"):
                with pytest.raises(UnsafeReplay):
                    with second.device_lock("device"):
                        pass
