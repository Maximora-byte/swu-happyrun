import importlib.util
import json
from pathlib import Path

import pytest


def load():
    path = Path(__file__).parents[2] / "scripts" / "mumu_evidence_experiment.py"
    assert path.is_file(), "zero-device experiment entrypoint is missing"
    spec = importlib.util.spec_from_file_location("experiment_entry", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("args", [[], ["--preview"], ["--execute"], ["private-path"]])
def test_entry_is_zero_process_no_device_and_safe(args, monkeypatch, capsys):
    import subprocess

    def forbidden(*args, **kwargs):
        pytest.fail("no child processes allowed")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    result = load().main(args)
    output = capsys.readouterr().out
    value = json.loads(output)
    assert value["launch_count"] == value["location_count"] == value["shutdown_count"] == 0
    assert value["install_count"] == 0
    assert value["execution_ready"] is False
    assert "private-path" not in output
    assert result == (0 if args in ([], ["--preview"]) else 3)


def test_process_facts_entry_reports_counts_not_private_identity(monkeypatch, capsys):
    from swu_happyrun.drivers.mumu import windows_process_facts as facts

    fact = facts.ProcessFact(123, 4, 567, "C:\\private\\app.exe", (1, 2), "ok")
    snapshot = facts.ProcessFactsSnapshot("partial", (fact,), "process_facts_partial")
    monkeypatch.setattr(facts, "query_process_facts", lambda deadline: snapshot)
    assert load().main(["--process-facts"]) == 3
    value = json.loads(capsys.readouterr().out)
    assert value["process_count"] == 1
    assert value["status"] == "partial"
    assert "private" not in json.dumps(value)
    assert "123" not in json.dumps(value)
    assert value["execution_ready"] is False
