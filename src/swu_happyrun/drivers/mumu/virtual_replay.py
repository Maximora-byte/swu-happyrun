"""Local virtual playback; no remote JobSpec, app actions, or school records.

The owner thread serializes route/journal operations. Other threads may only
request_halt(); this closes the fast final-write gate immediately. Native calls
and probe calls must enforce their own hard process budgets. No point queue is
created, and recovery can only inspect/stop the previous unresolved session.
"""

import json
import math
from collections.abc import Callable
from pathlib import Path
from threading import Event, Lock, RLock, get_ident
from typing import Protocol
from uuid import uuid4

from swu_happyrun.agent.journal import RunJournal, UnsafeReplay
from swu_happyrun.core.clock import Clock
from swu_happyrun.core.geo import distance_between_points_m
from swu_happyrun.core.models import GeoPoint
from swu_happyrun.core.route import RouteExecution
from swu_happyrun.drivers.base import DriverError


class NativeWriter(Protocol):
    def write_location(self, point: GeoPoint, *, deadline: float) -> None: ...
    def stop(self) -> None: ...


class Probe(Protocol):
    def sample(self, channel: str, *, duration_ms: int) -> tuple: ...


class VirtualReplaySession:
    """Single local owner, durable exclusion, generation-specific adapters.

    Factory callbacks are dependency-injection seams, not evidence. The real CLI
    constructs MuMuNative684 and OwnProbe; tests explicitly supply synthetic
    implementations. Every replacement writer gets a fresh generation guard.
    A pause closes its writer permanently and requires an acknowledged stop
    before explicit resume can construct another. The original start intent
    covers that one in-process session, never an automatic crash restart.
    """

    def __init__(
        self,
        execution: RouteExecution | None,
        *,
        journal: RunJournal,
        device_id: str,
        native_factory: Callable[[Callable[[], None]], NativeWriter],
        probe_factory: Callable[[Callable[[], None]], Probe],
        authorization_check: Callable[[], None],
        calibration_check: Callable[[], None],
        max_error_m: float,
        clock: Clock,
        action_timeout_seconds: float = 5.0,
        sample_duration_ms: int = 250,
    ):
        if execution is not None and (
            execution.snapshot.state != "ready"
            or not hasattr(execution, "maximum_duration_seconds")
        ):
            raise DriverError("replay_route_not_ready")
        if not device_id or not isinstance(device_id, str):
            raise DriverError("invalid_device_id")
        for value in (max_error_m, action_timeout_seconds):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise DriverError("invalid_replay_budget")
        if (
            action_timeout_seconds > 5
            or type(sample_duration_ms) is not int
            or not 1 <= sample_duration_ms <= 5000
        ):
            raise DriverError("invalid_replay_budget")
        self.execution = execution
        self.journal = journal
        self.device_id = device_id
        self.clock = clock
        self._native_factory = native_factory
        self._probe_factory = probe_factory
        self._authorization_check = authorization_check
        self._calibration_check = calibration_check
        self._max_error_m = float(max_error_m)
        self._timeout = float(action_timeout_seconds)
        self._sample_duration_ms = sample_duration_ms
        self._owner = get_ident()
        self._lock = RLock()
        self._halt = Event()
        self._gate_lock = Lock()
        self._halt_reason = "cancel_requested"
        self._generation = 0
        self._native = None
        self._probe = None
        self._device_lock = None
        self._reservation = None
        self._session_id = str(uuid4())
        self._state = "ready"
        self._reason = None
        self._stop_confirmed = False
        self._writes = 0
        self._intent_recorded = False
        self._deadline = None
        self._last_confirmed = None
        self._probe_pending = False

    def _owner_only(self):
        if get_ident() != self._owner:
            raise DriverError("replay_owner_thread_required")

    def _read_marker(self):
        return self.journal.read_replay_reservation(self.device_id)

    def _persist(self, status):
        if self._reservation is None:
            if status != "active":
                raise UnsafeReplay("device reservation owner required")
            self._reservation = self.journal.reserve_replay(
                self.device_id, self._session_id, generation=self._generation
            )
        else:
            self.journal.update_replay(
                self._reservation,
                generation=self._generation,
                status=status,
                probe_pending=self._probe_pending,
            )

    def _acquire_device(self, *, recovery=False):
        if self._device_lock is None:
            context = (
                self.journal.replay_recovery_lock(self.device_id)
                if recovery
                else self.journal.device_lock(self.device_id)
            )
            permit = context.__enter__()
            self._device_lock = context
            if recovery:
                self._reservation = permit

    def request_halt(self, reason="cancel_requested"):
        """Thread-safe, nonblocking invalidation, including during observation.

        The owner must subsequently call pause/stop. It must not start another
        tick while a request is pending. Only explicit resume clears a pause.
        """
        if reason not in {"cancel_requested", "pause_requested", "lease_expired"}:
            raise DriverError("invalid_halt_reason")
        with self._gate_lock:
            # A pause must never downgrade a cancellation or expired lease.
            if self._halt.is_set() and self._halt_reason != "pause_requested":
                return
            self._halt_reason = reason
            self._halt.set()

    def _check(self, generation, *, observing=False):
        # No external observations after this final gate in the native adapter.
        if self._halt.is_set():
            raise DriverError(self._halt_reason)
        if generation != self._generation or self._state != "running":
            raise DriverError("replay_generation_expired")
        self._authorization_check()
        if self._deadline is None or self.clock.monotonic() >= self._deadline:
            raise DriverError("duration_limit")
        if self._halt.is_set() or generation != self._generation:
            raise DriverError(self._halt_reason)
        self.journal.verify_replay(self._reservation, generation=generation)
        marker = self._read_marker()
        if (
            not self._intent_recorded
            or not self.journal.has_intent(self._session_id, "start")
            or marker is None
            or marker["session_id"] != self._session_id
            or marker["status"] != "active"
            or marker["generation"] != generation
        ):
            raise DriverError("replay_intent_missing")
        if self._probe_pending and not observing:
            raise DriverError("replay_observation_pending")
        self._calibration_check()
        # Disk/authorization checks can themselves consume a lease or set halt.
        self._authorization_check()
        if self._deadline is None or self.clock.monotonic() >= self._deadline:
            raise DriverError("duration_limit")
        if self._halt.is_set() or generation != self._generation:
            raise DriverError(self._halt_reason)

    def _new_adapters(self):
        generation = self._generation

        def check():
            self._check(generation)

        self._native = self._native_factory(check)

        def observation_check():
            self._check(generation, observing=True)

        self._probe = self._probe_factory(observation_check)

    @property
    def progress(self):
        value = self.execution.snapshot if self.execution is not None else None
        return {
            "status": self._state,
            "reason_code": self._reason,
            "distance_m": value.distance_m if value else 0.0,
            "total_distance_m": value.total_distance_m if value else 0.0,
            "progress": value.progress if value else 0.0,
            "elapsed_seconds": value.elapsed_seconds if value else 0.0,
            "route_finished": bool(self._last_confirmed and self._last_confirmed.finished),
            "last_confirmed_distance_m": (
                self._last_confirmed.distance_m if self._last_confirmed else 0.0
            ),
            "writes": self._writes,
            "stop_confirmed": self._stop_confirmed,
            "observation_cleanup_confirmed": not self._probe_pending,
            "record_verified": False,
        }

    def start(self):
        self._owner_only()
        with self._lock:
            if self._state != "ready" or self.execution is None:
                raise DriverError("replay_start_forbidden")
            self._acquire_device()
            marker = self._read_marker()
            if marker is not None and marker["status"] != "stopped":
                raise UnsafeReplay("replay_recovery_requires_stop")
            self._authorization_check()
            self._calibration_check()
            self._generation += 1
            self._persist("active")
            self.journal.record_intent(self._session_id, self._generation, "start")
            self._intent_recorded = True
            self._state = "running"
            try:
                self._new_adapters()
                self._deadline = self.clock.monotonic() + self.execution.maximum_duration_seconds
                self.execution.start()
                self._write_current()
                self.journal.record_result(self._session_id, 1, "start", "confirmed")
            except BaseException:
                self._state = "needs_attention"
                self._reason = "replay_write_uncertain"
                self.request_halt()
                self._persist("uncertain")
                raise
            return self.progress

    def _write_current(self):
        self._calibration_check()
        self._check(self._generation)
        point = self.execution.snapshot.position
        self._native.write_location(
            point, deadline=min(self.clock.monotonic() + self._timeout, self._deadline)
        )
        self._writes += 1
        self._probe_pending = True
        self._persist("active")
        samples = self._probe.sample("location", duration_ms=self._sample_duration_ms)
        self._probe_pending = False
        self._persist("active")
        self._check(self._generation)
        if not samples:
            raise DriverError("replay_readback_missing")
        # OwnProbe validates nonce, boot, sample age, ordering and listener cleanup.
        # Device elapsedRealtime is never compared against this host clock.
        for sample in samples:
            if sample.channel != "location" or len(sample.values) != 2:
                raise DriverError("replay_readback_invalid")
            observed = GeoPoint(latitude=sample.values[0], longitude=sample.values[1])
            if distance_between_points_m(point, observed) > self._max_error_m:
                raise DriverError("replay_readback_mismatch")
        self._last_confirmed = self.execution.snapshot

    def tick(self):
        self._owner_only()
        with self._lock:
            if self._state != "running":
                raise DriverError("replay_tick_forbidden")
            try:
                if self._deadline is not None and self.clock.monotonic() >= self._deadline:
                    self.execution.tick()
                    self._reason = "duration_limit"
                    return self.stop()
                self._check(self._generation)
                self.execution.tick()
                self._write_current()
                if self.execution.snapshot.finished:
                    self._reason = "route_finished"
                    return self.stop()
                return self.progress
            except BaseException as error:
                if isinstance(error, DriverError) and error.reason_code == "pause_requested":
                    return self.pause()
                self._state = "needs_attention"
                self._reason = (
                    error.reason_code
                    if isinstance(error, DriverError)
                    else "replay_write_uncertain"
                )
                self.request_halt()
                self._persist("uncertain")
                try:
                    self.stop()
                except DriverError:
                    pass  # Keep the original failure plus stop_unconfirmed in progress.
                raise

    def pause(self):
        self._owner_only()
        if self._state != "running":
            raise DriverError("replay_pause_forbidden")
        self.request_halt("pause_requested")
        with self._lock:
            self._generation += 1
            self.execution.pause()
            try:
                self._native.stop()
                if self._probe_pending:
                    raise DriverError("stop_unconfirmed")
            except BaseException:
                self._state = "needs_attention"
                self._reason = "stop_unconfirmed"
                self._persist("uncertain")
                raise DriverError("stop_unconfirmed") from None
            self._stop_confirmed = True
            if self.execution.snapshot.state in {"completed", "stopped"}:
                self._state = "stopped"
                self._reason = "duration_limit"
                self._persist("stopped")
            else:
                self._state = "paused"
                self._persist("active")
            return self.progress

    def resume(self):
        self._owner_only()
        with self._lock:
            if (
                self._state != "paused"
                or not self._stop_confirmed
                or self._halt_reason != "pause_requested"
            ):
                raise DriverError("replay_resume_forbidden")
            self._authorization_check()
            self._calibration_check()
            self._generation += 1
            self._persist("active")
            with self._gate_lock:
                if self._halt_reason != "pause_requested":
                    raise DriverError(self._halt_reason)
                self._halt.clear()
            self._state = "running"
            self._stop_confirmed = False
            self._deadline = (
                self.clock.monotonic()
                + self.execution.maximum_duration_seconds
                - self.execution.snapshot.elapsed_seconds
            )
            self.execution.resume()
            self._new_adapters()
            return self.progress

    def stop(self):
        self._owner_only()
        if self._device_lock is None or self._native is None:
            raise DriverError("replay_stop_requires_owner")
        self.request_halt()
        with self._lock:
            if self._state == "stopped" and self._stop_confirmed:
                return self.progress
            self._generation += 1
            if self.execution is not None:
                self.execution.stop()
            try:
                if self._native is None:
                    raise DriverError("stop_unconfirmed")
                self._native.stop()
                if self._probe_pending:
                    raise DriverError("stop_unconfirmed")
                self._persist("stopped")
            except BaseException:
                self._state = "needs_attention"
                self._stop_confirmed = False
                self._reason = "stop_unconfirmed"
                self._persist("uncertain")
                raise DriverError("stop_unconfirmed") from None
            self._state = "stopped"
            self._stop_confirmed = True
            return self.progress

    def recover_stop(self):
        """Explicit recovery never calls start, tick, or writes a location."""
        self._owner_only()
        with self._lock:
            if self._state != "ready":
                raise DriverError("replay_recovery_forbidden")
            self._acquire_device(recovery=True)
            marker = self._read_marker()
            if marker is None or marker["status"] == "stopped":
                raise DriverError("replay_recovery_not_needed")
            self._session_id = marker["session_id"]
            self._generation = marker["generation"]
            self._probe_pending = marker["probe_pending"]
            self.request_halt()
            self._native = self._native_factory(
                lambda: (_ for _ in ()).throw(DriverError("recovery_write_forbidden"))
            )
            return self.stop()

    def close(self):
        """Release only the process lock; unresolved durable exclusion remains.

        Caller must explicitly stop first. Closing is never a stop acknowledgment.
        """
        self._owner_only()
        self.request_halt()
        if self._device_lock is not None:
            self._device_lock.__exit__(None, None, None)
            self._device_lock = None


def read_private_json(path: Path):
    """Bounded, duplicate-key-rejecting local input; never follow source_ref."""
    from swu_happyrun.core.profiles import _unique_keys

    path = Path(path)
    if path.is_symlink() or path.stat().st_size > 1_000_000:
        raise DriverError("replay_input_invalid")
    with path.open(encoding="utf-8") as handle:
        return json.load(handle, object_pairs_hook=_unique_keys)


def _read_calibration(path, binding, clock):
    from datetime import datetime

    from swu_happyrun.drivers.mumu.calibration import CalibrationRecord, CalibrationSample

    try:
        data = read_private_json(path)
        if set(data) != set(CalibrationRecord.__dataclass_fields__):
            raise ValueError
        samples = []
        for item in data["samples"]:
            if set(item) != set(CalibrationSample.__dataclass_fields__):
                raise ValueError
            samples.append(
                CalibrationSample(
                    target=GeoPoint.model_validate(item["target"]),
                    observed=GeoPoint.model_validate(item["observed"]),
                    observed_crs=item["observed_crs"],
                )
            )
        data["samples"] = tuple(samples)
        data["observed_at"] = datetime.fromisoformat(data["observed_at"])
        data["expires_at"] = datetime.fromisoformat(data["expires_at"])
        calibration = CalibrationRecord(**data)
        calibration.validate(binding, now=clock.utcnow(), channel="location")
        if (
            calibration.input_crs != "WGS84"
            or len(samples) < 2
            or len({(s.target.latitude, s.target.longitude) for s in samples}) < 2
            or any(s.target.latitude == s.target.longitude for s in samples)
        ):
            raise DriverError("replay_location_calibration_required")
        return calibration
    except (ValueError, TypeError, KeyError, AttributeError):
        raise DriverError("replay_location_calibration_required") from None


def run_local_cli(args, *, execution, clock, emit):
    """Construct real adapters only. Missing evidence never selects a fake backend."""
    import sys
    from queue import Queue
    from threading import Thread

    from swu_happyrun.agent.lifecycle import Shutdown, ShutdownRequested
    from swu_happyrun.drivers.command import ProbeError, run_readonly
    from swu_happyrun.drivers.mumu.binding import resolve_binding

    try:
        from swu_happyrun.drivers.mumu.native_684 import MuMuNative684
        from swu_happyrun.drivers.mumu.own_probe import OwnProbe
    except ImportError:
        raise DriverError("replay_native_adapter_unavailable") from None

    binding = resolve_binding(
        instance_index=args.instance,
        adb_serial=args.serial,
        observation=read_private_json(args.binding),
        now=clock.utcnow(),
    )
    calibration = None if args.recover_stop else _read_calibration(args.calibration, binding, clock)

    def binding_check():
        binding.assert_current(read_private_json(args.binding), now=clock.utcnow())
        boot = run_readonly(
            args.adb,
            "-s",
            args.serial,
            "shell",
            "cat",
            "/proc/sys/kernel/random/boot_id",
            timeout=5,
        ).strip()
        if boot != binding.boot_id:
            raise DriverError("binding_changed")

    def calibration_check():
        if calibration is None:
            raise DriverError("replay_location_calibration_required")
        calibration.validate(binding, now=clock.utcnow(), channel="location")

    shutdown = Shutdown()
    commands = Queue(maxsize=16)
    with RunJournal(args.journal) as journal, shutdown.signals():
        session = VirtualReplaySession(
            execution,
            journal=journal,
            device_id=args.device_id,
            native_factory=lambda check: MuMuNative684(
                args.manager,
                binding,
                adb=args.adb,
                binding_check=binding_check,
                authorization_check=check,
                clock=clock,
            ),
            probe_factory=lambda check: OwnProbe(
                args.adb,
                binding,
                binding_check=binding_check,
                authorization_check=check,
            ),
            authorization_check=shutdown.check,
            calibration_check=calibration_check,
            max_error_m=calibration.max_error_m if calibration else 1.0,
            clock=clock,
        )

        try:
            if args.recover_stop:
                emit(session.recover_stop())
                return 0
            emit(session.start())
            if not args.no_interactive:
                Thread(
                    target=_read_control_commands, args=(sys.stdin, session, commands), daemon=True
                ).start()
            _run_control_loop(session, shutdown, commands, emit)
            return 0 if session.progress["stop_confirmed"] else 3
        except (
            DriverError,
            ProbeError,
            UnsafeReplay,
            ShutdownRequested,
            KeyboardInterrupt,
        ) as error:
            reason = (
                error.reason_code
                if isinstance(error, DriverError)
                else error.code
                if isinstance(error, ProbeError)
                else "replay_interrupted_or_unresolved"
            )
            emit(
                {
                    "status": "needs_attention",
                    "reason_code": reason,
                    "stop_confirmed": False,
                    "record_verified": False,
                }
            )
            return 3
        finally:
            # A failed start still left durable intent before any device action.
            try:
                if session._native is not None and not session.progress["stop_confirmed"]:
                    try:
                        emit(session.stop())
                    except DriverError:
                        emit(session.progress)
            finally:
                # Storage/reporting failures must not skip process-lock release.
                # Closing never clears the durable marker or acknowledges stop.
                session.close()


def _read_control_commands(stream, session, commands):
    """Bound memory before parsing; this thread never touches journal/adapters."""
    from queue import Full

    while True:
        try:
            line = stream.readline(65)
        except (OSError, UnicodeError):
            session.request_halt()
            return
        if not line or len(line) > 64:
            session.request_halt()
            return
        command = line.strip().lower()
        if command in {"pause", "stop"}:
            session.request_halt("pause_requested" if command == "pause" else "cancel_requested")
        if command in {"pause", "resume", "stop", "progress"}:
            try:
                commands.put_nowait(command)
            except Full:
                pass  # Fast halt latch is independent of this bounded control queue.


def _run_control_loop(session, shutdown, commands, emit):
    from queue import Empty

    while session.progress["status"] in {"running", "paused"}:
        shutdown.check()
        if session._halt.is_set() and session._halt_reason != "pause_requested":
            emit(session.stop())
            break
        # Control traffic cannot defer the independent active-duration cutoff.
        if (
            session.progress["status"] == "running"
            and session._deadline is not None
            and session.clock.monotonic() >= session._deadline
        ):
            emit(session.tick())
            break
        try:
            command = commands.get_nowait()
        except Empty:
            command = None
        if command == "stop":
            emit(session.stop())
            break
        if command == "pause" and session.progress["status"] == "running":
            emit(session.pause())
        elif command == "resume":
            emit(session.resume())
        elif command == "progress":
            emit(session.progress)
        if session.progress["status"] == "running":
            emit(session.tick())
        if session.progress["status"] == "stopped":
            break
        # Waiting from now, not the previous target time, never catches up a queue.
        shutdown.wait(0.5)
