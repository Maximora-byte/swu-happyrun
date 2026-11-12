"""Cross-language fixture freshness; this is not Android or device acceptance."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from swu_happyrun.core.models import VerificationResult
from swu_happyrun.core.states import JobState, transition_allowed

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "contracts/android-local-boundary-v1.json"


def export(*args):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts/export_android_boundary.py"), *args],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_android_boundary_is_generated_from_current_shared_contract(tmp_path):
    generated = tmp_path / "boundary.json"
    result = export("--output", str(generated))
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(generated.read_text())
    assert (
        data["source_schema_sha256"]
        == hashlib.sha256((ROOT / "contracts/protocol-v1.schema.json").read_bytes()).hexdigest()
    )
    expected = [
        [source.value, target.value]
        for source in JobState
        for target in JobState
        if transition_allowed(source, target, "simulation")
    ]
    assert data["simulation_structural_edges"] == expected
    assert all(target != "succeeded" for _, target in expected)
    assert data["wire_protocol_client"] is False
    assert data["structural_edges_are_authorization"] is False
    assert data["verified_execution_capabilities"] == []
    verification = VerificationResult.model_validate(data["simulation_verification"])
    assert verification.status == "unknown"
    assert verification.reason_code == "simulation_only"
    assert verification.evidence == []
    assert data["simulation_completion"] == "completed"
    assert data["record_verified"] is False


def test_committed_android_boundary_has_no_drift():
    result = export("--check")
    assert result.returncode == 0, result.stdout + result.stderr
    assert FIXTURE.is_file()


def test_changed_android_fixture_is_rejected_without_overwrite(tmp_path):
    path = tmp_path / "boundary.json"
    path.write_text('{"record_verified":true}\n')
    before = path.read_bytes()
    result = export("--check", "--output", str(path))
    assert result.returncode == 1
    assert path.read_bytes() == before


def test_missing_android_fixture_check_does_not_create_it(tmp_path):
    path = tmp_path / "missing.json"
    assert export("--check", "--output", str(path)).returncode == 1
    assert not path.exists()
