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


def test_windows_pin_partition_is_exhaustive_and_does_not_enable_native_qa():
    workflow = (Path(__file__).resolve().parents[2] / ".github/workflows/checks.yml").read_text()
    main = workflow.split("  contracts-and-diagnostics:\n", 1)[1].split("  windows-review-pin:", 1)[
        0
    ]
    pin = workflow.split("  windows-review-pin:\n", 1)[1].split("  console-browser-qa:", 1)[0]
    linux = "uv run --no-sync python -m pytest -vv -o faulthandler_timeout=60 --durations=20"
    # Windows timed traceback dumping itself can crash the interpreter. Fatal
    # crash tracebacks and fixed job deadlines remain enabled independently.
    command = "uv run --no-sync python -m pytest -vv -o faulthandler_timeout=0 --durations=20"
    pipeline = "tests/agent/test_enrollment_review_pin.py"
    # Exact selectors establish all-tests-minus-P plus P, with no hidden filters,
    # no native opt-in and no unrelated ignored paths. Linux remains all-tests.
    lines = main.splitlines()
    test_steps = [
        (lines[i - 1].strip(), line.strip())
        for i, line in enumerate(lines)
        if "python -m pytest" in line
    ]
    assert test_steps == [
        ("if: runner.os != 'Windows'", "run: " + linux),
        ("if: runner.os == 'Windows'", "run: " + command + " --ignore=" + pipeline),
    ]
    expression = (
        "test_authority_at_each_pin_mutation_stops_immediately or "
        "test_publish_failure_retains_pin_attempt_without_repair or "
        "test_lock_conflict_has_zero_sqlite_storage_mkdir_or_native or "
        "test_original_device_byte_uses_owner_fd_no_second_handle or "
        "test_issue_and_read_pin_readonly_never_ready"
    )
    pin_lines = pin.splitlines()
    steps = [
        (pin_lines[i - 1].strip(), line.strip())
        for i, line in enumerate(pin_lines)
        if "python -m pytest" in line
    ]
    assert steps == [
        (
            "if: matrix.group == 'boundaries'",
            "run: " + command + " " + pipeline + ' -k "' + expression + '"',
        ),
        (
            "if: matrix.group == 'remaining'",
            "run: " + command + " " + pipeline + ' -k "not (' + expression + ')"',
        ),
    ]
    assert "group: [boundaries, remaining]" in pin
    assert "runs-on: windows-latest" in pin
    assert "timeout-minutes: 30" in pin
    assert 'python: ["3.11", "3.13"]' in pin
    assert "fail-fast: false" in pin
    assert "continue-on-error" not in pin
    assert "--run-native-enrollment" not in workflow
    assert (Path(__file__).resolve().parents[2] / pipeline).is_file()
