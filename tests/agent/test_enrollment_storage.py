"""Synthetic file transactions only; not Windows ACL/rename acceptance evidence."""

import dataclasses
import hashlib
import importlib
import importlib.util
import os
from contextlib import contextmanager
from pathlib import Path

import pytest

from swu_happyrun.drivers.mumu.enrollment_authority import ApprovalNotReady
from swu_happyrun.drivers.mumu.instance_attribution import FileIdentity

MODULE = "swu_happyrun.drivers.mumu.enrollment_storage"
TX = "a" * 64
SID = "S-1-5-21-1-2-3-1001"
PAYLOAD = b"synthetic private enrollment\n"


def module():
    assert importlib.util.find_spec(MODULE) is not None, "exclusive storage is not implemented"
    return importlib.import_module(MODULE)


def test_exclusive_private_storage_api_exists():
    storage = module()
    assert callable(storage.private_storage)


class SyntheticIO:
    """Native-boundary stand-in confined to private temporary test directories."""

    def __init__(self, api, sid):
        self.events = api.events
        self.fault = api.fault
        self.after = api.after
        self.root = api.root
        assert sid == SID

    def operation(self, name, function):
        self.events.append((name, "before"))
        if self.fault == (name, "before"):
            raise OSError("synthetic private path should not escape")
        result = function()
        self.events.append((name, "after"))
        if self.after:
            self.after(name, result)
        if self.fault == (name, "after"):
            # Native create owns/closes its handle if post-create validation fails.
            if name in {"create", "open_read"}:
                os.close(result)
            raise OSError("synthetic private path should not escape")
        return result

    def create(self, path):
        assert path.parent == self.root
        return self.operation(
            "create", lambda: os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        )

    def write(self, fd, data):
        return self.operation("write", lambda: os.write(fd, data))

    def fsync(self, fd):
        return self.operation("fsync", lambda: os.fsync(fd))

    def flush(self, fd):
        return self.operation("flush", lambda: os.fsync(fd))

    def close(self, fd):
        return self.operation("close", lambda: os.close(fd))

    def open_read(self, path):
        return self.operation("open_read", lambda: os.open(path, os.O_RDONLY))

    def check_fd(self, fd):
        info = os.fstat(fd)
        assert info.st_nlink == 1

    def check_path(self, fd, path):
        # This synthetic backend alone can compare path stat; production must use
        # GetFinalPathNameByHandleW because its exclusive native fd cannot reopen.
        assert FileIdentity.from_stat(os.fstat(fd)) == FileIdentity.from_stat(path.stat())

    def move(self, source, destination):
        def rename():
            assert source.parent == destination.parent == self.root
            # Exclusive link publication models only the no-overwrite outcome on
            # Linux; it does not claim Windows atomic-move or durability evidence.
            os.link(source, destination)
            source.unlink()

        return self.operation("move", rename)


@pytest.fixture
def synthetic(tmp_path, monkeypatch):
    storage = module()

    class API:
        events = []
        fault = None
        after = None
        root = tmp_path

        def current_sid(self):
            return SID

        def security(self, path):
            return f"O:{SID}D:P(A;;FA;;;{SID})"

    api = API()
    held = []

    @contextmanager
    def guard(path, identity):
        assert path == tmp_path
        assert identity == (tmp_path.stat().st_dev, tmp_path.stat().st_ino)
        held.append(True)
        try:
            yield api, SID, identity
        finally:
            held.pop()

    monkeypatch.setattr(storage, "_require_local_ntfs", lambda _: None)
    monkeypatch.setattr(storage.windows_private, "verified_directory", guard)
    monkeypatch.setattr(storage, "_NativeIO", SyntheticIO)

    def current():
        assert held, "mutations must hold the verified parent guard"
        api.events.append(("authority", "check"))

    def context(callback=current):
        return storage.private_storage(
            tmp_path,
            parent_identity=FileIdentity.from_stat(tmp_path.stat()),
            validate_current=callback,
        )

    return storage, tmp_path, api, context


def test_staging_and_publication_preserve_exact_identity_and_hash(synthetic):
    storage, root, api, context = synthetic
    with context() as session:
        staged = session.stage("ready.json", PAYLOAD, transaction_id=TX)
        assert staged.path == root / (".ready.json." + TX + ".staged")
        assert staged.path.read_bytes() == PAYLOAD
        assert not staged.destination.exists()
        result = session.publish(staged)
        assert result.identity == staged.identity
        assert result.sha256 == staged.sha256 == hashlib.sha256(PAYLOAD).hexdigest()
        assert (root / "ready.json").read_bytes() == PAYLOAD
        assert not staged.path.exists()
    assert [event for event in api.events if event == ("create", "before")] == [
        ("create", "before")
    ]
    for operation in ("create", "write", "fsync", "flush", "move"):
        index = api.events.index((operation, "before"))
        assert api.events[index - 1] == ("authority", "check")
    with pytest.raises(storage.StorageIncomplete):
        session.stage("other.json", PAYLOAD, transaction_id=TX)


@pytest.mark.parametrize("operation", ["create", "write", "fsync", "flush", "move"])
@pytest.mark.parametrize("when", ["before", "after"])
def test_each_mutation_failure_leaves_artifacts_and_never_retries(synthetic, operation, when):
    storage, root, api, context = synthetic
    api.fault = (operation, when)
    with context() as session:
        with pytest.raises(storage.StorageIncomplete) as error:
            staged = session.stage("ready.json", PAYLOAD, transaction_id=TX)
            session.publish(staged)
        assert str(error.value) == "enrollment_storage_incomplete"
        assert error.value.phase == operation
        assert error.value.uncertain is True
        snapshot = {path.name: path.read_bytes() for path in root.iterdir()}
        before = list(api.events)
        with pytest.raises(storage.StorageIncomplete):
            session.stage("ready.json", PAYLOAD, transaction_id=TX)
        assert api.events == before
        assert {path.name: path.read_bytes() for path in root.iterdir()} == snapshot
    assert len([e for e in api.events if e == (operation, "before")]) == 1
    if operation == "create" and when == "before":
        assert snapshot == {}
    elif operation == "move" and when == "after":
        assert snapshot == {"ready.json": PAYLOAD}
    else:
        assert list(snapshot) == [".ready.json." + TX + ".staged"]


def test_destination_exists_before_stage_is_preserved_without_create(synthetic):
    storage, root, api, context = synthetic
    destination = root / "ready.json"
    destination.write_bytes(b"existing private bytes")
    with context() as session, pytest.raises(storage.StorageIncomplete):
        session.stage(destination.name, PAYLOAD, transaction_id=TX)
    assert destination.read_bytes() == b"existing private bytes"
    assert not any(event[0] == "create" for event in api.events)


def test_destination_appearing_at_native_move_is_never_replaced(synthetic):
    storage, root, api, context = synthetic
    with context() as session:
        staged = session.stage("ready.json", PAYLOAD, transaction_id=TX)
        original_move = session._io.move

        def racing_move(source, destination):
            destination.write_bytes(b"concurrent claimant")
            return original_move(source, destination)

        session._io.move = racing_move
        with pytest.raises(storage.StorageIncomplete) as error:
            session.publish(staged)
        assert error.value.uncertain
        assert staged.path.read_bytes() == PAYLOAD
        assert (root / "ready.json").read_bytes() == b"concurrent claimant"


def test_existing_stage_marker_is_never_adopted_or_truncated(synthetic):
    storage, root, api, context = synthetic
    path = root / (".ready.json." + TX + ".staged")
    path.write_bytes(b"abandoned attempt")
    with context() as session, pytest.raises(storage.StorageIncomplete):
        session.stage("ready.json", PAYLOAD, transaction_id=TX)
    assert path.read_bytes() == b"abandoned attempt"
    assert len([e for e in api.events if e == ("create", "before")]) == 1


@pytest.mark.parametrize("replacement", ["content", "identity"])
def test_changed_source_is_rejected_before_publication(synthetic, replacement):
    storage, _, api, context = synthetic
    with context() as session:
        staged = session.stage("ready.json", PAYLOAD, transaction_id=TX)
        if replacement == "content":
            staged.path.write_bytes(b"different data")
        else:
            previous = staged.path.with_suffix(".saved")
            staged.path.rename(previous)
            staged.path.write_bytes(PAYLOAD)
        with pytest.raises(storage.StorageIncomplete):
            session.publish(staged)
        assert not staged.destination.exists()
        assert not any(e[0] == "move" for e in api.events)


def test_same_content_destination_replacement_after_move_is_uncertain(synthetic):
    storage, root, api, context = synthetic
    with context() as session:
        staged = session.stage("ready.json", PAYLOAD, transaction_id=TX)

        def replace_after_move(operation, _):
            if operation == "move":
                destination = root / "ready.json"
                destination.rename(root / "moved-original.json")
                destination.write_bytes(PAYLOAD)

        session._io.after = replace_after_move
        with pytest.raises(storage.StorageIncomplete) as error:
            session.publish(staged)
        assert error.value.uncertain
        assert (root / "ready.json").read_bytes() == PAYLOAD
        with pytest.raises(storage.StorageIncomplete):
            session.publish(staged)
    assert len([e for e in api.events if e == ("move", "before")]) == 1


def test_stage_objects_cannot_be_forged_reused_or_cross_session(synthetic):
    storage, _, _, context = synthetic
    with context() as first:
        staged = first.stage("ready.json", PAYLOAD, transaction_id=TX)
        forged = dataclasses.replace(staged)
        with pytest.raises(storage.StorageIncomplete):
            first.publish(forged)
    with context() as second, pytest.raises(storage.StorageIncomplete):
        second.publish(staged)
    assert staged.path.read_bytes() == PAYLOAD
    assert not staged.destination.exists()


def test_successful_stage_cannot_be_published_twice(synthetic):
    storage, _, api, context = synthetic
    with context() as session:
        staged = session.stage("ready.json", PAYLOAD, transaction_id=TX)
        session.publish(staged)
        before = list(api.events)
        with pytest.raises(storage.StorageIncomplete):
            session.publish(staged)
        assert api.events == before


@pytest.mark.parametrize("deny_at", range(2, 8))
def test_authority_loss_prevents_the_next_mutation(synthetic, deny_at):
    storage, root, api, context = synthetic
    count = 0

    def revalidate():
        nonlocal count
        count += 1
        api.events.append(("authority", "check"))
        if count == deny_at:
            raise ApprovalNotReady()

    with context(revalidate) as session, pytest.raises(storage.StorageIncomplete):
        staged = session.stage("ready.json", PAYLOAD, transaction_id=TX)
        session.publish(staged)
    assert count == deny_at
    assert not (root / "ready.json").exists()


@pytest.mark.parametrize("name", ["../x", "x/y", "x\\y", "x:stream", "CON", "NUL.json", "x."])
def test_invalid_names_never_mutate(synthetic, name):
    storage, root, api, context = synthetic
    with context() as session, pytest.raises(storage.StorageIncomplete):
        session.stage(name, PAYLOAD, transaction_id=TX)
    assert not list(root.iterdir())
    assert not any(e[0] == "create" for e in api.events)


def test_oversized_payload_never_creates_and_chunk_writes_are_bounded(synthetic):
    storage, root, api, context = synthetic
    with context() as session, pytest.raises(storage.StorageIncomplete):
        session.stage("ready.json", b"x" * (storage.MAX_STORAGE_BYTES + 1), transaction_id=TX)
    assert not list(root.iterdir())
    with context() as session:
        lengths = []
        write = session._io.write

        def bounded(fd, data):
            lengths.append(len(data))
            return write(fd, data)

        session._io.write = bounded
        session.stage("ready.json", b"x" * (storage.WRITE_CHUNK_BYTES + 1), transaction_id=TX)
    assert lengths == [storage.WRITE_CHUNK_BYTES, 1]


def test_no_directory_creation_and_unsupported_platform_fails_closed(tmp_path):
    storage = module()
    if os.name == "nt":
        pytest.skip("the synthetic suite does not provision native private directories")
    missing = tmp_path / "not-created"
    with pytest.raises(storage.StorageIncomplete):
        with storage.private_storage(
            missing,
            parent_identity=FileIdentity.from_stat(tmp_path.stat()),
            validate_current=lambda: None,
        ):
            pytest.fail("unsupported platform")
    assert not missing.exists()


def test_issued_stage_cannot_be_retargeted_by_mutating_dataclass(synthetic):
    storage, root, api, context = synthetic
    with context() as session:
        staged = session.stage("ready.json", PAYLOAD, transaction_id=TX)
        foreign = root / "foreign.json"
        foreign.write_bytes(PAYLOAD)
        object.__setattr__(staged, "path", foreign)
        object.__setattr__(staged, "identity", FileIdentity.from_stat(foreign.stat()))
        with pytest.raises(storage.StorageIncomplete):
            session.publish(staged)
        assert foreign.read_bytes() == PAYLOAD
        assert not staged.destination.exists()
        assert not any(e[0] == "move" for e in api.events)


def test_zero_write_does_not_flush_or_publish(synthetic):
    storage, _, api, context = synthetic
    with context() as session:
        session._io.write = lambda *_: 0
        with pytest.raises(storage.StorageIncomplete) as error:
            session.stage("ready.json", PAYLOAD, transaction_id=TX)
        assert error.value.phase == "write"
        assert not any(e[0] in {"flush", "fsync", "move"} for e in api.events)


def test_partial_write_revalidates_before_writing_remaining_bytes(synthetic):
    storage, _, api, context = synthetic
    with context() as session:
        original = session._io.write
        session._io.write = lambda fd, data: original(fd, data[:3])
        staged = session.stage("ready.json", PAYLOAD, transaction_id=TX)
        session.publish(staged)
    assert staged.destination.read_bytes() == PAYLOAD
    for index, event in enumerate(api.events):
        if event == ("write", "before"):
            assert api.events[index - 1] == ("authority", "check")


def test_source_hardlink_is_rejected_before_publication(synthetic):
    storage, root, _, context = synthetic
    with context() as session:
        staged = session.stage("ready.json", PAYLOAD, transaction_id=TX)
        os.link(staged.path, root / "alias.json")
        with pytest.raises(storage.StorageIncomplete):
            session.publish(staged)
        assert staged.path.read_bytes() == PAYLOAD
        assert not staged.destination.exists()


def test_private_parent_acl_is_revalidated_before_create(synthetic):
    storage, root, api, context = synthetic
    with context() as session:
        api.security = lambda _: f"O:{SID}D:P(A;;FA;;;WD)"
        with pytest.raises(storage.StorageIncomplete):
            session.stage("ready.json", PAYLOAD, transaction_id=TX)
    assert not list(root.iterdir())


def test_token_change_is_rejected_before_create(synthetic):
    storage, root, api, context = synthetic
    with context() as session:
        api.current_sid = lambda: "S-1-5-21-1-2-3-1002"
        with pytest.raises(storage.StorageIncomplete):
            session.stage("ready.json", PAYLOAD, transaction_id=TX)
    assert not list(root.iterdir())


def test_parent_identity_change_is_rejected_before_create(synthetic, monkeypatch):
    storage, root, api, context = synthetic
    with context() as session:
        original = storage._chain

        def changed(path):
            result = original(path)
            if path == root:
                fake = FileIdentity(
                    "python_stat", result[-1][1].volume, result[-1][1].file_index + 1
                )
                return (*result[:-1], (path, fake))
            return result

        monkeypatch.setattr(storage, "_chain", changed)
        with pytest.raises(storage.StorageIncomplete):
            session.stage("ready.json", PAYLOAD, transaction_id=TX)
    assert not list(root.iterdir())
    assert not any(e[0] == "create" for e in api.events)


def test_native_boundary_reuses_exclusive_private_create_and_no_replace_move():
    storage = module()
    calls = []

    class Kernel:
        def MoveFileExW(self, source, destination, flags):
            calls.append(("move", source, destination, flags))
            return True

    class API:
        kernel = Kernel()
        _require = staticmethod(storage.windows_private._WinAPI._require)

        def create_private_file(self, path, sid):
            calls.append(("create", path, sid))
            return 91

    native = object.__new__(storage._NativeIO)
    native.api, native.sid = API(), SID
    assert native.create(Path("stage")) == 91
    native.move(Path("stage"), Path("final"))
    assert calls == [("create", Path("stage"), SID), ("move", "stage", "final", 8)]


def test_native_flush_false_is_not_success(monkeypatch):
    import sys
    from types import SimpleNamespace

    storage = module()
    handles = []

    def flush(handle):
        handles.append(handle)
        return False

    native = object.__new__(storage._NativeIO)
    native.api = SimpleNamespace(
        kernel=SimpleNamespace(FlushFileBuffers=flush),
        _require=storage.windows_private._WinAPI._require,
    )
    monkeypatch.setitem(sys.modules, "msvcrt", SimpleNamespace(get_osfhandle=lambda fd: 77))
    with pytest.raises(storage.windows_private.WindowsPrivacyError):
        native.flush(4)
    assert handles == [77]


def test_native_move_false_is_not_success():
    from types import SimpleNamespace

    storage = module()
    native = object.__new__(storage._NativeIO)
    native.api = SimpleNamespace(
        kernel=SimpleNamespace(MoveFileExW=lambda *_: False),
        _require=storage.windows_private._WinAPI._require,
    )
    with pytest.raises(storage.windows_private.WindowsPrivacyError):
        native.move(Path("stage"), Path("destination"))


def test_readback_checks_private_handle_again_after_read(synthetic):
    storage, _, _, context = synthetic
    with context() as session:
        original = session._io.check_fd
        read_fd = None
        read_checks = 0
        open_read = session._io.open_read

        def opening(path):
            nonlocal read_fd
            read_fd = open_read(path)
            return read_fd

        def check(fd):
            nonlocal read_checks
            if fd == read_fd:
                read_checks += 1
                if read_checks == 2:
                    raise storage.windows_private.WindowsPrivacyError("private_acl_unverified")
            original(fd)

        session._io.open_read = opening
        session._io.check_fd = check
        with pytest.raises(storage.StorageIncomplete):
            session.stage("ready.json", PAYLOAD, transaction_id=TX)
        assert read_checks == 2


def test_base_exception_poisons_session_without_retry(synthetic):
    storage, root, api, context = synthetic

    class Interrupted(BaseException):
        pass

    with context() as session:
        original = session._io.write

        def interrupted(fd, data):
            original(fd, data)
            raise Interrupted()

        session._io.write = interrupted
        with pytest.raises(Interrupted):
            session.stage("ready.json", PAYLOAD, transaction_id=TX)
        snapshot = {path.name: path.read_bytes() for path in root.iterdir()}
        before = list(api.events)
        with pytest.raises(storage.StorageIncomplete):
            session.stage("different.json", PAYLOAD, transaction_id=TX)
        assert api.events == before
        assert {path.name: path.read_bytes() for path in root.iterdir()} == snapshot


def test_source_replacement_during_last_authority_check_is_rejected(synthetic):
    storage, root, api, context = synthetic
    sessions = []
    replaced = False

    def current():
        nonlocal replaced
        if sessions and sessions[0]._phase == "move" and not replaced:
            path = root / (".ready.json." + TX + ".staged")
            path.rename(root / "original-staged")
            path.write_bytes(PAYLOAD)
            replaced = True

    with context(current) as session:
        sessions.append(session)
        staged = session.stage("ready.json", PAYLOAD, transaction_id=TX)
        with pytest.raises(storage.StorageIncomplete):
            session.publish(staged)
        assert replaced
        assert not staged.destination.exists()
        assert not any(e[0] == "move" for e in api.events)


def test_final_destination_readback_is_after_last_authority_callback(synthetic):
    storage, root, _, context = synthetic
    replaced = False

    def current():
        nonlocal replaced
        destination = root / "ready.json"
        if destination.exists() and not replaced:
            destination.rename(root / "original-published")
            destination.write_bytes(PAYLOAD)
            replaced = True

    with context(current) as session:
        staged = session.stage("ready.json", PAYLOAD, transaction_id=TX)
        with pytest.raises(storage.StorageIncomplete) as error:
            session.publish(staged)
        assert replaced
        assert error.value.uncertain
        assert staged.destination.exists()


def test_live_staging_observations_are_fd_based_during_pre_return_callbacks(synthetic):
    storage, root, _, context = synthetic
    sessions = []
    observed = []

    def current():
        if sessions:
            observed.extend(sessions[0].live_staging_observations)

    with context(current) as session:
        sessions.append(session)
        assert session.live_staging_observations == ()
        staged = session.stage("ready.json", PAYLOAD, transaction_id=TX)
        assert session.live_staging_observations == ()
        assert observed
        assert {item.size for item in observed} == {0, len(PAYLOAD)}
        for item in observed:
            assert item.path == staged.path
            assert item.identity == staged.identity
            assert item.parent_identity == FileIdentity.from_stat(root.stat())
            assert item.file_type == "regular"
            assert not hasattr(item, "sha256")
            assert not hasattr(item, "payload")
        session.publish(staged)
        assert session.live_staging_observations == ()
    with pytest.raises(storage.StorageIncomplete):
        _ = session.live_staging_observations


def test_live_staging_never_path_stats_exclusively_open_stage(synthetic, monkeypatch):
    storage, _, _, context = synthetic
    original_chain = storage._chain
    sessions = []

    def chain(path):
        if sessions and sessions[0]._live_stage is not None:
            assert path != sessions[0]._live_stage[1], "share=0 cannot rely on reopening stage"
        return original_chain(path)

    monkeypatch.setattr(storage, "_chain", chain)

    def current():
        if sessions:
            _ = sessions[0].live_staging_observations

    with context(current) as session:
        sessions.append(session)
        staged = session.stage("ready.json", PAYLOAD, transaction_id=TX)
        session.publish(staged)
    assert staged.destination.read_bytes() == PAYLOAD


def test_replaced_live_stage_is_not_a_phase_scope_exemption(synthetic):
    storage, root, api, context = synthetic
    sessions = []
    replaced = False

    def current():
        nonlocal replaced
        if sessions and sessions[0]._phase == "write" and not replaced:
            path = root / (".ready.json." + TX + ".staged")
            path.rename(root / "original-stage")
            path.write_bytes(b"foreign")
            replaced = True
            _ = sessions[0].live_staging_observations

    with context(current) as session:
        sessions.append(session)
        with pytest.raises(storage.StorageIncomplete):
            session.stage("ready.json", PAYLOAD, transaction_id=TX)
        assert replaced
        assert not any(event[0] == "write" for event in api.events)
        with pytest.raises(storage.StorageIncomplete):
            _ = session.live_staging_observations
    assert (root / "original-stage").read_bytes() == b""
    assert not (root / "ready.json").exists()


def test_live_staging_clears_before_uncertain_close(synthetic):
    storage, _, _, context = synthetic
    with context() as session:
        close = session._io.close
        snapshots = []

        def closing(fd):
            snapshots.append(session.live_staging_observations)
            return close(fd)

        session._io.close = closing
        session.stage("ready.json", PAYLOAD, transaction_id=TX)
        assert snapshots and all(item == () for item in snapshots)


def test_native_live_name_query_uses_only_owned_handle(monkeypatch):
    import sys
    from types import SimpleNamespace

    storage = module()
    calls = []

    def query(handle, buffer, capacity, flags):
        calls.append((handle, capacity, flags))
        buffer.value = str(Path("/synthetic/stage"))
        return len(buffer.value)

    native = object.__new__(storage._NativeIO)
    native.api = SimpleNamespace(
        kernel=SimpleNamespace(GetFinalPathNameByHandleW=query),
        _require=storage.windows_private._WinAPI._require,
    )
    monkeypatch.setitem(sys.modules, "msvcrt", SimpleNamespace(get_osfhandle=lambda _: 77))
    native.check_path(4, Path("/synthetic/stage"))
    assert calls == [(77, 32768, 0)]
    with pytest.raises(storage.windows_private.WindowsPrivacyError):
        native.check_path(4, Path("/synthetic/foreign"))
