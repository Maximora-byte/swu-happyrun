import json

import pytest


def test_workspace_reopens_same_synthetic_identity_and_profiles(tmp_path):
    from swu_happyrun.desktop.workspace import Workspace

    root = tmp_path / "desktop"
    first = Workspace.open(root)
    second = Workspace.open(root)
    assert first.agent_id == second.agent_id
    assert first.device_id == second.device_id
    assert first.school == second.school
    assert first.route == second.route
    assert first.school.campus == "synthetic-desktop-only"
    assert first.job_spec().mode == "simulation"
    assert first.job_spec().expected_app_version is None
    assert not (root / "server.sqlite").exists()


def test_corrupt_workspace_is_never_replaced(tmp_path):
    from swu_happyrun.desktop.workspace import Workspace

    root = tmp_path / "desktop"
    Workspace.open(root)
    path = root / "workspace.json"
    path.write_text('{"schema":1,"schema":2}', encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(ValueError):
        Workspace.open(root)
    assert path.read_bytes() == before


def test_workspace_manifest_contains_no_credentials(tmp_path):
    from swu_happyrun.desktop.workspace import Workspace

    workspace = Workspace.open(tmp_path / "desktop")
    raw = json.loads((workspace.root / "workspace.json").read_text(encoding="utf-8"))
    assert set(raw) == {"schema", "agent_id", "device_id", "profile_id", "route_id"}
