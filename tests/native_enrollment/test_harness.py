"""Portable safety/control-flow checks. These do not execute native acceptance."""

import ast
import json
import os
import stat
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from .harness import OwnedChild, delegated_call, gate_reason, invoke

REPO = Path(__file__).resolve().parents[2]
NATIVE_TEST = "tests/native_enrollment/test_native_mechanisms.py"


def _stat_with(info, **changes):
    """Keep named OS fields and nanosecond precision when changing one fixture field."""
    values = {name: getattr(info, name) for name in dir(info) if name.startswith("st_")}
    values.update(changes)
    return SimpleNamespace(**values)


@pytest.mark.parametrize(
    ("enabled", "authorized", "root", "platform", "reason"),
    [
        (False, False, None, "nt", "opt-in"),
        (False, True, "C:\\qa", "nt", "opt-in"),
        (True, False, "C:\\qa", "nt", "authorization"),
        (True, True, None, "nt", "selecting"),
        (True, True, "/tmp/qa", "posix", "Linux"),
        (True, True, "C:\\qa", "nt", None),
    ],
    ids=["default", "no-enable", "no-auth", "no-root", "non-windows", "explicit-windows"],
)
def test_gate_requires_all_inputs(enabled, authorized, root, platform, reason):
    result = gate_reason(enabled=enabled, authorized=authorized, root=root, platform=platform)
    assert (result is None) if reason is None else reason in result


@pytest.mark.parametrize("flags", [[], ["--run-native-enrollment"]], ids=["default", "no-auth"])
def test_real_pytest_collection_never_creates_selected_root(tmp_path, flags):
    root = tmp_path / "must-not-be-created"
    environment = dict(os.environ)
    environment.pop("PYTEST_ADDOPTS", None)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            NATIVE_TEST,
            "--native-enrollment-qa-root",
            str(root),
            *flags,
        ],
        cwd=REPO,
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "12 skipped" in result.stdout
    assert not root.exists()


@pytest.mark.skipif(os.name == "nt", reason="non-Windows refusal check only")
def test_all_opt_ins_still_cannot_run_windows_mechanisms_on_linux(tmp_path):
    root = tmp_path / "must-not-be-created"
    environment = dict(os.environ)
    environment.pop("PYTEST_ADDOPTS", None)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            NATIVE_TEST,
            "--run-native-enrollment",
            "--authorize-native-enrollment-writes",
            "--native-enrollment-qa-root",
            str(root),
        ],
        cwd=REPO,
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "12 skipped" in result.stdout
    assert "Linux is not native acceptance" in result.stdout
    assert not root.exists()


@pytest.mark.parametrize("operation", ["write", "fsync", "flush", "move"])
@pytest.mark.parametrize("edge", [None, "before", "after"], ids=["normal", "before", "after"])
def test_fault_wrapper_delegates_except_intended_before_fault(operation, edge):
    calls, events = [], []

    def captured_action():
        calls.append("real-boundary-called")
        return 17

    fault = None if edge is None else (operation, edge)
    if edge is None:
        assert delegated_call(operation, captured_action, events, fault=fault) == 17
    else:
        with pytest.raises(OSError, match="native_qa_injected"):
            delegated_call(operation, captured_action, events, fault=fault)
    assert len(calls) == (0 if edge == "before" else 1)
    assert len(events) == 1
    assert events[0]["delegated"] is (edge != "before")
    assert events[0]["returned"] is (edge != "before")


def test_native_exception_is_not_relabelled_as_injected_success():
    events = []

    def failed_native():
        raise PermissionError("native-call-failed")

    with pytest.raises(PermissionError):
        delegated_call("move", failed_native, events, fault=("move", "after"))
    assert events == [{"operation": "move", "delegated": True, "returned": False}]


def echo_worker(value, connection):
    connection.send({"event": "echo", "value": value})
    connection.close()


def waiting_worker(connection):
    time.sleep(30)
    connection.close()


def test_owned_child_success_is_joined():
    assert invoke(echo_worker, 7) == {"event": "echo", "value": 7}


def test_owned_child_timeout_is_reaped():
    child = OwnedChild(waiting_worker)
    try:
        with pytest.raises(TimeoutError):
            child.receive(0.05)
    finally:
        child.close()
    assert child.process._closed


def test_fixture_database_contains_synthetic_history_without_file_creation(tmp_path):
    import sqlite3

    from .worker import _existing_database

    raw = _existing_database()
    with closing(sqlite3.connect(":memory:")) as database:
        database.deserialize(raw)
        assert database.execute("SELECT job_id, fence, result FROM intents").fetchall() == [
            ("synthetic-historic-job", 7, "confirmed")
        ]
        assert database.execute("SELECT count(*) FROM stop_acks").fetchone() == (0,)
    assert list(tmp_path.iterdir()) == []


def test_report_payload_is_json_serializable_and_has_no_path_or_environment():
    from .worker import Observations

    observed = Observations(Path("synthetic.sqlite"))
    observed.active = True
    observed.audit("open", ("synthetic.sqlite", "r", os.O_RDONLY))
    observed.audit("sqlite3.connect", (":memory:",))
    with pytest.raises(RuntimeError, match="external_process_forbidden"):
        observed.audit("subprocess.Popen", ("synthetic-manager.exe",))
    payload = observed.payload()
    assert payload["journal_byte_opens"] == payload["sqlite_connects"] == 1
    assert payload["device_process_attempts"] == 1
    assert "synthetic.sqlite" not in json.dumps(payload)
    assert "active" not in payload


def test_native_worker_does_not_replace_platform_or_private_guards():
    source = (Path(__file__).parent / "worker.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    protected = {
        "_protected_paths",
        "verified_directory",
        "verify_directory",
        "provision_private_directory",
        "_require_local_ntfs",
    }
    for node in ast.walk(module):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            assert all(
                not isinstance(target, ast.Attribute) or target.attr not in protected
                for target in targets
            )
    assert "os.O_WRONLY" not in source  # fixture byte files use native binary-handle storage


def test_snapshot_bounds_inventory_before_opening_or_descending(tmp_path, monkeypatch):
    from . import harness

    for index in range(4):
        (tmp_path / str(index)).mkdir()
    monkeypatch.setattr(harness, "MAX_SNAPSHOT_ENTRIES", 3)
    real_scandir = os.scandir
    visited = []

    def scandir(path):
        visited.append(path)
        return real_scandir(path)

    monkeypatch.setattr(harness.os, "scandir", scandir)
    monkeypatch.setattr(
        harness.os, "open", lambda *a, **k: pytest.fail("overlimit inventory opened bytes")
    )
    with pytest.raises(RuntimeError, match="snapshot_limit"):
        harness.snapshot(tmp_path)
    assert visited == [tmp_path]


@pytest.mark.parametrize(
    "mode",
    [stat.S_IFIFO, stat.S_IFSOCK, stat.S_IFCHR, stat.S_IFBLK],
    ids=["fifo", "socket", "character", "block"],
)
def test_snapshot_rejects_special_metadata_before_any_open(tmp_path, monkeypatch, mode):
    """Portable special-file metadata simulation, never a native guard substitute."""
    from . import harness

    path = tmp_path / "special"
    path.write_bytes(b"synthetic")
    real_lstat = Path.lstat

    def lstat(target):
        original = real_lstat(target)
        if target == path:
            return _stat_with(original, st_mode=mode | 0o600)
        return original

    monkeypatch.setattr(Path, "lstat", lstat)
    monkeypatch.setattr(harness.os, "open", lambda *a, **k: pytest.fail("opened special object"))
    with pytest.raises(RuntimeError, match="special_artifact"):
        harness.snapshot(tmp_path)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="real POSIX FIFO only")
def test_snapshot_real_fifo_never_opens_it(tmp_path, monkeypatch):
    from . import harness

    os.mkfifo(tmp_path / "pipe")
    monkeypatch.setattr(harness.os, "open", lambda *a, **k: pytest.fail("opened FIFO"))
    with pytest.raises(RuntimeError, match="special_artifact"):
        harness.snapshot(tmp_path)


def test_snapshot_rejects_reparse_metadata_before_descending(tmp_path, monkeypatch):
    from . import harness

    redirected = tmp_path / "redirected"
    redirected.mkdir()
    (redirected / "unread").write_bytes(b"outside")
    real_lstat, real_scandir = Path.lstat, os.scandir
    visited = []

    def lstat(path):
        if path == redirected:
            return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        return real_lstat(path)

    def scandir(path):
        visited.append(path)
        return real_scandir(path)

    monkeypatch.setattr(Path, "lstat", lstat)
    monkeypatch.setattr(harness.os, "scandir", scandir)
    with pytest.raises(RuntimeError, match="redirected_artifact"):
        harness.snapshot(tmp_path)
    assert visited == [tmp_path]


def test_snapshot_symlink_does_not_visit_target(tmp_path, symlink_or_skip):
    from .harness import snapshot

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "unread").write_bytes(b"outside")
    root = tmp_path / "root"
    root.mkdir()
    symlink_or_skip(root / "link", outside, target_is_directory=True)
    with pytest.raises(RuntimeError, match="redirected_artifact"):
        snapshot(root)


def test_snapshot_reads_bounded_chunks_and_detects_opened_identity_change(tmp_path, monkeypatch):
    from . import harness

    path = tmp_path / "payload"
    path.write_bytes(b"abc")
    expected = path.lstat()
    other = tmp_path / "different"
    other.write_bytes(b"abc")
    real_open = os.open
    monkeypatch.setattr(harness.os, "open", lambda *a, **k: real_open(other, a[1]))
    monkeypatch.setattr(harness.os, "read", lambda *a: pytest.fail("read changed identity"))
    with pytest.raises(RuntimeError, match="snapshot_changed"):
        harness._snapshot_digest(path, expected, 3)


def test_snapshot_enforces_per_file_and_total_byte_budgets(tmp_path, monkeypatch):
    from . import harness

    (tmp_path / "a").write_bytes(b"abc")
    (tmp_path / "b").write_bytes(b"def")
    monkeypatch.setattr(harness, "MAX_SNAPSHOT_FILE_BYTES", 2)
    with pytest.raises(RuntimeError, match="artifact_limit"):
        harness.snapshot(tmp_path)
    monkeypatch.setattr(harness, "MAX_SNAPSHOT_FILE_BYTES", 4)
    monkeypatch.setattr(harness, "MAX_SNAPSHOT_TOTAL_BYTES", 5)
    with pytest.raises(RuntimeError, match="artifact_limit"):
        harness.snapshot(tmp_path)


def test_snapshot_metadata_only_avoids_locked_byte_open(tmp_path, monkeypatch):
    from . import harness

    path = tmp_path / "locked"
    path.write_bytes(b"0")
    monkeypatch.setattr(harness.os, "open", lambda *a, **k: pytest.fail("opened locked byte"))
    result = harness.snapshot(tmp_path, metadata_only=(path,))
    assert result["locked"]["size"] == 1
    assert "sha256" not in result["locked"]


@pytest.mark.parametrize("formal_exists", [False, True], ids=["missing-formal", "existing-formal"])
def test_canonical_qa_parent_allows_disjoint_root(tmp_path, formal_exists):
    from .worker import canonical_qa_parent

    selected = tmp_path / "qa"
    selected.mkdir()
    account = tmp_path / "account"
    account.mkdir()
    formal = account / "swu-happyrun"
    if formal_exists:
        formal.mkdir()
    assert canonical_qa_parent(selected, formal) == selected.resolve(strict=True)


@pytest.mark.parametrize("target", ["formal", "child", "ancestor"], ids=["same", "inside", "above"])
def test_canonical_qa_parent_rejects_alias_of_formal_ancestry(tmp_path, monkeypatch, target):
    """Simulate Windows final-path expansion of a non-reparse 8.3 spelling."""
    from .worker import canonical_qa_parent

    selected = tmp_path / "short-spelling"
    selected.mkdir()
    account = tmp_path / "account"
    account.mkdir()
    formal = account / "swu-happyrun"
    formal.mkdir()
    child = formal / "child"
    child.mkdir()
    expanded = {"formal": formal, "child": child, "ancestor": account}[target]
    real_resolve = Path.resolve
    resolutions = []

    def resolve(path, *, strict=False):
        resolutions.append((path, strict))
        return expanded if path == selected else real_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", resolve)
    with pytest.raises(ValueError, match="formal_state_forbidden"):
        canonical_qa_parent(selected, formal)
    assert (selected, True) in resolutions
    assert (formal, True) in resolutions


def test_canonical_qa_parent_resolves_nearest_existing_formal_ancestor(tmp_path, monkeypatch):
    from .worker import canonical_qa_parent

    selected = tmp_path / "alias"
    selected.mkdir()
    account = tmp_path / "account"
    account.mkdir()
    formal = account / "missing" / "swu-happyrun"
    real_resolve = Path.resolve
    resolutions = []

    def resolve(path, *, strict=False):
        resolutions.append((path, strict))
        return account if path == selected else real_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", resolve)
    with pytest.raises(ValueError, match="formal_state_forbidden"):
        canonical_qa_parent(selected, formal)
    assert (account, True) in resolutions
    assert not formal.exists()


def test_snapshot_and_original_observation_helpers_are_owned_children(tmp_path):
    import hashlib

    from .worker import observe_files, snapshot_state

    path = tmp_path / "payload"
    raw = b"binary:\x00\x1a\xff\r\n"
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    captured = invoke(snapshot_state, tmp_path, ())
    assert captured["snapshot"]["payload"]["sha256"] == digest
    observed = invoke(observe_files, {"fixture": path})
    assert observed["observations"]["fixture"]["sha256"] == digest
    assert observed["observations"]["fixture"]["size"] == len(raw)


def test_stat_fixture_preserves_named_windows_fields_and_nanoseconds(tmp_path):
    original = _stat_with(
        tmp_path.lstat(),
        st_file_attributes=0x20,
        st_reparse_tag=0,
        st_birthtime_ns=123456789,
        st_ctime_ns=987654321,
    )
    changed = _stat_with(original, st_mode=stat.S_IFIFO | 0o600)
    assert vars(changed) == {**vars(original), "st_mode": stat.S_IFIFO | 0o600}


@pytest.mark.parametrize("filename", ["payload", "manager.exe"], ids=["data", "exe"])
def test_snapshot_accepts_windows_cross_api_ctime_and_execute_bit_semantics(
    tmp_path,
    monkeypatch,
    filename,
):
    """Simulate CPython 3.13 Windows metadata only; real regular-file reads remain."""
    import hashlib

    from . import harness

    path = tmp_path / filename
    path.write_bytes(b"abc")
    real_lstat, real_fstat = Path.lstat, os.fstat

    def lstat(target):
        original = real_lstat(target)
        if target != path:
            return original
        return _stat_with(
            original,
            st_file_attributes=0x20,
            st_birthtime_ns=100,
            st_ctime_ns=100,
            st_mode=original.st_mode | (0o111 if filename.endswith(".exe") else 0),
        )

    def fstat(fd):
        original = real_fstat(fd)
        return _stat_with(
            original,
            st_file_attributes=0x20,
            st_birthtime_ns=100,
            st_ctime_ns=200,
            st_mode=original.st_mode & ~0o111,
        )

    monkeypatch.setattr(Path, "lstat", lstat)
    monkeypatch.setattr(harness.os, "fstat", fstat)
    assert harness.snapshot(tmp_path)[filename]["sha256"] == hashlib.sha256(b"abc").hexdigest()


@pytest.mark.parametrize(
    "field",
    ["st_ctime_ns", "st_mode", "st_ino", "st_mtime_ns"],
    ids=["ctime", "mode", "id", "mtime"],
)
def test_snapshot_rejects_same_fd_changes_and_closes_handle(tmp_path, monkeypatch, field):
    from . import harness

    path = tmp_path / "payload"
    path.write_bytes(b"abc")
    expected = path.lstat()
    real_fstat, real_close = os.fstat, os.close
    calls, closed = [], []

    def fstat(fd):
        original = real_fstat(fd)
        calls.append(fd)
        if len(calls) == 2:
            return _stat_with(original, **{field: getattr(original, field) + 1})
        return original

    def close(fd):
        closed.append(fd)
        return real_close(fd)

    monkeypatch.setattr(harness.os, "fstat", fstat)
    monkeypatch.setattr(harness.os, "close", close)
    with pytest.raises(RuntimeError, match="snapshot_changed_fd"):
        harness._snapshot_digest(path, expected, 3)
    assert len(calls) == 2 and closed == [calls[0]]
    with pytest.raises(OSError):
        real_fstat(closed[0])


@pytest.mark.parametrize("field", ["st_ctime_ns", "st_mode"], ids=["ctime", "mode"])
def test_snapshot_retains_full_same_path_checks_before_open(tmp_path, monkeypatch, field):
    from . import harness

    path = tmp_path / "payload"
    path.write_bytes(b"abc")
    expected = path.lstat()
    monkeypatch.setattr(
        Path,
        "lstat",
        lambda target: _stat_with(expected, **{field: getattr(expected, field) + 1}),
    )
    monkeypatch.setattr(harness.os, "open", lambda *a, **k: pytest.fail("opened changed path"))
    with pytest.raises(RuntimeError, match="snapshot_changed_path"):
        harness._snapshot_digest(path, expected, 3)


@pytest.mark.parametrize("known", [False, True], ids=["unknown", "snapshot-reason"])
def test_worker_error_reports_only_whitelisted_type_and_snapshot_reason(known):
    from .harness import WorkerFailure
    from .worker import _send_error

    error = (
        RuntimeError("native_qa_snapshot_changed_opened")
        if known
        else type("private-path-secret", (RuntimeError,), {})("private path and detail")
    )
    events = []
    _send_error(SimpleNamespace(send=events.append), error, phase="snapshot_retained_state")
    assert events == [
        {
            "event": "error",
            "phase": "snapshot_retained_state",
            "error_type": "RuntimeError" if known else "OtherError",
            "reason": "native_qa_snapshot_changed_opened" if known else "unspecified",
        }
    ]
    rendered = str(WorkerFailure(events[0]))
    assert events[0]["error_type"] in rendered and events[0]["reason"] in rendered
    assert "private" not in rendered


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("st_dev", 99),
        ("st_ino", 99),
        ("st_mode", stat.S_IFREG | 0o444),
        ("st_size", 4),
        ("st_mtime_ns", 99),
        ("st_birthtime_ns", 99),
        ("st_file_attributes", 0x21),
    ],
    ids=["device", "inode", "read-only-mode", "size", "mtime", "birthtime", "attributes"],
)
def test_windows_cross_api_signature_retains_compatible_fields(field, changed):
    from .harness import _snapshot_signature

    expected = SimpleNamespace(
        st_dev=1,
        st_ino=2,
        st_mode=stat.S_IFREG | 0o666,
        st_size=3,
        st_mtime_ns=10,
        st_ctime_ns=11,
        st_birthtime_ns=11,
        st_file_attributes=0x20,
    )
    opened = _stat_with(expected, st_ctime_ns=12)
    assert _snapshot_signature(opened, cross_api=True) == _snapshot_signature(
        expected, cross_api=True
    )
    altered = _stat_with(opened, **{field: changed})
    assert _snapshot_signature(altered, cross_api=True) != _snapshot_signature(
        expected, cross_api=True
    )


def test_owned_snapshot_worker_failure_exposes_safe_type_without_raw_path(tmp_path):
    from .harness import WorkerFailure
    from .worker import snapshot_state

    path = tmp_path / "private-not-present"
    with pytest.raises(WorkerFailure, match="snapshot_retained_state:FileNotFoundError") as caught:
        invoke(snapshot_state, path, ())
    assert caught.value.evidence["reason"] == "unspecified"
    assert "private" not in str(caught.value) and str(path) not in json.dumps(caught.value.evidence)
