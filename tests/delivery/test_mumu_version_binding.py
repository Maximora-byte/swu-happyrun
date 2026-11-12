"""Observed Manager/ADB release formats must agree without weakening identity."""

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
runner = importlib.import_module("check_mumu_https")


@pytest.fixture
def observed_instance(monkeypatch):
    from swu_happyrun.drivers.mumu import discovery, manager

    binding = runner.BoundSession("0", "synthetic", "boot", "a" * 64)
    binding.engine_version, binding.host_version = "15", "6.8.4.0"
    binding.checked_at = -1
    values = dict(
        manager="15.0",
        adb="15",
        index="0",
        android_started=True,
        process_started=True,
        boot="boot",
        state="device",
        app="a" * 64,
        test="b" * 64,
    )

    def inspect(self, index):
        return [
            SimpleNamespace(
                index=values["index"],
                android_version=values["manager"],
                android_started=values["android_started"],
                process_started=values["process_started"],
            )
        ]

    monkeypatch.setattr(manager.MuMuManager, "inspect", inspect)
    monkeypatch.setattr(discovery, "host_version", lambda p: "6.8.4.0")

    def query(*args):
        return values[
            {
                "get-state": "state",
                "/proc/sys/kernel/random/boot_id": "boot",
                "ro.build.version.release": "adb",
            }[args[-1]]
        ]

    adb = SimpleNamespace(
        query=query, installed_hash=lambda p: values["test" if p.endswith(".test") else "app"]
    )
    pair = {"app": {"sha256": "a" * 64}, "test": {"sha256": "b" * 64}}

    def refresh():
        runner.refresh_binding(
            SimpleNamespace(manager=Path("manager"), instance="0"), binding, pair, adb
        )

    return binding, values, refresh


@pytest.mark.parametrize(
    "manager,adb,bound",
    [
        ("15.0", "15", "15"),
        ("15", "15.0", "15"),
        ("15.0.0", "15", "15.0"),
        ("15.1.0", "15.1", "15.1"),
    ],
)
def test_real_refresh_accepts_only_trailing_zero_equivalence(
    observed_instance, manager, adb, bound
):
    binding, values, refresh = observed_instance
    values.update(manager=manager, adb=adb)
    binding.engine_version = bound
    refresh()
    assert binding.checked_at > 0
    evidence = binding.engine_version_evidence
    assert evidence["manager"]["raw"] == manager
    assert evidence["adb"]["raw"] == adb
    assert evidence["binding"]["raw"] == bound
    assert (
        evidence["manager"]["canonical"]
        == evidence["adb"]["canonical"]
        == evidence["binding"]["canonical"]
    )
    assert values["manager"] == manager and binding.engine_version == bound


@pytest.mark.parametrize(
    "field,value",
    [
        ("manager", "14"),
        ("adb", "14"),
        ("manager", "15.1"),
        ("adb", "15.0.1"),
        ("manager", "15-preview"),
        ("manager", None),
        ("adb", ""),
        ("index", "1"),
        ("boot", "changed"),
        ("state", "offline"),
        ("android_started", False),
        ("process_started", False),
        ("app", "changed"),
        ("test", "changed"),
    ],
)
def test_real_refresh_rejects_version_and_identity_changes(observed_instance, field, value):
    binding, values, refresh = observed_instance
    values[field] = value
    with pytest.raises(RuntimeError):
        refresh()
    assert binding.checked_at == -1


@pytest.mark.parametrize(
    "value",
    [
        "",
        None,
        15,
        True,
        "0",
        "00",
        "015",
        "15.00",
        "15.01",
        " 15",
        "15 ",
        "15\n",
        "15.",
        "15..0",
        "15.0.0.0",
        "15-beta",
        "１５",
        "15/0",
        "1000",
        "15.1000",
        pytest.param("9" * 10000, id="oversized"),
    ],
)
def test_unknown_or_unbounded_version_is_rejected(value):
    assert hasattr(runner, "canonical_android_release"), "bounded semantic parser required"
    with pytest.raises(RuntimeError):
        runner.canonical_android_release(value)


@pytest.mark.parametrize("value", ["14", "15.1", None, "15-preview"])
def test_reviewed_binding_version_must_also_agree(observed_instance, value):
    binding, values, refresh = observed_instance
    binding.engine_version = value
    with pytest.raises(RuntimeError):
        refresh()
    assert binding.checked_at == -1


def test_version_mismatch_keeps_running_flags_and_original_evidence(observed_instance):
    binding, values, refresh = observed_instance
    values["manager"] = "14.0"
    with pytest.raises(RuntimeError, match="manager_android_release_mismatch"):
        refresh()
    assert values["android_started"] and values["process_started"]
    assert binding.engine_version_evidence == {
        "manager": {"raw": "14.0", "canonical": (14,)},
        "adb": {"raw": "15", "canonical": (15,)},
        "binding": {"raw": "15", "canonical": (15,)},
    }
    assert binding.checked_at == -1


def test_android_release_parser_bounds_and_nonzero_components():
    assert runner.canonical_android_release("999.999.999") == (999, 999, 999)
    assert runner.canonical_android_release("15.0.1") == (15, 0, 1)
    assert runner.canonical_android_release("15.1.0") == (15, 1)
