import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from swu_happyrun.drivers.mumu.enrollment_transaction_records import (
    ArtifactObservation,
    RecordInvalid,
    TransactionLayout,
    decode_record,
    diagnose_transaction,
    encode_record,
)
from swu_happyrun.drivers.mumu.instance_attribution import FileIdentity


def fixture(tmp_path):
    root = tmp_path / "control-v1"
    layout = TransactionLayout(
        root,
        "a" * 64,
        "b" * 64,
        tmp_path / "journal",
        tmp_path / "mumu-experiment-registration.json",
        "11111111-1111-4111-8111-111111111111",
    )
    observations = {}
    records = []
    for sequence, role in enumerate(layout.roles, 1):
        value = ArtifactObservation(
            role,
            layout.path(role),
            FileIdentity("python_stat", 1, sequence),
            FileIdentity("python_stat", 1, 100),
            sequence,
            str(sequence) * 64,
        )
        observations[role] = value
        raw = encode_record(
            layout, sequence, hashlib.sha256(records[-1]).hexdigest() if records else None, value
        )
        records.append(raw)
    return layout, records, observations


def test_empty_partial_and_complete_are_never_ready(tmp_path):
    layout, records, observations = fixture(tmp_path)
    assert diagnose_transaction(layout, [], {}).status == "unstarted"
    for count in range(1, len(records)):
        result = diagnose_transaction(
            layout, records[:count], {k: observations[k] for k in layout.roles[:count]}
        )
        assert result.status == "incomplete"
        assert result.execution_allowed is False
    result = diagnose_transaction(layout, records, observations)
    assert result.status == "candidate_unpinned"
    assert result.execution_allowed is False


def test_complete_journal_is_mutable_but_identity_is_not(tmp_path):
    layout, records, observed = fixture(tmp_path)
    observed["journal"] = replace(observed["journal"], sha256="f" * 64, size=4096)
    assert diagnose_transaction(layout, records, observed).status == "candidate_unpinned"
    observed["journal"] = replace(observed["journal"], identity=FileIdentity("python_stat", 1, 900))
    assert diagnose_transaction(layout, records, observed).status == "incomplete"


@pytest.mark.parametrize(
    "change",
    ["hash", "identity", "parent", "path", "missing", "extra", "order", "previous", "truncated"],
)
def test_mismatch_never_repairs_or_completes(tmp_path, change):
    layout, records, observed = fixture(tmp_path)
    value = observed["receipt"]
    if change == "hash":
        observed["receipt"] = replace(value, sha256="f" * 64)
    elif change == "identity":
        observed["receipt"] = replace(value, identity=FileIdentity("python_stat", 1, 900))
    elif change == "parent":
        observed["receipt"] = replace(value, parent_identity=FileIdentity("python_stat", 1, 901))
    elif change == "path":
        observed["receipt"] = replace(value, path=tmp_path / "another")
    elif change == "missing":
        del observed["receipt"]
    elif change == "extra":
        observed["alien"] = value
    elif change == "order":
        records[0], records[1] = records[1], records[0]
    elif change == "previous":
        bad = json.loads(records[1])
        bad["previous_sha256"] = "0" * 64
        records[1] = json.dumps(bad).encode()
    else:
        records[-1] = records[-1][:-1]
    assert diagnose_transaction(layout, records, observed).status == "incomplete"


def test_partial_journal_hash_must_match(tmp_path):
    layout, records, observed = fixture(tmp_path)
    count = layout.roles.index("journal") + 1
    observed = {k: observed[k] for k in layout.roles[:count]}
    observed["journal"] = replace(observed["journal"], sha256="f" * 64)
    assert diagnose_transaction(layout, records[:count], observed).status == "incomplete"


@pytest.mark.parametrize(
    "raw",
    [b"{}", b'{"schema":1,"schema":1}', b'{"value":NaN}', b"[]", b"x" * 65537],
    ids=["empty", "duplicate", "nan", "array", "oversized"],
)
def test_strict_record_parser(raw):
    with pytest.raises(RecordInvalid):
        decode_record(raw)


def test_layout_fixed_paths_and_no_filesystem_calls(tmp_path, monkeypatch):
    layout, records, observed = fixture(tmp_path)
    assert layout.path("admission") == layout.root / "admissions" / (layout.plan_sha256 + ".json")
    assert layout.path("intent") == layout.directory / "enrollment-intent-v1.json"
    assert layout.path("provenance") == layout.journal.parent / "enrollment-v1.json"
    assert layout.record_path(1) == layout.directory / "stage-01.json"
    monkeypatch.setattr(Path, "open", lambda *a, **k: pytest.fail("unexpected file I/O"))
    monkeypatch.setattr(Path, "mkdir", lambda *a, **k: pytest.fail("unexpected directory mutation"))
    assert diagnose_transaction(layout, records, observed).status == "candidate_unpinned"


def test_wrong_identity_domain_rejected(tmp_path):
    layout, _, observed = fixture(tmp_path)
    wrong = replace(observed["admission"], identity=FileIdentity("win32_legacy_ntfs", 1, 1))
    with pytest.raises(RecordInvalid):
        encode_record(layout, 1, None, wrong)


def test_record_cannot_alias_reserved_stage_or_control_file(tmp_path):
    layout, _, _ = fixture(tmp_path)
    for path in (layout.record_path(1), layout.root / "authority-v1.json", layout.path("receipt")):
        with pytest.raises(RecordInvalid):
            replace(layout, journal=path)


def test_duplicate_trailing_or_wrong_plan_record_rejected(tmp_path):
    layout, records, observed = fixture(tmp_path)
    assert diagnose_transaction(layout, records + [records[-1]], observed).status == "incomplete"
    assert (
        diagnose_transaction(replace(layout, plan_sha256="c" * 64), records, observed).status
        == "incomplete"
    )
    assert (
        diagnose_transaction(replace(layout, transaction_id="c" * 64), records, observed).status
        == "incomplete"
    )
