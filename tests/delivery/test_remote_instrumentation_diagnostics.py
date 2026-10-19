"""Fixed diagnostic parsing; never serialize arbitrary instrumentation output."""

import ast
import importlib.util
import json
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load():
    spec = importlib.util.spec_from_file_location(
        "remote_diag", ROOT / "scripts/remote_instrumentation_diagnostics.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_failure_details_are_fixed_and_private():
    module = load()
    output = "\n".join(
        [
            "PRIVATE_TOKEN /private/path",
            "REMOTE_QA PHASE worker_join_return",
            "REMOTE_QA PHASE PRIVATE_TOKEN",
            "REMOTE_QA ERROR kind=AssertionFailedError phase=assert_worker",
            "REMOTE_QA ERROR kind=PRIVATE_TOKEN phase=assert_worker",
            "Acceptance must not rely on emergency fallback stop PRIVATE_TOKEN",
            " at org.happyrun.app.remoteqa.RemoteHttpsAcceptanceTest.exercise"
            "(RemoteHttpsAcceptanceTest.java:108)",
            " at private.Token.secret(PRIVATE_TOKEN:1)",
            "FAILURES!!!",
        ]
    )
    result = module.summarize(output, 0)
    assert result["phases"] == ["worker_join_return"]
    assert result["errors"] == [{"kind": "AssertionFailedError", "phase": "assert_worker"}]
    assert result["assertion_codes"] == ["fallback_stop"]
    assert result["frames"] == [{"method": "exercise", "line": 108}]
    assert result["junit_ok_one"] == 0 and result["platform_failure"]
    assert "PRIVATE_TOKEN" not in str(result) and "/private" not in str(result)


def test_snapshot_enums_and_counts_are_bounded():
    module = load()
    value = (
        "REMOTE_QA SNAPSHOT starts=1 stopped=true worker_alive=false "
        "runner_error=false local=attention_unconfirmed"
    )
    evidence = module.summarize(value, 0)
    assert evidence["snapshots"] == [
        {
            "starts": 1,
            "stopped": True,
            "worker_alive": False,
            "runner_error": False,
            "local": "attention_unconfirmed",
        }
    ]
    assert (
        module.summarize(value.replace("attention_unconfirmed", "PRIVATE_TOKEN"), 0)["snapshots"]
        == []
    )
    assert module.summarize(value.replace("starts=1", "starts=123456"), 0)["snapshots"] == []


def test_junit_failure_is_not_inferred_success_from_marker():
    module = load()
    result = module.summarize("OK (1 test)\nException PRIVATE_TOKEN", 1)
    assert result["junit_ok_one"] == 1 and result["exception_indicator"]
    assert result["returncode"] == 1


HOST = ROOT / "scripts/check_remote_https_android.py"
JAVA = (
    ROOT
    / "android/app/src/remoteQaAndroidTest/java/org/happyrun/app/remoteqa"
    / "RemoteHttpsAcceptanceTest.java"
)


def host_function(name, namespace):
    tree = ast.parse(HOST.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(HOST), "exec"), namespace)
    return namespace[name]


@pytest.mark.parametrize(
    "output,code",
    [
        ("FAILURES!!!", 0),
        ("OK (1 test)\nException PRIVATE_TOKEN", 0),
        ("OK (1 test)", 1),
        ("PRIVATE_TOKEN", 0),
        ("OK (1 test)\nREMOTE_QA_STATE state=running starts=1 stopped=true\nFAILURES", 0),
    ],
)
def test_actual_instrumentation_preserves_strict_failure(output, code):
    diagnostics = {}
    ns = {
        "subprocess": SimpleNamespace(
            run=lambda *a, **k: SimpleNamespace(stdout=output, returncode=code),
            TimeoutExpired=subprocess.TimeoutExpired,
        ),
        "command": lambda *a: ["PRIVATE_TOKEN"],
        "summarize": load().summarize,
        "re": re,
    }
    with pytest.raises(RuntimeError):
        host_function("instrumentation", ns)({}, "lost_event", diagnostics)
    assert diagnostics["phase"] == "instrumentation"
    assert diagnostics["instrumentation"]["returncode"] == code
    assert "PRIVATE_TOKEN" not in json.dumps(diagnostics)


def test_actual_instrumentation_pass_retains_observation():
    output = "OK (1 test)\nREMOTE_QA_STATE state=running starts=1 stopped=true"
    ns = {
        "subprocess": SimpleNamespace(
            run=lambda *a, **k: SimpleNamespace(stdout=output, returncode=0),
            TimeoutExpired=subprocess.TimeoutExpired,
        ),
        "command": lambda *a: [],
        "summarize": load().summarize,
        "re": re,
    }
    assert host_function("instrumentation", ns)({}, "lost_renew") == {
        "android_state": "running",
        "driver_starts": 1,
        "driver_stopped": True,
    }


def test_timeout_preserves_safe_partial_phase_and_raises_original():
    failure = subprocess.TimeoutExpired(
        ["PRIVATE_TOKEN"], 90, output=b"REMOTE_QA PHASE worker_join_begin\nPRIVATE_TOKEN"
    )

    def run(*a, **k):
        raise failure

    ns = {
        "subprocess": SimpleNamespace(run=run, TimeoutExpired=subprocess.TimeoutExpired),
        "command": lambda *a: [],
        "summarize": load().summarize,
        "re": re,
    }
    diagnostics = {}
    with pytest.raises(subprocess.TimeoutExpired) as actual:
        host_function("instrumentation", ns)({}, "lost_event", diagnostics)
    assert actual.value is failure
    assert diagnostics["instrumentation"]["phases"] == ["worker_join_begin"]
    assert "PRIVATE_TOKEN" not in json.dumps(diagnostics)


def test_original_success_gate_and_budgets_are_unchanged():
    source = HOST.read_text(encoding="utf-8")
    assert 'result.returncode\n        or not re.search(r"OK \\(1 test\\)", output)' in source
    assert 'or re.search(r"FAILURES|INSTRUMENTATION_FAILED|Exception", output)' in source
    assert "timeout=90" in source
    java = JAVA.read_text(encoding="utf-8")
    for call in ["worker.join(15000)", "worker.join(7000)", "SystemClock.sleep(200)"]:
        assert call in java
    for label in load().ASSERTIONS.values():
        assert label in java
    stages = set(re.findall(r'phase\("([a-z_]+)"\)', java))
    assert stages <= load().PHASES
    assert "diagnosticError(failure, diagnosticPhase);\n            throw failure;" in java


@pytest.mark.parametrize(
    "contaminated,executed,results",
    [
        (True, ["lost_event"], ["failed", "not_run"]),
        (False, ["lost_event", "completed"], ["failed", "passed"]),
    ],
)
def test_actual_main_failure_is_hard_and_contamination_stops_cases(
    tmp_path, contaminated, executed, results
):
    import tempfile

    calls = []
    output = tmp_path / "report"

    def run_case(case, directory, certs, diagnostics):
        calls.append(case)
        if case == "lost_event":
            diagnostics["phase"] = "instrumentation"
            if contaminated:
                diagnostics["fixture_shutdown_code"] = "shutdown_failed"
            raise RuntimeError("PRIVATE_TOKEN")
        return {"case": case, "result": "passed"}

    class Parser:
        def add_argument(self, *a, **k):
            pass

        def parse_args(self):
            return SimpleNamespace(action="run", private_dir=tmp_path, output=output)

    ns = {
        "argparse": SimpleNamespace(ArgumentParser=Parser),
        "Path": Path,
        "guard": lambda: None,
        "adb": lambda *a: "OK (3 tests)",
        "PACKAGE": "org.happyrun.app",
        "re": re,
        "json": json,
        "tempfile": tempfile,
        "CASES": ("lost_event", "completed"),
        "run_case": run_case,
        "error_type": lambda e: "RuntimeError",
        "failure_evidence": lambda e, d: dict(d),
        "suite_contaminated": lambda d: d.get("fixture_shutdown_code") == "shutdown_failed",
        "remaining_not_run": lambda cases, n: [
            {"case": c, "result": "not_run", "reason": "fixture_contaminated"} for c in cases[n:]
        ],
    }
    with pytest.raises(SystemExit) as failure:
        host_function("main", ns)()
    assert failure.value.code == 1
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert calls == executed
    assert [case["result"] for case in report["cases"]] == results
    assert "PRIVATE_TOKEN" not in json.dumps(report)


def test_extracted_java_diagnostic_cannot_replace_original_failure(tmp_path):
    import shutil

    java = shutil.which("java")
    if not java:
        pytest.skip("Java unavailable; no Java execution claimed")
    source = JAVA.read_text(encoding="utf-8")
    methods = source[
        source.index("    private String diagnosticPhase") : source.index(
            "    private void exercise()"
        )
    ]
    harness = (
        """import java.util.*;
public final class DiagnosticCheck {
 static class Bundle {String value;void putString(String key,String value){this.value=value;}}
 final List<String> output=new ArrayList<>();boolean unavailable;
 final AssertionError primary=new AssertionError("PRIVATE_TOKEN");
 DiagnosticCheck getInstrumentation(){return this;}
 void sendStatus(int code,Bundle result){
  if(unavailable)throw new IllegalStateException("PRIVATE_TOKEN");output.add(result.value);
 }
 void exercise(){phase("assert_worker");throw primary;}
"""
        + methods
        + """
 public static void main(String[] args)throws Exception {
  for(boolean unavailable:new boolean[]{false,true}){
   DiagnosticCheck check=new DiagnosticCheck();check.unavailable=unavailable;
   try{check.testScenario();throw new RuntimeException("missing failure");}
   catch(AssertionError actual){if(actual!=check.primary)throw new RuntimeException("replaced");}
   if(!unavailable && !check.output.get(1).contains(
       "ERROR kind=AssertionError phase=assert_worker"))throw new RuntimeException("missing code");
   if(check.output.toString().contains("PRIVATE_TOKEN"))throw new RuntimeException("leak");
  }
 }
}
"""
    )
    file = tmp_path / "DiagnosticCheck.java"
    file.write_text(harness, encoding="utf-8")
    subprocess.run(
        [
            java,
            "com.sun.tools.javac.Main",
            "-source",
            "17",
            "-target",
            "17",
            "-d",
            str(tmp_path),
            str(file),
        ],
        check=True,
        capture_output=True,
        timeout=40,
    )
    subprocess.run(
        [java, "-cp", str(tmp_path), "DiagnosticCheck"], check=True, capture_output=True, timeout=10
    )
