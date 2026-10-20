"""CI wall-clock budget is independent of product execution deadlines."""

from pathlib import Path


def test_windows_full_contract_suite_has_bounded_platform_budget():
    workflow = (Path(__file__).resolve().parents[2] / ".github/workflows/checks.yml").read_text()
    contract = workflow.split("  contracts-and-diagnostics:\n", 1)[1].split(
        "  console-browser-qa:", 1
    )[0]
    assert "timeout-minutes: ${{ matrix.os == 'windows-latest' && 30 || 15 }}" in contract
    assert "os: [ubuntu-latest, windows-latest]" in contract
    assert 'python: ["3.11", "3.13"]' in contract
    assert (
        "uv run --no-sync python -m pytest -vv -o faulthandler_timeout=60 --durations=20"
        in contract
    )
    assert "continue-on-error" not in contract
    assert "fail-fast: false" in contract
