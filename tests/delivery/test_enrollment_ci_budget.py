"""CI coverage budgets cannot weaken product deadlines or hide missing nodes."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def sections():
    workflow = (ROOT / ".github/workflows/checks.yml").read_text()
    main, windows = workflow.split("  windows-full-suite:\n", 1)
    windows, aggregate = windows.split("  python-suite-completeness:\n", 1)
    aggregate = aggregate.split("  console-browser-qa:\n", 1)[0]
    return workflow, main, windows, aggregate


def test_windows_full_contract_suite_has_bounded_platform_budget():
    workflow, main, windows, _ = sections()
    assert "timeout-minutes: ${{ matrix.os == 'windows-latest' && 30 || 15 }}" in main
    assert "os: [ubuntu-latest, windows-latest]" in main
    assert 'python: ["3.11", "3.13"]' in main
    assert "--index 0 --count 1 --budget-seconds 750" in main
    assert "if: runner.os != 'Windows'" in main
    assert "timeout-minutes: 30" in windows
    assert "max-parallel: 4" in windows
    assert "shard: [0, 1, 2, 3, 4, 5]" in windows
    assert 'python: ["3.11", "3.13"]' in windows
    assert "--index ${{ matrix.shard }} --count 6 --budget-seconds 1500" in windows
    for section in (main, windows):
        assert "fail-fast: false" in section
        assert "continue-on-error" not in section
        assert "uv sync --extra server --extra agent --extra dev --frozen" in section
    assert "--run-native-enrollment" not in workflow


def test_full_node_union_is_gated_on_all_jobs_and_same_attempt_artifacts():
    _, main, windows, aggregate = sections()
    assert "needs: [contracts-and-diagnostics, windows-full-suite]" in aggregate
    assert "if: always()" in aggregate
    assert "timeout-minutes: 5" in aggregate
    for expected in ("Linux:3.11:1", "Linux:3.13:1", "Windows:3.11:6", "Windows:3.13:6"):
        assert f'--expect "{expected}"' in aggregate
    for job in ("contracts-and-diagnostics", "windows-full-suite"):
        assert f'--job-result "${{{{ needs.{job}.result }}}}"' in aggregate
    assert (
        "pattern: python-suite-*-${{ github.sha }}-attempt-${{ github.run_attempt }}" in aggregate
    )
    assert "--expected-sha ${{ github.sha }}" in aggregate
    assert "--run-id ${{ github.run_id }} --attempt ${{ github.run_attempt }}" in aggregate
    for section in (main, windows):
        assert "github.run_attempt" in section
        assert "if-no-files-found: error" in section
    assert "if: always() && runner.os != 'Windows'" in main
    assert "if: always()" in windows
    for forbidden in ("--ignore", " -k ", " -m ", "windows-review-pin", "continue-on-error"):
        assert forbidden not in main + windows + aggregate


def test_original_reporter_and_full_module_entry_are_preserved():
    helper = (ROOT / "scripts/ci_python_suite.py").read_text()
    tree = ast.parse(helper)
    command = next(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "command" for target in node.targets)
    )
    assert ast.unparse(command.elts[0]) == "sys.executable"
    assert [item.value for item in command.elts[1:8]] == [
        "-m",
        "pytest",
        "tests",
        "-vv",
        "-o",
        "faulthandler_timeout=60",
        "--durations=20",
    ]
    assert '"PYTEST_PLUGINS"' in helper
    assert "child.wait(timeout=budget)" in helper
