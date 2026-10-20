"""Declared numeric comparisons from synthetic private observations only."""

import importlib
import importlib.util
import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import pytest

from swu_happyrun.core.models import GeoPoint
from swu_happyrun.drivers.command import ProbeError
from swu_happyrun.drivers.mumu.own_probe import OwnProbe


@pytest.fixture
def comparison():
    name = "swu_happyrun.drivers.mumu.point_evidence"
    assert importlib.util.find_spec(name) is not None
    return importlib.import_module(name)


@pytest.fixture
def transport(monkeypatch):
    binding = SimpleNamespace(
        package="org.happyrun.app",
        adb_serial="private-serial",
        boot_id="private-boot",
        identity_digest="a" * 64,
    )
    probe = OwnProbe(
        Path("adb"), binding, binding_check=lambda: None, authorization_check=lambda: None
    )
    calls, mutations = [], []
    state = {}

    def command(args, *, timeout):
        calls.append(args)
        if "instrument" in args:
            state["nonce"] = args[args.index("ownedObservationNonce") + 1]
            assert args[args.index("ownedObservationDurationMs") + 1] == "1000"
            return b"OK (1 test)\nINSTRUMENTATION_CODE: -1\n"
        if "cat" in args:
            report = dict(
                schema=1,
                nonce=state["nonce"],
                binding_digest="a" * 64,
                boot_id="private-boot",
                channel="location",
                duration_ms=1000,
                window_start_ns=10**12,
                window_end_ns=10**12 + 10**9,
                cleanup_confirmed=True,
                status="samples_observed",
                samples=[
                    dict(
                        channel="location",
                        elapsed_realtime_ns=10**12 + 1,
                        values=[1.25, 2.75],
                        accuracy=500.0,
                    )
                ],
            )
            for mutate in mutations:
                mutate(report)
            return json.dumps(report).encode()
        return b""

    monkeypatch.setattr(probe, "_command", command)
    return probe, calls, mutations


def test_private_numeric_evidence_retains_envelope_and_never_claims_calibration(
    comparison, transport
):
    probe, calls, _ = transport
    result = comparison.observe_declared_point(probe, GeoPoint(latitude=1.25, longitude=2.75), 0)
    assert result.observation_status == "samples_within_declared_tolerance"
    assert result.sample_count == 1
    assert result.distances_m == (0.0,)
    private = result.private_dict()
    assert private["target"] == {"latitude": 1.25, "longitude": 2.75}
    assert private["tolerance_m"] == 0
    assert private["observation"]["nonce"] == result.observation.nonce
    assert private["observation"]["boot_id"] == "private-boot"
    assert private["observation"]["samples"][0]["accuracy"] == 500.0
    assert private["calibration"] == "unknown"
    assert private["coordinate_semantics"] == "raw_vendor_unverified"
    assert private["comparison_semantics"] == "numeric_great_circle_only"
    assert private["causal_attribution"] == "unverified"
    assert private["injection_ack"] == "unconfirmed"
    assert sum("instrument" in c for c in calls) == 1
    assert "private-boot" not in repr(result) and "1.25" not in repr(result)
    with pytest.raises(FrozenInstanceError):
        result.tolerance_m = 1


def test_accuracy_does_not_expand_declared_tolerance(comparison, transport):
    probe, _, _ = transport
    result = comparison.observe_declared_point(probe, GeoPoint(latitude=1.251, longitude=2.75), 1)
    assert result.observation_status == "samples_outside_declared_tolerance"
    assert 100 < result.distances_m[0] < 120


@pytest.mark.parametrize("tolerance", [-1, float("nan"), float("inf"), True, "1", 10**1000])
def test_invalid_tolerance_observes_nothing(comparison, transport, tolerance):
    probe, calls, _ = transport
    with pytest.raises(ProbeError, match="point_comparison_invalid"):
        comparison.observe_declared_point(probe, GeoPoint(latitude=1, longitude=2), tolerance)
    assert calls == []


@pytest.mark.parametrize(
    "target",
    [
        None,
        {"latitude": 1, "longitude": 2},
        GeoPoint.model_construct(latitude=float("nan"), longitude=2),
        GeoPoint.model_construct(latitude=True, longitude=2),
    ],
)
def test_invalid_target_observes_nothing(comparison, transport, target):
    probe, calls, _ = transport
    with pytest.raises(ProbeError, match="point_comparison_invalid"):
        comparison.observe_declared_point(probe, target, 1)
    assert calls == []


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("nonce", "old", "observation_correlation_invalid"),
        ("binding_digest", "old", "observation_correlation_invalid"),
        ("boot_id", "old", "observation_correlation_invalid"),
        ("window_end_ns", 10**12 + 1, "observation_window_invalid"),
        ("status", "no_samples", "no_samples"),
    ],
)
def test_invalid_or_empty_observation_never_retries(comparison, transport, field, value, code):
    probe, calls, mutations = transport
    mutations.append(lambda report: report.update({field: value}))
    with pytest.raises(ProbeError, match=code):
        comparison.observe_declared_point(probe, GeoPoint(latitude=1, longitude=2), 1)
    assert sum("instrument" in c for c in calls) == 1


def test_comparison_module_is_available():
    assert importlib.util.find_spec("swu_happyrun.drivers.mumu.point_evidence") is not None


def test_constructor_rejects_forged_envelope_and_recomputes_distances(comparison, transport):
    from dataclasses import replace

    probe, _, _ = transport
    result = comparison.observe_declared_point(probe, GeoPoint(latitude=1.25, longitude=2.75), 0)
    for changes in [
        {"samples": ()},
        {"duration_ms": 1},
        {"channel": "gravity"},
        {"window_end_ns": 1},
        {"nonce": ""},
        {"binding_digest": ""},
        {"boot_id": ""},
        {"samples": (replace(result.observation.samples[0], accuracy=True),)},
    ]:
        forged = replace(result.observation, **changes)
        with pytest.raises(ProbeError, match="observation_payload_invalid"):
            comparison.PointObservation(forged, (1.25, 2.75), 0)
    shifted = comparison.PointObservation(result.observation, (1.251, 2.75), 1)
    assert shifted.distances_m != result.distances_m


def test_declared_boundary_is_inclusive_and_every_sample_counts(comparison, transport):
    probe, calls, mutations = transport

    def second_sample(report):
        report["samples"].append(
            dict(
                channel="location",
                elapsed_realtime_ns=10**12 + 2,
                values=[1.251, 2.75],
                accuracy=0.0,
            )
        )

    mutations.append(second_sample)
    result = comparison.observe_declared_point(probe, GeoPoint(latitude=1.25, longitude=2.75), 0)
    assert result.observation_status == "samples_outside_declared_tolerance"
    boundary = comparison.PointObservation(
        result.observation, result.target, max(result.distances_m)
    )
    assert boundary.observation_status == "samples_within_declared_tolerance"
    assert boundary.sample_count == 2
    assert sum("instrument" in c for c in calls) == 1


def test_maximum_sample_window_is_fixed_and_no_public_values(comparison, transport):
    probe, calls, mutations = transport

    def full_window(report):
        first = report["samples"][0]
        report["samples"] = [dict(first, elapsed_realtime_ns=10**12 + i + 1) for i in range(128)]

    mutations.append(full_window)
    result = comparison.observe_declared_point(probe, GeoPoint(latitude=1.25, longitude=2.75), 0)
    assert result.sample_count == 128
    public = OwnProbe.public_report("location", result.observation.samples)
    assert public["calibration"] == "unknown"
    assert "private-boot" not in json.dumps(public)
    assert "1.25" not in json.dumps(public)
    assert sum("instrument" in c for c in calls) == 1


def test_envelope_private_conversion_is_detached(comparison, transport):
    probe, _, _ = transport
    result = comparison.observe_declared_point(probe, GeoPoint(latitude=1.25, longitude=2.75), 0)
    private = result.private_dict()
    private["observation"]["samples"][0]["accuracy"] = -1
    private["target"]["latitude"] = 50
    assert result.observation.samples[0].accuracy == 500
    assert result.target == (1.25, 2.75)
