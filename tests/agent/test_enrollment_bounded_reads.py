"""Bound allocation by the opened file, preserving frozen-evidence rejection."""

import hashlib
import os

import pytest

from swu_happyrun.drivers.mumu import enrollment_authority as authority
from swu_happyrun.drivers.mumu import enrollment_transaction as transaction
from swu_happyrun.drivers.mumu.instance_attribution import FileIdentity


@pytest.fixture(params=["authority", "transaction"])
def read_evidence(request, tmp_path):
    path = tmp_path / "frozen-evidence.json"
    payload = b'{"synthetic":"frozen"}'
    path.write_bytes(payload)
    pin = authority.FrozenFile(
        FileIdentity.from_stat(path.stat()), hashlib.sha256(payload).hexdigest()
    )

    def read(cap):
        if request.param == "authority":
            return authority._read(path, pin, cap)
        return transaction._observe(path, "intent", cap=cap)[1]

    return path, payload, read


def track_reads(monkeypatch, transform=lambda source, size: source.read(size)):
    original = os.fdopen
    requests = []

    class Reader:
        def __init__(self, *args, **kwargs):
            self.source = original(*args, **kwargs)

        def __enter__(self):
            self.source.__enter__()
            return self

        def __exit__(self, *args):
            return self.source.__exit__(*args)

        def read(self, size):
            requests.append(size)
            return transform(self.source, size)

    monkeypatch.setattr(os, "fdopen", Reader)
    return requests


def test_tiny_evidence_never_requests_journal_sized_buffer(read_evidence, monkeypatch):
    _, payload, read = read_evidence
    requests = track_reads(monkeypatch)
    assert read(128 * 1024 * 1024) == payload
    assert requests and max(requests) <= len(payload) + 1


def test_growth_past_cap_before_opened_stat_rejected_before_read(read_evidence, monkeypatch):
    path, payload, read = read_evidence
    original = os.open

    def grow_on_open(*args, **kwargs):
        fd = original(*args, **kwargs)
        with path.open("ab") as output:
            output.write(b"x" * 64)
        return fd

    monkeypatch.setattr(os, "open", grow_on_open)
    requests = track_reads(monkeypatch)
    with pytest.raises(authority.ApprovalNotReady):
        read(len(payload))
    assert requests == []


def test_growth_during_read_still_rejected(read_evidence, monkeypatch):
    path, _, read = read_evidence

    def grow(source, size):
        with path.open("ab") as output:
            output.write(b"x")
        return source.read(size)

    track_reads(monkeypatch, grow)
    with pytest.raises(authority.ApprovalNotReady):
        read(128 * 1024 * 1024)


def test_short_read_still_rejected(read_evidence, monkeypatch):
    _, _, read = read_evidence
    track_reads(monkeypatch, lambda source, size: source.read(size)[:-1])
    with pytest.raises(authority.ApprovalNotReady):
        read(128 * 1024 * 1024)
