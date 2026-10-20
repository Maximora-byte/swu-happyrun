"""Real adapter imports/composition with synthetic bytes, never device acceptance.

Run on the frozen N1+N2+N3 combination. The standalone N3 PR intentionally skips
this module until those separately reviewed implementations are present.
"""

import json
import subprocess
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_mumu_binding import sample
from test_mumu_virtual_replay import Clock, execution

from swu_happyrun.agent.journal import RunJournal, UnsafeReplay
from swu_happyrun.drivers.base import DriverError
from swu_happyrun.drivers.command import ProbeError
from swu_happyrun.drivers.mumu.binding import resolve_binding
from swu_happyrun.drivers.mumu.virtual_replay import VirtualReplaySession, run_local_cli

native = pytest.importorskip(
    "swu_happyrun.drivers.mumu.native_684", reason="N1 integration required"
)
probe_module = pytest.importorskip(
    "swu_happyrun.drivers.mumu.own_probe", reason="N2 integration required"
)


@pytest.fixture
def local_inputs(tmp_path):
    clock = Clock()
    observation = sample()
    observation["observed_at"] = clock.utcnow().isoformat()
    binding = resolve_binding(
        instance_index="0",
        adb_serial=observation["adb_serial"],
        observation=observation,
        now=clock.utcnow(),
    )
    binding_path = tmp_path / "binding.json"
    binding_path.write_text(json.dumps(observation), encoding="utf-8")
    targets = [{"latitude": 1.25, "longitude": 2.75}, {"latitude": 1.251, "longitude": 2.753}]
    calibration_path = tmp_path / "calibration.json"
    calibration_path.write_text(
        json.dumps(
            {
                "binding_digest": binding.digest,
                "host_version": binding.host_version,
                "engine_version": binding.engine_version,
                "app_version": binding.app_version,
                "channel": "location",
                "input_crs": "WGS84",
                "observed_at": clock.utcnow().isoformat(),
                "expires_at": (clock.utcnow() + timedelta(minutes=1)).isoformat(),
                "max_error_m": 5,
                "samples": [
                    {"target": point, "observed": point, "observed_crs": "WGS84"}
                    for point in targets
                ],
            }
        ),
        encoding="utf-8",
    )
    args = SimpleNamespace(
        manager=Path("synthetic-manager"),
        adb=Path("synthetic-adb"),
        serial=observation["adb_serial"],
        instance="0",
        binding=binding_path,
        calibration=calibration_path,
        journal=tmp_path / "agent.sqlite",
        device_id="00000000-0000-4000-8000-000000000004",
        recover_stop=False,
        no_interactive=True,
    )
    return args, binding, clock


def test_actual_cli_native_unknown_ack_never_retries_or_claims_stop(local_inputs, monkeypatch):
    from swu_happyrun.drivers import command

    args, binding, clock = local_inputs
    calls, constructed, reports = [], [], []
    original = probe_module.OwnProbe.__init__

    def record_constructor(self, *a, **kw):
        original(self, *a, **kw)
        constructed.append(self)

    def capture(path, *argv, timeout, before_spawn, cancel_event):
        before_spawn()
        calls.append(argv)
        return b"synthetic process exit only", b"", 0

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: pytest.fail("real process forbidden"))
    monkeypatch.setattr(command, "run_readonly", lambda *a, **kw: binding.boot_id)
    monkeypatch.setattr(native, "run_readonly", lambda *a, **kw: "35")
    monkeypatch.setattr(native, "_run_bounded_bytes", capture)
    monkeypatch.setattr(probe_module.OwnProbe, "__init__", record_constructor)

    assert run_local_cli(args, execution=execution(clock), clock=clock, emit=reports.append) == 3
    assert len(calls) == 1
    assert len(constructed) == 1 and type(constructed[0]) is probe_module.OwnProbe
    assert any(r.get("reason_code") == "write_ack_unconfirmed" for r in reports)
    assert reports[-1]["reason_code"] == "stop_unconfirmed"
    assert not reports[-1]["stop_confirmed"]
    assert not reports[-1]["record_verified"]
    assert run_local_cli(args, execution=execution(clock), clock=clock, emit=reports.append) == 3
    assert len(calls) == 1
    args.recover_stop = True
    assert run_local_cli(args, execution=None, clock=clock, emit=reports.append) == 3
    assert len(calls) == 1  # Actual native recovery stop never invokes a write.
    assert len(constructed) == 1  # Recovery does not create/restart observation.
    public = json.dumps(reports)
    for private in (args.serial, str(args.binding), binding.boot_id, "latitude", "longitude"):
        assert private not in public


def test_actual_own_probe_decoding_and_cleanup_error_keep_replay_uncertain(
    local_inputs, monkeypatch
):
    args, binding, clock = local_inputs
    points = []
    requests = []

    class SyntheticWriter:
        def __init__(self, check):
            self.check = check

        def write_location(self, point, *, deadline):
            self.check()
            points.append(point)

        def stop(self):
            pass  # Synthetic accepted transport, deliberately not native evidence.

    def command(self, argv, *, timeout):
        requests.append(argv)
        if "instrument" in argv:
            self._test_nonce = argv[argv.index("ownedObservationNonce") + 1]
            return b"OK (1 test)\nINSTRUMENTATION_CODE: -1\n"
        if "cat" in argv:
            return json.dumps(
                dict(
                    schema=1,
                    nonce=self._test_nonce,
                    binding_digest=binding.identity_digest,
                    boot_id=binding.boot_id,
                    channel="location",
                    duration_ms=250,
                    window_start_ns=10**12,
                    window_end_ns=10**12 + 250_000_000,
                    cleanup_confirmed=True,
                    status="samples_observed",
                    samples=[
                        dict(
                            channel="location",
                            elapsed_realtime_ns=10**12 + 1,
                            values=[points[-1].latitude, points[-1].longitude],
                            accuracy=1.0,
                        )
                    ],
                )
            ).encode()
        raise ProbeError("private_cleanup_unconfirmed")

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: pytest.fail("real process forbidden"))
    monkeypatch.setattr(probe_module.OwnProbe, "_command", command)
    with RunJournal(args.journal) as journal:
        session = VirtualReplaySession(
            execution(clock),
            journal=journal,
            device_id=args.device_id,
            native_factory=SyntheticWriter,
            probe_factory=lambda check: probe_module.OwnProbe(
                args.adb, binding, binding_check=lambda: None, authorization_check=check
            ),
            authorization_check=lambda: None,
            calibration_check=lambda: None,
            max_error_m=5,
            clock=clock,
        )
        try:
            with pytest.raises(ProbeError, match="cleanup_unconfirmed"):
                session.start()
            assert len(points) == 1
            assert any("run-as" in call and "cat" in call for call in requests)
            with pytest.raises(DriverError, match="stop_unconfirmed"):
                session.stop()
            assert not session.progress["stop_confirmed"]
        finally:
            session.close()


@pytest.mark.parametrize("outcome", ["ack", "timeout", "cleanup", "missing_delivery"])
def test_actual_single_point_only_observes_confirmed_process_exit(
    local_inputs, monkeypatch, outcome
):
    from swu_happyrun.core.models import GeoPoint
    from swu_happyrun.drivers.mumu import probe_point

    args, binding, clock = local_inputs
    args.duration_ms = 10
    args.private_output = args.journal.parent / "private-evidence.json"
    captures, observations, reports = [], [], []
    point = GeoPoint(latitude=1.25, longitude=2.75)

    def capture(path, *argv, timeout, before_spawn, cancel_event):
        before_spawn()
        captures.append(argv)
        if outcome in {"timeout", "cleanup"}:
            raise ProbeError(
                "command_timeout" if outcome == "timeout" else "command_cleanup_unconfirmed"
            )
        return b"synthetic exit only", b"", 0

    def command(self, argv, *, timeout):
        observations.append(argv)
        if "instrument" in argv:
            self._test_nonce = argv[argv.index("ownedObservationNonce") + 1]
            return b"OK (1 test)\nINSTRUMENTATION_CODE: -1\n"
        if "cat" in argv:
            return json.dumps(
                dict(
                    schema=1,
                    nonce=self._test_nonce,
                    binding_digest=binding.identity_digest,
                    boot_id=binding.boot_id,
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
                            values=[point.latitude, point.longitude],
                            accuracy=1.0,
                        )
                    ],
                )
            ).encode()
        return b""

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: pytest.fail("real process forbidden"))
    monkeypatch.setattr(probe_point, "run_readonly", lambda *a, **kw: binding.boot_id)
    monkeypatch.setattr(native, "run_readonly", lambda *a, **kw: "35")
    monkeypatch.setattr(native, "_run_bounded_bytes", capture)
    monkeypatch.setattr(probe_module.OwnProbe, "_command", command)
    if outcome == "missing_delivery":

        def no_receipt(*a, **kw):
            raise DriverError("write_ack_unconfirmed")

        monkeypatch.setattr(native.MuMuNative684, "write_location", no_receipt)
    assert probe_point.run_probe_point_cli(args, point=point, clock=clock, emit=reports.append) == 3
    result = reports[-1]
    assert not result["replay_enabled"]
    assert not result["record_verified"]
    assert result["stop_status"] == "stop_unconfirmed"
    if outcome == "ack":
        assert len(captures) == 1
        assert len(observations) == 3
        assert result["command_status"] == "write_ack_unconfirmed"
        assert result["observation_status"] == "samples_observed"
        assert result["private_evidence_saved"]
        evidence = json.loads(args.private_output.read_text())
        assert evidence["target"] == point.model_dump(mode="json")
        assert evidence["coordinate_semantics"] == "raw_vendor_unverified"
    else:
        assert observations == []
        assert not args.private_output.exists()
    before = len(captures)
    args.private_output = args.journal.parent / "second-private-evidence.json"
    assert probe_point.run_probe_point_cli(args, point=point, clock=clock, emit=reports.append) == 3
    assert len(captures) == before
    assert reports[-1]["reason_code"] == "probe_reservation_unresolved"
    assert "latitude" not in json.dumps(reports)
    assert args.serial not in json.dumps(reports)


@pytest.mark.parametrize("body_fails", [False, True])
@pytest.mark.parametrize("close_fails", [False, True])
@pytest.mark.parametrize("storage_error", [OSError, UnsafeReplay])
def test_cli_closes_real_session_after_stop_persistence_failure(
    local_inputs, monkeypatch, body_fails, close_fails, storage_error
):
    """Releasing the OS lock cannot clear unresolved durable exclusion."""
    from swu_happyrun.agent.journal import UnsafeReplay
    from swu_happyrun.drivers.mumu import virtual_replay as module

    args, _, clock = local_inputs
    state = {"writes": 0, "stops": 0, "closes": 0}
    body_error = RuntimeError("synthetic body failure")
    stop_error = storage_error("synthetic storage failure")
    close_error = OSError("synthetic close failure")
    reports = []

    class Session(VirtualReplaySession):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            state["session"] = self

        def close(self):
            state["closes"] += 1
            super().close()
            if close_fails:
                raise close_error

    class SyntheticNative:
        def __init__(self, *a, **kw):
            pass

        def write_location(self, point, *, deadline):
            state["writes"] += 1
            state["point"] = point
            if body_fails:
                raise body_error

        def stop(self):
            state["stops"] += 1
            session = state["session"]
            state["marker"] = session.journal.read_replay_reservation(args.device_id)

            def fail_persistence(*a, **kw):
                raise stop_error

            monkeypatch.setattr(session.journal, "_write_reservation", fail_persistence)
            raise DriverError("stop_unconfirmed")

    class SyntheticProbe:
        def __init__(self, *a, **kw):
            pass

        def sample(self, channel, *, duration_ms):
            point = state["point"]
            return (SimpleNamespace(channel=channel, values=(point.latitude, point.longitude)),)

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: pytest.fail("real process forbidden"))
    monkeypatch.setattr(module, "VirtualReplaySession", Session)
    monkeypatch.setattr(native, "MuMuNative684", SyntheticNative)
    monkeypatch.setattr(probe_module, "OwnProbe", SyntheticProbe)
    monkeypatch.setattr(module, "_run_control_loop", lambda *a: None)
    try:
        with pytest.raises((OSError, UnsafeReplay)) as caught:
            run_local_cli(args, execution=execution(clock), clock=clock, emit=reports.append)
        assert state["closes"] == 1
        assert state["session"]._device_lock is None
        assert state["writes"] == state["stops"] == 1
        assert caught.value is (close_error if close_fails else stop_error)
        chain = []
        error = caught.value
        while error is not None and error not in chain:
            chain.append(error)
            error = error.__context__
        assert stop_error in chain
        if body_fails:
            assert body_error in chain
        assert not state["session"].progress["stop_confirmed"]
        assert all(not report["stop_confirmed"] for report in reports)
        with RunJournal(args.journal) as journal:
            with pytest.raises(UnsafeReplay, match="replay_recovery_requires_stop"):
                with journal.device_lock(args.device_id):
                    pytest.fail("unresolved device became writable")
            with journal.replay_recovery_lock(args.device_id):
                # OS lock released, but durable exclusion remains unchanged.
                assert journal.read_replay_reservation(args.device_id) == state["marker"]
    finally:
        # Test cleanup also releases the lock on an unfixed implementation.
        VirtualReplaySession.close(state["session"])


def test_cli_closes_real_session_when_cleanup_report_fails(local_inputs, monkeypatch):
    from swu_happyrun.drivers.mumu import virtual_replay as module

    args, _, clock = local_inputs
    sessions, writes, stops = [], [], []
    reports = []
    report_error = OSError("synthetic output unavailable")

    class Session(VirtualReplaySession):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            sessions.append(self)

    class SyntheticNative:
        def __init__(self, *a, **kw):
            pass

        def write_location(self, point, *, deadline):
            writes.append(point)
            raise DriverError("write_ack_unconfirmed")

        def stop(self):
            stops.append(True)
            raise DriverError("stop_unconfirmed")

    def emit(report):
        reports.append(report)
        if len(reports) == 2:
            raise report_error

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: pytest.fail("real process forbidden"))
    monkeypatch.setattr(module, "VirtualReplaySession", Session)
    monkeypatch.setattr(native, "MuMuNative684", SyntheticNative)
    monkeypatch.setattr(probe_module, "OwnProbe", lambda *a, **kw: object())
    try:
        with pytest.raises(OSError) as caught:
            run_local_cli(args, execution=execution(clock), clock=clock, emit=emit)
        assert caught.value is report_error
        assert len(writes) == len(stops) == 1
        assert sessions[0]._device_lock is None
        assert not reports[-1]["stop_confirmed"]
        with RunJournal(args.journal) as journal:
            with journal.replay_recovery_lock(args.device_id):
                assert journal.read_replay_reservation(args.device_id)["status"] == "uncertain"
    finally:
        sessions[0].close()
