"""Synthetic fixed runtime/uncertainty retention; no native execution acceptance."""

import copy
import importlib
import importlib.util
import json
import os
import sqlite3
import stat
from contextlib import closing, contextmanager
from pathlib import Path

import pytest
from test_enrollment_review_pin import issue
from test_enrollment_transaction import synthetic as synthetic  # noqa: F401

from swu_happyrun.agent.journal import RunJournal, UnsafeReplay
from swu_happyrun.drivers.base import DriverError
from swu_happyrun.drivers.mumu.enrollment import require_native_enrollment
from swu_happyrun.drivers.mumu.enrollment_authority import ApprovalNotReady

MODULE = "swu_happyrun.drivers.mumu.enrollment_runtime"


def runtime():
    assert importlib.util.find_spec(MODULE), "typed runtime resolver is missing"
    return importlib.import_module(MODULE)


def test_fixed_runtime_holds_original_locks_and_reads_current_sql(synthetic):
    module = runtime()
    _, _, _, _, _, plan, paths, _, _, _, pinned = issue(synthetic)
    with module.resolve_fixed_runtime(pinned) as context:
        assert context.inspect().intent_count == 0
        assert context.inspect().execution_allowed is False
        with pytest.raises(UnsafeReplay):
            with RunJournal.lock_existing(paths["journal"], plan["device_id"]):
                pytest.fail("original device lock was released")
        for value in (context, pinned, True, {"approved": True}):
            with pytest.raises(DriverError, match="enrollment_execution_not_ready"):
                require_native_enrollment(value)
        with pytest.raises(DriverError, match="enrollment_execution_not_ready"):
            context.require_execution()
    with pytest.raises(ApprovalNotReady):
        context.inspect()


def test_runtime_cannot_be_constructed_copied_or_reused(synthetic):
    module = runtime()
    *_, pinned = issue(synthetic)
    with pytest.raises(TypeError):
        module.RuntimeContext()
    with pytest.raises(TypeError):
        module.OriginalScopeCleanup()
    with module.resolve_fixed_runtime(pinned) as context:
        forged = object.__new__(module.RuntimeContext)
        with pytest.raises(ApprovalNotReady):
            forged.inspect()
        with pytest.raises(TypeError):
            copy.copy(context)
        assert context.inspect().execution_allowed is False


def test_runtime_revalidates_mutable_rows_without_changing_pin(synthetic):
    module = runtime()
    _, _, _, _, _, _, paths, _, _, _, pinned = issue(synthetic)
    with module.resolve_fixed_runtime(pinned) as context:
        with closing(sqlite3.connect(paths["journal"])) as db, db:
            db.execute("INSERT INTO intents VALUES ('old-start', 'start', 1, NULL)")
            db.execute("INSERT INTO intents VALUES ('old-upload', 'upload', 2, 'uncertain')")
        observed = context.inspect()
        assert observed.intent_count == observed.unresolved_intent_count == 2
        assert observed.status == "unresolved"
        with closing(sqlite3.connect(paths["journal"])) as db, db:
            db.execute("UPDATE intents SET result='confirmed'")
        # A confirmed start is not proof of stop, and never silently erased.
        assert context.inspect().unresolved_intent_count == 1
        with pytest.raises(DriverError, match="enrollment_execution_not_ready"):
            context.require_execution()


@pytest.mark.parametrize("change", ["expiry", "revocation", "pin", "schema"])
def test_invalid_runtime_before_start_is_permanently_sealed_without_writes(
    synthetic, monkeypatch, change
):
    module = runtime()
    _, state, root, _, _, _, paths, _, _, _, pinned = issue(synthetic)
    lock_bytes = paths["device_lock"].read_bytes()
    with module.resolve_fixed_runtime(pinned) as context:
        token = module._CONTEXTS[context].session.device
        read_bytes = Path.read_bytes

        def deny_locked_read(path):
            if path == token.lock_path and token.fd is not None:
                raise PermissionError("synthetic Windows byte-lock read denial")
            return read_bytes(path)

        monkeypatch.setattr(Path, "read_bytes", deny_locked_read)

        def snapshot():
            # Only the exact held lock uses metadata: Windows byte locking
            # prohibits a second handle's read. All other files retain bytes.
            def identity(info):
                return (
                    info.st_dev,
                    info.st_ino,
                    stat.S_IFMT(info.st_mode),
                    info.st_size,
                    info.st_nlink,
                )

            return {
                path: (
                    identity(os.fstat(token.fd)),
                    identity(path.lstat()),
                )
                if path == token.lock_path
                else path.read_bytes()
                for path in paths["journal"].parent.iterdir()
                if path.is_file()
            }

        if change == "expiry":
            state["now"] = 1000
        elif change == "revocation":
            (root / "authority-v1.json").write_bytes(b"{}")
        elif change == "pin":
            (root / "reviews" / pinned.runner.plan_sha256 / "review-pin-v1.json").write_bytes(b"{}")
        else:
            with closing(sqlite3.connect(paths["journal"])) as db, db:
                db.execute("CREATE TABLE unexpected (value)")
        before = snapshot()
        with pytest.raises(ApprovalNotReady):
            context.inspect()
        state["now"] = 10
        with pytest.raises(ApprovalNotReady):
            context.inspect()
        with pytest.raises(DriverError, match="enrollment_execution_not_ready"):
            context.require_execution()
        assert context.sealed is True
        assert before == snapshot()
    assert paths["device_lock"].read_bytes() == lock_bytes


def test_expiry_during_original_lock_acquisition_opens_no_database(synthetic, monkeypatch):
    module = runtime()
    _, state, _, _, _, _, _, _, _, _, pinned = issue(synthetic)
    original = RunJournal.lock_existing

    @contextmanager
    def delayed(*args, **kwargs):
        with original(*args, **kwargs) as token:
            state["now"] = 1000
            yield token

    monkeypatch.setattr(RunJournal, "lock_existing", delayed)
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: pytest.fail("SQLite after expiry"))
    with pytest.raises(ApprovalNotReady):
        with module.resolve_fixed_runtime(pinned):
            pytest.fail("expired context")


def start_synthetic(module, context):
    """Test-only state seed. No public or production native issuer exists."""
    state = module._CONTEXTS[context]
    journal = state.journal
    # The already-started fixture persists through the exact held connection and
    # original reservation API. It does not monkeypatch native admission.
    job = "33333333-3333-4333-8333-333333333333"
    journal._db.execute("INSERT INTO intents VALUES (?, 'start', 1, NULL)", (job,))
    journal._db.commit()
    permit = journal.reserve_replay(state.session.plan.device_id, job, generation=1)
    cleanup = module._bind_original_scope(context, deadline=module.time.monotonic() + 45.0)
    return state, permit, cleanup


@pytest.mark.parametrize("change", ["expiry", "revocation", "pin"])
def test_started_scope_retains_uncertainty_after_gate_loss(synthetic, change):
    module = runtime()
    _, fixture, root, _, _, _, _, _, _, _, pinned = issue(synthetic)
    with module.resolve_fixed_runtime(pinned) as context:
        state, permit, cleanup = start_synthetic(module, context)
        lock_fd = state.session.device.fd
        if change == "expiry":
            fixture["now"] = 1000
        elif change == "revocation":
            (root / "authority-v1.json").write_bytes(b"{}")
        else:
            (root / "reviews" / pinned.runner.plan_sha256 / "review-pin-v1.json").write_bytes(b"{}")
        result = cleanup.retain_uncertain()
        assert result.status == "uncertainty_retained"
        assert result.native_cleanup_allowed is False
        assert context.sealed is True
        assert state.session.device.fd == lock_fd
        assert state.journal.read_replay_reservation(permit.device_id)["status"] == "uncertain"
        assert state.journal._db.execute("SELECT count(*) FROM intents").fetchone()[0] == 1
        assert permit.marker["generation"] == 1
        with pytest.raises(ApprovalNotReady):
            context.inspect()
        with pytest.raises(DriverError, match="enrollment_execution_not_ready"):
            context.require_execution()
    with pytest.raises(ApprovalNotReady):
        cleanup.retain_uncertain()


@pytest.mark.parametrize("change", ["reservation", "journal", "lock", "budget"])
def test_uncertain_cleanup_never_releases_or_overwrites_changed_identity(
    synthetic, monkeypatch, change
):
    module = runtime()
    _, _, _, _, _, _, paths, _, _, _, pinned = issue(synthetic)
    lock_bytes = paths["device_lock"].read_bytes()
    with module.resolve_fixed_runtime(pinned) as context:
        state, permit, cleanup = start_synthetic(module, context)
        path = state.journal._reservation_path(permit.device_id)
        if change in {"journal", "lock", "reservation"}:
            target = {
                "journal": state.journal.path,
                "lock": state.session.device.lock_path,
                "reservation": path,
            }[change]
            original = lock_bytes if change == "lock" else target.read_bytes()
            replacement = target.with_suffix(".replacement")
            replacement.write_bytes(original)
            try:
                replacement.replace(target)
            except PermissionError:
                if change not in {"journal", "lock"}:
                    raise
                pytest.skip("OS handle prevents replacement; portable identity test is separate")
        else:
            times = iter([10.0, 100.0])
            monkeypatch.setattr(module.time, "monotonic", lambda: next(times, 100.0))
        original = path.read_bytes()
        result = cleanup.retain_uncertain()
        assert result.status == "retention_unconfirmed"
        assert context.sealed is True
        assert path.read_bytes() == original
        assert json.loads(original)["status"] == "active"


@pytest.mark.parametrize("change", ["journal", "lock"])
def test_changed_observed_identity_is_rejected_with_original_handles_held(
    synthetic, monkeypatch, change
):
    module = runtime()
    journal_module = importlib.import_module("swu_happyrun.agent.journal")
    *_, pinned = issue(synthetic)
    with module.resolve_fixed_runtime(pinned) as context:
        state, permit, cleanup = start_synthetic(module, context)
        token = state.session.device
        target = state.journal.path if change == "journal" else token.lock_path
        descriptor = token.fd
        path = state.journal._reservation_path(permit.device_id)
        before = path.read_bytes()
        chain = journal_module._original_chain
        observed = []

        def changed_identity(candidate, **kwargs):
            value = chain(candidate, **kwargs)
            if candidate == target:
                observed.append(candidate)
                name, device, inode, kind = value[-1]
                return (*value[:-1], (name, device, inode + 1, kind))
            return value

        # Simulate identity substitution, not successful Windows rename. Keep
        # actual original SQL/lock handles live and exercise their validator.
        monkeypatch.setattr(journal_module, "_original_chain", changed_identity)
        with pytest.raises(UnsafeReplay, match="original_path_changed"):
            token.validate(check_marker=False)
        result = cleanup.retain_uncertain()
        assert result.status == "retention_unconfirmed"
        assert observed
        assert token.fd == descriptor
        assert state.journal._db.execute("SELECT count(*) FROM intents").fetchone()[0] == 1
        assert path.read_bytes() == before
        assert json.loads(before)["status"] == "active"
        monkeypatch.setattr(journal_module, "_original_chain", chain)
        token.validate(check_marker=False)
        assert cleanup.retain_uncertain() is result
        assert context.sealed
        with pytest.raises(ApprovalNotReady):
            context.inspect()
        with pytest.raises(DriverError, match="enrollment_execution_not_ready"):
            context.require_execution()


@pytest.mark.parametrize("status", ["active", "uncertain"])
def test_incoming_unresolved_reservation_is_preserved_before_sql(synthetic, monkeypatch, status):
    module = runtime()
    _, _, _, _, _, plan, paths, _, _, _, pinned = issue(synthetic)
    with RunJournal(paths["journal"]) as journal:
        with journal.device_lock(plan["device_id"]):
            permit = journal.reserve_replay(
                plan["device_id"], "33333333-3333-4333-8333-333333333333", generation=1
            )
            if status == "uncertain":
                journal.update_replay(permit, generation=1, status="uncertain")
            marker = journal._reservation_path(plan["device_id"])
    before = marker.read_bytes()
    monkeypatch.setattr(
        sqlite3,
        "connect",
        lambda *a, **k: pytest.fail("SQL before unresolved reservation rejection"),
    )
    with pytest.raises(UnsafeReplay):
        with module.resolve_fixed_runtime(pinned):
            pytest.fail("unresolved reservation admitted")
    assert marker.read_bytes() == before


def test_context_exception_retains_original_pending_probe(synthetic):
    module = runtime()
    *_, pinned = issue(synthetic)
    with pytest.raises(RuntimeError, match="synthetic failure"):
        with module.resolve_fixed_runtime(pinned) as context:
            state = module._CONTEXTS[context]
            job = "33333333-3333-4333-8333-333333333333"
            state.journal._db.execute("INSERT INTO intents VALUES (?, 'start', 1, NULL)", (job,))
            state.journal._db.commit()
            permit = state.journal.reserve_replay(state.session.plan.device_id, job, generation=1)
            value = dict(permit.marker, probe_pending=True)
            path = state.journal._reservation_path(permit.device_id)
            path.write_text(json.dumps(value))
            permit.marker = value
            module._bind_original_scope(context, deadline=module.time.monotonic() + 45.0)
            raise RuntimeError("synthetic failure")
    assert json.loads(path.read_bytes())["status"] == "uncertain"
    assert json.loads(path.read_bytes())["probe_pending"] is True
    with pytest.raises(ApprovalNotReady):
        context.inspect()


def test_invalidated_inspection_automatically_seals_and_retains(synthetic):
    module = runtime()
    _, fixture, _, _, _, _, _, _, _, _, pinned = issue(synthetic)
    with module.resolve_fixed_runtime(pinned) as context:
        state, permit, cleanup = start_synthetic(module, context)
        fixture["now"] = 1000
        with pytest.raises(ApprovalNotReady):
            context.inspect()
        assert context.sealed
        assert cleanup.retain_uncertain().status == "uncertainty_retained"
        assert state.journal.read_replay_reservation(permit.device_id)["status"] == "uncertain"
        fixture["now"] = 10
        with pytest.raises(ApprovalNotReady):
            context.inspect()


@pytest.mark.parametrize("change", ["session", "generation", "start_intent", "probe"])
def test_retention_binds_exact_original_reservation_and_intent(synthetic, change):
    module = runtime()
    *_, pinned = issue(synthetic)
    with module.resolve_fixed_runtime(pinned) as context:
        state, permit, cleanup = start_synthetic(module, context)
        path = state.journal._reservation_path(permit.device_id)
        value = dict(permit.marker)
        if change == "start_intent":
            state.journal._db.execute("DELETE FROM intents")
            state.journal._db.commit()
        else:
            key, replacement = {
                "session": ("session_id", "44444444-4444-4444-8444-444444444444"),
                "generation": ("generation", 2),
                "probe": ("probe_pending", True),
            }[change]
            value[key] = replacement
            path.write_text(json.dumps(value))
            permit.marker = value
        before = path.read_bytes()
        assert cleanup.retain_uncertain().status == "retention_unconfirmed"
        assert path.read_bytes() == before
        assert context.sealed


def test_failed_attempt_never_renews_budget_or_retries(synthetic, monkeypatch):
    module = runtime()
    *_, pinned = issue(synthetic)
    with module.resolve_fixed_runtime(pinned) as context:
        state, permit, cleanup = start_synthetic(module, context)
        path = state.journal._reservation_path(permit.device_id)
        before = path.read_bytes()
        times = iter([0.0, 3.0])
        monkeypatch.setattr(module.time, "monotonic", lambda: next(times, 3.0))
        result = cleanup.retain_uncertain()
        assert result.status == "retention_unconfirmed"
        monkeypatch.setattr(module.time, "monotonic", lambda: 0.0)
        assert cleanup.retain_uncertain() is result
        assert path.read_bytes() == before


def test_original_marker_descriptor_never_publishes_foreign_file(synthetic, monkeypatch):
    module = runtime()
    *_, pinned = issue(synthetic)
    with module.resolve_fixed_runtime(pinned) as context:
        state, permit, cleanup = start_synthetic(module, context)
        path = state.journal._reservation_path(permit.device_id)
        original_identity = path.stat().st_ino
        monkeypatch.setattr(module.os, "replace", lambda *a: pytest.fail("cleanup replaced marker"))
        assert cleanup.retain_uncertain().status == "uncertainty_retained"
        assert path.stat().st_ino == original_identity
        assert json.loads(path.read_bytes())["status"] == "uncertain"


def test_partial_retention_write_stays_unresolved_and_is_not_retried(synthetic, monkeypatch):
    module = runtime()
    *_, pinned = issue(synthetic)
    with module.resolve_fixed_runtime(pinned) as context:
        state, permit, cleanup = start_synthetic(module, context)
        path = state.journal._reservation_path(permit.device_id)
        original_identity = path.stat().st_ino
        write = module.os.write
        calls = []

        def partial(fd, data):
            calls.append(True)
            if len(calls) > 1:
                raise OSError("injected storage failure")
            return write(fd, data[:9])

        monkeypatch.setattr(module.os, "write", partial)
        result = cleanup.retain_uncertain()
        assert result.status == "retention_unconfirmed"
        assert path.stat().st_ino == original_identity
        assert path.exists()
        assert cleanup.retain_uncertain() is result
        assert len(calls) == 2
        with pytest.raises(UnsafeReplay):
            state.journal.read_replay_reservation(permit.device_id)


@pytest.mark.parametrize("boundary", ["open", "write", "ftruncate", "fsync", "readback"])
def test_retention_fault_boundaries_never_report_success_or_clear_occupancy(
    synthetic, monkeypatch, boundary
):
    module = runtime()
    *_, pinned = issue(synthetic)
    with module.resolve_fixed_runtime(pinned) as context:
        state, permit, cleanup = start_synthetic(module, context)
        path = state.journal._reservation_path(permit.device_id)
        original = path.read_bytes()
        if boundary == "open":
            operation = module.os.open

            def fail_open(target, flags, *args):
                if target == path and flags & module.os.O_RDWR:
                    raise OSError("injected open")
                return operation(target, flags, *args)

            monkeypatch.setattr(module.os, "open", fail_open)
        elif boundary == "readback":
            read = module._original_read

            def fail_read(target, cap):
                value = read(target, cap)
                if target == path and b'"status":"uncertain"' in value:
                    raise OSError("injected readback")
                return value

            monkeypatch.setattr(module, "_original_read", fail_read)
        else:

            def fail(*args):
                raise KeyboardInterrupt("injected interruption")

            monkeypatch.setattr(module.os, boundary, fail)
        result = cleanup.retain_uncertain()
        assert result.status == "retention_unconfirmed"
        assert context.sealed
        assert path.exists()
        assert json.loads(path.read_bytes())["status"] in {"active", "uncertain"}
        assert permit.marker["status"] == "active"
        if boundary in {"open", "write"}:
            assert path.read_bytes() == original
        assert cleanup.retain_uncertain() is result


def test_close_failure_downgrades_result_without_masking_original_exception(synthetic, monkeypatch):
    module = runtime()
    *_, pinned = issue(synthetic)
    cleanup = None
    with pytest.raises(RuntimeError, match="original failure"):
        with module.resolve_fixed_runtime(pinned) as context:
            state, permit, cleanup = start_synthetic(module, context)
            retained = module._CLEANUPS[cleanup]
            path = state.journal._reservation_path(permit.device_id)
            open_file, close_file = module.os.open, module.os.close
            writer = []
            attempts = []

            def track_open(target, flags, *args):
                fd = open_file(target, flags, *args)
                if target == path and flags & module.os.O_RDWR:
                    writer.append(fd)
                return fd

            def close(fd):
                close_file(fd)
                if writer and fd == writer[0]:
                    attempts.append(True)
                    raise OSError("uncertain close outcome")

            monkeypatch.setattr(module.os, "open", track_open)
            monkeypatch.setattr(module.os, "close", close)
            raise RuntimeError("original failure")
    assert len(attempts) == 1
    assert retained.result.status == "retention_unconfirmed"
    assert json.loads(path.read_bytes())["status"] == "uncertain"


def test_original_deadline_cannot_be_renewed_at_bind_or_cleanup(synthetic, monkeypatch):
    module = runtime()
    *_, pinned = issue(synthetic)
    with module.resolve_fixed_runtime(pinned) as context:
        now = [100.0]
        monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
        state = module._CONTEXTS[context]
        job = "33333333-3333-4333-8333-333333333333"
        state.journal._db.execute("INSERT INTO intents VALUES (?, 'start', 1, NULL)", (job,))
        state.journal._db.commit()
        permit = state.journal.reserve_replay(state.session.plan.device_id, job, generation=1)
        for deadline in (100.0, 146.0, float("nan"), True):
            with pytest.raises(ApprovalNotReady):
                module._bind_original_scope(context, deadline=deadline)
        cleanup = module._bind_original_scope(context, deadline=101.0)
        now[0] = 102.0
        path = state.journal._reservation_path(permit.device_id)
        before = path.read_bytes()
        result = cleanup.retain_uncertain()
        assert result.status == "retention_unconfirmed"
        assert path.read_bytes() == before
        now[0] = 100.0
        assert cleanup.retain_uncertain() is result
        assert path.read_bytes() == before


def test_close_overrun_is_not_reported_as_bounded_success(synthetic, monkeypatch):
    module = runtime()
    *_, pinned = issue(synthetic)
    with module.resolve_fixed_runtime(pinned) as context:
        now = [100.0]
        monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
        state, permit, cleanup = start_synthetic(module, context)
        path = state.journal._reservation_path(permit.device_id)
        open_file, close_file = module.os.open, module.os.close
        writer = []

        def track_open(target, flags, *args):
            fd = open_file(target, flags, *args)
            if target == path and flags & module.os.O_RDWR:
                writer.append(fd)
            return fd

        def close(fd):
            close_file(fd)
            if writer and fd == writer[0]:
                now[0] = 103.0

        monkeypatch.setattr(module.os, "open", track_open)
        monkeypatch.setattr(module.os, "close", close)
        assert cleanup.retain_uncertain().status == "retention_unconfirmed"
        assert json.loads(path.read_bytes())["status"] == "uncertain"
