"""Synthetic controller tests, never MuMu or school-record acceptance."""

import json
from datetime import UTC, datetime

import pytest

from swu_happyrun.core.canonical import profile_revision
from swu_happyrun.core.models import GeoPoint, RouteProfile
from swu_happyrun.core.route import RouteExecution


class Clock:
    value = 0.0

    def monotonic(self):
        return self.value

    def utcnow(self):
        return datetime(2026, 10, 19, tzinfo=UTC)


def route():
    value = RouteProfile(
        route_id="00000000-0000-4000-8000-000000000003",
        revision="0" * 64,
        input_crs="WGS84",
        points=[GeoPoint(latitude=0.2, longitude=0.2), GeoPoint(latitude=0.2, longitude=0.21)],
        source_ref="synthetic local controller fixture",
    )
    value.revision = profile_revision(value)
    return value


def execution(clock=None, duration=30.0):
    return RouteExecution.for_local_replay(
        route(), speed_mps=2.0, maximum_duration_seconds=duration, clock=clock or Clock()
    )


def test_local_replay_does_not_fabricate_school_profile(monkeypatch):
    import swu_happyrun.core.route as module

    monkeypatch.setattr(module, "SchoolProfile", lambda *a, **kw: pytest.fail("fabricated school"))
    engine = execution()
    engine.start(now=0)
    end = engine.tick(now=100)
    assert end.distance_m == 60
    assert end.progress < 1
    assert end.state == "stopped"
    assert not end.finished
    assert end.position != route().points[-1]


def test_local_route_revision_is_verified():
    value = route()
    value.points[-1].longitude += 0.01
    with pytest.raises(ValueError, match="route_revision_mismatch"):
        RouteExecution.for_local_replay(
            value, speed_mps=2, maximum_duration_seconds=30, clock=Clock()
        )


@pytest.mark.parametrize("field", ["speed_mps", "maximum_duration_seconds"])
@pytest.mark.parametrize("bad", [0, -1, True, float("nan"), float("inf"), "3"])
def test_local_parameters_are_explicit_positive_finite_numbers(field, bad):
    kwargs = {"speed_mps": 2, "maximum_duration_seconds": 30, "clock": Clock()}
    kwargs[field] = bad
    with pytest.raises(ValueError):
        RouteExecution.for_local_replay(route(), **kwargs)


def test_preview_starts_zero_processes(tmp_path, monkeypatch, capsys):
    import subprocess

    from swu_happyrun.cli import main

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: pytest.fail("preview process"))
    path = tmp_path / "route.json"
    path.write_text(route().model_dump_json(), encoding="utf-8")
    assert (
        main(
            [
                "mumu",
                "replay",
                "--instance",
                "0",
                "--route",
                str(path),
                "--speed-mps",
                "2",
                "--duration-seconds",
                "30",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "preview"
    assert result["processes_started"] == 0
    assert result["record_verified"] is False
    assert not list(tmp_path.glob("*.sqlite"))


@pytest.fixture
def controller(tmp_path):
    from types import SimpleNamespace

    from swu_happyrun.agent.journal import RunJournal
    from swu_happyrun.drivers.base import DriverError
    from swu_happyrun.drivers.mumu.virtual_replay import VirtualReplaySession

    clock = Clock()
    controls = {
        "authorized": True,
        "confirmed": True,
        "sample_hook": None,
        "write_hook": None,
        "missing": False,
        "mismatch": False,
    }
    natives = []
    journal = RunJournal(tmp_path / "agent.sqlite")

    class SyntheticNative:
        def __init__(self, check):
            self.check = check
            self.points = []
            self.closed = False
            natives.append(self)

        def write_location(self, point, *, deadline):
            if controls["write_hook"]:
                controls["write_hook"]()
            self.check()
            if self.closed:
                raise DriverError("channel_halted")
            assert journal.has_intent(session._session_id, "start")
            assert session._read_marker()["status"] == "active"
            self.points.append(point.model_copy(deep=True))

        def stop(self):
            self.closed = True
            if not controls["confirmed"]:
                raise DriverError("stop_unconfirmed")

    class SyntheticProbe:
        def __init__(self, check):
            self.check = check

        def sample(self, channel, *, duration_ms):
            if controls["sample_hook"]:
                controls["sample_hook"]()
            self.check()
            if controls["missing"]:
                return ()
            point = natives[-1].points[-1]
            return (
                SimpleNamespace(
                    channel="location",
                    values=(point.latitude, point.longitude + (1 if controls["mismatch"] else 0)),
                    elapsed_realtime_ns=999999999999999,
                    accuracy=1.0,
                ),
            )

    def authorize():
        if not controls["authorized"]:
            raise DriverError("lease_expired")

    kwargs = dict(
        journal=journal,
        device_id="synthetic-device",
        native_factory=SyntheticNative,
        probe_factory=SyntheticProbe,
        authorization_check=authorize,
        calibration_check=lambda: None,
        max_error_m=5,
        clock=clock,
    )
    session = VirtualReplaySession(execution(clock), **kwargs)
    yield SimpleNamespace(
        session=session,
        clock=clock,
        controls=controls,
        natives=natives,
        journal=journal,
        kwargs=kwargs,
        cls=VirtualReplaySession,
    )
    session.close()
    journal.close()


def test_late_tick_never_bursts_missed_points(controller):
    c = controller
    c.session.start()
    c.clock.value = 20
    result = c.session.tick()
    assert result["writes"] == 2
    assert result["distance_m"] == 40
    assert len(c.natives[0].points) == 2
    assert "latitude" not in json.dumps(result)
    assert "longitude" not in json.dumps(result)


def test_pause_cancel_or_lease_loss_adds_no_writes(controller):
    c = controller
    c.session.start()
    c.clock.value = 2
    c.session.pause()
    assert c.session.progress["status"] == "paused"
    c.clock.value = 10
    with pytest.raises(ValueError):
        c.session.tick()
    assert len(c.natives[0].points) == 1
    c.session.resume()
    c.clock.value = 11
    c.session.tick()
    assert c.session.progress["distance_m"] == 6
    assert len(c.natives[1].points) == 1
    c.controls["authorized"] = False
    with pytest.raises(ValueError, match="lease_expired"):
        c.session.tick()
    assert len(c.natives[1].points) == 1
    c.session.stop()
    with pytest.raises(ValueError):
        c.session.resume()


def test_cancel_between_observation_and_final_write_is_rechecked(controller):
    c = controller
    c.session.start()
    c.controls["write_hook"] = c.session.request_halt
    c.clock.value = 1
    with pytest.raises(ValueError, match="cancel_requested"):
        c.session.tick()
    assert len(c.natives[0].points) == 1


def test_old_generation_cannot_write_after_pause_resume(controller):
    c = controller
    c.session.start()
    old = c.natives[0]
    c.session.pause()
    c.session.resume()
    with pytest.raises(ValueError, match="generation"):
        old.write_location(route().points[0], deadline=5)
    assert len(old.points) == 1


def test_uncertain_stop_is_not_reported_success(controller):
    c = controller
    c.session.start()
    c.controls["confirmed"] = False
    with pytest.raises(ValueError, match="stop_unconfirmed"):
        c.session.stop()
    result = c.session.progress
    assert result["status"] == "needs_attention"
    assert result["stop_confirmed"] is False
    assert c.session._read_marker()["status"] == "uncertain"
    with pytest.raises(ValueError):
        c.session.resume()


def test_crash_restart_requires_explicit_stop_never_replays(controller):
    from swu_happyrun.agent.journal import UnsafeReplay

    c = controller
    c.session.start()
    c.session.close()  # Simulated lost owner; deliberately not a stop acknowledgment.
    recovered = c.cls(execution(c.clock), **c.kwargs)
    try:
        with pytest.raises(UnsafeReplay, match="recovery_requires_stop"):
            recovered.start()
        assert len(c.natives) == 1
        recovered.recover_stop()
        assert len(c.natives) == 2
        assert c.natives[1].points == []
        assert recovered.progress["stop_confirmed"]
        with pytest.raises(ValueError):
            recovered.start()
    finally:
        recovered.close()


def test_another_session_cannot_own_the_device(controller):
    from swu_happyrun.agent.journal import UnsafeReplay

    c = controller
    c.session.start()
    other = c.cls(execution(c.clock), **c.kwargs)
    try:
        with pytest.raises(UnsafeReplay, match="locked"):
            other.start()
        assert len(c.natives) == 1
    finally:
        other.close()


@pytest.mark.parametrize("fault", ["missing", "mismatch"])
def test_readback_failure_is_uncertain_and_never_retried(controller, fault):
    c = controller
    c.controls[fault] = True
    with pytest.raises(ValueError, match="readback"):
        c.session.start()
    assert len(c.natives[0].points) == 1
    with pytest.raises(ValueError):
        c.session.start()
    assert len(c.natives[0].points) == 1
    assert c.session.progress["status"] == "needs_attention"


def test_duration_cutoff_does_not_emit_endpoint_or_overdue_point(controller):
    c = controller
    c.session.start()
    c.clock.value = 100
    result = c.session.tick()
    assert len(c.natives[0].points) == 1
    assert result["reason_code"] == "duration_limit"
    assert result["distance_m"] == 60
    assert not result["route_finished"]
    assert result["stop_confirmed"]


def test_cancel_requested_during_probe_does_not_get_cleared(controller):
    c = controller
    c.session.start()
    c.controls["sample_hook"] = c.session.request_halt
    c.clock.value = 1
    with pytest.raises(ValueError, match="cancel_requested"):
        c.session.tick()
    count = sum(len(n.points) for n in c.natives)
    with pytest.raises(ValueError):
        c.session.tick()
    assert sum(len(n.points) for n in c.natives) == count


def test_pause_at_duration_cutoff_cannot_resume_completed_prefix(controller):
    c = controller
    c.session.start()
    c.clock.value = 100
    result = c.session.pause()
    assert result["status"] == "stopped"
    assert result["reason_code"] == "duration_limit"
    with pytest.raises(ValueError):
        c.session.resume()


def test_unowned_stop_cannot_overwrite_another_session_marker(controller):
    c = controller
    c.session.start()
    before = c.session._read_marker()
    other = c.cls(execution(c.clock), **c.kwargs)
    try:
        with pytest.raises(ValueError, match="owner"):
            other.stop()
        assert c.session._read_marker() == before
    finally:
        other.close()


def test_pause_request_never_overrides_cancel(controller):
    c = controller
    c.session.start()
    c.session.request_halt()
    c.session.request_halt("pause_requested")
    with pytest.raises(ValueError, match="cancel_requested"):
        c.session.tick()
    assert len(c.natives[0].points) == 1


def test_cancel_during_resume_calibration_cannot_reopen_gate(controller):
    c = controller
    c.session.start()
    c.session.pause()
    c.session._calibration_check = c.session.request_halt
    with pytest.raises(ValueError):
        c.session.resume()
    assert len(c.natives) == 1


def test_final_native_gate_enforces_duration_after_observation(controller):
    c = controller
    c.session.start()
    c.controls["write_hook"] = lambda: setattr(c.clock, "value", 31)
    c.clock.value = 1
    with pytest.raises(ValueError, match="duration_limit"):
        c.session.tick()
    assert len(c.natives[0].points) == 1


def test_constructor_without_local_factory_is_not_execution_authority(controller):
    from test_route_engine import engine_fixture

    c = controller
    with pytest.raises(ValueError, match="not_ready"):
        c.cls(engine_fixture()[0], **c.kwargs)


def test_preview_does_not_import_native_adapters(tmp_path, monkeypatch, capsys):
    import builtins

    from swu_happyrun.cli import main

    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        assert not name.endswith(("native_684", "own_probe"))
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    path = tmp_path / "route.json"
    path.write_text(route().model_dump_json(), encoding="utf-8")
    assert (
        main(
            [
                "mumu",
                "replay",
                "--instance",
                "0",
                "--route",
                str(path),
                "--speed-mps",
                "2",
                "--duration-seconds",
                "30",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == "preview"


def test_actual_execution_missing_evidence_is_blocked_without_processes(
    tmp_path, monkeypatch, capsys
):
    import subprocess

    from swu_happyrun.cli import main

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: pytest.fail("unexpected process"))
    path = tmp_path / "route.json"
    path.write_text(route().model_dump_json(), encoding="utf-8")
    assert (
        main(
            [
                "mumu",
                "replay",
                "--instance",
                "0",
                "--route",
                str(path),
                "--speed-mps",
                "2",
                "--duration-seconds",
                "30",
                "--execute-virtual-replay",
                "--isolated-no-personal-data",
            ]
        )
        == 3
    )
    assert json.loads(capsys.readouterr().out)["reason_code"] == "enrollment_execution_not_ready"


def test_oversized_control_line_is_bounded_and_requests_stop(controller):
    from queue import Queue

    from swu_happyrun.drivers.mumu.virtual_replay import _read_control_commands

    class LongInput:
        def readline(self, size=-1):
            assert size == 65
            return "x" * size

    c = controller
    c.session.start()
    _read_control_commands(LongInput(), c.session, Queue(maxsize=16))
    with pytest.raises(ValueError, match="cancel_requested"):
        c.session.tick()
    assert len(c.natives[0].points) == 1


def test_progress_command_flood_does_not_delay_duration_stop(controller):
    from queue import Queue

    from swu_happyrun.drivers.mumu.virtual_replay import _run_control_loop

    c = controller
    c.session.start()
    commands = Queue(maxsize=16)
    for _ in range(16):
        commands.put_nowait("progress")
    outputs = []

    class Shutdown:
        def check(self):
            pass

        def wait(self, seconds):
            c.clock.value += 10

    _run_control_loop(c.session, Shutdown(), commands, outputs.append)
    assert c.session.progress["stop_confirmed"]
    assert c.session.progress["reason_code"] == "duration_limit"
    assert c.clock.value == 30
    assert len(c.natives[0].points) <= 4


def test_probe_cleanup_uncertainty_survives_native_stop_and_recovery(controller):
    from swu_happyrun.drivers.command import ProbeError

    c = controller

    def failed():
        raise ProbeError("private_cleanup_unconfirmed")

    c.controls["sample_hook"] = failed
    with pytest.raises(ProbeError):
        c.session.start()
    with pytest.raises(ValueError, match="stop_unconfirmed"):
        c.session.stop()
    assert not c.session.progress["stop_confirmed"]
    c.session.close()
    recovered = c.cls(None, **c.kwargs)
    try:
        with pytest.raises(ValueError, match="stop_unconfirmed"):
            recovered.recover_stop()
        assert not recovered.progress["stop_confirmed"]
        assert sum(len(n.points) for n in c.natives) == 1
    finally:
        recovered.close()


def test_point_preview_does_not_start_processes_or_require_calibration(
    tmp_path, monkeypatch, capsys
):
    import subprocess

    from swu_happyrun.cli import main

    path = tmp_path / "point.json"
    path.write_text('{"latitude":1.25,"longitude":2.75}', encoding="utf-8")
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: pytest.fail("preview process"))
    assert main(["mumu", "probe-point", "--instance", "0", "--point", str(path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["processes_started"] == 0
    assert result["coordinate_semantics"] == "raw_vendor_unverified"
    assert not list(tmp_path.glob("*.sqlite"))


@pytest.mark.parametrize(
    "failure",
    [OSError("private stream error"), UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid")],
)
def test_control_read_error_requests_stop_without_leaking_exception(controller, failure):
    from queue import Queue

    from swu_happyrun.drivers.mumu.virtual_replay import _read_control_commands

    class BrokenInput:
        def readline(self, size):
            raise failure

    c = controller
    c.session.start()
    _read_control_commands(BrokenInput(), c.session, Queue(maxsize=16))
    with pytest.raises(ValueError, match="cancel_requested"):
        c.session.tick()
    assert len(c.natives[0].points) == 1
