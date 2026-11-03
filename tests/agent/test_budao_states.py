"""Synthetic negative inputs only: no real selectors or device interaction."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from test_geo import profiles

NOW = datetime(2026, 10, 19, tzinfo=UTC)


def adapter_case(**changes):
    from swu_happyrun.drivers.budao.adapter import BudaoAdapter
    from swu_happyrun.drivers.budao.selectors import PageObservation

    school, _ = profiles()
    page = PageObservation(
        package=school.app_package,
        version_name=school.app_version,
        version_code=123,
        captured_at=NOW,
        state="start",
        authorized=True,
        dynamic_points_confirmed=True,
        session_id="synthetic-session",
    )
    adb = Mock()
    adapter = BudaoAdapter(adb, school, page=replace(page, **changes), now=lambda: NOW)
    return adapter, adb


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"state": "unknown"}, "unknown_page"),
        ({"state": "success_toast"}, "unknown_page"),
        ({"captured_at": NOW - timedelta(seconds=30)}, "stale_page"),
        ({"captured_at": NOW + timedelta(seconds=1)}, "stale_page"),
        ({"captured_at": NOW.replace(tzinfo=None)}, "stale_page"),
        ({"authorized": False}, "authorization_required"),
        ({"dynamic_points_confirmed": False}, "dynamic_points_missing"),
        ({"session_id": None}, "session_missing"),
        ({"version_name": "changed"}, "app_version_mismatch"),
        ({"package": "other.package"}, "app_version_mismatch"),
        ({"version_code": None}, "version_code_missing"),
        ({"version_code": True}, "version_code_missing"),
        ({"version_code": 0}, "version_code_missing"),
        ({}, "needs_samples"),
    ],
)
def test_offline_state_gate_never_writes(changes, reason):
    from swu_happyrun.drivers.base import DriverError

    adapter, adb = adapter_case(**changes)
    assert adapter.inspect_state() == "unknown"
    assert adapter.reason_code == reason
    for operation in (adapter.start, adapter.finish):
        with pytest.raises(DriverError, match=f"^{reason}$"):
            operation()
    assert adb.mock_calls == []


def test_real_registry_empty_immutable_and_no_synthetic_registration():
    from swu_happyrun.drivers.budao.selectors import REAL_VERSION_REGISTRY

    assert dict(REAL_VERSION_REGISTRY) == {}
    with pytest.raises(TypeError):
        REAL_VERSION_REGISTRY[("example.package", "test-1", 123)] = object()


def test_observation_absent_never_probes_or_writes():
    from swu_happyrun.drivers.base import DriverError
    from swu_happyrun.drivers.budao.adapter import BudaoAdapter

    adb = Mock()
    school, _ = profiles()
    adapter = BudaoAdapter(adb, school)
    assert adapter.inspect_state() == "unknown"
    with pytest.raises(DriverError, match="page_missing"):
        adapter.start()
    assert adapter.read_result().status == "unknown"
    assert adb.mock_calls == []


def test_matching_page_without_bound_record_does_not_create_evidence():
    adapter, adb = adapter_case()
    assert adapter.read_result().status == "unknown"
    assert adapter.read_result().reason_code == "session_missing"
    assert adapter.read_result().evidence == []
    assert adb.mock_calls == []
