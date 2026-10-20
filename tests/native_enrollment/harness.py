"""Process supervision and pure checks. No product bindings change in this process."""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import platform
import stat
import subprocess
import time
from pathlib import Path
from uuid import uuid4

MAX_REPORT_BYTES = 128 * 1024
CHILD_SECONDS = 90
MAX_SNAPSHOT_ENTRIES = 256
MAX_SNAPSHOT_FILE_BYTES = 16 * 1024 * 1024
MAX_SNAPSHOT_TOTAL_BYTES = 32 * 1024 * 1024
WORKER_ERROR_TYPES = frozenset(
    {
        "AssertionError",
        "EOFError",
        "FileNotFoundError",
        "OSError",
        "PermissionError",
        "RuntimeError",
        "TimeoutError",
        "TypeError",
        "ValueError",
        "OtherError",
    }
)
SNAPSHOT_ERROR_REASONS = frozenset(
    {
        "native_qa_artifact_limit",
        "native_qa_redirected_artifact",
        "native_qa_snapshot_changed_fd",
        "native_qa_snapshot_changed_opened",
        "native_qa_snapshot_changed_path",
        "native_qa_snapshot_changed_read_size",
        "native_qa_snapshot_limit",
        "native_qa_snapshot_root_invalid",
        "native_qa_special_artifact",
    }
)


class WorkerFailure(RuntimeError):
    def __init__(self, evidence):
        self.evidence = evidence
        error_type = evidence.get("error_type")
        if error_type not in WORKER_ERROR_TYPES:
            error_type = "OtherError"
        reason = evidence.get("reason")
        if reason not in SNAPSHOT_ERROR_REASONS:
            reason = "unspecified"
        super().__init__(f"native_qa_worker_failed:{evidence['phase']}:{error_type}:{reason}")


def gate_reason(*, enabled, authorized, root, platform):
    if not enabled:
        return "native enrollment QA is opt-in; no Windows state was touched"
    if not authorized:
        return "requires explicit --authorize-native-enrollment-writes operator authorization"
    if not root:
        return "requires --native-enrollment-qa-root selecting a disposable QA directory"
    if platform != "nt":
        return "real Windows local-NTFS mechanisms required; Linux is not native acceptance"
    return None


def delegated_call(name, action, events, *, fault=None):
    """Record one boundary; only the selected before-fault skips its real action."""
    event = {"operation": name, "delegated": False, "returned": False}
    if len(events) >= 1024:
        raise RuntimeError("native_qa_event_limit")
    events.append(event)
    if fault == (name, "before"):
        event["injected"] = "before"
        raise OSError("native_qa_injected_before")
    event["delegated"] = True
    result = action()
    event["returned"] = True
    if fault == (name, "after"):
        event["injected"] = "after"
        raise OSError("native_qa_injected_after")
    return result


class OwnedChild:
    """Spawn and reap only this harness's own process, with finite IPC waits."""

    def __init__(self, target, *args):
        context = multiprocessing.get_context("spawn")
        self.parent, child = context.Pipe()
        self.process = context.Process(target=target, args=(*args, child))
        self.process.start()
        child.close()

    def receive(self, seconds=CHILD_SECONDS):
        if not self.parent.poll(seconds):
            raise TimeoutError("native_qa_child_deadline")
        value = self.parent.recv()
        if value["event"] == "error":
            raise WorkerFailure(value)
        return value

    def send(self, value):
        self.parent.send(value)

    def finish(self):
        self.process.join(5)
        if self.process.is_alive() or self.process.exitcode != 0:
            raise RuntimeError("native_qa_child_exit_unconfirmed")

    def close(self):
        self.process.join(2)
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(5)
        if self.process.is_alive():
            self.process.kill()
            self.process.join(5)
        self.parent.close()
        if self.process.is_alive():
            raise RuntimeError("native_qa_owned_child_not_reaped")
        self.process.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def invoke(target, *args):
    with OwnedChild(target, *args) as child:
        result = child.receive()
        child.finish()
        return result


def _snapshot_signature(info, *, cross_api=False):
    # CPython 3.13 Windows path stat reports birthtime as ctime and adds execute
    # bits based on the filename; fd stat reports ChangeTime and has no filename.
    # Compare compatible fields across those APIs, but retain each API's complete
    # signature for its own pre/post checks, including ctime and all mode bits.
    windows_fields = hasattr(info, "st_file_attributes")
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode & ~0o111 if cross_api and windows_fields else info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        None if cross_api and windows_fields else info.st_ctime_ns,
        getattr(info, "st_birthtime_ns", None),
        getattr(info, "st_file_attributes", None),
    )


def _snapshot_kind(info):
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise RuntimeError("native_qa_redirected_artifact")
    if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
        raise RuntimeError("native_qa_special_artifact")


def _snapshot_recheck(path, expected):
    current = path.lstat()
    _snapshot_kind(current)
    if _snapshot_signature(current) != _snapshot_signature(expected):
        raise RuntimeError("native_qa_snapshot_changed_path")


def _snapshot_digest(path, expected, budget):
    """Never read a non-regular object; cap allocation and detect byte/identity races."""
    _snapshot_recheck(path, expected)
    if not stat.S_ISREG(expected.st_mode):
        raise RuntimeError("native_qa_special_artifact")
    cap = min(MAX_SNAPSHOT_FILE_BYTES, budget)
    if not 0 <= expected.st_size <= cap:
        raise RuntimeError("native_qa_artifact_limit")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        _snapshot_kind(opened)
        if not stat.S_ISREG(opened.st_mode):
            raise RuntimeError("native_qa_special_artifact")
        if _snapshot_signature(opened, cross_api=True) != _snapshot_signature(
            expected, cross_api=True
        ):
            raise RuntimeError("native_qa_snapshot_changed_opened")
        _snapshot_recheck(path, expected)
        digest, count = hashlib.sha256(), 0
        while count <= cap:
            raw = os.read(fd, min(65536, cap + 1 - count))
            if not raw:
                break
            count += len(raw)
            digest.update(raw)
        if count > cap:
            raise RuntimeError("native_qa_artifact_limit")
        final = os.fstat(fd)
        _snapshot_kind(final)
        if _snapshot_signature(final) != _snapshot_signature(opened):
            raise RuntimeError("native_qa_snapshot_changed_fd")
        if count != expected.st_size:
            raise RuntimeError("native_qa_snapshot_changed_read_size")
        _snapshot_recheck(path, expected)
        return digest.hexdigest(), count
    finally:
        os.close(fd)


def snapshot(root, *, metadata_only=()):
    """Capped non-following inventory, then bounded identity-checked regular reads."""
    initial = root.lstat()
    _snapshot_kind(initial)
    if not stat.S_ISDIR(initial.st_mode):
        raise RuntimeError("native_qa_snapshot_root_invalid")
    pending, inventory = [(root, initial)], []
    directories = [(root, initial)]
    while pending:
        directory, expected = pending.pop()
        _snapshot_recheck(directory, expected)
        with os.scandir(directory) as entries:
            for entry in entries:
                # Bound enumeration itself, before sorting, descending or byte opens.
                if len(inventory) >= MAX_SNAPSHOT_ENTRIES:
                    raise RuntimeError("native_qa_snapshot_limit")
                path = Path(entry.path)
                info = path.lstat()
                _snapshot_kind(info)
                inventory.append((path, info))
                if stat.S_ISDIR(info.st_mode):
                    pending.append((path, info))
                    directories.append((path, info))
        _snapshot_recheck(directory, expected)
    result, remaining = {}, MAX_SNAPSHOT_TOTAL_BYTES
    for path, info in sorted(inventory, key=lambda item: str(item[0])):
        _snapshot_recheck(path, info)
        is_directory = stat.S_ISDIR(info.st_mode)
        entry = {"identity": [info.st_dev, info.st_ino], "directory": is_directory}
        if not is_directory:
            if not 0 <= info.st_size <= min(MAX_SNAPSHOT_FILE_BYTES, remaining):
                raise RuntimeError("native_qa_artifact_limit")
            entry.update(size=info.st_size, mtime=info.st_mtime_ns, ctime=info.st_ctime_ns)
            if path not in metadata_only:
                entry["sha256"], _ = _snapshot_digest(path, info, remaining)
            remaining -= info.st_size
        result[str(path.relative_to(root))] = entry
    for path, info in directories:
        _snapshot_recheck(path, info)
    return result


def checkout_evidence():
    root = Path(__file__).resolve().parents[2]

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()

    files = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((root / "src").rglob("*.py"))
    }
    return {
        "commit": git("rev-parse", "HEAD"),
        "tree": git("rev-parse", "HEAD^{tree}"),
        "product_python_sha256": hashlib.sha256(
            json.dumps(files, sort_keys=True).encode()
        ).hexdigest(),
        "working_tree_dirty": bool(git("status", "--porcelain")),
        "python": platform.python_version(),
        "platform": platform.platform(),
    }


def run_case(selected_root, name, *, fault=None):
    """Keep the report even on assertions; never clean up or retry retained state."""
    from . import worker

    report = {
        "schema": "native-enrollment-qa-v1",
        "case": name,
        "fault": fault,
        "execution_allowed": False,
        "device_acceptance": False,
        "outcome": "not_completed",
        "checkout": checkout_evidence(),
    }
    case = Path(selected_root) / ("eq-" + uuid4().hex[:16])
    started = time.monotonic()
    try:
        bundle = invoke(worker.setup, str(case), name, report["checkout"])["bundle"]
        case = bundle["case"]
        report["fixture"] = bundle["summary"]
        if name == "account_contention":
            account = bundle["control"] / "admission.lock"
            with OwnedChild(worker.transaction, bundle, "winner") as winner:
                assert winner.receive()["event"] == "account_lock_held"
                before = invoke(worker.snapshot_state, bundle["state"], (account,))["snapshot"]
                loser = invoke(worker.transaction, bundle, "loser")
                after = invoke(worker.snapshot_state, bundle["state"], (account,))["snapshot"]
                report["loser"] = loser
                report["loser_state_unchanged"] = before == after
                # Release even if later checks fail; the winner is a coordinator,
                # not a standalone low-level lock-only test.
                winner.send("release")
                won = winner.receive()
                winner.finish()
                report["winner"] = won
                assert before == after
                assert loser["status"] == "incomplete"
                assert loser["account_lock_attempted"] == 1
                assert loser["account_lock_acquired"] == 0
                assert loser["journal_byte_opens"] == loser["sqlite_connects"] == 0
                assert loser["mutation_audit"] == loser["device_process_attempts"] == 0
                assert loser["native_events"] == []
                assert won["status"] == "candidate_unpinned"
                assert won["execution_allowed"] is False
                assert won["candidate_present"] is True
                assert won["sqlite_connects"] == 1
                assert won["device_process_attempts"] == 0
                lock = invoke(worker.observe_files, {"account": account})["observations"]["account"]
                assert lock["size"] == 1 and lock["sha256"] == hashlib.sha256(b"0").hexdigest()
        elif name == "device_contention":
            originals = {role: bundle[role] for role in ("journal", "device_lock")}
            original = invoke(worker.observe_files, originals)["observations"]
            with OwnedChild(worker.hold_device, bundle) as holder:
                assert holder.receive()["event"] == "device_lock_held"
                contender = invoke(worker.transaction, bundle, "contender")
                report["contender"] = contender
                holder.send("release")
                assert holder.receive()["event"] == "released"
                holder.finish()
            report["originals_unchanged"] = (
                original == invoke(worker.observe_files, originals)["observations"]
            )
            assert report["originals_unchanged"]
            assert contender["status"] == "incomplete"
            assert contender["sqlite_connects"] == contender["device_process_attempts"] == 0
            assert contender["account_lock_acquired"] == 1
            assert contender["device_lock_acquired"] == 0
            assert contender["boundary"] in {"original_device_lock", "locked_byte_read"}
            assert contender["candidate_present"] is False
        elif name == "existing_positive":
            originals = {role: bundle[role] for role in ("journal", "device_lock")}
            original = invoke(worker.observe_files, originals)["observations"]
            result = invoke(worker.transaction, bundle, "single")
            report["transaction"] = result
            report["originals_unchanged"] = (
                original == invoke(worker.observe_files, originals)["observations"]
            )
            assert result["status"] == "candidate_unpinned"
            assert result["execution_allowed"] is False
            assert result["candidate_present"] is True
            assert result["sqlite_connects"] == 1
            assert result["device_process_attempts"] == 0
            assert report["originals_unchanged"]
        else:
            result = invoke(worker.storage_case, bundle, fault)
            report["storage"] = result
            if fault is None:
                assert result["status"] == "published"
                assert result["stage_present"] is False
                assert result["destination_matches"] is True
                assert {event["operation"] for event in result["native_events"]} == {
                    "create",
                    "write",
                    "fsync",
                    "flush",
                    "move",
                }
                assert all(event["returned"] for event in result["native_events"])
            else:
                operation, edge = fault
                assert result["status"] == "incomplete"
                assert result["phase"] == operation
                assert result["uncertain"] is True
                injected = [
                    item for item in result["native_events"] if item.get("injected") == edge
                ]
                assert len(injected) == 1
                assert injected[0]["operation"] == operation
                assert injected[0]["delegated"] is (edge == "after")
                assert result["native_events"][-1] is injected[0]
                assert result["destination_present"] is (fault == ("move", "after"))
                assert result["stage_present"] is (fault != ("move", "after"))
                if fault == ("move", "after"):
                    assert result["destination_matches"] is True
            assert result["device_process_attempts"] == 0
        report["checkout_after"] = checkout_evidence()
        for key in ("commit", "tree", "product_python_sha256"):
            assert report["checkout_after"][key] == report["checkout"][key]
        report["outcome"] = "passed"
    except BaseException as error:
        report["outcome"] = "failed"
        report["error_type"] = type(error).__name__
        if isinstance(error, WorkerFailure):
            report["worker_failure"] = error.evidence
        raise
    finally:
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        # Setup creates this private, unscanned reports directory. A failure before
        # it exists is reported by pytest; do not repair/create it from the parent.
        if (case / "reports").is_dir():
            raw = json.dumps(report, indent=2, sort_keys=True).encode()
            if len(raw) > MAX_REPORT_BYTES:
                raise RuntimeError("native_qa_report_limit")
            invoke(worker.persist_report, case, raw)
        print(f"Retained QA artifacts: {case}")
    return report
