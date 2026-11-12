"""Only synthetic lifecycle actions; this suite never launches MuMu or ADB."""

import sys
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import mumu_experiment_harness as subject
import pytest
from test_experiment_shutdown import Clock

from swu_happyrun.agent.journal import RunJournal
from swu_happyrun.drivers.mumu.experiment_shutdown import Signal
from swu_happyrun.drivers.mumu.private_evidence import PrivateEvidenceStore


class Adapter:
    def __init__(self, registration):
        self.registration, self.calls = registration, []
        self.fail = None
        self.clean, self.identity = True, True

    def action(self, name):
        self.calls.append(name)
        if self.fail == name:
            raise KeyboardInterrupt("private details")

    def check_stopped_registration(self, registration):
        self.action("preflight")
        return registration == self.registration

    def launch(self):
        self.action("launch")

    def prepare(self):
        self.action("prepare")

    def capture_point(self):
        self.action("location")
        return subject.PointCapture(
            "write_ack_unconfirmed",
            True,
            b"synthetic",
            b"",
            {"complete": True},
        )

    def observe_point(self, *, duration_ms, max_samples):
        assert duration_ms == 1000 and max_samples == 128
        self.action("probe")
        from swu_happyrun.drivers.mumu.own_probe import OwnObservation, OwnSample
        from swu_happyrun.drivers.mumu.point_evidence import PointObservation

        observation = OwnObservation(
            nonce="0" * 32,
            binding_digest="1" * 64,
            boot_id="synthetic-boot",
            channel="location",
            duration_ms=1000,
            window_start_ns=0,
            window_end_ns=1_000_000_000,
            samples=(OwnSample((0.0, 0.0), 1, "location", 2.0),),
        )
        return PointObservation(observation, (0.0, 0.0), 1.0)

    def seal(self):
        self.action("seal")

    def drain(self, *, timeout, deadline):
        self.action("drain")
        return self.clean

    def verify_shutdown_identity(self, *, timeout, deadline):
        self.action("identity")
        return self.identity

    def shutdown(self, *, timeout, deadline):
        self.action("shutdown")

    def read(self, kind, *, timeout, deadline):
        self.action(kind)
        return Signal(True, True)


@pytest.fixture
def case(tmp_path):
    private = tmp_path / "private"
    if sys.platform == "win32":
        from swu_happyrun.drivers.mumu.windows_private import provision_private_directory

        provision_private_directory(private)
    else:
        private.mkdir(mode=0o700)
    registration = subject.Registration(
        stable_instance="synthetic-registered-instance",
        device_id=str(uuid4()),
        journal=tmp_path / "original.db",
        evidence_root=private,
    )
    return registration, Adapter(registration), PrivateEvidenceStore(private), Clock()


def run(case):
    registration, adapter, store, clock = case
    return subject.run_synthetic_experiment(registration, adapter=adapter, store=store, clock=clock)


def test_normal_path_keeps_reservation_and_never_claims_native_ack(case):
    result = run(case)
    reg, adapter, store, clock = case
    assert adapter.calls[:5] == ["preflight", "launch", "prepare", "location", "probe"]
    assert adapter.calls.count("shutdown") == 1
    assert result["shutdown_status"] == "sampled_shutdown_consistent"
    assert result["stop_status"] == "stop_unconfirmed"
    assert result["replay_enabled"] is False
    assert (store.root / "launch.intent").exists()
    assert (store.root / "location.intent").exists()
    assert (store.root / "shutdown.intent").exists()
    with RunJournal(reg.journal) as journal, journal.replay_recovery_lock(reg.device_id):
        assert journal.read_replay_reservation(reg.device_id)["status"] != "stopped"
    assert clock.now >= 30


def test_restart_is_zero_launch_and_location(case):
    run(case)
    case[1].calls.clear()
    result = run(case)
    assert "launch" not in case[1].calls
    assert "location" not in case[1].calls
    assert result["shutdown_status"] == "shutdown_not_attempted"


def test_old_reservation_blocks_launch_before_any_adapter_work(case):
    reg, adapter, store, clock = case
    with RunJournal(reg.journal) as journal, journal.device_lock(reg.device_id):
        journal.reserve_replay(reg.device_id, str(uuid4()), generation=1)
    run(case)
    assert adapter.calls == []


def test_wrong_registration_and_relocated_output_block_launch(case):
    reg, adapter, store, clock = case
    adapter.registration = replace(reg, stable_instance="different")
    run(case)
    assert "launch" not in adapter.calls
    adapter.calls.clear()
    result = subject.run_synthetic_experiment(
        replace(reg, evidence_root=Path("/wrong")), adapter=adapter, store=store, clock=clock
    )
    assert adapter.calls == []
    assert result["primary_error"] == "registration_invalid"


@pytest.mark.parametrize("stage", ["launch", "prepare", "location", "probe"])
def test_all_started_failure_and_cancellation_paths_make_shutdown_decision(case, stage):
    case[1].fail = stage
    result = run(case)
    assert "seal" in case[1].calls
    assert case[1].calls.count("shutdown") == 1
    assert result["primary_error"] == "experiment_interrupted"
    assert "private" not in str(result)


@pytest.mark.parametrize("condition", ["clean", "identity"])
def test_unknown_ownership_or_identity_never_spawns_shutdown(case, condition):
    setattr(case[1], condition, False)
    result = run(case)
    assert "shutdown" not in case[1].calls
    assert result["shutdown_status"] == "shutdown_not_attempted"


def test_evidence_fsync_failure_still_seals_and_makes_explicit_no_shutdown(case, monkeypatch):
    def fail(*args):
        raise OSError("private disk path")

    monkeypatch.setattr(case[2], "put_once", fail)
    result = run(case)
    assert "seal" in case[1].calls
    assert "shutdown" not in case[1].calls
    assert "probe" not in case[1].calls
    assert "drain" in case[1].calls
    assert result["evidence_error"] == "private_evidence_failed"
    assert result["shutdown_reason"] == "storage_unreliable"


def test_shutdown_intent_failure_prevents_command(case, monkeypatch):
    original = case[2].claim_intent

    def claim(action):
        if action == "shutdown":
            raise OSError("private path")
        original(action)

    monkeypatch.setattr(case[2], "claim_intent", claim)
    result = run(case)
    assert "shutdown" not in case[1].calls
    assert result["shutdown_reason"] == "shutdown_intent_failed"


def test_second_interrupt_during_cleanup_is_preserved_and_no_retry(case):
    case[1].fail = "seal"
    result = run(case)
    assert case[1].calls.count("seal") == 1
    assert "shutdown" not in case[1].calls
    assert result["shutdown_error"] == "experiment_interrupted"


def test_nonzero_capture_keeps_binary_but_never_probes(case):
    case[1].capture_point = lambda: subject.PointCapture(
        "write_failed_unconfirmed", True, b"\xff", b"\x00", {"complete": True}
    )
    result = run(case)
    assert "probe" not in case[1].calls
    assert (case[2].root / "command.stdout.bin").read_bytes() == b"\xff"
    assert result["command_status"] == "write_failed_unconfirmed"


def test_missing_registration_is_not_ready(case):
    result = subject.run_synthetic_experiment(None, adapter=case[1], store=case[2], clock=case[3])
    assert case[1].calls == []
    assert result["primary_error"] == "registration_invalid"


@pytest.mark.parametrize("field", ["device_id", "journal"])
def test_original_registry_rejects_changed_lock_mapping(case, field):
    reg, adapter, store, clock = case
    changed = str(uuid4()) if field == "device_id" else reg.journal.with_name("other.db")
    result = subject.run_synthetic_experiment(
        replace(reg, **{field: changed}), adapter=adapter, store=store, clock=clock
    )
    assert adapter.calls == ["preflight"]
    assert result["primary_error"] == "registration_invalid"


def test_corrupt_existing_marker_blocks_every_adapter_action(case):
    reg, adapter, store, clock = case
    with RunJournal(reg.journal) as journal:
        journal._reservation_path(reg.device_id).write_text("broken")
    run(case)
    assert adapter.calls == []


def _held_experiment(registration, entered, release, queue):
    class Held(Adapter):
        def launch(self):
            super().launch()
            entered.set()
            if not release.wait(10):
                raise TimeoutError

    adapter = Held(registration)
    result = subject.run_synthetic_experiment(
        registration,
        adapter=adapter,
        store=PrivateEvidenceStore(registration.evidence_root),
        clock=Clock(),
    )
    queue.put((result["shutdown_status"], adapter.calls.count("launch")))


def test_two_processes_only_one_can_launch_under_shared_lifecycle_lock(case):
    import multiprocessing

    context = multiprocessing.get_context("spawn")
    entered, release, queue = context.Event(), context.Event(), context.Queue()
    process = context.Process(target=_held_experiment, args=(case[0], entered, release, queue))
    process.start()
    try:
        assert entered.wait(10)
        run(case)
        assert case[1].calls == []
    finally:
        release.set()
        process.join(10)
        if process.is_alive():
            process.kill()
            process.join(5)
    assert process.exitcode == 0
    assert queue.get(timeout=1) == ("sampled_shutdown_consistent", 1)


@pytest.mark.parametrize("defect", ["incomplete", "cleanup", "truncated", "delivery", "status"])
def test_native_capture_adapter_does_not_relax_observation_gate(defect):
    from types import SimpleNamespace

    from swu_happyrun.drivers.base import DriverError
    from swu_happyrun.drivers.command import CaptureEvidence, CaptureSnapshot

    snapshot = CaptureSnapshot(
        stdout=b"\xff",
        stderr=b"",
        returncode=0,
        primary_code="ok",
        final_code="ok",
        cleanup_code="confirmed",
        started_monotonic=0,
        finished_monotonic=1,
        output_complete=True,
        truncated=False,
        process_started=True,
    )
    if defect == "incomplete":
        snapshot = replace(snapshot, output_complete=False)
    elif defect == "cleanup":
        snapshot = replace(snapshot, cleanup_code="unconfirmed")
    elif defect == "truncated":
        snapshot = replace(snapshot, truncated=True)
    evidence = CaptureEvidence()
    evidence.snapshot = snapshot

    class Native:
        last_delivery = None if defect == "delivery" else SimpleNamespace(command_completed=True)

        def write_location(self, point, *, deadline):
            raise DriverError(
                "write_encoding_invalid" if defect == "status" else "write_ack_unconfirmed"
            )

    capture = subject.capture_native_point(Native(), evidence, object(), deadline=5)
    assert not (capture.complete and capture.status == "write_ack_unconfirmed")
    assert capture.stdout == b"\xff"


def test_location_intent_failure_seals_drains_and_forbids_shutdown(case, monkeypatch):
    original = case[2].claim_intent

    def claim(action):
        if action == "location":
            raise OSError("private path")
        original(action)

    monkeypatch.setattr(case[2], "claim_intent", claim)
    result = run(case)
    assert "location" not in case[1].calls
    assert "drain" in case[1].calls
    assert "shutdown" not in case[1].calls
    assert result["shutdown_reason"] == "storage_unreliable"


def test_report_keeps_original_evidence_error_when_journal_update_also_fails(case, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("private path")

    monkeypatch.setattr(case[2], "put_once", fail)
    monkeypatch.setattr(RunJournal, "record_result", fail)
    result = run(case)
    assert result["evidence_error"] == "private_evidence_failed"
    assert result["journal_error"] == "journal_result_failed"


def test_untyped_observation_cannot_claim_samples_or_persist_private_payload(case):
    case[1].observe_point = lambda **kwargs: {"sample_count": 1, "private": "unvalidated"}
    result = run(case)
    assert result["observation_status"] == "observation_invalid"
    assert result["sample_count"] == 0
    assert not (case[2].root / "observation.json").exists()
    assert case[1].calls.count("shutdown") == 1


@pytest.mark.parametrize(
    "code", ["no_samples", "permission_required", "observation_correlation_invalid"]
)
def test_probe_failure_retains_safe_status_and_still_closes(case, code):
    from swu_happyrun.drivers.command import ProbeError

    def fail(**kwargs):
        raise ProbeError(code)

    case[1].observe_point = fail
    result = run(case)
    assert result["observation_status"] == code
    assert result["sample_count"] == 0
    assert case[1].calls.count("shutdown") == 1
    assert not (case[2].root / "observation.json").exists()


def test_private_correlation_saved_but_public_report_contains_only_status_count(case):
    import json

    result = run(case)
    private = json.loads((case[2].root / "observation.json").read_text())
    assert result["sample_count"] == 1
    assert result["observation_status"] == "samples_within_declared_tolerance"
    assert "nonce" in json.dumps(private)
    assert "nonce" not in json.dumps(result)
    assert "tolerance_m" not in json.dumps(result)
    assert result["stop_status"] == "stop_unconfirmed"
    assert result["replay_enabled"] is False


def test_observation_persistence_failure_keeps_private_values_out_and_forbids_shutdown(
    case, monkeypatch
):
    original = case[2].put_once

    def fail(name, value):
        if name == "observation.json":
            raise OSError("private target and tolerance")
        return original(name, value)

    monkeypatch.setattr(case[2], "put_once", fail)
    result = run(case)
    assert result["evidence_error"] == "private_evidence_failed"
    assert result["observation_status"] == "observation_failed"
    assert result["sample_count"] == 0
    assert case[1].calls.count("probe") == 1
    assert "drain" in case[1].calls
    assert "shutdown" not in case[1].calls
    assert "private target" not in str(result)


def test_unknown_probe_error_text_is_not_public(case):
    from swu_happyrun.drivers.command import ProbeError

    def fail(**kwargs):
        raise ProbeError("secret-identifier")

    case[1].observe_point = fail
    result = run(case)
    assert result["observation_status"] == "observation_failed"
    assert "secret" not in str(result)
