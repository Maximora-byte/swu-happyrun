"""In-memory simulation only. Never emits physical capabilities or app records."""

import json
import math
import os
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from swu_happyrun.core.clock import Clock, SystemClock
from swu_happyrun.core.models import DeviceCapability, JobSpec, JobView, VerificationResult
from swu_happyrun.core.profiles import LocalProfileStore
from swu_happyrun.core.route import RouteExecution, RouteProgress
from swu_happyrun.drivers.base import DriverError


class FakeDriver:
    def __init__(
        self,
        device_id: str,
        profiles: LocalProfileStore,
        *,
        clock: Clock | None = None,
        app_version: str = "test-1",
        scenario: str | None = None,
        state_path: Path | None = None,
        route_speed_mps: float | None = None,
    ):
        if scenario is not None and scenario not in {
            "normal",
            "start_crash",
            "upload_uncertain",
            "stop_failure",
            "inspect_timeout",
            "tick_failure",
        }:
            raise ValueError("unknown_fake_scenario")
        self.scenario = scenario or "normal"
        self._stop_failures_remaining = 1 if scenario == "stop_failure" else 0
        self.device_id = device_id
        self.profiles = profiles
        self.clock = clock or SystemClock()
        self.app_version = app_version
        self._route_speed_mps = route_speed_mps
        self._route: RouteExecution | None = None
        self._route_finished = False
        self.start_count = 0
        self.tick_count = 0
        self.stop_count = 0
        self._job: JobSpec | None = None
        self._bound_view: JobView | None = None
        self._active = False
        self._stopped = False
        self._elapsed = 0.0
        self._started = False
        self._lock = threading.RLock()
        self._execution_guard: Callable[[], None] = lambda: None
        self._state_path = Path(state_path) if state_path is not None else None
        self._load_state(scenario)

    def bind_session(self, view: JobView) -> None:
        with self._lock:
            view = JobView.model_validate(view.model_dump(mode="python"))
            if (
                view.run_session_id is None
                or view.spec.device_id != self.device_id
                or view.spec.mode != "simulation"
            ):
                raise DriverError("session_mismatch")
            previous = self._bound_view
            if previous is not None:
                if previous.job_id == view.job_id:
                    if previous.run_session_id != view.run_session_id or previous.spec != view.spec:
                        raise DriverError("session_mismatch")
                    if view.fence < previous.fence:
                        raise DriverError("stale_fence")
                else:
                    if self._active or previous.run_session_id == view.run_session_id:
                        raise DriverError("session_mismatch")
                    self._route = None
                    self._route_finished = False
                    self._job = None
                    self._started = False
                    self._stopped = False
                    self._elapsed = 0.0
            self._bound_view = view.model_copy(deep=True)
            self._save_state()

    def configure_execution_guard(self, check: Callable[[], None]) -> None:
        with self._lock:
            self._execution_guard = check

    def inspect(self) -> DeviceCapability:
        if self.scenario == "inspect_timeout":
            raise TimeoutError("fake_inspect_timeout")
        return DeviceCapability(
            device_id=self.device_id,
            probe_id=str(uuid4()),
            backend="fake",
            app_version=self.app_version,
            capabilities=[],
            observed_at=self.clock.utcnow(),
        )

    def _check_run_binding(self) -> None:
        if self._bound_view is None:
            raise DriverError("session_mismatch")
        if self._bound_view.desired_state == "cancel":
            raise DriverError("cancel_requested")
        if self._bound_view.recovery_action in {"verify_only", "stop_only"}:
            raise DriverError("recovery_cannot_start")

    def _validate(self, job: JobSpec) -> None:
        self._check_run_binding()
        if job.mode != "simulation":
            raise DriverError("fake_requires_simulation")
        if job.device_id != self.device_id:
            raise DriverError("device_mismatch")
        self.profiles.resolve(job, app_version=self.app_version)
        if self._bound_view is None or self._bound_view.spec != job:
            raise DriverError("session_mismatch")

    def prepare(self, job: JobSpec) -> None:
        with self._lock:
            if self._active:
                raise DriverError("driver_active")
            if self._started and self._job == job:
                raise DriverError("job_already_started")
            self._job = None
            self._route = None
            self._route_finished = False
            self._validate(job)
            self._job = job.model_copy(deep=True)
            self._stopped = False
            self._elapsed = 0.0
            self._started = False
            self._save_state()

    def start(self, job: JobSpec) -> None:
        with self._lock:
            if self._active or self._stopped or self._job != job:
                raise DriverError("start_not_prepared")
            # Recheck contents at the side-effect boundary, not just preflight.
            self._validate(job)
            school, route = self.profiles.resolve(job, app_version=self.app_version)
            # A deterministic simulation policy, never an inferred school target.
            speed = self._route_speed_mps
            if speed is None:
                speed = school.rules["maximum_speed_mps"]
            execution = RouteExecution(route, school, speed_mps=speed)
            self._execution_guard()
            execution.start(now=0.0)
            self._route = execution
            self._active = True
            self._started = True
            self.start_count += 1
            self._save_state()
            if self.scenario == "start_crash":
                raise DriverError("start_uncertain")

    def tick(self, job: JobSpec, elapsed_seconds: float) -> None:
        with self._lock:
            if not self._active or self._job != job:
                raise DriverError("driver_not_running")
            if (
                type(elapsed_seconds) not in (int, float)
                or not math.isfinite(elapsed_seconds)
                or elapsed_seconds < self._elapsed
            ):
                raise DriverError("invalid_elapsed_time")
            self._check_run_binding()
            if self.scenario == "tick_failure":
                raise DriverError("tick_failed")
            if self._route is None:
                # Persisted recovery may stop/verify, never silently resume motion.
                raise DriverError("route_recovery_requires_stop")
            self._execution_guard()
            self._route_finished = self._route.tick(now=elapsed_seconds).finished
            self._elapsed = elapsed_seconds
            self.tick_count += 1
            self._save_state()

    def stop(self) -> None:
        with self._lock:
            if self._active and self._stop_failures_remaining:
                self._stop_failures_remaining -= 1
                self._save_state()
                raise DriverError("stop_unconfirmed")
            if self._active:
                self.stop_count += 1
            if self._route is not None:
                self._route.stop()
            self._active = False
            self._stopped = True
            self._save_state()

    @property
    def route_progress(self) -> RouteProgress | None:
        """In-memory synthetic position only; absent on recovery, never evidence."""
        with self._lock:
            return self._route.snapshot if self._route is not None else None

    def verify(self, job: JobSpec) -> VerificationResult:
        with self._lock:
            if self._active or self._job != job or not self._stopped or not self._started:
                raise DriverError("verification_not_ready")
            reason = "simulation_only" if self._route_finished else "simulation_incomplete"
            if self.scenario == "upload_uncertain":
                reason = "upload_uncertain"
            return VerificationResult(status="unknown", evidence=[], reason_code=reason)

    def has_persisted_completion(self, view: JobView) -> bool:
        """Read-only recovery proof for this synthetic session, never app evidence.

        Re-open the private state through the same validated loader. An in-memory
        simulation_only result alone cannot authorize recovery completion.
        The agent holds the device lock throughout binding and this check.
        """
        with self._lock:
            if self._state_path is None or not self._state_path.exists():
                return False
            try:
                persisted = FakeDriver(
                    self.device_id,
                    self.profiles,
                    clock=self.clock,
                    app_version=self.app_version,
                    scenario=self.scenario,
                    state_path=self._state_path,
                )
            except (DriverError, OSError):
                return False
            for snapshot in (self, persisted):
                bound = snapshot._bound_view
                if (
                    bound is None
                    or bound.job_id != view.job_id
                    or bound.run_session_id != view.run_session_id
                    or bound.spec != view.spec
                    or bound.fence != view.fence
                    or bound.agent_id != view.agent_id
                    or snapshot._job != view.spec
                    or snapshot._active
                    or not snapshot._started
                    or not snapshot._stopped
                    or not snapshot._route_finished
                    or snapshot.scenario == "upload_uncertain"
                ):
                    return False
            return True

    def _save_state(self) -> None:
        """Synthetic device state, not a run journal or record acceptance proof.

        The owning agent must hold its per-device process lock. Atomic replace
        protects partial writes; it does not grant concurrent process ownership.
        """
        if self._state_path is None:
            return
        data = {
            "version": 2,
            "route_finished": self._route_finished,
            "device_id": self.device_id,
            "app_version": self.app_version,
            "scenario": self.scenario,
            "job": self._job.model_dump(mode="json") if self._job else None,
            "bound_view": self._bound_view.model_dump(mode="json") if self._bound_view else None,
            "active": self._active,
            "stopped": self._stopped,
            "started": self._started,
            "elapsed": self._elapsed,
            "start_count": self.start_count,
            "tick_count": self.tick_count,
            "stop_count": self.stop_count,
            "stop_failures_remaining": self._stop_failures_remaining,
        }
        temporary = None
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=".fake-", dir=self._state_path.parent)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, allow_nan=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._state_path)
            # POSIX directory fsync persists the rename. Windows has no portable
            # directory fsync here; no power-loss durability claim is made there.
            if os.name == "posix":
                directory = os.open(self._state_path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        except (OSError, ValueError):
            raise DriverError("fake_state_write_failed") from None
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)

    def _load_state(self, requested_scenario: str | None) -> None:
        if self._state_path is None:
            return
        if self._state_path.is_symlink():
            raise DriverError("fake_state_invalid")
        if not self._state_path.exists():
            return
        try:
            if self._state_path.is_symlink() or self._state_path.stat().st_size > 1_000_000:
                raise ValueError
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            if data["version"] != 2 or data["device_id"] != self.device_id:
                raise ValueError
            if data["app_version"] != self.app_version:
                raise ValueError
            scenario = data["scenario"]
            if scenario not in {
                "normal",
                "start_crash",
                "upload_uncertain",
                "stop_failure",
                "inspect_timeout",
                "tick_failure",
            }:
                raise ValueError
            if requested_scenario is not None and scenario != requested_scenario:
                raise ValueError
            route_finished = data.get("route_finished", False)
            if type(route_finished) is not bool or (route_finished and not data["started"]):
                raise ValueError
            for name in ("active", "stopped", "started"):
                if type(data[name]) is not bool:
                    raise ValueError
            for name in ("start_count", "tick_count", "stop_count", "stop_failures_remaining"):
                if type(data[name]) is not int or data[name] < 0:
                    raise ValueError
            if type(data["elapsed"]) not in (int, float) or not math.isfinite(data["elapsed"]):
                raise ValueError
            if data["elapsed"] < 0 or (data["active"] and (data["stopped"] or not data["started"])):
                raise ValueError
            bound_view = JobView.model_validate(data["bound_view"]) if data["bound_view"] else None
            job = JobSpec.model_validate(data["job"]) if data["job"] else None
            if job is not None and (job.mode != "simulation" or job.device_id != self.device_id):
                raise ValueError
            if bound_view is not None and (
                bound_view.spec.device_id != self.device_id
                or bound_view.spec.mode != "simulation"
                or bound_view.run_session_id is None
            ):
                raise ValueError
            if job is not None and (bound_view is None or bound_view.spec != job):
                raise ValueError
            if data["started"] and job is None:
                raise ValueError
        except (OSError, ValueError, TypeError, KeyError):
            raise DriverError("fake_state_invalid") from None
        self._job = job
        self._bound_view = bound_view
        self.scenario = scenario
        self._active, self._stopped, self._started = (
            data["active"],
            data["stopped"],
            data["started"],
        )
        self._elapsed = data["elapsed"]
        self._route_finished = route_finished
        self.start_count, self.tick_count = data["start_count"], data["tick_count"]
        self.stop_count = data["stop_count"]
        self._stop_failures_remaining = data["stop_failures_remaining"]
