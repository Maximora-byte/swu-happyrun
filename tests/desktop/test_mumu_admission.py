import json
from uuid import uuid4

import pytest

from swu_happyrun.desktop.mumu_admission import (
    host_namespace,
    remember_legacy_roots,
    require_clean_legacy_scope,
)
from swu_happyrun.drivers.command import ProbeError


@pytest.mark.parametrize(
    "name",
    [
        "replay-same-device.json",
        "device-same-device.lock",
        "agent.sqlite",
        "mumu-experiment-registration.json",
        "control-v1",
    ],
)
def test_legacy_unknown_or_unresolved_state_blocks_without_opening_database(tmp_path, name):
    legacy = tmp_path / "old"
    legacy.mkdir()
    (legacy / name).write_bytes(b"unknown")
    before = (legacy / name).read_bytes()
    with pytest.raises(ProbeError, match="legacy_runtime_requires_review"):
        require_clean_legacy_scope([legacy], current_root=tmp_path / "new")
    assert (legacy / name).read_bytes() == before


def test_current_canonical_journal_is_checked_by_its_own_reservation(tmp_path):
    current = tmp_path / "new"
    current.mkdir()
    (current / "journal.sqlite").write_bytes(b"fixture")
    require_clean_legacy_scope([current], current_root=current)


def test_fixture_subdirectories_are_outside_documented_direct_scope(tmp_path):
    (tmp_path / "unit-fixtures").mkdir()
    (tmp_path / "unit-fixtures" / "agent.sqlite").write_bytes(b"fixture")
    require_clean_legacy_scope([tmp_path], current_root=tmp_path / "new")


def test_configured_namespace_is_not_silently_rotated(tmp_path, monkeypatch):
    import swu_happyrun.desktop.mumu_admission as admission
    import swu_happyrun.drivers.mumu.enrollment as enrollment

    default = tmp_path / "swu-happyrun" / "host-id"
    default.parent.mkdir()
    default.write_text("129810e6-39c3-4dda-b076-43040b8565f5", encoding="ascii")
    override = tmp_path / "custom-id"
    override.write_text("6712fa66-956f-41ce-a13d-aa534a9a397e", encoding="ascii")
    monkeypatch.setenv("SWU_HAPPYRUN_HOST_ID_FILE", str(override))
    monkeypatch.setattr(enrollment, "_local_app_data", lambda: tmp_path)
    monkeypatch.setattr(admission, "_namespace_path", lambda: override)
    if admission.os.name != "nt":
        pytest.skip("Windows known-folder namespace policy")
    with pytest.raises(ProbeError, match="host_namespace_conflict"):
        host_namespace()
    assert default.read_text() != override.read_text()


def test_corrupt_configured_namespace_remains_unchanged(tmp_path, monkeypatch):
    import swu_happyrun.desktop.mumu_admission as admission

    override = tmp_path / "custom-id"
    override.write_text("broken", encoding="ascii")
    monkeypatch.setenv("SWU_HAPPYRUN_HOST_ID_FILE", str(override))
    monkeypatch.setattr(admission, "_namespace_path", lambda: override)
    with pytest.raises(ProbeError):
        host_namespace()
    assert override.read_text() == "broken"


def test_installation_change_keeps_prior_default_journal_roots(tmp_path):
    current = tmp_path / "current"
    current.mkdir()
    old = tmp_path / "old-source" / "local"
    new = tmp_path / "installed" / "local"
    remember_legacy_roots(current, [old])
    assert set(remember_legacy_roots(current, [new])) == {old, new}
    old.mkdir(parents=True)
    (old / "agent.sqlite").write_bytes(b"unresolved")
    with pytest.raises(ProbeError, match="legacy_runtime_requires_review"):
        require_clean_legacy_scope(remember_legacy_roots(current, [new]), current_root=current)


def test_corrupt_admission_scope_is_not_replaced(tmp_path):
    path = tmp_path / "legacy-roots.json"
    path.write_text("broken")
    with pytest.raises(ProbeError, match="legacy_scope_unavailable"):
        remember_legacy_roots(tmp_path, [])
    assert path.read_text() == "broken"


@pytest.fixture
def binding_scope(tmp_path, monkeypatch):
    import swu_happyrun.desktop.mumu_admission as admission
    import swu_happyrun.drivers.mumu.enrollment as enrollment

    root = tmp_path / "canonical"
    root.mkdir()
    manager = tmp_path / "MuMuManager.exe"
    manager.write_bytes(b"synthetic executable; never executed")
    default = tmp_path / "swu-happyrun" / "host-id"
    selected = [default]
    monkeypatch.delenv("SWU_HAPPYRUN_HOST_ID_FILE", raising=False)
    monkeypatch.setattr(enrollment, "_local_app_data", lambda: tmp_path)
    monkeypatch.setattr(admission, "_namespace_path", lambda: selected[0])
    return admission, root, manager, default, selected


def stopped_marker(root, *, digest="a" * 64, **updates):
    value = dict(
        schema=1,
        owner="local_virtual_replay",
        device_digest=digest,
        session_id=str(uuid4()),
        status="stopped",
        generation=3,
        probe_pending=False,
    )
    value.update(updates)
    path = root / f"replay-{digest}.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_first_override_pin_cannot_rotate_namespace_around_nonstopped_reservation(
    binding_scope, monkeypatch, tmp_path
):
    admission, root, manager, default, selected = binding_scope
    first = tmp_path / "override-a"
    first.write_text(str(uuid4()), encoding="ascii")
    selected[0] = first
    monkeypatch.setenv("SWU_HAPPYRUN_HOST_ID_FILE", str(first))
    namespace, source = admission.pinned_host_namespace(root, manager)
    assert namespace == first.read_text()
    assert source == first
    assert not default.exists()
    before = (root / "host-binding.json").read_bytes()
    stopped_marker(root, status="active")
    second = tmp_path / "override-b"
    second.write_text(str(uuid4()), encoding="ascii")
    selected[0] = second
    monkeypatch.setenv("SWU_HAPPYRUN_HOST_ID_FILE", str(second))
    with pytest.raises(ProbeError, match="host_binding_changed"):
        admission.pinned_host_namespace(root, manager)
    assert (root / "host-binding.json").read_bytes() == before
    assert not default.exists()


def test_deleted_pinned_default_identity_is_never_recreated(binding_scope):
    admission, root, manager, default, _ = binding_scope
    admission.pinned_host_namespace(root, manager)
    default.unlink()
    with pytest.raises(ProbeError, match="host_identity_unavailable"):
        admission.pinned_host_namespace(root, manager)
    assert not default.exists()


def test_changed_manager_path_cannot_rebind_existing_pin(binding_scope, tmp_path):
    admission, root, manager, _, _ = binding_scope
    admission.pinned_host_namespace(root, manager)
    before = (root / "host-binding.json").read_bytes()
    other = tmp_path / "other" / "MuMuManager.exe"
    other.parent.mkdir()
    other.write_bytes(b"another synthetic manager")
    with pytest.raises(ProbeError, match="host_binding_changed"):
        admission.pinned_host_namespace(root, other)
    assert (root / "host-binding.json").read_bytes() == before


@pytest.mark.parametrize(
    "raw",
    [
        b"broken",
        b'{"schema":1,"schema":1}',
        b'{"schema":NaN}',
        b"x" * 4097,
    ],
)
def test_corrupt_pin_is_unchanged_and_does_not_create_identity(binding_scope, raw):
    admission, root, manager, default, _ = binding_scope
    path = root / "host-binding.json"
    path.write_bytes(raw)
    with pytest.raises(ProbeError, match="host_binding_invalid"):
        admission.pinned_host_namespace(root, manager)
    assert path.read_bytes() == raw
    assert not default.exists()


def test_stopped_own_historical_marker_allows_first_pin(binding_scope):
    admission, root, manager, default, _ = binding_scope
    (root / "journal.sqlite").write_bytes(b"existing journal is never opened or modified")
    stopped_marker(root)
    (root / ("device-" + "a" * 64 + ".lock")).write_bytes(b"0")
    namespace, source = admission.pinned_host_namespace(root, manager)
    assert namespace == default.read_text().strip()
    assert source == default
    assert (root / "host-binding.json").is_file()


@pytest.mark.parametrize(
    "change",
    [
        {"status": "active"},
        {"status": "uncertain"},
        {"probe_pending": True},
        {"owner": "unattributed"},
        {"generation": True},
        {"session_id": "broken"},
        {"device_digest": "b" * 64},
        {"extra": "unrecognized"},
    ],
)
def test_unpinned_active_or_unattributed_marker_blocks_before_identity_creation(
    binding_scope, change
):
    admission, root, manager, default, _ = binding_scope
    path = stopped_marker(root, **change)
    before = path.read_bytes()
    with pytest.raises(ProbeError, match="host_binding_missing"):
        admission.pinned_host_namespace(root, manager)
    assert not default.exists()
    assert not (root / "host-binding.json").exists()
    assert path.read_bytes() == before


@pytest.mark.parametrize("name", ["journal.sqlite", "journal.sqlite-wal", "device-unknown.lock"])
def test_unpinned_journal_without_valid_stopped_markers_blocks(binding_scope, name):
    admission, root, manager, default, _ = binding_scope
    (root / name).write_bytes(b"unknown state")
    with pytest.raises(ProbeError, match="host_binding_missing"):
        admission.pinned_host_namespace(root, manager)
    assert not default.exists()


def test_repeated_same_binding_retains_immutable_pin(binding_scope):
    admission, root, manager, _, _ = binding_scope
    first = admission.pinned_host_namespace(root, manager)
    path = root / "host-binding.json"
    before = path.read_bytes(), path.stat().st_mtime_ns
    assert admission.pinned_host_namespace(root, manager) == first
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_even_same_uuid_override_alias_requires_manual_migration(
    binding_scope, monkeypatch, tmp_path
):
    admission, root, manager, default, selected = binding_scope
    admission.pinned_host_namespace(root, manager)
    alias = tmp_path / "namespace-copy"
    alias.write_bytes(default.read_bytes())
    selected[0] = alias
    monkeypatch.setenv("SWU_HAPPYRUN_HOST_ID_FILE", str(alias))
    with pytest.raises(ProbeError, match="host_binding_changed"):
        admission.pinned_host_namespace(root, manager)


def test_removing_override_cannot_create_a_new_default_identity(
    binding_scope, monkeypatch, tmp_path
):
    admission, root, manager, default, selected = binding_scope
    override = tmp_path / "override-only"
    override.write_text(str(uuid4()), encoding="ascii")
    selected[0] = override
    monkeypatch.setenv("SWU_HAPPYRUN_HOST_ID_FILE", str(override))
    admission.pinned_host_namespace(root, manager)
    selected[0] = default
    monkeypatch.delenv("SWU_HAPPYRUN_HOST_ID_FILE")
    with pytest.raises(ProbeError, match="host_binding_changed"):
        admission.pinned_host_namespace(root, manager)
    assert not default.exists()


def test_corrupt_original_pinned_identity_is_not_rewritten(binding_scope):
    admission, root, manager, default, _ = binding_scope
    admission.pinned_host_namespace(root, manager)
    default.write_text("broken", encoding="ascii")
    with pytest.raises(ProbeError, match="host_identity_unavailable"):
        admission.pinned_host_namespace(root, manager)
    assert default.read_text() == "broken"


def test_one_stopped_marker_cannot_cover_a_second_malformed_marker(binding_scope):
    admission, root, manager, default, _ = binding_scope
    stopped_marker(root)
    other = root / ("replay-" + "b" * 64 + ".json")
    other.write_bytes(b'{"schema":1,"schema":1}')
    with pytest.raises(ProbeError, match="host_binding_missing"):
        admission.pinned_host_namespace(root, manager)
    assert not default.exists()


def test_unpinned_direct_inventory_limit_blocks_before_identity_creation(binding_scope):
    admission, root, manager, default, _ = binding_scope
    for index in range(1001):
        (root / f"unrelated-{index}").write_bytes(b"")
    with pytest.raises(ProbeError, match="host_binding_missing"):
        admission.pinned_host_namespace(root, manager)
    assert not default.exists()


def test_uppercase_marker_alias_does_not_hide_unresolved_state(binding_scope):
    admission, root, manager, default, _ = binding_scope
    stopped_marker(root)
    (root / ("Replay-" + "b" * 64 + ".json")).write_bytes(b"unknown")
    with pytest.raises(ProbeError, match="host_binding_missing"):
        admission.pinned_host_namespace(root, manager)
    assert not default.exists()


@pytest.mark.parametrize("corrupt", [False, True])
def test_exclusive_pin_race_reads_winner_without_overwriting(binding_scope, monkeypatch, corrupt):
    from pathlib import Path

    admission, root, manager, _, _ = binding_scope
    expected = admission.pinned_host_namespace(root, manager)
    pin = root / "host-binding.json"
    winner = b"partial" if corrupt else pin.read_bytes()
    pin.unlink()
    original_open = Path.open

    def race_open(path, mode="r", *args, **kwargs):
        if path == pin and mode == "xb":
            with original_open(path, "wb") as stream:
                stream.write(winner)
            raise FileExistsError
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", race_open)
    if corrupt:
        with pytest.raises(ProbeError, match="host_binding_invalid"):
            admission.pinned_host_namespace(root, manager)
    else:
        assert admission.pinned_host_namespace(root, manager) == expected
    assert pin.read_bytes() == winner
