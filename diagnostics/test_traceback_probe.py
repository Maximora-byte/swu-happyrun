import importlib.util
import tempfile
import threading
from pathlib import Path


def load_probe():
    path = Path(__file__).with_name("traceback_probe.py")
    assert path.exists(), "diagnostic helper is missing"
    spec = importlib.util.spec_from_file_location("traceback_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_python_watchdog_dumps_metadata_without_locals():
    probe = load_probe()
    secret_marker = "DO_NOT_PRINT_LOCAL_CONTENT_72945"
    with tempfile.TemporaryFile(mode="w+b") as output:
        watchdog = probe.PythonWatchdog(output, seconds=0.01)
        watchdog.start()
        watchdog.join(timeout=2)
        assert not watchdog.is_alive()
        output.seek(0)
        text = output.read().decode()
    assert "Thread" in text
    assert "test_python_watchdog_dumps_metadata_without_locals" in text
    assert secret_marker not in text


def test_python_watchdog_cancels_and_joins_without_dump():
    probe = load_probe()
    with tempfile.TemporaryFile(mode="w+b") as output:
        watchdog = probe.PythonWatchdog(output, seconds=60)
        watchdog.start()
        watchdog.cancel()
        watchdog.join(timeout=2)
        assert not watchdog.is_alive()
        output.seek(0)
        assert output.read() == b""
    assert not any(t.name == "traceback-probe" for t in threading.enumerate())


def test_modes_change_only_reporter_not_target_or_threshold():
    probe = load_probe()
    a = probe.pytest_arguments("async")
    b = probe.pytest_arguments("python-thread")
    assert (
        a[-1]
        == b[-1]
        == (
            "tests/agent/test_enrollment_review_pin.py::"
            "test_journal_intent_and_result_changes_preserve_pin_not_ready"
        )
    )
    assert "faulthandler_timeout=60" in a
    assert "faulthandler_timeout=0" in b
    assert probe.OBSERVATION_SECONDS == 60
    assert "-p" not in a + b  # Fatal handler plugin must stay enabled.
