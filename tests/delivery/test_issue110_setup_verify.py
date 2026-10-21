"""Setup-only checks; no CDB or original product group is ever launched."""

import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def verifier():
    path = ROOT / "scripts/diagnostics/issue110_setup_verify.py"
    spec = importlib.util.spec_from_file_location("issue110_setup_verify", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("code", [0, 7])
def test_setup_stage_preserves_tool_exit_and_private_output(verifier, tmp_path, code):
    receipt = {}
    output = tmp_path / "receipt.json"
    command = [sys.executable, "-c", f"print('PRIVATE_CANARY');raise SystemExit({code})"]
    if code:
        with pytest.raises(ValueError, match="stage_failed"):
            verifier.run_stage(command, "test", tmp_path, output, receipt, time.monotonic() + 5, 3)
    else:
        verifier.run_stage(command, "test", tmp_path, output, receipt, time.monotonic() + 5, 3)
    assert receipt["tool_exit"] == code
    assert receipt["setup_parent_exit_verified"] is True
    assert receipt["setup_descendant_cleanup"] == "unverified"
    assert "PRIVATE_CANARY" not in output.read_text()


def test_setup_stage_deadline_does_not_start_command(verifier, tmp_path):
    receipt = {}
    with pytest.raises(ValueError, match="setup_deadline"):
        verifier.run_stage(
            ["must-not-execute"],
            "test",
            tmp_path,
            tmp_path / "receipt.json",
            receipt,
            time.monotonic() - 1,
            3,
        )
    assert receipt["tool_exit"] is None


def test_setup_stage_timeout_stops_only_owned_parent(verifier, tmp_path):
    receipt = {}
    with pytest.raises(ValueError, match="setup_deadline"):
        verifier.run_stage(
            [sys.executable, "-c", "import time;time.sleep(30)"],
            "test",
            tmp_path,
            tmp_path / "receipt.json",
            receipt,
            time.monotonic() + 5,
            0.05,
        )
    assert receipt["tool_exit"] is None
    assert receipt["setup_parent_exit_verified"] is True
    assert (
        json.loads((tmp_path / "receipt.json").read_text())["setup_descendant_cleanup"]
        == "unverified"
    )


def test_setup_stage_output_limit_never_exports_raw_output(verifier, tmp_path):
    receipt = {}
    output = tmp_path / "receipt.json"
    with pytest.raises(ValueError, match="setup_output_limit"):
        verifier.run_stage(
            [sys.executable, "-c", "import sys;sys.stdout.write('X'*4194305)"],
            "test",
            tmp_path,
            output,
            receipt,
            time.monotonic() + 5,
            3,
        )
    assert receipt["setup_parent_exit_verified"] is True
    assert output.stat().st_size < 1024


def test_setup_environment_rejects_redirects_and_omits_credentials(verifier):
    assert verifier.clean_environment({"PATH": "tools", "GITHUB_TOKEN": "PRIVATE"}) == {
        "PATH": "tools"
    }
    for name in ("UV_PROJECT", "UV_WORKING_DIR", "UV_CONFIG_FILE"):
        with pytest.raises(ValueError, match="setup_source_override"):
            verifier.clean_environment({name: "PRIVATE"})


def test_junit_summary_keeps_only_counts_and_numeric_case_indexes(verifier, tmp_path):
    path = tmp_path / "junit.xml"
    path.write_text(
        '<testsuites><testsuite tests="2" failures="1" errors="0" skipped="0">'
        '<testcase name="test_safe[external_path]"><failure>PRIVATE_CANARY</failure>'
        '</testcase><testcase name="PRIVATE_CANARY"><failure/></testcase>'
        "</testsuite></testsuites>"
    )
    counts, failed = verifier.test_summary(path)
    assert counts == {"tests": 2, "failures": 1, "errors": 0, "skipped": 0}
    assert failed == [0, 1]
    assert "PRIVATE_CANARY" not in json.dumps([counts, failed])


def test_setup_only_workflow_is_one_shot_and_never_calls_native_controller():
    workflow = (ROOT / ".github/workflows/issue110-setup-only.yml").read_text()
    assert "github.event.before == '6ce2d7d848479bae43ae42b4b394f4560053eaf5'" in workflow
    assert "github.run_attempt == 1" in workflow
    assert 'branches: ["diagnostics/issue110-native-capture"]' in workflow
    assert "workflow_dispatch" not in workflow and "pull_request" not in workflow
    assert "timeout-minutes: 8" in workflow and "strategy:" not in workflow
    assert "issue110_setup_verify.py" in workflow
    assert "issue110_capture.py" not in workflow and "cdb" not in workflow.lower()
    native = (ROOT / ".github/workflows/issue110-native-capture.yml").read_text()
    predecessor = "github.event.before == '10b699e5db338a785074064f54beed6b2116d0cb'"
    assert native.count(predecessor) == 2
    assert predecessor not in workflow


@pytest.mark.parametrize("gate_fails", [False, True])
def test_fixed_setup_order_requires_independent_gate_before_real_helper(
    verifier, tmp_path, monkeypatch, gate_fails
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "subject").mkdir()
    (tmp_path / "subject/uv.lock").write_text("fixed lock")
    cache = tmp_path / "toolcache"
    base = cache / "Python/3.12.14/x64/python.exe"
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(verifier.sys, "platform", "win32")
    monkeypatch.setattr(verifier.sys, "version_info", (3, 12, 14))
    monkeypatch.setattr(verifier.sys, "executable", str(base))
    monkeypatch.setattr(verifier.sys, "argv", ["verify", "--pwsh", "pwsh", "--uv", "uv"])
    monkeypatch.setattr(
        verifier.os,
        "environ",
        {
            "GITHUB_WORKSPACE": str(tmp_path),
            "RUNNER_TEMP": str(temp),
            "RUNNER_TOOL_CACHE": str(cache),
            "ISSUE110_SETUP_STARTED": str(int(time.time())),
        },
    )
    stages = []

    def fake(command, stage, private, output, receipt, deadline, cap):
        stages.append(stage)
        log = private / f"{stage}.log"
        body = ""
        if stage == "uv_version":
            body = "uv 0.12.19 (test)"
        elif stage == "source_check":
            body = verifier.SOURCE if command[-1] == "HEAD" else verifier.TREE
        elif stage == "independent_tests":
            (private / "tests.xml").write_text(
                f'<testsuites><testsuite tests="1" failures="{int(gate_fails)}"/></testsuites>'
            )
            if gate_fails:
                raise ValueError("stage_failed")
        elif stage == "real_setup":
            (private / "helper-env").write_text(
                f"ISSUE110_PYTHON={temp / 'issue110-python-1/python.exe'}\n"
            )
        elif stage == "identity":
            body = '{"pytest":"9.1.1","pydantic":"2.14.1","swu-happyrun":"0.1.0"}'
        log.write_text(body)
        return log

    monkeypatch.setattr(verifier, "run_stage", fake)
    assert verifier.main() == int(gate_fails)
    prefix = [
        "uv_version",
        "source_check",
        "source_check",
        "independent_venv",
        "independent_pytest",
        "independent_tests",
    ]
    assert stages == prefix + (
        [] if gate_fails else ["real_setup", "identity", "package_check", "source_unchanged"]
    )
    receipt = json.loads((tmp_path / "evidence/setup-only.json").read_text())
    assert receipt["native_started"] is False and receipt["original_group_started"] is False


@pytest.mark.parametrize(
    "cleanup, verified, kills, waits",
    [
        ("exited", True, 0, 0),
        ("waited", True, 1, 1),
        ("wait_timeout", False, 1, 1),
        ("poll_error", None, 0, 0),
        ("kill_error", None, 1, 0),
        ("wait_error", None, 1, 1),
    ],
)
def test_setup_output_limit_race_records_only_observed_parent_exit(
    verifier, tmp_path, monkeypatch, cleanup, verified, kills, waits
):
    from types import SimpleNamespace

    receipt = {}
    output = tmp_path / "receipt.json"
    state = {"polls": 0, "kills": 0, "waits": 0, "started": 0, "original": None}
    original_stat = verifier.Path.stat

    def stat(path, *args, **kwargs):
        if path == tmp_path / "test.log":
            return SimpleNamespace(st_size=4194305)
        return original_stat(path, *args, **kwargs)

    class Child:
        returncode = None

        def poll(self):
            state["polls"] += 1
            if state["polls"] == 1:
                return None
            state["original"] = sys.exception()
            if cleanup == "poll_error":
                raise OSError("PRIVATE_CANARY")
            if cleanup == "exited":
                self.returncode = 0
                return 0
            return None

        def kill(self):
            state["kills"] += 1
            if cleanup == "kill_error":
                raise OSError("PRIVATE_CANARY")

        def wait(self, timeout):
            assert timeout == 1
            state["waits"] += 1
            if cleanup == "wait_timeout":
                raise verifier.subprocess.TimeoutExpired("PRIVATE_CANARY", timeout)
            if cleanup == "wait_error":
                raise OSError("PRIVATE_CANARY")
            self.returncode = -9
            return self.returncode

    def launch(command, **kwargs):
        state["started"] += 1
        assert command == ["fake-owned-child"]
        kwargs["stdout"].write(b"PRIVATE_CANARY")
        return Child()

    monkeypatch.setattr(verifier.Path, "stat", stat)
    monkeypatch.setattr(verifier.subprocess, "Popen", launch)
    monkeypatch.setattr(verifier.time, "monotonic", lambda: 0)
    with pytest.raises(ValueError, match="^setup_output_limit$") as caught:
        verifier.run_stage(["fake-owned-child"], "test", tmp_path, output, receipt, 100, 3)
    assert caught.value is state["original"]
    assert state["started"] == 1 and state["polls"] == 2
    assert state["kills"] == kills and state["waits"] == waits
    assert receipt["tool_exit"] is None
    assert receipt["setup_parent_exit_verified"] is verified
    assert receipt["setup_descendant_cleanup"] == "unverified"
    assert json.loads(output.read_text()) == receipt
    assert "PRIVATE_CANARY" not in output.read_text()


def test_setup_cleanup_failure_cannot_turn_success_into_pass(verifier, tmp_path, monkeypatch):
    receipt = {}
    output = tmp_path / "receipt.json"
    error = OSError("PRIVATE_CANARY")
    polls = []

    class Child:
        returncode = 0

        def poll(self):
            polls.append(1)
            if len(polls) == 1:
                return 0
            raise error

        def kill(self):
            pytest.fail("already-exited child was killed")

    monkeypatch.setattr(verifier.subprocess, "Popen", lambda *a, **kw: Child())
    # An unrelated caller exception must not be mistaken for this stage failing.
    try:
        raise RuntimeError("unrelated caller failure")
    except RuntimeError:
        with pytest.raises(OSError) as caught:
            verifier.run_stage(
                ["fake-owned-child"], "test", tmp_path, output, receipt, time.monotonic() + 5, 3
            )
    assert caught.value is error and len(polls) == 2
    # Exit was observed in the body; failure of the later poll cannot erase that fact.
    assert receipt["tool_exit"] == 0 and receipt["setup_parent_exit_verified"] is True
    assert receipt["setup_descendant_cleanup"] == "unverified"
    assert json.loads(output.read_text()) == receipt
    assert "PRIVATE_CANARY" not in output.read_text()


@pytest.mark.parametrize(
    "primary, cleanup_error",
    [
        (KeyboardInterrupt("PRIVATE_CANARY"), OSError("PRIVATE_CANARY")),
        (SystemExit("PRIVATE_CANARY"), OSError("PRIVATE_CANARY")),
        (ValueError("setup_output_limit"), KeyboardInterrupt("PRIVATE_CANARY")),
        (ValueError("setup_output_limit"), SystemExit("PRIVATE_CANARY")),
    ],
)
def test_setup_cleanup_preserves_primary_cancellation_without_catching_its_own(
    verifier, tmp_path, monkeypatch, primary, cleanup_error
):
    receipt = {}
    output = tmp_path / "receipt.json"
    polls = []
    original_stat = verifier.Path.stat

    def stat(path, *args, **kwargs):
        if path == tmp_path / "test.log":
            raise primary
        return original_stat(path, *args, **kwargs)

    class Child:
        returncode = None

        def poll(self):
            polls.append(1)
            if len(polls) == 1:
                return None
            raise cleanup_error

    monkeypatch.setattr(verifier.Path, "stat", stat)
    monkeypatch.setattr(verifier.subprocess, "Popen", lambda *a, **kw: Child())
    expected = primary if isinstance(cleanup_error, Exception) else cleanup_error
    with pytest.raises(type(expected)) as caught:
        verifier.run_stage(
            ["fake-owned-child"], "test", tmp_path, output, receipt, time.monotonic() + 5, 3
        )
    assert caught.value is expected and len(polls) == 2
    assert receipt["tool_exit"] is None and receipt["setup_parent_exit_verified"] is None
    assert receipt["setup_descendant_cleanup"] == "unverified"
    assert json.loads(output.read_text()) == receipt
    assert "PRIVATE_CANARY" not in output.read_text()


def test_setup_final_save_failure_keeps_existing_propagation(verifier, tmp_path, monkeypatch):
    from types import SimpleNamespace

    receipt = {}
    output = tmp_path / "receipt.json"
    error = OSError("PRIVATE_CANARY")
    saves, polls = [], []
    original_save, original_stat = verifier.save, verifier.Path.stat

    def save(path, data):
        saves.append(1)
        if len(saves) == 2:
            raise error
        original_save(path, data)

    def stat(path, *args, **kwargs):
        if path == tmp_path / "test.log":
            return SimpleNamespace(st_size=4194305)
        return original_stat(path, *args, **kwargs)

    class Child:
        returncode = None

        def poll(self):
            polls.append(1)
            return None if len(polls) == 1 else 0

    monkeypatch.setattr(verifier, "save", save)
    monkeypatch.setattr(verifier.Path, "stat", stat)
    monkeypatch.setattr(verifier.subprocess, "Popen", lambda *a, **kw: Child())
    with pytest.raises(OSError) as caught:
        verifier.run_stage(
            ["fake-owned-child"], "test", tmp_path, output, receipt, time.monotonic() + 5, 3
        )
    assert caught.value is error and len(saves) == len(polls) == 2
    assert receipt["tool_exit"] is None and receipt["setup_parent_exit_verified"] is True
    assert receipt["setup_descendant_cleanup"] == "unverified"
    assert "PRIVATE_CANARY" not in output.read_text()
