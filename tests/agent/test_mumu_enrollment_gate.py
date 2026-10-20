"""The first enrollment batch is inspection-only, not an execution capability."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from swu_happyrun.drivers.base import DriverError


def test_production_entries_reject_before_any_io(monkeypatch):
    import sqlite3

    from swu_happyrun.drivers import command, identity
    from swu_happyrun.drivers.mumu import (
        evidence_experiment,
        native_684,
        probe_point,
        virtual_replay,
    )

    def forbidden(*args, **kwargs):
        pytest.fail("production entry reached side effects")

    monkeypatch.setattr(Path, "mkdir", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(identity, "load_host_id", forbidden)
    monkeypatch.setattr(command, "run_readonly", forbidden)
    monkeypatch.setattr(command, "_run_bounded_bytes", forbidden)
    monkeypatch.setenv("SWU_HAPPYRUN_TEST_MODE", "1")
    monkeypatch.setenv("SWU_HAPPYRUN_CONTROL_ROOT", "alternate")
    monkeypatch.setattr(virtual_replay, "RunJournal", forbidden)
    for call in (
        lambda: native_684.MuMuNative684(
            None, None, adb=None, binding_check=forbidden, authorization_check=forbidden, clock=None
        ),
        lambda: probe_point.run_probe_point_cli(
            SimpleNamespace(), point=None, clock=None, emit=forbidden
        ),
        lambda: virtual_replay.run_local_cli(
            SimpleNamespace(recover_stop=True), execution=None, clock=None, emit=forbidden
        ),
        lambda: evidence_experiment.run_experiment(None, adapter=None, store=None, clock=None),
        lambda: evidence_experiment.run_experiment(
            evidence_experiment.Registration(
                "static-uuid", "alternate-device", Path("alternate"), Path("evidence")
            ),
            adapter=native_684.MuMuNative684,
            store=object(),
            clock=None,
        ),
    ):
        with pytest.raises(DriverError, match="enrollment_execution_not_ready"):
            call()


def test_known_folder_resolution_never_uses_environment(monkeypatch, tmp_path):
    from swu_happyrun.drivers.mumu import enrollment

    actual = tmp_path / "actual"
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "alternate"))
    monkeypatch.setenv("SWU_HAPPYRUN_CONTROL_ROOT", str(tmp_path / "alternate"))
    monkeypatch.setattr(enrollment, "_local_app_data", lambda: actual)
    assert enrollment.resolve_control_root() == actual / "swu-happyrun" / "control-v1"
    assert list(tmp_path.iterdir()) == []


def test_resolver_does_not_issue_execution_capability():
    from swu_happyrun.drivers.mumu.enrollment import require_native_enrollment

    for value in (None, True, {}, {"approved": True}, object()):
        with pytest.raises(DriverError, match="enrollment_execution_not_ready"):
            require_native_enrollment(value)


def test_direct_own_probe_rejects_without_instrumentation():
    from swu_happyrun.drivers.mumu.own_probe import OwnProbe

    with pytest.raises(DriverError, match="enrollment_execution_not_ready"):
        OwnProbe(None, None, binding_check=lambda: None, authorization_check=lambda: None)


def test_manager_capability_does_not_create_host(tmp_path, monkeypatch):
    from swu_happyrun.drivers.command import ProbeError
    from swu_happyrun.drivers.mumu.manager import MuMuInstance, MuMuManager

    host = tmp_path / "missing" / "host-id"
    monkeypatch.setenv("SWU_HAPPYRUN_HOST_ID_FILE", str(host))
    with pytest.raises(ProbeError, match="host_identity_unavailable"):
        MuMuManager(tmp_path / "manager").capability(MuMuInstance("0", "15", False, False))
    assert not host.parent.exists()


def test_real_windows_known_folder_read_only():
    import os

    from swu_happyrun.drivers.mumu.enrollment import resolve_control_root

    if os.name != "nt":
        pytest.skip("native Windows Known Folder API")
    root = resolve_control_root()
    assert root.is_absolute()
    assert root.parts[-2:] == ("swu-happyrun", "control-v1")
    # Existence is intentionally not required; resolution must not initialize it.
