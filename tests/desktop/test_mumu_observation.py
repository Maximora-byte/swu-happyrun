import json

import pytest

from swu_happyrun.desktop.mumu_transport import (
    LocalMuMuTransport,
    decode_delivery,
    decode_observation,
    decode_retained_location,
)
from swu_happyrun.drivers.command import ProbeError


def envelope():
    return dict(
        schema=1,
        nonce="a" * 32,
        boot_id="boot-1",
        sequence=2,
        state="observing",
        error_code=None,
        window_start_ns=100,
        reported_at_ns=300,
        sample=dict(latitude=30.0, longitude=106.0, accuracy=2.0, elapsed_realtime_ns=200),
    )


def decode(value):
    return decode_observation(json.dumps(value).encode(), nonce="a" * 32, boot_id="boot-1")


def test_fresh_correlated_observation_and_empty_ready():
    assert decode(envelope())["sequence"] == 2
    value = envelope()
    value.update(sequence=0, sample=None)
    assert decode(value)["sample"] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("nonce", "b" * 32),
        ("boot_id", "boot-2"),
        ("sequence", True),
        ("reported_at_ns", 99),
        ("schema", 2),
        ("state", "succeeded"),
    ],
)
def test_invalid_envelopes_are_not_evidence(field, value):
    data = envelope()
    data[field] = value
    with pytest.raises(ProbeError):
        decode(data)


@pytest.mark.parametrize(
    "field,value",
    [
        ("latitude", 91.0),
        ("longitude", float("nan")),
        ("accuracy", -1.0),
        ("elapsed_realtime_ns", 99),
        ("elapsed_realtime_ns", 301),
    ],
)
def test_invalid_samples_rejected(field, value):
    data = envelope()
    data["sample"][field] = value
    with pytest.raises(ProbeError):
        decode(data)


def test_duplicate_keys_rejected():
    raw = json.dumps(envelope()).replace('"schema": 1', '"schema": 1, "schema": 1')
    with pytest.raises(ProbeError):
        decode_observation(raw.encode(), nonce="a" * 32, boot_id="boot-1")


def test_observed_684_tool_delivery_format_is_distinct_from_inventory():
    assert decode_delivery(b'{"errcode":0,"errmsg":""}') is None
    for raw in [
        b'{"error_code":0}',
        b'{"errcode":true,"errmsg":""}',
        b'{"errcode":1,"errmsg":"failed"}',
        b'{"errcode":0,"errmsg":"unknown"}',
    ]:
        with pytest.raises(ProbeError, match="write_ack_unconfirmed"):
            decode_delivery(raw)


@pytest.mark.parametrize("index", [5, "5"])
def test_recovery_checks_static_identity_before_shutdown(index):
    transport = LocalMuMuTransport.__new__(LocalMuMuTransport)
    transport.manager = "unit-manager"
    transport.observer = transport._output = None
    calls = []

    def run(path, *args, **kwargs):
        calls.append(args)
        return json.dumps(
            dict(
                index=index,
                error_code=0,
                created_timestamp=200,
                is_process_started=True,
                is_android_started=True,
            )
        ).encode()

    transport._run = run
    with pytest.raises(ProbeError, match="recovery_instance_changed"):
        transport.shutdown("5", expected_created_timestamp=100)
    assert all("shutdown" not in call for call in calls)


def test_retained_system_fix_is_separate_from_new_listener_sample():
    raw = b"""Location Manager State:
  Location Providers:
    passive provider:
      last location=Location[gps 30.0,110.0 hAcc=1 et=+1s]
    gps provider:
      service: ProviderRequest[OFF]
      last location=Location[gps 30.001,110.002 hAcc=1 et=+2s]
  Event Log:
"""
    assert decode_retained_location(raw) == (30.001, 110.002)
    with pytest.raises(ProbeError, match="held_location_unavailable"):
        decode_retained_location(raw.replace(b"    gps provider:", b"    network provider:"))
    with pytest.raises(ProbeError, match="held_location_unavailable"):
        decode_retained_location(raw.replace(b"30.001,110.002", b"91.0,110.002"))


@pytest.mark.parametrize("index", [5, "5"])
def test_already_stopped_original_instance_is_confirmed(index):
    transport = LocalMuMuTransport.__new__(LocalMuMuTransport)
    transport.manager = "unit-manager"
    transport.observer = transport._output = None
    calls = []

    def run(path, *args, **kwargs):
        calls.append(args)
        return json.dumps(
            dict(
                index=index,
                created_timestamp=100,
                error_code=0,
                is_process_started=False,
                is_android_started=False,
            )
        ).encode()

    transport._run = run
    transport.shutdown("5", expected_created_timestamp=100)
    assert all("shutdown" not in call for call in calls)
