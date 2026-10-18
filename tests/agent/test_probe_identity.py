from swu_happyrun.drivers.mumu.manager import MuMuInstance, MuMuManager


def test_cached_mumu_probe_does_not_refresh_report(tmp_path):
    manager = MuMuManager(tmp_path / "manager.exe", host_id="00000000-0000-4000-8000-000000000009")
    instance = MuMuInstance("0", "15.0", False, False)
    first = manager.capability(instance)
    second = manager.capability(instance)
    assert first == second
    assert first.probe_id == second.probe_id
    assert first.observed_at == second.observed_at


def test_new_completed_observation_has_new_probe_id(tmp_path):
    manager = MuMuManager(tmp_path / "manager.exe", host_id="00000000-0000-4000-8000-000000000009")
    first = manager.capability(MuMuInstance("0", "15.0", False, False))
    second = manager.capability(MuMuInstance("0", "15.0", False, False))
    assert first.device_id == second.device_id
    assert first.probe_id != second.probe_id
    assert first.capabilities == second.capabilities == []
