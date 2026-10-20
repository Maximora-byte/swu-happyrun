"""Disposable helper workers. Only these subprocesses inject synthetic namespace paths.

No production resolver, CLI, environment switch, native guard or NTFS check is
changed in product code. All storage operations delegate to the captured native
implementation. No worker can launch a device/manager command.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from .harness import CHILD_SECONDS, MAX_SNAPSHOT_TOTAL_BYTES, _snapshot_digest, delegated_call

HOST = "11111111-1111-4111-8111-111111111111"
INSTANCE = "22222222-2222-4222-8222-222222222222"
PAYLOAD = b"native enrollment QA\nbinary:\x00\x1a\xff\r\n"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def identity(path):
    info = path.stat()
    return [info.st_dev, info.st_ino]


def _send_error(connection, error, *, phase):
    # No raw exception text, environment, command lines, or stack in the report.
    connection.send({"event": "error", "error_type": type(error).__name__, "phase": phase})


def _native_only():
    sys.dont_write_bytecode = True
    if os.name != "nt":
        raise RuntimeError("native_qa_requires_windows")


def canonical_qa_parent(selected, formal):
    """Exclude formal state by native-resolved paths and existing ancestor identities."""
    from swu_happyrun.drivers.mumu.enrollment_authority import _chain

    selected_chain = _chain(selected)  # reject redirects before resolving aliases
    if not stat.S_ISDIR(selected.lstat().st_mode):
        raise ValueError("native_qa_root_invalid")
    nearest = formal
    while True:
        try:
            info = nearest.lstat()
            break
        except FileNotFoundError:
            if nearest == nearest.parent:
                raise ValueError("native_qa_formal_root_unavailable") from None
            nearest = nearest.parent
    formal_chain = _chain(nearest)
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError("native_qa_formal_root_unavailable")
    # On Windows strict resolve uses the filesystem's final path, expanding 8.3
    # spellings. Missing formal descendants are appended only after resolving the
    # nearest existing ancestor. No state is created to make resolution succeed.
    canonical_selected = selected.resolve(strict=True)
    canonical_nearest = nearest.resolve(strict=True)
    canonical_formal = canonical_nearest / formal.relative_to(nearest)
    if (
        canonical_selected.is_relative_to(canonical_formal)
        or canonical_formal.is_relative_to(canonical_selected)
        or selected_chain[-1][1] in {entry[1] for entry in formal_chain}
        or (nearest == formal and formal_chain[-1][1] in {entry[1] for entry in selected_chain})
    ):
        raise ValueError("native_qa_formal_state_forbidden")
    if (
        _chain(canonical_selected)[-1][1] != selected_chain[-1][1]
        or _chain(canonical_nearest)[-1][1] != formal_chain[-1][1]
        or _chain(selected) != selected_chain
        or _chain(nearest) != formal_chain
    ):
        raise ValueError("native_qa_root_changed")
    return canonical_selected


def inject_namespace(bundle):
    _native_only()
    from swu_happyrun.drivers.mumu import enrollment_admission as admission
    from swu_happyrun.drivers.mumu import enrollment_inspection as inspection
    from swu_happyrun.drivers.mumu import enrollment_reviewer as reviewer
    from swu_happyrun.drivers.mumu import enrollment_transaction as transaction

    # Child-process-only discovery isolation. The production Known Folder
    # resolver remains unmodified, and no parent's environment is changed.
    os.environ["LOCALAPPDATA"] = str(bundle["namespace"])
    os.environ["XDG_CONFIG_HOME"] = str(bundle["namespace"])
    os.environ.pop("SWU_HAPPYRUN_HOST_ID_FILE", None)
    inspection._namespace_path = lambda: bundle["host"]
    reviewer.resolve_control_root = lambda: bundle["control"]
    transaction.resolve_control_root = lambda: bundle["control"]
    admission.resolve_control_root = lambda: bundle["control"]


def _private_file(path, raw):
    from swu_happyrun.drivers.mumu import windows_private
    from swu_happyrun.drivers.mumu.enrollment_storage import private_storage
    from swu_happyrun.drivers.mumu.instance_attribution import FileIdentity

    parent_id = FileIdentity.from_stat(path.parent.stat())

    def validate():
        windows_private.verify_directory(path.parent)

    with private_storage(
        path.parent, parent_identity=parent_id, validate_current=validate
    ) as store:
        staged = store.stage(path.name, raw, transaction_id="f" * 64)
        store.publish(staged)


def _existing_database():
    # Synthetic history only. Serialize memory; native storage publishes the
    # fixture with an explicit current-user owner/DACL, even for elevated tokens.
    from swu_happyrun.drivers.mumu.enrollment_transaction import _empty_journal

    database = sqlite3.connect(":memory:", timeout=0)
    try:
        database.deserialize(_empty_journal())
        database.execute(
            "INSERT INTO intents(job_id, action, fence, result) VALUES (?, ?, ?, ?)",
            ("synthetic-historic-job", "start", 7, "confirmed"),
        )
        database.commit()
        return database.serialize()
    finally:
        database.close()


def setup(case_text, name, checkout, connection):
    """Create only new private case paths; reviewer APIs produce all control state."""
    phase = "validate_selected_root"
    try:
        _native_only()
        from swu_happyrun.drivers.identity import device_id
        from swu_happyrun.drivers.mumu import enrollment_reviewer as reviewer
        from swu_happyrun.drivers.mumu import windows_private
        from swu_happyrun.drivers.mumu.enrollment import resolve_control_root
        from swu_happyrun.drivers.mumu.enrollment_admission import _require_local_ntfs
        from swu_happyrun.drivers.mumu.enrollment_inspection import (
            DiscoveryScope,
            inspect_enrollment,
        )
        from swu_happyrun.drivers.mumu.enrollment_review_scope import build_review_scope

        case = Path(case_text)
        selected = case.parent
        if (
            not selected.is_absolute()
            or ".." in selected.parts
            or str(selected).startswith(("//", "\\\\"))
            or selected == Path(selected.anchor)
            or not selected.is_dir()
            or os.path.lexists(case)
        ):
            raise ValueError("native_qa_root_invalid")
        formal = resolve_control_root().parent
        selected = canonical_qa_parent(selected, formal)
        case = selected / case.name
        if os.path.lexists(case):
            raise ValueError("native_qa_root_invalid")
        _require_local_ntfs(selected)
        phase = "provision_new_private_directories"
        windows_private.provision_private_directory(case)
        for relative in (
            "reports",
            "state",
            "state/ns",
            "state/ns/swu-happyrun",
            "state/journal",
            "state/MuMu-0",
            "evidence",
        ):
            windows_private.provision_private_directory(case / relative)
        bundle = {
            "case": case,
            "state": case / "state",
            "namespace": case / "state/ns",
            "host": case / "state/ns/swu-happyrun/host-id",
            "control": case / "state/ns/swu-happyrun/control-v1",
            "journal": case / "state/journal/runs.sqlite",
            "evidence": case / "evidence",
            "manager": case / "state/manager.exe",
            "config": case / "state/MuMu-0/MuMu-0.nemu",
            "existing": name in {"device_contention", "existing_positive"},
        }
        inject_namespace(bundle)
        phase = "publish_synthetic_fixture_files"
        _private_file(bundle["host"], (HOST + "\n").encode("ascii"))
        _private_file(bundle["manager"], b"Synthetic manager bytes, never executable.\n")
        config = f'<Machine uuid="{INSTANCE}" name="MuMu-0"/>\n'.encode()
        _private_file(bundle["config"], config)
        _private_file(bundle["config"].with_suffix(".nemu-prev"), config)
        product = device_id(
            "mumu", f"{os.path.normcase(str(bundle['manager'].resolve()))}:0", host_id=HOST
        )
        bundle["device_id"] = product
        bundle["device_lock"] = bundle["journal"].parent / (
            "device-" + hashlib.sha256(product.encode()).hexdigest() + ".lock"
        )
        bundle["receipt"] = bundle["host"].with_name("mumu-experiment-registration.json")
        if bundle["existing"]:
            _private_file(bundle["journal"], _existing_database())
            _private_file(bundle["device_lock"], b"0")
        tx = hashlib.sha256(case.name.encode()).hexdigest()
        phase = "reviewer_prepare_control_layout"
        layout = reviewer.prepare_control_layout(tx)
        phase = "inspect_synthetic_scope"
        reviewed = build_review_scope(
            inspect_enrollment(
                DiscoveryScope(
                    (bundle["journal"].parent,),
                    (bundle["journal"],) if bundle["existing"] else (),
                    unchecked_categories=(),
                    declared_complete=True,
                ),
                manager=bundle["manager"],
                instance_index="0",
                expected_journal=bundle["journal"] if bundle["existing"] else None,
            ),
            expected_host_id=HOST,
            expected_device_id=product,
            expected_journal=bundle["journal"] if bundle["existing"] else None,
        )
        paths = {
            key: bundle[key]
            for key in ("host", "manager", "config", "journal", "receipt", "device_lock")
        }
        paths["config_previous"] = bundle["config"].with_suffix(".nemu-prev")
        targets = {
            key: {
                "path": str(path),
                "parent_identity": identity(path.parent),
                "identity": identity(path) if path.exists() else None,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()
                if path.exists() and key != "journal"
                else None,
            }
            for key, path in paths.items()
        }
        directories = {
            key: {"path": str(path), "identity": [pin.volume, pin.file_index]}
            for key, path, pin in layout.directories
            if key != "reviews"
        }
        directories["evidence"] = {
            "path": str(bundle["evidence"]),
            "identity": identity(bundle["evidence"]),
        }
        plan = {
            "schema": "approved-plan-v2",
            "epoch": 1,
            "kind": "existing" if bundle["existing"] else "new_enrollment",
            "expires_at": time.time() + 1800,
            "reviewed_scope_sha256": reviewed.sha256,
            "manager_version": "6.8.4.0",
            "host_namespace": HOST,
            "stable_instance": INSTANCE,
            "device_id": product,
            "instance_index": "0",
            "targets": targets,
            "transaction_id": tx,
            "product_commit": checkout["commit"],
            "product_tree": checkout["tree"],
            "directories": directories,
        }
        phase = "reviewer_publish_initial_approval"
        anchors = reviewer.publish_initial_approval(layout, canonical(plan), reviewed)
        bundle.update(layout=layout, reviewed=reviewed, anchors=anchors, transaction_id=tx)
        bundle["summary"] = {
            "synthetic_identity": True,
            "kind": plan["kind"],
            "declared_scope": "synthetic namespace and synthetic journal directory only",
            "reviewer_publication": "completed",
            "approval_plan_sha256": anchors.plan_sha256,
            "reviewed_scope_sha256": reviewed.sha256,
            "existing_acl_modified": False,
            "parent_environment_modified": False,
        }
        connection.send({"event": "setup", "bundle": bundle})
    except BaseException as error:
        _send_error(connection, error, phase=phase)
    finally:
        connection.close()


class Observations:
    """Audit the tested call only, not setup, IPC, snapshots or report writing."""

    def __init__(self, journal):
        self.journal = os.path.normcase(str(journal))
        self.active = False
        self.journal_byte_opens = 0
        self.sqlite_connects = 0
        self.mutation_audit = 0
        self.device_process_attempts = 0
        self.native_events = []
        self.account_lock_attempted = 0
        self.account_lock_acquired = 0
        self.device_lock_attempted = 0
        self.device_lock_acquired = 0
        self.device_lock_errors = 0
        self.locked_byte_read_errors = 0

    def audit(self, event, arguments):
        if not self.active:
            return
        if event == "open":
            path, _, flags = arguments
            if isinstance(path, (str, bytes, os.PathLike)):
                if os.path.normcase(os.fsdecode(path)) == self.journal:
                    self.journal_byte_opens += 1
            if flags & (os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                self.mutation_audit += 1
        elif event == "sqlite3.connect":
            self.sqlite_connects += 1
        elif event in {"os.mkdir", "os.rename", "os.remove", "os.rmdir", "os.link", "os.symlink"}:
            self.mutation_audit += 1
        elif event in {"subprocess.Popen", "os.system", "os.posix_spawn", "os.spawn"}:
            self.device_process_attempts += 1
            raise RuntimeError("native_qa_external_process_forbidden")

    def payload(self):
        return {key: value for key, value in vars(self).items() if key not in {"journal", "active"}}


def instrument_storage(observation, fault=None):
    from swu_happyrun.drivers.mumu import enrollment_storage as storage

    original = storage._NativeIO
    captured = {
        name: getattr(original, name) for name in ("create", "write", "fsync", "flush", "move")
    }

    class DelegatingNativeIO(original):
        # Constructor, ACL checks, path checks, owned-handle readback and closing
        # are inherited unchanged. Every successful boundary is genuinely native.
        def create(self, path):
            return delegated_call(
                "create",
                lambda: captured["create"](self, path),
                observation.native_events,
                fault=fault,
            )

        def write(self, fd, data):
            return delegated_call(
                "write", lambda: captured["write"](fd, data), observation.native_events, fault=fault
            )

        def fsync(self, fd):
            return delegated_call(
                "fsync", lambda: captured["fsync"](fd), observation.native_events, fault=fault
            )

        def flush(self, fd):
            return delegated_call(
                "flush", lambda: captured["flush"](self, fd), observation.native_events, fault=fault
            )

        def move(self, source, destination):
            return delegated_call(
                "move",
                lambda: captured["move"](self, source, destination),
                observation.native_events,
                fault=fault,
            )

    storage._NativeIO = DelegatingNativeIO


def instrument_transaction(bundle, observation, role, connection):
    from swu_happyrun.agent.journal import RunJournal
    from swu_happyrun.drivers.mumu import enrollment_transaction as transaction

    real_account_lock = transaction._existing_lock
    real_device_lock = RunJournal.lock_existing
    real_read = transaction._read

    @contextmanager
    def account_lock(path, expected):
        account = path == bundle["control"] / "admission.lock"
        if account:
            observation.account_lock_attempted += 1
        with real_account_lock(path, expected) as token:
            if account:
                observation.account_lock_acquired += 1
                if role == "winner":
                    connection.send({"event": "account_lock_held"})
                    if not connection.poll(CHILD_SECONDS) or connection.recv() != "release":
                        raise TimeoutError("native_qa_release_deadline")
            yield token

    @contextmanager
    def device_lock(cls, *args, **kwargs):
        observation.device_lock_attempted += 1
        try:
            with real_device_lock(*args, **kwargs) as token:
                observation.device_lock_acquired += 1
                yield token
        except Exception:
            observation.device_lock_errors += 1
            raise

    def read(path, *args, **kwargs):
        try:
            return real_read(path, *args, **kwargs)
        except Exception:
            if path == bundle["device_lock"]:
                observation.locked_byte_read_errors += 1
            raise

    transaction._existing_lock = account_lock
    RunJournal.lock_existing = classmethod(device_lock)
    transaction._read = read


def transaction(bundle, role, connection):
    try:
        inject_namespace(bundle)
        from swu_happyrun.drivers.mumu import enrollment_transaction as coordinator

        observed = Observations(bundle["journal"])
        instrument_storage(observed)
        instrument_transaction(bundle, observed, role, connection)
        sys.addaudithook(observed.audit)
        observed.active = True
        try:
            result = coordinator.initialize_candidate(bundle["anchors"], bundle["reviewed"])
        finally:
            observed.active = False
        data = observed.payload()
        data.update(
            event="transaction",
            status=result.status,
            execution_allowed=result.execution_allowed,
            candidate_present=(
                bundle["control"] / "transactions" / bundle["transaction_id"] / "candidate-v1.json"
            ).exists(),
            boundary="original_device_lock"
            if observed.device_lock_errors and not observed.device_lock_acquired
            else "locked_byte_read"
            if observed.locked_byte_read_errors and not observed.device_lock_acquired
            else "earlier",
            admission_present=(
                bundle["control"] / "admissions" / (bundle["anchors"].plan_sha256 + ".json")
            ).exists(),
            intent_present=(
                bundle["control"]
                / "transactions"
                / bundle["transaction_id"]
                / "enrollment-intent-v1.json"
            ).exists(),
        )
        connection.send(data)
    except BaseException as error:
        _send_error(connection, error, phase="initialize_candidate")
    finally:
        connection.close()


def observe_files(paths, connection):
    """Read retained file evidence in an owned child, never an unbounded parent open."""
    try:
        if len(paths) > 8:
            raise ValueError("native_qa_observation_limit")
        observations, budget = {}, MAX_SNAPSHOT_TOTAL_BYTES
        for role, path in paths.items():
            info = path.lstat()
            digest, count = _snapshot_digest(path, info, budget)
            budget -= count
            observations[role] = {
                "identity": [info.st_dev, info.st_ino],
                "size": count,
                "sha256": digest,
            }
        connection.send({"event": "observations", "observations": observations})
    except BaseException as error:
        _send_error(connection, error, phase="observe_retained_files")
    finally:
        connection.close()


def snapshot_state(root, metadata_only, connection):
    try:
        from .harness import snapshot

        connection.send(
            {"event": "snapshot", "snapshot": snapshot(root, metadata_only=metadata_only)}
        )
    except BaseException as error:
        _send_error(connection, error, phase="snapshot_retained_state")
    finally:
        connection.close()


def hold_device(bundle, connection):
    try:
        inject_namespace(bundle)
        from swu_happyrun.agent.journal import RunJournal

        with RunJournal.lock_existing(bundle["journal"], bundle["device_id"]):
            connection.send({"event": "device_lock_held"})
            if not connection.poll(CHILD_SECONDS) or connection.recv() != "release":
                raise TimeoutError("native_qa_release_deadline")
        connection.send({"event": "released"})
    except BaseException as error:
        _send_error(connection, error, phase="hold_original_device_lock")
    finally:
        connection.close()


def storage_case(bundle, fault, connection):
    try:
        inject_namespace(bundle)
        from swu_happyrun.drivers.mumu import enrollment_reviewer as reviewer
        from swu_happyrun.drivers.mumu.enrollment_admission import _existing_lock
        from swu_happyrun.drivers.mumu.enrollment_storage import StorageIncomplete, private_storage
        from swu_happyrun.drivers.mumu.enrollment_transaction_plan import load_transaction_plan
        from swu_happyrun.drivers.mumu.instance_attribution import FileIdentity

        observed = Observations(bundle["journal"])
        instrument_storage(observed, fault)
        sys.addaudithook(observed.audit)
        destination = bundle["evidence"] / "native-payload.bin"
        stage = destination.with_name(f".{destination.name}.{bundle['transaction_id']}.staged")
        result = {"status": "not_started"}
        with _existing_lock(
            bundle["control"] / "admission.lock", bundle["anchors"].lock_identity
        ) as (fd, _):

            def validate_current():
                reviewer._inspect_control_layout(bundle["layout"], fd)
                load_transaction_plan(bundle["control"], bundle["anchors"], now=time.time())

            observed.active = True
            try:
                with private_storage(
                    destination.parent,
                    parent_identity=FileIdentity.from_stat(destination.parent.stat()),
                    validate_current=validate_current,
                ) as store:
                    staged = store.stage(
                        destination.name, PAYLOAD, transaction_id=bundle["transaction_id"]
                    )
                    result_pin = store.publish(staged)
                    assert result_pin == staged.file
                    result = {"status": "published"}
            except StorageIncomplete as error:
                result = {
                    "status": "incomplete",
                    "phase": error.phase,
                    "uncertain": error.uncertain,
                }
            finally:
                observed.active = False
        retained = []
        for path in (stage, destination):
            if path.exists():
                info = path.lstat()
                digest, count = _snapshot_digest(path, info, MAX_SNAPSHOT_TOTAL_BYTES)
                retained.append({"name": path.name, "size": count, "sha256": digest})
        final = next((item for item in retained if item["name"] == destination.name), None)
        result.update(
            event="storage",
            stage_present=stage.exists(),
            destination_present=destination.exists(),
            destination_matches=final is not None
            and final["size"] == len(PAYLOAD)
            and final["sha256"] == hashlib.sha256(PAYLOAD).hexdigest(),
            retained_files=retained,
            **observed.payload(),
        )
        connection.send(result)
    except BaseException as error:
        _send_error(connection, error, phase="native_storage")
    finally:
        connection.close()


def persist_report(case, raw, connection):
    """Reports use the same native private creation boundary, outside scan roots."""
    try:
        _native_only()
        if len(raw) > 128 * 1024:
            raise ValueError("native_qa_report_limit")
        _private_file(case / "reports" / "result.json", raw)
        connection.send({"event": "report_written"})
    except BaseException as error:
        _send_error(connection, error, phase="persist_private_report")
    finally:
        connection.close()
