"""Synthetic transport and private protocol tests, never device acceptance."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from swu_happyrun.drivers.command import ProbeError
from swu_happyrun.drivers.mumu.own_probe import OwnProbe


@pytest.fixture
def bridge(monkeypatch):
    binding = SimpleNamespace(
        package="org.happyrun.app",
        adb_serial="synthetic-serial",
        boot_id="synthetic-boot",
        identity_digest="a" * 64,
    )
    probe = OwnProbe(
        Path("adb"), binding, binding_check=lambda: None, authorization_check=lambda: None
    )
    calls = []
    mutation = []

    def command(args, *, timeout):
        calls.append(args)
        if "instrument" in args:
            nonce = args[args.index("ownedObservationNonce") + 1]
            probe._test_nonce = nonce
            return b"OK (1 test)\nINSTRUMENTATION_CODE: -1\n"
        if "cat" in args:
            report = dict(
                schema=1,
                nonce=probe._test_nonce,
                binding_digest="a" * 64,
                boot_id="synthetic-boot",
                channel="location",
                duration_ms=10,
                window_start_ns=10**12,
                window_end_ns=10**12 + 10_000_000,
                cleanup_confirmed=True,
                status="samples_observed",
                samples=[
                    dict(
                        channel="location",
                        elapsed_realtime_ns=10**12 + 1,
                        values=[1.25, 2.75],
                        accuracy=3.5,
                    )
                ],
            )
            for change in mutation:
                change(report)
            return json.dumps(report).encode()
        return b""

    monkeypatch.setattr(probe, "_command", command)
    return probe, calls, mutation


def test_host_and_android_clocks_are_not_compared_directly(bridge):
    probe, calls, _ = bridge
    samples = probe.sample("location", duration_ms=10)
    assert samples[0].elapsed_realtime_ns == 10**12 + 1
    assert samples[0].values == (1.25, 2.75)
    assert samples[0].accuracy == 3.5
    assert any("run-as" in call and "cat" in call for call in calls)
    assert "rm" in calls[-1]


@pytest.mark.parametrize(
    "field,value", [("nonce", "old"), ("boot_id", "old"), ("binding_digest", "b" * 64)]
)
def test_old_nonce_or_boot_is_rejected(bridge, field, value):
    probe, calls, mutation = bridge
    mutation.append(lambda report: report.update({field: value}))
    with pytest.raises(ProbeError, match="observation_correlation_invalid"):
        probe.sample("location", duration_ms=10)
    assert "rm" in calls[-1]


@pytest.mark.parametrize("kind", ["old", "duplicate", "late", "future"])
def test_old_duplicate_or_late_sample_is_rejected(bridge, kind):
    probe, _, mutation = bridge

    def change(report):
        sample = report["samples"][0]
        if kind == "duplicate":
            report["samples"].append(dict(sample))
        else:
            sample["elapsed_realtime_ns"] = {
                "old": 10**12 - 1,
                "late": 10**12 + 10_000_000,
                "future": 10**12 + 20_000_000,
            }[kind]

    mutation.append(change)
    with pytest.raises(ProbeError, match="observation_sample_invalid"):
        probe.sample("location", duration_ms=10)


def test_gravity_samples_do_not_enable_gyro_or_steps(bridge):
    probe, _, mutation = bridge

    def change(report):
        report["channel"] = "gravity"
        report["samples"] = [
            dict(
                channel="gravity",
                elapsed_realtime_ns=10**12 + 1,
                values=[1.0, 2.0, 3.0],
                accuracy=3,
            )
        ]

    mutation.append(change)
    result = probe.sample("gravity", duration_ms=10)
    assert result[0].accuracy == 3 and type(result[0].accuracy) is int
    assert probe.capabilities == ()
    for channel in ["gyro", "steps"]:
        with pytest.raises(ProbeError, match="channel_unsupported"):
            probe.sample(channel, duration_ms=10)


@pytest.mark.parametrize("duration", [0, 5001, True, 1.5])
def test_invalid_budget_starts_zero_commands(bridge, duration):
    probe, calls, _ = bridge
    with pytest.raises(ProbeError, match="observation_budget_invalid"):
        probe.sample("location", duration_ms=duration)
    assert calls == []


@pytest.mark.parametrize(
    "status", ["permission_required", "no_samples", "observation_cleanup_unconfirmed"]
)
def test_failures_do_not_return_success(bridge, status):
    probe, _, mutation = bridge
    mutation.append(lambda report: report.update(status=status, samples=[]))
    with pytest.raises(ProbeError, match=status):
        probe.sample("location", duration_ms=10)


def test_private_cleanup_failure_overrides_samples(bridge, monkeypatch):
    probe, _, _ = bridge
    original = probe._command

    def command(args, *, timeout):
        if "rm" in args:
            raise ProbeError("command_failed")
        return original(args, timeout=timeout)

    monkeypatch.setattr(probe, "_command", command)
    with pytest.raises(ProbeError, match="private_cleanup_unconfirmed"):
        probe.sample("location", duration_ms=10)


def test_private_readback_never_enters_public_report(bridge):
    probe, _, _ = bridge
    samples = probe.sample("location", duration_ms=10)
    text = json.dumps(probe.public_report("location", samples))
    assert json.loads(text) == {
        "channel": "location",
        "sample_count": 1,
        "status": "samples_observed",
        "calibration": "unknown",
        "injection_stop": "unconfirmed",
    }
    for private in ["1.25", "2.75", "synthetic-serial", "files/", probe._test_nonce, "a" * 64]:
        assert private not in text


@pytest.mark.parametrize(
    "status", ["boot_unavailable", "self_probe_required", "private_write_failed"]
)
def test_pre_sample_failures_are_safe_codes(bridge, monkeypatch, status):
    probe, _, _ = bridge
    original = probe._command

    def command(args, *, timeout):
        if "instrument" in args:
            return (
                f"INSTRUMENTATION_STATUS: owned_observation={status}\n"
                "OK (1 test)\nINSTRUMENTATION_CODE: -1\n"
            ).encode()
        return original(args, timeout=timeout)

    monkeypatch.setattr(probe, "_command", command)
    with pytest.raises(ProbeError, match=status):
        probe.sample("location", duration_ms=10)


@pytest.mark.parametrize(
    "kind",
    [
        "oversized",
        "duplicates",
        "invalid_utf8",
        "nonfinite",
        "huge_integer",
        "boolean_accuracy",
        "too_many",
    ],
)
def test_malformed_private_payload_fails_closed(bridge, monkeypatch, kind):
    probe, _, _ = bridge
    original = probe._command

    def command(args, *, timeout):
        raw = original(args, timeout=timeout)
        if "cat" not in args:
            return raw
        if kind == "oversized":
            return b" " * 65537
        if kind == "duplicates":
            return raw[:-1] + b',"schema":1}'
        if kind == "invalid_utf8":
            return b"\xff"
        report = json.loads(raw)
        if kind == "nonfinite":
            report["samples"][0]["accuracy"] = float("nan")
        if kind == "huge_integer":
            report["samples"][0]["accuracy"] = 10**1000
        if kind == "boolean_accuracy":
            report["samples"][0]["accuracy"] = True
        if kind == "too_many":
            report["samples"] *= 129
        return json.dumps(report).encode()

    monkeypatch.setattr(probe, "_command", command)
    with pytest.raises(ProbeError):
        probe.sample("location", duration_ms=10)


def test_transport_bounds_actual_child_output(bridge, monkeypatch):
    import subprocess
    import sys

    probe, _, _ = bridge
    monkeypatch.undo()
    real_popen = subprocess.Popen
    calls = []

    def launch(argv, **kwargs):
        calls.append((argv, kwargs["shell"]))
        return real_popen(
            [sys.executable, "-c", 'import sys; sys.stdout.buffer.write(b"x"*2000000)'], **kwargs
        )

    monkeypatch.setattr(subprocess, "Popen", launch)
    with pytest.raises(ProbeError, match="command_output_limit"):
        probe._command(
            ("exec-out", "run-as", "org.happyrun.app", "cat", "files/synthetic"), timeout=3
        )
    assert calls[0][1] is False
    assert calls[0][0][:3] == ["adb", "-s", "synthetic-serial"]


def test_transport_timeout_is_not_retried(bridge, monkeypatch):
    import subprocess
    import sys

    probe, _, _ = bridge
    monkeypatch.undo()
    real_popen = subprocess.Popen
    calls = []

    def launch(argv, **kwargs):
        calls.append(argv)
        return real_popen([sys.executable, "-c", "import time; time.sleep(10)"], **kwargs)

    monkeypatch.setattr(subprocess, "Popen", launch)
    with pytest.raises(ProbeError, match="command_timeout"):
        probe._command(("shell", "am", "instrument"), timeout=0.05)
    assert len(calls) == 1


def test_script_preview_starts_zero_commands(monkeypatch, capsys):
    import importlib.util

    path = Path(__file__).resolve().parents[2] / "scripts/check_mumu_virtual_channel.py"
    spec = importlib.util.spec_from_file_location("virtual_channel", path)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    monkeypatch.setattr(script, "OwnProbe", lambda *a, **k: pytest.fail("preview touched device"))
    assert script.main(["--channel", "location"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "not_run_opt_in_required"


def test_wrong_own_package_starts_zero_commands(bridge):
    probe, calls, _ = bridge
    probe._binding.package = "com.lptiyu.tanke"
    with pytest.raises(ProbeError, match="own_target_required"):
        probe.sample("location", duration_ms=10)
    assert calls == []


def test_uncertain_instrumentation_never_claims_cleanup_and_cannot_restart(bridge, monkeypatch):
    probe, calls, _ = bridge
    original = probe._command

    def command(args, *, timeout):
        if "instrument" in args:
            calls.append(args)
            raise ProbeError("observation_transport_timeout")
        return original(args, timeout=timeout)

    monkeypatch.setattr(probe, "_command", command)
    with pytest.raises(ProbeError, match="private_cleanup_unconfirmed"):
        probe.sample("location", duration_ms=10)
    count = len(calls)
    with pytest.raises(ProbeError, match="observation_recovery_required"):
        probe.sample("location", duration_ms=10)
    assert len(calls) == count


def test_authorization_revoked_before_readback_returns_no_samples(bridge):
    probe, calls, _ = bridge
    checks = []

    def guard():
        checks.append(1)
        if len(checks) > 1:
            raise ProbeError("authorization_revoked")

    probe._authorization_check = guard
    with pytest.raises(ProbeError, match="authorization_revoked"):
        probe.sample("location", duration_ms=10)
    assert not any("cat" in call for call in calls)
    assert "rm" in calls[-1]


def test_reader_oserror_cannot_return_success(bridge, monkeypatch):
    import io
    import subprocess

    probe, _, _ = bridge
    monkeypatch.undo()

    class Broken(io.BytesIO):
        def read(self, *args):
            raise OSError("private details")

        def read1(self, *args):
            raise OSError("private details")

    class Process:
        stdout = io.BytesIO(b"valid")
        stderr = Broken()
        returncode = 0

        def poll(self):
            return self.returncode

        def wait(self, **kwargs):
            return self.returncode

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: Process())
    with pytest.raises(ProbeError, match="command_reader_failed"):
        probe._command(
            ("exec-out", "run-as", "org.happyrun.app", "cat", "files/synthetic"), timeout=1
        )


@pytest.mark.parametrize("failed_start", [1, 2])
def test_reader_start_failure_retains_ownership_and_uncertain_probe(
    monkeypatch, request, failed_start
):
    # Unconfirmed startup is intentionally process-local and may never recover.
    # Do not reset the production pending guard to let another test continue.
    if os.environ.get("HAPPYRUN_TEST_PROBE_START_FAILURE") != "1":
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", f"{__file__}::{request.node.name}"],
            env={**os.environ, "HAPPYRUN_TEST_PROBE_START_FAILURE": "1"},
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return

    import threading

    from swu_happyrun.drivers import command

    probe, _, _ = request.getfixturevalue("bridge")
    monkeypatch.undo()
    original_popen, original_start = subprocess.Popen, threading.Thread.start
    processes, starts = [], []

    def popen(_argv, **kwargs):
        process = original_popen([sys.executable, "-c", "import time; time.sleep(5)"], **kwargs)
        processes.append(process)
        return process

    def start(thread):
        starts.append(thread)
        if len(starts) == failed_start:
            raise RuntimeError("private details")
        original_start(thread)

    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(threading.Thread, "start", start)
    args = ("exec-out", "run-as", "org.happyrun.app", "cat", "files/synthetic")
    began = time.monotonic()
    with pytest.raises(ProbeError, match="command_cleanup_unconfirmed") as caught:
        probe._command(args, timeout=1)
    assert caught.value.primary_code == "command_reader_failed"
    assert "private details" not in str(caught.value)
    assert time.monotonic() - began < 1.5
    assert len(processes) == 1 and processes[0].poll() is not None
    attempted_pipe = getattr(processes[0], ("stdout", "stderr")[failed_start - 1])
    assert not attempted_pipe.closed
    assert len(command._PENDING_CAPTURE[1]) == failed_start
    assert not command._CAPTURE_LOCK.locked()
    for _ in range(3):
        with pytest.raises(ProbeError, match="command_cleanup_unconfirmed") as blocked:
            probe._command(args, timeout=1)
        assert blocked.value.primary_code == "command_reader_failed"
    with pytest.raises(ProbeError, match="private_cleanup_unconfirmed") as uncertain:
        probe.sample("location", duration_ms=10)
    assert uncertain.value.primary_code == "command_reader_failed"
    with pytest.raises(ProbeError, match="observation_recovery_required"):
        probe.sample("location", duration_ms=10)
    assert len(processes) == 1 and len(starts) == failed_start


def test_primary_failure_survives_private_cleanup_failure(bridge, monkeypatch):
    probe, _, _ = bridge

    def command(args, *, timeout):
        raise ProbeError("command_timeout" if "instrument" in args else "command_failed")

    monkeypatch.setattr(probe, "_command", command)
    with pytest.raises(ProbeError) as raised:
        probe.sample("location", duration_ms=10)
    assert raised.value.code == "private_cleanup_unconfirmed"
    assert raised.value.primary_code == "command_timeout"


def test_script_private_reader_rejects_symlinks_and_oversize(tmp_path):
    import importlib.util

    path = Path(__file__).resolve().parents[2] / "scripts/check_mumu_virtual_channel.py"
    spec = importlib.util.spec_from_file_location("private_paths", path)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    target = tmp_path / "data"
    target.write_bytes(b"12345")
    with pytest.raises(ProbeError):
        script.read_private(target, limit=4)
    link = tmp_path / "link"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ProbeError):
        script.read_private(link, limit=5)
    parent = tmp_path / "linked-parent"
    parent.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ProbeError):
        script.read_private(parent / "data", limit=5)
    with pytest.raises(ProbeError):
        script.write_private(parent / "new", "private")


def test_script_private_reader_rejects_fifo_without_open(tmp_path):
    import importlib.util
    import os

    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO unavailable")
    path = Path(__file__).resolve().parents[2] / "scripts/check_mumu_virtual_channel.py"
    spec = importlib.util.spec_from_file_location("private_fifo", path)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    with pytest.raises(ProbeError):
        script.read_private(fifo, limit=100)


@pytest.mark.parametrize("interruption", [KeyboardInterrupt, SystemExit])
def test_private_cleanup_interruption_latches_recovery(bridge, monkeypatch, interruption):
    probe, calls, _ = bridge
    original = probe._command

    def command(args, *, timeout):
        if "rm" in args:
            raise interruption()
        return original(args, timeout=timeout)

    monkeypatch.setattr(probe, "_command", command)
    with pytest.raises(interruption):
        probe.sample("location", duration_ms=10)
    monkeypatch.setattr(probe, "_command", original)
    count = len(calls)
    with pytest.raises(ProbeError, match="observation_recovery_required"):
        probe.sample("location", duration_ms=10)
    assert len(calls) == count
