"""Independent reviewer-only control provisioning, never an initializer import.

Preparing a layout does not approve an instance. Approval publication and returned
pins must be independently reviewed in a fixed runner; no runner or ReviewPin is
silently issued. These explicit Windows writes require the original reviewer's
operation-specific authorization; ordinary inspection never calls this module.
"""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

from . import windows_private
from .enrollment import resolve_control_root
from .enrollment_admission import _require_local_ntfs
from .enrollment_authority import FrozenFile, _chain, _digest, _read
from .enrollment_storage import private_storage
from .instance_attribution import FileIdentity


class ReviewProvisionIncomplete(RuntimeError):
    def __init__(self):
        super().__init__("review_provision_incomplete")


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _id_value(identity):
    if type(identity) is not FileIdentity or identity.domain != "python_stat":
        raise ReviewProvisionIncomplete()
    return [identity.volume, identity.file_index]


@dataclass(frozen=True, repr=False)
class ReviewerLayout:
    root: Path
    transaction_id: str
    root_identity: FileIdentity
    lock: FrozenFile
    record: FrozenFile
    directories: tuple[tuple[str, Path, FileIdentity], ...]


def _layout_paths(root, transaction_id):
    _digest(transaction_id)
    return {
        "reviews": root / "reviews",
        "admissions": root / "admissions",
        "transactions": root / "transactions",
        "transaction": root / "transactions" / transaction_id,
    }


def _check_directories(root, root_identity, directories):
    if _chain(root)[-1][1] != root_identity:
        raise ReviewProvisionIncomplete()
    for _, path, identity in directories:
        if _chain(path)[-1][1] != identity or not path.is_dir():
            raise ReviewProvisionIncomplete()


def _names(directory):
    result = set()
    with os.scandir(directory) as items:
        for item in items:
            if len(result) >= 32:
                raise ReviewProvisionIncomplete()
            result.add(item.name)
    return result


def _layout_payload(root_identity, transaction_id, lock, directories):
    return {
        "schema": "review-layout-v1",
        "transaction_id": transaction_id,
        "root_identity": _id_value(root_identity),
        "lock": {"identity": _id_value(lock.identity), "sha256": lock.sha256},
        "directories": {
            name: {"path": str(path), "identity": _id_value(identity)}
            for name, path, identity in directories
        },
    }


def prepare_control_layout(transaction_id: str) -> ReviewerLayout:
    """Create one initial layout exclusively; an existing/partial root is refused.

    No authority/approved-plan/journal/receipt is written. All failures retain
    attempted artifacts for independent diagnosis, never automatic repair.
    """
    try:
        _digest(transaction_id)
        root = resolve_control_root()
        _require_local_ntfs(root.parent)
        if os.path.lexists(root):
            raise ReviewProvisionIncomplete()
        windows_private.provision_private_directory(root)
        with ExitStack() as guards:
            api, sid, raw_root = guards.enter_context(windows_private.verified_directory(root))
            root_identity = FileIdentity("python_stat", *raw_root)
            directories = []
            for name, path in _layout_paths(root, transaction_id).items():
                windows_private.provision_private_directory(path)
                _, _, raw_identity = guards.enter_context(windows_private.verified_directory(path))
                directories.append((name, path, FileIdentity("python_stat", *raw_identity)))
            directories = tuple(directories)
            pending = {}
            required = set()

            def validate_current():
                _check_directories(root, root_identity, directories)
                for path in [root, *(p for _, p, _ in directories)]:
                    windows_private.validate_sddl(api.security(path), sid, protected=True)
                for path, pin in pending.items():
                    if os.path.lexists(path):
                        windows_private.validate_sddl(api.security(path), sid, protected=True)
                        _read(path, pin)
                        windows_private.validate_sddl(api.security(path), sid, protected=True)
                    elif path in required:
                        raise ReviewProvisionIncomplete()

            def publish(name, payload):
                with private_storage(
                    root, parent_identity=root_identity, validate_current=validate_current
                ) as storage:
                    staged = storage.stage(name, payload, transaction_id=transaction_id)
                    pending[staged.destination] = FrozenFile(staged.identity, staged.sha256)
                    pin = storage.publish(staged)
                    required.add(staged.destination)
                    validate_current()
                    return pin

            lock = publish("admission.lock", b"0")
            payload = _layout_payload(root_identity, transaction_id, lock, directories)
            record = publish("review-layout-v1.json", _canonical(payload))
            return ReviewerLayout(root, transaction_id, root_identity, lock, record, directories)
    except ReviewProvisionIncomplete:
        raise
    except Exception:
        raise ReviewProvisionIncomplete() from None


def inspect_control_layout(layout: ReviewerLayout) -> ReviewerLayout:
    """Read existing exact reviewer layout, without creating, repairing or approving."""
    return _inspect_control_layout(layout)


def _inspect_control_layout(layout, lock_fd=None):
    try:
        if type(layout) is not ReviewerLayout or layout.root != resolve_control_root():
            raise ReviewProvisionIncomplete()
        expected = _layout_paths(layout.root, layout.transaction_id)
        if {name: path for name, path, _ in layout.directories} != expected:
            raise ReviewProvisionIncomplete()
        _require_local_ntfs(layout.root)
        with ExitStack() as guards:
            api, sid, _ = guards.enter_context(
                windows_private.verified_directory(
                    layout.root, tuple(_id_value(layout.root_identity))
                )
            )

            def validate_files():
                for path in (layout.root / "admission.lock", layout.root / "review-layout-v1.json"):
                    windows_private.validate_sddl(api.security(path), sid, protected=True)

            validate_files()
            for _, path, identity in layout.directories:
                guards.enter_context(
                    windows_private.verified_directory(path, tuple(_id_value(identity)))
                )
            _check_directories(layout.root, layout.root_identity, layout.directories)
            if _names(layout.root / "transactions") != {layout.transaction_id}:
                raise ReviewProvisionIncomplete()
            if lock_fd is None:
                if _read(layout.root / "admission.lock", layout.lock) != b"0":
                    raise ReviewProvisionIncomplete()
            else:
                info = os.fstat(lock_fd)
                if (
                    FileIdentity.from_stat(info) != layout.lock.identity
                    or _chain(layout.root / "admission.lock")[-1][1] != layout.lock.identity
                    or info.st_size != 1
                ):
                    raise ReviewProvisionIncomplete()
            raw = _read(layout.root / "review-layout-v1.json", layout.record)
            expected_payload = _layout_payload(
                layout.root_identity, layout.transaction_id, layout.lock, layout.directories
            )
            if raw != _canonical(expected_payload):
                raise ReviewProvisionIncomplete()
            validate_files()
            return layout
    except ReviewProvisionIncomplete:
        raise
    except Exception:
        raise ReviewProvisionIncomplete() from None


def publish_initial_approval(layout: ReviewerLayout, raw_plan: bytes, reviewed_scope):
    """Reviewer-only initial approval; never replace authority or emit ReviewPin.

    Returns anchors for independent inspection and embedding in a separately
    reviewed immutable runner. The returned object itself is not runtime approval.
    All target parents already exist. No journal, receipt or device lock is created.
    """
    import time

    from .enrollment_admission import _existing_lock
    from .enrollment_authority import RunnerAnchors
    from .enrollment_inspection import inspect_enrollment
    from .enrollment_phase_scope import require_phase_scope
    from .enrollment_review_scope import (
        MAX_REVIEW_SCOPE_BYTES,
        load_review_scope,
        require_matching_reinspection,
    )
    from .enrollment_transaction_plan import parse_plan_payload, validate_frozen_inputs

    try:
        inspect_control_layout(layout)
        root = layout.root
        plan = parse_plan_payload(root, raw_plan)
        if plan.transaction_id != layout.transaction_id:
            raise ReviewProvisionIncomplete()
        selected = {item.name: item for item in plan.targets}
        known_dirs = {name: (path, identity) for name, path, identity in layout.directories}
        for name, path, identity in plan.directories:
            if name != "evidence" and known_dirs.get(name) != (path, identity):
                raise ReviewProvisionIncomplete()
        reviewed = load_review_scope(
            reviewed_scope.canonical_bytes,
            expected_sha256=plan.reviewed_scope_sha256,
            expected_host_id=plan.host_namespace,
            expected_device_id=plan.device_id,
            expected_journal=selected["journal"].path if plan.kind == "existing" else None,
        )
        sources = reviewed.inspection.identity_sources
        if (
            sources["host_path"] != str(selected["host"].path)
            or sources["manager_path"] != str(selected["manager"].path)
            or tuple(sources["host_identity"]) != tuple(_id_value(selected["host"].identity))
            or tuple(sources["manager_identity"]) != tuple(_id_value(selected["manager"].identity))
        ):
            raise ReviewProvisionIncomplete()
        if reviewed.kind != plan.kind:
            raise ReviewProvisionIncomplete()
        parent = selected["journal"].path.parent
        parent_id = tuple(_id_value(selected["journal"].parent_identity))
        if not any(
            root.path == str(parent)
            and root.identity_domain == "python_stat"
            and root.identity == parent_id
            and not root.missing
            and not root.errors
            and not root.exclusions
            for root in reviewed.inspection.roots
        ):
            raise ReviewProvisionIncomplete()
        digest = hashlib.sha256(raw_plan).hexdigest()
        folder = root / "reviews" / digest
        pending = {}
        required = set()
        lock_fd = None
        root_api = root_sid = None
        review_folder_created = False
        folder_identity = None
        active_storage = None
        staged_paths = {}

        def initial_targets():
            for role in ("journal", "device_lock", "receipt"):
                item = selected[role]
                if item.identity is None:
                    if os.path.lexists(item.path):
                        raise ReviewProvisionIncomplete()
                else:
                    if _chain(item.path)[-1][1] != item.identity or not item.path.is_file():
                        raise ReviewProvisionIncomplete()
                    if item.sha256 is not None:
                        _read(item.path, FrozenFile(item.identity, item.sha256))
            for path in (
                selected["journal"].path.parent / "enrollment-v1.json",
                root / "admissions" / (digest + ".json"),
            ):
                if os.path.lexists(path):
                    raise ReviewProvisionIncomplete()

        def validate_current():
            _inspect_control_layout(layout, lock_fd)
            if time.time() >= plan.expires_at:
                raise ReviewProvisionIncomplete()
            validate_frozen_inputs(plan)
            initial_targets()
            if _names(root / "admissions") or _names(root / "transactions" / layout.transaction_id):
                raise ReviewProvisionIncomplete()
            if _names(root / "reviews") != ({digest} if review_folder_created else set()):
                raise ReviewProvisionIncomplete()
            for path, pin in pending.items():
                if os.path.lexists(path):
                    windows_private.validate_sddl(root_api.security(path), root_sid, protected=True)
                    _read(
                        path,
                        pin,
                        cap=MAX_REVIEW_SCOPE_BYTES
                        if path.name == "reviewed-scope-v1.json"
                        else 65536,
                    )
                    windows_private.validate_sddl(root_api.security(path), root_sid, protected=True)
                elif path in required:
                    raise ReviewProvisionIncomplete()
            additions = {}
            if review_folder_created:
                additions[folder] = (folder_identity, True)
            for path, pin in pending.items():
                if os.path.lexists(path):
                    additions[path] = (pin.identity, False)
            for path, identity in staged_paths.items():
                if os.path.lexists(path):
                    additions[path] = (identity, False)
            live_staging = (
                active_storage.live_staging_observations if active_storage is not None else ()
            )
            if live_staging:
                for observation in live_staging:
                    additions[observation.path] = (observation.identity, False)
            current = inspect_enrollment(
                reviewed.inspection.scope,
                manager=selected["manager"].path,
                instance_index=plan.instance_index,
                expected_journal=selected["journal"].path if plan.kind == "existing" else None,
                _live_staging=live_staging,
            )
            require_phase_scope(reviewed, current, additions, live_staging=live_staging)
            if time.time() >= plan.expires_at:
                raise ReviewProvisionIncomplete()
            authority = root / "authority-v1.json"
            if authority not in pending and os.path.lexists(authority):
                raise ReviewProvisionIncomplete()

        with ExitStack() as guards:
            for path, identity in [
                (root, layout.root_identity),
                *((p, i) for _, p, i in layout.directories),
                (plan.evidence_root, plan.evidence_identity),
            ]:
                context = guards.enter_context(
                    windows_private.verified_directory(path, tuple(_id_value(identity)))
                )
                if path == root:
                    root_api, root_sid, _ = context
            with _existing_lock(root / "admission.lock", layout.lock.identity) as (lock_fd, _):
                validate_current()
                if _names(root / "admissions") or _names(
                    root / "transactions" / layout.transaction_id
                ):
                    raise ReviewProvisionIncomplete()
                if _names(root / "reviews"):
                    raise ReviewProvisionIncomplete()
                fresh = inspect_enrollment(
                    reviewed.inspection.scope,
                    manager=selected["manager"].path,
                    instance_index=plan.instance_index,
                    expected_journal=selected["journal"].path if plan.kind == "existing" else None,
                )
                require_matching_reinspection(reviewed, fresh)
                validate_current()
                windows_private.provision_private_directory(folder)
                review_folder_created = True
                _, _, folder_raw_id = guards.enter_context(
                    windows_private.verified_directory(folder)
                )
                folder_identity = FileIdentity("python_stat", *folder_raw_id)

                def publish(parent, parent_identity, name, payload):
                    nonlocal active_storage
                    with private_storage(
                        parent, parent_identity=parent_identity, validate_current=validate_current
                    ) as storage:
                        active_storage = storage
                        staged = storage.stage(name, payload, transaction_id=layout.transaction_id)
                        staged_paths[staged.path] = staged.identity
                        pending[staged.destination] = FrozenFile(staged.identity, staged.sha256)
                        result = storage.publish(staged)
                        required.add(staged.destination)
                        validate_current()
                        active_storage = None
                        return result

                publish(folder, folder_identity, "reviewed-scope-v1.json", reviewed.canonical_bytes)
                plan_pin = publish(folder, folder_identity, "approved-plan-v2.json", raw_plan)
                authority_pin = publish(
                    root,
                    layout.root_identity,
                    "authority-v1.json",
                    _canonical(
                        {
                            "schema": "authority-v1",
                            "epoch": plan.epoch,
                            "approved_plan_sha256": digest,
                            "revoked_plan_sha256": [],
                        }
                    ),
                )
                return RunnerAnchors(
                    layout.root_identity,
                    layout.lock.identity,
                    authority_pin,
                    digest,
                    plan_pin,
                    folder_identity,
                )
    except ReviewProvisionIncomplete:
        raise
    except Exception:
        raise ReviewProvisionIncomplete() from None
