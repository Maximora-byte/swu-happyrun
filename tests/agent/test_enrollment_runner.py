"""Fixed-entry integration on synthetic storage, not original-machine approval."""

import ast
import importlib
import importlib.util
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from test_enrollment_transaction import synthetic as synthetic  # noqa: F401

from swu_happyrun.drivers.base import DriverError
from swu_happyrun.drivers.mumu.enrollment import require_native_enrollment

MODULE = "swu_happyrun.drivers.mumu.enrollment_runner"


def runner():
    assert importlib.util.find_spec(MODULE), "fixed runner entry is missing"
    return importlib.import_module(MODULE)


@pytest.mark.parametrize("existing", [False, True])
def test_fixed_initializer_loads_pinned_scope_and_remains_closed(synthetic, existing):
    entry = runner()
    _, _, bundle = synthetic
    root, anchors, _, _, _ = bundle(existing=existing, nested=True)
    result = entry.initialize_fixed_candidate(anchors)
    assert result.status == "candidate_unpinned"
    assert result.execution_allowed is False
    with pytest.raises(DriverError, match="enrollment_execution_not_ready"):
        require_native_enrollment(result)


def test_fixed_diagnosis_does_not_initialize_or_open_sqlite(synthetic, monkeypatch):
    entry = runner()
    _, state, bundle = synthetic
    root, anchors, _, _, paths = bundle(nested=True)
    before = {p: p.read_bytes() for p in root.parent.rglob("*") if p.is_file()}
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: pytest.fail("diagnosis SQLite"))
    result = entry.diagnose_fixed_candidate(anchors)
    assert result.status == "unstarted"
    assert result.execution_allowed is False
    assert not paths["journal"].exists()
    assert not state["events"]
    assert before == {p: p.read_bytes() for p in root.parent.rglob("*") if p.is_file()}


@pytest.mark.parametrize("change", ["missing", "tampered", "oversized"])
def test_scope_failure_has_zero_mutations(synthetic, change):
    entry = runner()
    _, state, bundle = synthetic
    root, anchors, _, _, paths = bundle(nested=True)
    scope = root / "reviews" / anchors.plan_sha256 / "reviewed-scope-v1.json"
    if change == "missing":
        scope.unlink()
    else:
        scope.write_bytes(b"x" * (2 * 1024 * 1024 + 1) if change == "oversized" else b"{}")
    before = {p: p.read_bytes() for p in root.parent.rglob("*") if p.is_file()}
    result = entry.initialize_fixed_candidate(anchors)
    assert result.status == "incomplete"
    assert result.reason_code == "fixed_runner_evidence_mismatch"
    assert not paths["journal"].exists()
    assert not state["events"]
    assert before == {p: p.read_bytes() for p in root.parent.rglob("*") if p.is_file()}
    assert str(root) not in repr(result)


@pytest.mark.parametrize("value", [None, True, {}, "latest"])
@pytest.mark.parametrize(
    "operation", ["initialize_fixed_candidate", "diagnose_fixed_candidate", "inspect_fixed_pin"]
)
def test_plain_input_rejected_before_root_resolution(monkeypatch, value, operation):
    entry = runner()
    monkeypatch.setattr(
        entry.transaction, "resolve_control_root", lambda: pytest.fail("untrusted input I/O")
    )
    result = getattr(entry, operation)(value)
    assert result.status == "incomplete"
    assert result.execution_allowed is False


def test_fixed_pin_entry_loads_scope_but_does_not_issue_or_open_sqlite(synthetic, monkeypatch):
    entry = runner()
    from swu_happyrun.drivers.mumu.enrollment_pin_reviewer import issue_review_pin
    from swu_happyrun.drivers.mumu.enrollment_review_pin import ReviewPinAnchors

    _, state, bundle = synthetic
    root, anchors, reviewed, _, _ = bundle(nested=True)
    assert entry.initialize_fixed_candidate(anchors).status == "candidate_unpinned"
    publication = issue_review_pin(anchors, reviewed, reviewer_id="original-machine-codex")
    assert publication.status == "candidate_pinned"
    pinned = ReviewPinAnchors(
        anchors, publication.file, publication.parent_identity, "original-machine-codex"
    )
    before = {p: p.read_bytes() for p in root.parent.rglob("*") if p.is_file()}
    events = tuple(state["events"])
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: pytest.fail("pin SQLite"))
    result = entry.inspect_fixed_pin(pinned)
    assert result.status == "candidate_pinned"
    assert result.execution_allowed is False
    assert before == {p: p.read_bytes() for p in root.parent.rglob("*") if p.is_file()}
    assert tuple(state["events"]) == events


@pytest.mark.parametrize("name", ["fixed_candidate_runner.py", "independent_pin_reviewer.py"])
def test_unconfigured_templates_fail_closed_without_io(name, monkeypatch, capsys):
    path = Path(__file__).parents[2] / "examples" / "enrollment" / name
    assert path.is_file(), "fixed external entry template is missing"
    spec = importlib.util.spec_from_file_location("fixed_example", path)
    template = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(template)
    monkeypatch.setattr(
        runner().transaction, "resolve_control_root", lambda: pytest.fail("template I/O")
    )
    assert template.main(["--approve", "--latest"]) == 2
    assert template.main([]) == 2
    output = capsys.readouterr().out
    assert "execution_allowed" in output
    assert str(path) not in output


@pytest.mark.parametrize("name", ["fixed_candidate_runner.py", "independent_pin_reviewer.py"])
def test_configured_templates_still_refuse_arguments(name, synthetic, capsys):
    _, state, bundle = synthetic
    _, anchors, _, _, paths = bundle(nested=True)
    path = Path(__file__).parents[2] / "examples" / "enrollment" / name
    spec = importlib.util.spec_from_file_location("fixed_example", path)
    template = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(template)
    template.RUNNER_ANCHORS = anchors
    template.OPERATION = "initialize"
    assert template.main(["--approve"]) == 2
    assert not paths["journal"].exists()
    assert not state["events"]
    assert "execution_allowed" in capsys.readouterr().out


def test_separate_fixed_reviewer_issues_once_and_does_not_initialize(synthetic):
    entry = runner()
    name = "swu_happyrun.drivers.mumu.enrollment_pin_reviewer"
    reviewer = importlib.import_module(name)
    assert callable(getattr(reviewer, "issue_fixed_pin", None))
    _, state, bundle = synthetic
    root, anchors, _, _, paths = bundle(nested=True)
    assert reviewer.issue_fixed_pin(anchors).status == "incomplete"
    assert not paths["journal"].exists()
    assert not state["events"]
    assert entry.initialize_fixed_candidate(anchors).status == "candidate_unpinned"
    result = reviewer.issue_fixed_pin(anchors)
    assert result.status == "candidate_pinned"
    assert result.execution_allowed is False
    before = {p: p.read_bytes() for p in root.parent.rglob("*") if p.is_file()}
    events = tuple(state["events"])
    assert reviewer.issue_fixed_pin(anchors).status == "incomplete"
    assert before == {p: p.read_bytes() for p in root.parent.rglob("*") if p.is_file()}
    assert tuple(state["events"]) == events


def test_runner_import_does_not_import_any_reviewer():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import swu_happyrun.drivers.mumu.enrollment_runner; "
            "assert not any(n.endswith(('enrollment_pin_reviewer', 'enrollment_reviewer', "
            "'enrollment_reviewer_entry')) for n in sys.modules)",
        ],
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr.decode()


def test_external_reviewer_import_is_outside_production_package():
    root = Path(__file__).parents[2]
    package = root / "src" / "swu_happyrun"
    assert not (package / "drivers/mumu/enrollment_reviewer_entry.py").exists()
    script = root / "examples/enrollment/independent_pin_reviewer.py"
    imports = [
        node.module
        for node in ast.walk(ast.parse(script.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom)
    ]
    assert "swu_happyrun.drivers.mumu.enrollment_pin_reviewer" in imports
    for file in package.rglob("*.py"):
        if file.name == "enrollment_pin_reviewer.py":
            continue
        for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                assert "enrollment_pin_reviewer" not in (node.module or "")
            elif isinstance(node, ast.Import):
                assert all("enrollment_pin_reviewer" not in alias.name for alias in node.names)


def test_approval_loss_after_loading_scope_still_causes_zero_writes(synthetic, monkeypatch):
    entry = runner()
    _, state, bundle = synthetic
    root, anchors, _, _, paths = bundle(nested=True)
    load = entry._load_fixed_scope

    def revoke_after_read(value):
        reviewed = load(value)
        (root / "authority-v1.json").write_bytes(b"{}")
        return reviewed

    monkeypatch.setattr(entry, "_load_fixed_scope", revoke_after_read)
    result = entry.initialize_fixed_candidate(anchors)
    assert result.status == "incomplete"
    assert not paths["journal"].exists()
    assert not state["events"]
