"""Offline trace checks do not execute or certify a physical channel."""

import json

import pytest
from pydantic import ValidationError

from swu_happyrun.drivers.mumu.channel_probe_plan import (
    ChannelTrace,
    ProbeBudget,
    assess_trace,
    version_plan,
)


def trace(channel="location"):
    return {
        "channel": channel,
        "source": "synthetic",
        "host_version": "6.8.4.0",
        "android_api": 35,
        "steps": [
            {
                "phase": phase,
                "outcome": "observed",
                "started_ms": i * 100,
                "finished_ms": i * 100 + 50,
            }
            for i, phase in enumerate(("binding", "write", "readback", "stop", "quiescence"))
        ],
    }


def test_help_is_facts_not_activation():
    plan = version_plan()
    assert plan["status"] == "unsupported"
    assert plan["capabilities"] == []
    assert plan["channels"]["location"]["readback_command"] is None
    assert plan["channels"]["gyro"]["stop_command"] is None
    assert "step" not in plan["channels"]["gyro"]["quantity"]
    assert "--longitude LONGITUDE --latitude LATITUDE" in plan["channels"]["location"]["help"]


@pytest.mark.parametrize("channel", ["location", "gyro"])
def test_complete_trace_never_authorizes_or_writes(channel):
    result = assess_trace(ChannelTrace.model_validate(trace(channel)), ProbeBudget())
    assert result.status == "unsupported"
    assert result.trace_result == "consistent"
    assert result.capabilities == ()
    assert result.writes_performed == 0
    assert result.reason == "physical_transport_not_implemented"


@pytest.mark.parametrize("phase", ["binding", "write", "readback", "stop", "quiescence"])
@pytest.mark.parametrize("outcome", ["failed", "timeout", "unknown", "not_run"])
def test_each_incomplete_phase_fails_closed(phase, outcome):
    data = trace()
    next(s for s in data["steps"] if s["phase"] == phase)["outcome"] = outcome
    result = assess_trace(ChannelTrace.model_validate(data), ProbeBudget())
    assert result.trace_result == "rejected"
    assert result.reason == f"{phase}_unconfirmed"
    assert result.status == "unsupported" and result.capabilities == ()


def test_stops_remain_separate_and_all_channels_assessed():
    loc, gyro = trace(), trace("gyro")
    loc["steps"][3]["outcome"] = "timeout"
    reports = [assess_trace(ChannelTrace.model_validate(t), ProbeBudget()) for t in (loc, gyro)]
    assert [r.trace_result for r in reports] == ["rejected", "consistent"]
    assert all(r.status == "unsupported" for r in reports)


@pytest.mark.parametrize(
    "mutation", ["missing", "duplicate", "reordered", "overlap", "negative", "backwards"]
)
def test_invalid_sequence_rejected(mutation):
    data = trace()
    if mutation == "missing":
        data["steps"].pop()
    if mutation == "duplicate":
        data["steps"][1]["phase"] = "binding"
    if mutation == "reordered":
        data["steps"].reverse()
    if mutation == "overlap":
        data["steps"][2]["started_ms"] = 149
    if mutation == "negative":
        data["steps"][0]["started_ms"] = -1
    if mutation == "backwards":
        data["steps"][1]["finished_ms"] = 99
    with pytest.raises(ValidationError):
        ChannelTrace.model_validate(data)


@pytest.mark.parametrize(
    "field,value",
    [
        ("call_timeout_ms", 0),
        ("call_timeout_ms", True),
        ("call_timeout_ms", 5001),
        ("total_timeout_ms", 30001),
        ("max_output_bytes", 65537),
        ("max_output_bytes", float("nan")),
    ],
)
def test_budget_rejects_unbounded_or_coerced_input(field, value):
    with pytest.raises(ValidationError):
        ProbeBudget(**{field: value})


def test_exact_deadline_is_expired():
    data = trace()
    data["steps"][-1]["finished_ms"] = 5400
    result = assess_trace(ChannelTrace.model_validate(data), ProbeBudget())
    assert result.reason == "call_budget_exceeded"


def test_overall_budget_is_independent():
    data = trace()
    for i, step in enumerate(data["steps"]):
        step["started_ms"], step["finished_ms"] = i * 7000, i * 7000 + 3000
    assert (
        assess_trace(ChannelTrace.model_validate(data), ProbeBudget()).reason
        == "total_budget_exceeded"
    )


@pytest.mark.parametrize(
    "key,value",
    [
        ("adb_serial", "private-device"),
        ("binding_digest", "private"),
        ("raw_stdout", "secret"),
        ("stop_command", "invented"),
    ],
)
def test_unknown_private_fields_rejected(key, value):
    data = trace()
    data[key] = value
    with pytest.raises(ValidationError):
        ChannelTrace.model_validate(data)


def test_report_schema_is_fixed_and_no_raw_identifiers():
    result = assess_trace(ChannelTrace.model_validate(trace()), ProbeBudget())
    encoded = result.model_dump_json()
    assert "binding_digest" not in encoded and "adb" not in encoded
    assert json.loads(encoded)["capabilities"] == []
    assert ChannelTrace.model_json_schema()["additionalProperties"] is False


@pytest.mark.parametrize(
    "field,value", [("host_version", "6.8.5.0"), ("android_api", 31), ("source", "certified")]
)
def test_other_versions_and_provenance_labels_rejected(field, value):
    data = trace()
    data[field] = value
    with pytest.raises(ValidationError):
        ChannelTrace.model_validate(data)


def test_output_budget_rejection():
    data = trace()
    data["steps"][1]["output_bytes"] = 65537
    assert (
        assess_trace(ChannelTrace.model_validate(data), ProbeBudget()).reason
        == "output_budget_exceeded"
    )


def test_nested_mutation_is_revalidated():
    data = ChannelTrace.model_validate(trace())
    data.steps.reverse()
    with pytest.raises(ValidationError):
        assess_trace(data, ProbeBudget())


def test_plan_is_not_mutable_global_authority():
    data = version_plan()
    data["capabilities"].append("location_write")
    assert version_plan()["capabilities"] == []


@pytest.mark.parametrize("api", [35.0, "35", True])
def test_android_api_does_not_coerce(api):
    data = trace()
    data["android_api"] = api
    with pytest.raises(ValidationError):
        ChannelTrace.model_validate(data)
