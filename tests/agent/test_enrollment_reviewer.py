"""Reviewer-only synthetic provisioning, never formal user state."""

import hashlib
import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from swu_happyrun.drivers.mumu import enrollment_reviewer as reviewer
from swu_happyrun.drivers.mumu.enrollment_authority import FrozenFile
from swu_happyrun.drivers.mumu.instance_attribution import FileIdentity


@pytest.fixture
def layout_backend(tmp_path, monkeypatch):
    root = tmp_path / "control-v1"
    monkeypatch.setattr(reviewer, "resolve_control_root", lambda: root)
    monkeypatch.setattr(reviewer, "_require_local_ntfs", lambda p: None)
    monkeypatch.setattr(
        reviewer.windows_private, "provision_private_directory", lambda p: p.mkdir()
    )

    @contextmanager
    def guard(path, identity=None):
        actual = (path.stat().st_dev, path.stat().st_ino)
        if identity is not None:
            assert identity == actual
        sid = "S-1-5-21-1-2-3-1001"
        api = SimpleNamespace(
            security=lambda _: f"O:{sid}D:P(A;;FA;;;{sid})",
            current_sid=lambda: sid,
            root=path,
            events=[],
            fault=None,
            after=None,
        )
        yield api, sid, actual

    class Store:
        def __init__(self, path, validate):
            self.path, self.validate = path, validate

        @property
        def live_staging_observations(self):
            return ()

        def stage(self, name, payload, transaction_id):
            self.validate()
            path = self.path / ("." + name + "." + transaction_id + ".staged")
            with path.open("xb") as f:
                f.write(payload)
            return SimpleNamespace(
                path=path,
                destination=self.path / name,
                identity=FileIdentity.from_stat(path.stat()),
                sha256=hashlib.sha256(payload).hexdigest(),
            )

        def publish(self, item):
            self.validate()
            import os

            os.link(item.path, item.destination)
            item.path.unlink()
            self.validate()
            return FrozenFile(item.identity, item.sha256)

    @contextmanager
    def storage(path, *, parent_identity, validate_current):
        assert FileIdentity.from_stat(path.stat()) == parent_identity
        yield Store(path, validate_current)

    monkeypatch.setattr(reviewer.windows_private, "verified_directory", guard)
    monkeypatch.setattr(reviewer, "private_storage", storage)
    return root


def test_prepare_layout_only_has_no_approval_or_instance_state(layout_backend):
    root = layout_backend
    result = reviewer.prepare_control_layout("a" * 64)
    assert result.root == root
    assert (root / "admission.lock").read_bytes() == b"0"
    value = json.loads((root / "review-layout-v1.json").read_bytes())
    assert value["transaction_id"] == "a" * 64
    assert set(value["directories"]) == {"reviews", "admissions", "transactions", "transaction"}
    assert not (root / "authority-v1.json").exists()
    assert not list((root / "reviews").iterdir())
    assert not list((root / "admissions").iterdir())
    assert not list((root / "transactions" / ("a" * 64)).iterdir())
    assert reviewer.inspect_control_layout(result) == result


def test_repeat_prepare_does_not_repair_or_overwrite(layout_backend):
    root = layout_backend
    reviewer.prepare_control_layout("a" * 64)
    before = {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    with pytest.raises(reviewer.ReviewProvisionIncomplete):
        reviewer.prepare_control_layout("a" * 64)
    assert {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_partial_prepare_stays_incomplete(layout_backend, monkeypatch):
    root = layout_backend
    real = reviewer.windows_private.provision_private_directory

    def fail(path):
        if path.name == "admissions":
            raise OSError("private path")
        real(path)

    monkeypatch.setattr(reviewer.windows_private, "provision_private_directory", fail)
    with pytest.raises(reviewer.ReviewProvisionIncomplete) as error:
        reviewer.prepare_control_layout("a" * 64)
    assert str(error.value) == "review_provision_incomplete"
    assert root.is_dir()
    assert not (root / "authority-v1.json").exists()
    with pytest.raises(reviewer.ReviewProvisionIncomplete):
        reviewer.prepare_control_layout("a" * 64)


def test_layout_replacement_fails_readonly_inspection(layout_backend):
    result = reviewer.prepare_control_layout("a" * 64)
    record = result.root / "review-layout-v1.json"
    data = record.read_bytes()
    record.rename(record.with_suffix(".old"))
    record.write_bytes(data)
    with pytest.raises(reviewer.ReviewProvisionIncomplete):
        reviewer.inspect_control_layout(result)


def test_unsupported_native_platform_creates_nothing(tmp_path, monkeypatch):
    import os

    if os.name == "nt":
        pytest.skip("native Windows handled by mechanism acceptance")
    root = tmp_path / "control-v1"
    monkeypatch.setattr(reviewer, "resolve_control_root", lambda: root)
    with pytest.raises(reviewer.ReviewProvisionIncomplete):
        reviewer.prepare_control_layout("a" * 64)
    assert not root.exists()


def review_payload(layout_backend, tmp_path, monkeypatch):
    from pathlib import Path

    from test_enrollment_transaction_plan import bundle

    from swu_happyrun.drivers.mumu.enrollment_inspection import DiscoveryScope, inspect_enrollment
    from swu_happyrun.drivers.mumu.enrollment_review_scope import build_review_scope

    template = tmp_path / "template"
    template.mkdir()
    _, _, plan = bundle(template)
    layout = reviewer.prepare_control_layout(plan["transaction_id"])
    host = Path(plan["targets"]["host"]["path"])
    manager = Path(plan["targets"]["manager"]["path"])
    journal = Path(plan["targets"]["journal"]["path"])
    monkeypatch.setenv("SWU_HAPPYRUN_HOST_ID_FILE", str(host))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "missing-config"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "missing-appdata"))
    scope = DiscoveryScope(roots=(journal.parent,), unchecked_categories=(), declared_complete=True)
    inspection = inspect_enrollment(scope, manager=manager, instance_index="0")
    reviewed = build_review_scope(
        inspection, expected_host_id=plan["host_namespace"], expected_device_id=plan["device_id"]
    )
    plan["reviewed_scope_sha256"] = reviewed.sha256
    for name, path, identity in layout.directories:
        if name != "reviews":
            plan["directories"][name] = {
                "path": str(path),
                "identity": [identity.volume, identity.file_index],
            }
    monkeypatch.setattr("time.time", lambda: 10)
    return layout, plan, reviewed


def test_reviewer_seals_plan_then_authority_without_instance_writes(
    layout_backend, tmp_path, monkeypatch
):
    from pathlib import Path

    from swu_happyrun.drivers.mumu.enrollment_transaction_plan import load_transaction_plan

    layout, plan, reviewed = review_payload(layout_backend, tmp_path, monkeypatch)
    anchors = reviewer.publish_initial_approval(layout, json.dumps(plan).encode(), reviewed)
    actual = load_transaction_plan(layout.root, anchors, now=10)
    assert actual.execution_allowed is False
    assert actual.plan_sha256 == anchors.plan_sha256
    folder = layout.root / "reviews" / anchors.plan_sha256
    assert (folder / "reviewed-scope-v1.json").read_bytes() == reviewed.canonical_bytes
    assert not (folder / "review-pin-v1.json").exists()
    for name in ("journal", "receipt", "device_lock"):
        assert not Path(plan["targets"][name]["path"]).exists()
    before = {p: p.read_bytes() for p in layout.root.rglob("*") if p.is_file()}
    with pytest.raises(reviewer.ReviewProvisionIncomplete):
        reviewer.publish_initial_approval(layout, json.dumps(plan).encode(), reviewed)
    assert {p: p.read_bytes() for p in layout.root.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize(
    "cause", ["expired", "foreign_journal", "wrong_scope", "existing_authority"]
)
def test_approval_preflight_failure_has_no_publication(
    layout_backend, tmp_path, monkeypatch, cause
):
    from pathlib import Path

    layout, plan, reviewed = review_payload(layout_backend, tmp_path, monkeypatch)
    if cause == "expired":
        monkeypatch.setattr("time.time", lambda: 1001)
    elif cause == "foreign_journal":
        Path(plan["targets"]["journal"]["path"]).write_bytes(b"unexpected")
    elif cause == "wrong_scope":
        plan["reviewed_scope_sha256"] = "0" * 64
    else:
        (layout.root / "authority-v1.json").write_bytes(b"foreign")
    before = {p: p.read_bytes() for p in layout.root.rglob("*") if p.is_file()}
    with pytest.raises(reviewer.ReviewProvisionIncomplete):
        reviewer.publish_initial_approval(layout, json.dumps(plan).encode(), reviewed)
    assert {p: p.read_bytes() for p in layout.root.rglob("*") if p.is_file()} == before
    assert not list((layout.root / "reviews").iterdir())


def test_account_locked_byte_is_not_reread_through_second_handle(
    layout_backend, tmp_path, monkeypatch
):
    from swu_happyrun.drivers.mumu import enrollment_admission

    layout, plan, reviewed = review_payload(layout_backend, tmp_path, monkeypatch)
    original_lock = enrollment_admission._existing_lock
    original_read = reviewer._read
    held = []

    @contextmanager
    def locked(*args, **kwargs):
        with original_lock(*args, **kwargs) as value:
            held.append(True)
            try:
                yield value
            finally:
                held.pop()

    def read(path, *args, **kwargs):
        if held and path == layout.root / "admission.lock":
            pytest.fail("Windows locked-byte second handle read")
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(enrollment_admission, "_existing_lock", locked)
    monkeypatch.setattr(reviewer, "_read", read)
    assert reviewer.publish_initial_approval(layout, json.dumps(plan).encode(), reviewed)


def test_approval_loss_after_staging_retains_partial_without_authority(
    layout_backend, tmp_path, monkeypatch
):
    layout, plan, reviewed = review_payload(layout_backend, tmp_path, monkeypatch)
    original = reviewer.private_storage

    @contextmanager
    def expire_after_stage(*args, **kwargs):
        with original(*args, **kwargs) as storage:
            stage = storage.stage

            def expire(*a, **k):
                result = stage(*a, **k)
                monkeypatch.setattr("time.time", lambda: 1001)
                return result

            storage.stage = expire
            yield storage

    monkeypatch.setattr(reviewer, "private_storage", expire_after_stage)
    with pytest.raises(reviewer.ReviewProvisionIncomplete):
        reviewer.publish_initial_approval(layout, json.dumps(plan).encode(), reviewed)
    assert not (layout.root / "authority-v1.json").exists()
    assert list((layout.root / "reviews").rglob("*.staged"))


def test_expiry_during_scope_refresh_prevents_review_directory_create(
    layout_backend, tmp_path, monkeypatch
):
    from swu_happyrun.drivers.mumu import enrollment_inspection

    layout, plan, reviewed = review_payload(layout_backend, tmp_path, monkeypatch)
    original = enrollment_inspection.inspect_enrollment

    def expires(*args, **kwargs):
        result = original(*args, **kwargs)
        monkeypatch.setattr("time.time", lambda: 1001)
        return result

    monkeypatch.setattr(enrollment_inspection, "inspect_enrollment", expires)
    with pytest.raises(reviewer.ReviewProvisionIncomplete):
        reviewer.publish_initial_approval(layout, json.dumps(plan).encode(), reviewed)
    assert not list((layout.root / "reviews").iterdir())


def test_unreviewed_journal_parent_cannot_receive_approval(layout_backend, tmp_path, monkeypatch):
    from pathlib import Path

    layout, plan, reviewed = review_payload(layout_backend, tmp_path, monkeypatch)
    foreign = tmp_path / "unreviewed-parent"
    foreign.mkdir()
    (foreign / "historic.sqlite").write_bytes(b"unreviewed history")
    for role in ("journal", "device_lock"):
        target = plan["targets"][role]
        target["path"] = str(foreign / Path(target["path"]).name)
        target["parent_identity"] = [foreign.stat().st_dev, foreign.stat().st_ino]
    with pytest.raises(reviewer.ReviewProvisionIncomplete):
        reviewer.publish_initial_approval(layout, json.dumps(plan).encode(), reviewed)
    assert not (layout.root / "authority-v1.json").exists()
    assert not list((layout.root / "reviews").iterdir())


def test_orphan_transaction_directory_blocks_approval(layout_backend, tmp_path, monkeypatch):
    layout, plan, reviewed = review_payload(layout_backend, tmp_path, monkeypatch)
    orphan = layout.root / "transactions" / ("f" * 64)
    orphan.mkdir()
    (orphan / "stage-01.json").write_bytes(b"foreign")
    with pytest.raises(reviewer.ReviewProvisionIncomplete):
        reviewer.publish_initial_approval(layout, json.dumps(plan).encode(), reviewed)
    assert not (layout.root / "authority-v1.json").exists()


def test_late_foreign_admission_blocks_approval(layout_backend, tmp_path, monkeypatch):
    layout, plan, reviewed = review_payload(layout_backend, tmp_path, monkeypatch)
    original = reviewer.private_storage
    injected = []

    @contextmanager
    def inject(*args, **kwargs):
        with original(*args, **kwargs) as storage:
            publish = storage.publish

            def late(item):
                result = publish(item)
                if not injected:
                    (layout.root / "admissions" / ("f" * 64 + ".json")).write_bytes(b"foreign")
                    injected.append(True)
                return result

            storage.publish = late
            yield storage

    monkeypatch.setattr(reviewer, "private_storage", inject)
    with pytest.raises(reviewer.ReviewProvisionIncomplete):
        reviewer.publish_initial_approval(layout, json.dumps(plan).encode(), reviewed)
    assert not (layout.root / "authority-v1.json").exists()


def test_late_foreign_history_blocks_approval(layout_backend, tmp_path, monkeypatch):
    from pathlib import Path

    layout, plan, reviewed = review_payload(layout_backend, tmp_path, monkeypatch)
    original = reviewer.private_storage
    injected = []

    @contextmanager
    def inject(*args, **kwargs):
        with original(*args, **kwargs) as storage:
            publish = storage.publish

            def late(item):
                result = publish(item)
                if not injected:
                    (Path(plan["targets"]["journal"]["path"]).parent / "foreign.db").write_bytes(
                        b"foreign"
                    )
                    injected.append(True)
                return result

            storage.publish = late
            yield storage

    monkeypatch.setattr(reviewer, "private_storage", inject)
    with pytest.raises(reviewer.ReviewProvisionIncomplete):
        reviewer.publish_initial_approval(layout, json.dumps(plan).encode(), reviewed)
    assert not (layout.root / "authority-v1.json").exists()


def test_control_inside_default_reviewed_root_accounts_only_owned_additions(
    layout_backend, tmp_path, monkeypatch
):
    import os

    default = (
        tmp_path / ("missing-appdata" if os.name == "nt" else "missing-config") / "swu-happyrun"
    )
    default.mkdir(parents=True)
    root = default / "control-v1"
    monkeypatch.setattr(reviewer, "resolve_control_root", lambda: root)
    layout, plan, reviewed = review_payload(root, tmp_path, monkeypatch)
    assert any(item.path == str(default) for item in reviewed.inspection.roots)
    anchors = reviewer.publish_initial_approval(layout, json.dumps(plan).encode(), reviewed)
    assert anchors.plan_sha256
    assert (root / "authority-v1.json").exists()


def test_nested_scope_with_real_storage_live_stage_protocol(layout_backend, tmp_path, monkeypatch):
    """Real storage orchestration, synthetic native I/O only; no Windows claim."""
    import os

    from test_enrollment_storage import SyntheticIO

    from swu_happyrun.drivers.mumu import enrollment_storage

    monkeypatch.setattr(enrollment_storage, "_NativeIO", SyntheticIO)
    monkeypatch.setattr(enrollment_storage, "_require_local_ntfs", lambda _: None)
    monkeypatch.setattr(reviewer, "private_storage", enrollment_storage.private_storage)
    default = (
        tmp_path / ("missing-appdata" if os.name == "nt" else "missing-config") / "swu-happyrun"
    )
    default.mkdir(parents=True)
    root = default / "control-v1"
    monkeypatch.setattr(reviewer, "resolve_control_root", lambda: root)
    layout, plan, reviewed = review_payload(root, tmp_path, monkeypatch)
    anchors = reviewer.publish_initial_approval(layout, json.dumps(plan).encode(), reviewed)
    assert anchors.plan_sha256
    assert (root / "authority-v1.json").exists()
    assert not list(root.rglob("*.staged"))
