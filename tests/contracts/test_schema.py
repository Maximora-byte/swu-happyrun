import json
import subprocess
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from swu_happyrun.core.models import JobSpec

ROOT = Path(__file__).resolve().parents[2]


def export(*args):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts/export_schema.py"), *args],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )


def test_schema_export_and_drift_check(tmp_path, spec_data):
    target = tmp_path / "schema.json"
    result = export("--output", str(target))
    assert result.returncode == 0, result.stderr
    schema = json.loads(target.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert "VerificationResult" in schema["$defs"]
    assert "LeaseGrant" in schema["$defs"]
    assert schema["$defs"]["JobView"]["additionalProperties"] is False
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    validator.validate(JobSpec(**spec_data).model_dump(mode="json"))
    assert export("--output", str(target), "--check").returncode == 0
    target.write_text("{}", encoding="utf-8")
    assert export("--output", str(target), "--check").returncode == 1


def test_missing_schema_is_a_drift_failure(tmp_path):
    assert export("--output", str(tmp_path / "missing.json"), "--check").returncode == 1
