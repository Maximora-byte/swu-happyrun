"""One-owner local MuMu trajectory tool; separate from school device jobs.

The fixed host-wide journal is independent of --data-dir. A reservation survives
process death and only an explicit stop can clear uncertainty. No action resumes
automatically, and no school record is started or declared valid here.
"""

import copy
import hashlib
import json
import os
import queue
import threading
import time
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from swu_happyrun.agent.journal import RunJournal, UnsafeReplay
from swu_happyrun.core.canonical import profile_revision
from swu_happyrun.core.clock import SystemClock
from swu_happyrun.core.coordinates import normalize_points
from swu_happyrun.core.geo import distance_between_points_m
from swu_happyrun.core.models import GeoPoint, RouteProfile
from swu_happyrun.core.route import RouteExecution
from swu_happyrun.desktop.mumu_admission import (
    legacy_roots,
    pinned_host_namespace,
    remember_legacy_roots,
    require_clean_legacy_scope,
)
from swu_happyrun.desktop.mumu_mapping import VENDOR_CRS, vendor_point
from swu_happyrun.desktop.mumu_transport import LocalMuMuTransport
from swu_happyrun.desktop.workspace import _check_path
from swu_happyrun.drivers.command import ProbeError
from swu_happyrun.drivers.identity import device_id


def validate_local_route(route):
    route = RouteProfile.model_validate(route.model_dump(mode="python"))
    if len(route.points) > 10000:
        raise ValueError("route_too_large")
    if route.revision != profile_revision(route):
        raise ValueError("route_revision_mismatch")
    RouteExecution.for_local_replay(
        route, speed_mps=1.0, maximum_duration_seconds=1800.0, clock=SystemClock()
    )
    for point in normalize_points(route):
        vendor_point(point)  # Reject unsupported conversion domains before effects.
    return route


def choose_calibration_points(route):
    points = normalize_points(validate_local_route(route))
    first = points[0]
    second = max(points[1:], key=lambda point: distance_between_points_m(first, point))
    if distance_between_points_m(first, second) < 30:
        raise ValueError("calibration_points_too_close")
    return first, second


def _progress_view(value):
    result = asdict(value)
    result["position"] = value.position.model_dump(mode="json")
    return result


def canonical_root():
    if os.name == "nt":
        from swu_happyrun.drivers.mumu.enrollment import _local_app_data

        return _local_app_data() / "HappyRunMuMu"
    return Path.home() / ".happyrun-mumu"


def _private_root(root):
    _check_path(root)
    if os.name == "nt":
        from swu_happyrun.drivers.mumu.windows_private import (
            provision_private_directory,
            verify_directory,
        )

        if not root.exists():
            provision_private_directory(root)
        verify_directory(root)
    else:
        root.mkdir(mode=0o700, exist_ok=True)
        if root.stat().st_mode & 0o077:
            raise ValueError("workspace_must_be_private")


class TrajectoryController:
    """The HTTP surface enqueues requests; only this thread touches the device."""

    def __init__(self, *, root=None, transport_factory=LocalMuMuTransport):
        self.root = Path(root) if root is not None else canonical_root()
        self.transport_factory = transport_factory
        self._lock = threading.RLock()
        self._commands = queue.Queue()
        self._halt = threading.Event()
        self._closing = threading.Event()
        self._pending = None
        self._transport = None
        self._journal = self._device_lock = self._permit = None
        self._uncertain = False
        self._execution = None
        self._calibration = None
        self._route = None
        self._trace = None
        self._last_write_at = 0.0
        self._view = dict(
            state="disconnected",
            error_code=None,
            instances=[],
            instance_index=None,
            host_version=None,
            android_api=None,
            device_verified=False,
            record_verified=False,
            route=None,
            progress=None,
            sample=None,
            writes=0,
            max_error_m=None,
            stop_confirmed=False,
            observation_state=None,
            vendor_crs=VENDOR_CRS,
        )
        self.thread = threading.Thread(target=self._loop, name="happyrun-mumu", daemon=True)
        self._started = False
        self._last_inventory = time.monotonic()

    def snapshot(self):
        with self._lock:
            if not self._started:
                self.thread.start()
                self._started = True
            return copy.deepcopy(self._view)

    def _set(self, **values):
        with self._lock:
            self._view.update(values)

    def submit(self, action, **values):
        with self._lock:
            if not self._started:
                self.thread.start()
                self._started = True
            if self._closing.is_set():
                raise ValueError("controller_closed")
            state = self._view["state"]
            allowed = {
                "connect": {"disconnected", "unavailable", "connected", "stopped", "completed"},
                "route": {"connected", "ready", "stopped", "completed"},
                "calibrate": {"connected", "ready", "stopped", "completed"},
                "start": {"ready"},
                "pause": {"running"},
                "resume": {"paused"},
                "stop": {
                    "connecting",
                    "connected",
                    "calibrating",
                    "ready",
                    "running",
                    "paused",
                    "stopping",
                    "stopped",
                    "completed",
                    "needs_attention",
                },
            }
            if action not in allowed or state not in allowed[action]:
                raise ValueError("invalid_mumu_state")
            if action == "stop":
                self._halt.set()
                self._view["state"] = "stopping"
                return
            if self._pending is not None or self._halt.is_set():
                raise ValueError("mumu_busy")
            if action == "route":
                values["route"] = validate_local_route(values["route"])
            if action == "connect":
                self._view["state"] = "connecting"
            elif action == "calibrate":
                if self._route is None:
                    raise ValueError("route_required")
                choose_calibration_points(self._route)
                self._view["state"] = "calibrating"
            self._pending = action
            self._commands.put((action, values))

    def _loop(self):
        try:
            try:
                self._transport = self.transport_factory()
                self._set(
                    instances=self._transport.inventory(), host_version=self._transport.host_version
                )
            except Exception as error:
                self._failure(error, unavailable=True)
            while not self._closing.is_set() or self._halt.is_set():
                if self._halt.is_set():
                    try:
                        self._stop()
                    except Exception as error:
                        self._failure(error)
                    finally:
                        with self._lock:
                            while True:
                                try:
                                    self._commands.get_nowait()
                                except queue.Empty:
                                    break
                            self._pending = None
                            self._halt.clear()
                    if self._closing.is_set():
                        break
                try:
                    action, values = self._commands.get(timeout=0.1)
                except queue.Empty:
                    if self._view["state"] == "running":
                        try:
                            self._tick()
                        except Exception as error:
                            self._failure(error)
                    elif self._view["state"] in {
                        "disconnected",
                        "unavailable",
                        "stopped",
                        "completed",
                    }:
                        if time.monotonic() - self._last_inventory >= 5:
                            self._last_inventory = time.monotonic()
                            try:
                                if self._transport is None:
                                    self._transport = self.transport_factory()
                                self._set(
                                    instances=self._transport.inventory(),
                                    host_version=self._transport.host_version,
                                )
                            except Exception:
                                pass  # Inventory cannot change an execution result.
                    continue
                try:
                    if self._closing.is_set():
                        continue
                    getattr(self, "_do_" + action)(**values)
                except Exception as error:
                    self._failure(error)
                finally:
                    with self._lock:
                        self._pending = None
        finally:
            # Unconfirmed markers are intentionally retained when cleanup fails.
            self._release()

    def _failure(self, error, *, unavailable=False):
        if isinstance(error, ProbeError) and error.code == "trajectory_stop_requested":
            return  # The already requested stop consumes any completed delivery.
        code = error.code if isinstance(error, ProbeError) else str(error)
        allowed = {
            "route_required",
            "route_revision_mismatch",
            "calibration_points_too_close",
            "route_too_large",
            "invalid_route_duration",
            "invalid_route_speed",
        }
        if not isinstance(error, ProbeError) and code not in allowed:
            code = "mumu_operation_failed"
        self._uncertain = self._permit is not None
        if self._permit is not None:
            try:
                self._journal.update_replay(
                    self._permit, generation=self._permit.marker["generation"], status="uncertain"
                )
            except Exception:
                code = "replay_journal_unavailable"
        self._set(
            state="unavailable" if unavailable else "needs_attention",
            error_code=code,
            device_verified=False,
            stop_confirmed=False,
        )

    def _acquire(self, index):
        if self._journal is not None:
            return
        _private_root(self.root)
        # Same persisted host namespace and MuMu identity spelling as the agent.
        identity = f"{os.path.normcase(str(self._transport.manager.resolve()))}:{index}"
        namespace, host_file = pinned_host_namespace(self.root, self._transport.manager)
        self._legacy_roots = remember_legacy_roots(self.root, legacy_roots(host_file))
        require_clean_legacy_scope(self._legacy_roots, current_root=self.root)
        self._device_id = device_id("mumu", identity, host_id=namespace)
        digest = hashlib.sha256(self._device_id.encode()).hexdigest()
        for name in (
            "journal.sqlite",
            "journal.sqlite-wal",
            "journal.sqlite-shm",
            f"device-{digest}.lock",
            f"replay-{digest}.json",
        ):
            _check_path(self.root / name)
        self._journal = RunJournal(self.root / "journal.sqlite")
        self._device_lock = self._journal.device_lock(self._device_id)
        try:
            self._device_lock.__enter__()
        except UnsafeReplay as error:
            if str(error) != "replay_recovery_requires_stop":
                self._journal.close()
                self._journal = self._device_lock = None
                raise ProbeError("device_busy") from None
            self._device_lock = self._journal.replay_recovery_lock(self._device_id)
            self._permit = self._device_lock.__enter__()
            self._uncertain = True

    def _release(self):
        if self._trace is not None:
            self._trace.close()
            self._trace = None
        if self._device_lock is not None:
            self._device_lock.__exit__(None, None, None)
            self._device_lock = None
        if self._journal is not None:
            self._journal.close()
            self._journal = None
        self._permit = None

    def _do_connect(self, instance_index):
        if self._transport is None:
            self._transport = self.transport_factory()
        if self._transport.observer is not None:
            raise ProbeError("stop_required")
        self._release()
        self._uncertain = False
        self._calibration = None
        self._execution = None
        self._acquire(instance_index)
        self._set(instance_index=instance_index)
        if self._uncertain:
            trace = self.root / ("trace-" + self._permit.marker["session_id"] + ".jsonl")
            _check_path(trace)
            try:
                with trace.open(encoding="utf-8") as source:
                    previous = json.loads(source.readline(8192))
                identity = self._transport.inspect_identity(instance_index)
                if (
                    previous["kind"] != "intent"
                    or previous["binding"]["created_timestamp"] != identity["created_timestamp"]
                    or previous["binding"]["index"] != instance_index
                ):
                    raise ValueError
            except (OSError, ValueError, KeyError, TypeError):
                self._recovery_binding_changed = True
                raise ProbeError("recovery_instance_changed") from None
            self._recovery_binding_changed = False
            self._binding = previous["binding"]
            self._set(
                state="needs_attention",
                error_code="replay_recovery_requires_stop",
                host_version=self._transport.host_version,
                android_api=None,
                instances=self._transport.inventory(),
                device_verified=False,
                stop_confirmed=False,
            )
            return
        binding = self._transport.connect(instance_index)
        self._set(
            instance_index=instance_index,
            host_version=self._transport.host_version,
            android_api=self._transport.android_api,
            instances=self._transport.inventory(),
            device_verified=False,
            stop_confirmed=False,
            writes=0,
            sample=None,
            error_code=None,
            progress=None,
            max_error_m=None,
        )
        self._binding = binding
        self._set(state="connected")

    def _do_route(self, route):
        if self._permit is not None:
            self._stop()
        self._route = route
        self._calibration = None
        self._set(
            route=route.model_dump(mode="json"),
            state="connected",
            error_code=None,
            device_verified=False,
            progress=None,
        )

    def _ensure_session(self):
        self._acquire(self._view["instance_index"])
        if self._uncertain:
            raise ProbeError("replay_recovery_requires_stop")
        if self._permit is None:
            self._permit = self._journal.reserve_replay(self._device_id, str(uuid4()), generation=1)
            name = "trace-" + self._permit.marker["session_id"] + ".jsonl"
            self._trace = (self.root / name).open("x", encoding="utf-8")
            self._record(dict(kind="intent", binding=self._transport.binding))
        if self._transport.observer is None:
            self._record(dict(kind="probe_prepare_intent"))
            self._transport.prepare_probe(self._check)
            self._check()
            self._transport.start_observation(self.root)
            self._set(observation_state="observing")
        self._set(stop_confirmed=False)

    def _record(self, value):
        if self._trace is None:
            raise ProbeError("intent_journal_required")
        self._trace.write(json.dumps(value, allow_nan=False, separators=(",", ":")) + "\n")
        self._trace.flush()
        os.fsync(self._trace.fileno())

    def _check(self):
        if self._halt.is_set() or self._closing.is_set():
            raise ProbeError("trajectory_stop_requested")
        self._journal.verify_replay(self._permit, generation=1)
        pinned_host_namespace(self.root, self._transport.manager)
        require_clean_legacy_scope(self._legacy_roots, current_root=self.root)

    def _report(self):
        value = self._transport.read_observation()
        if value["state"] != "observing":
            raise ProbeError(value["error_code"] or "observation_ended")
        self._set(observation_state=value["state"], sample=value["sample"])
        return value

    def _write(self, point):
        self._check()
        before = self._report()
        command_point = vendor_point(point)
        self._record(
            dict(
                kind="write_intent",
                point=command_point.model_dump(),
                expected_wgs84=point.model_dump(),
                vendor_crs=VENDOR_CRS,
                after_device_ns=before["reported_at_ns"],
                observer_bootstrap=False,
            )
        )
        self._check()
        self._transport.write_location(command_point)
        self._last_write_at = time.monotonic()
        self._set(writes=self._view["writes"] + 1)
        deadline = time.monotonic() + 6
        last = None
        while time.monotonic() < deadline:
            # A stop seals future writes, but still consumes this command's receipt.
            value = self._report()
            sample = value["sample"]
            if (
                sample is not None
                and value["sequence"] > before["sequence"]
                and sample["elapsed_realtime_ns"] > before["reported_at_ns"]
            ):
                last = distance_between_points_m(
                    point, GeoPoint(latitude=sample["latitude"], longitude=sample["longitude"])
                )
                if last <= 5 and sample["accuracy"] <= 20:
                    self._record(dict(kind="readback", error_m=last, observation=value))
                    self._last_confirmed_sample_ns = sample["elapsed_realtime_ns"]
                    self._last_confirmed_point = point.model_copy(deep=True)
                    self._set(max_error_m=max(self._view["max_error_m"] or 0, last))
                    return
            time.sleep(0.1)
        raise ProbeError(
            "location_readback_mismatch" if last is not None else "fresh_location_required"
        )

    def _do_calibrate(self):
        self._ensure_session()
        self._set(writes=0, max_error_m=None, device_verified=False)
        first, second = choose_calibration_points(self._route)
        # Restore the start while the running app is still idle. Otherwise its
        # first recorded fix can jump from the distant second calibration point.
        for point in (first, second, first):
            self._write(point)
        self._calibration = dict(self._transport.binding)
        self._set(state="ready", device_verified=True, error_code=None)

    def _do_start(self, speed_mps, maximum_duration_seconds):
        if self._calibration is None or self._calibration != self._transport.binding:
            raise ProbeError("calibration_required")
        self._check()
        self._transport.assert_current()
        self._execution = RouteExecution.for_local_replay(
            self._route,
            speed_mps=speed_mps,
            maximum_duration_seconds=maximum_duration_seconds,
            clock=SystemClock(),
        )
        value = self._execution.start()
        self._record(
            dict(
                kind="trajectory_intent",
                route_revision=self._route.revision,
                speed_mps=speed_mps,
                maximum_duration_seconds=maximum_duration_seconds,
            )
        )
        self._write(value.position)
        self._set(state="running", progress=_progress_view(value), error_code=None)

    def _tick(self):
        if time.monotonic() - self._last_write_at < 0.8:
            return
        value = self._execution.tick()
        self._write(value.position)
        self._set(progress=_progress_view(value))
        if value.state in {"completed", "stopped"}:
            self._stop(final_state=value.state)

    def _do_pause(self):
        value = self._execution.pause()
        self._stable_window(2.2)
        self._set(state="paused", progress=_progress_view(value))

    def _do_resume(self):
        self._check()
        self._transport.assert_current()
        self._set(state="running", progress=_progress_view(self._execution.resume()))

    def _stable_window(self, seconds):
        first = self._report()
        sample = first["sample"]
        if sample is None:
            raise ProbeError("fresh_location_required")
        anchor = self._last_confirmed_point
        if (
            distance_between_points_m(
                anchor, GeoPoint(latitude=sample["latitude"], longitude=sample["longitude"])
            )
            > 5
        ):
            raise ProbeError("position_not_stable")
        end = time.monotonic() + seconds
        if sample["elapsed_realtime_ns"] < self._last_confirmed_sample_ns:
            raise ProbeError("observation_stale")
        start_sequence = first["sequence"]
        while time.monotonic() < end:
            value = self._report()
            current = value["sample"]
            if current is not None:
                if (
                    distance_between_points_m(
                        anchor,
                        GeoPoint(latitude=current["latitude"], longitude=current["longitude"]),
                    )
                    > 5
                ):
                    raise ProbeError("position_not_stable")
                if current["elapsed_realtime_ns"] < self._last_confirmed_sample_ns:
                    raise ProbeError("observation_stale")
            time.sleep(0.15)
        lat, lon = self._transport.read_retained_location()
        retained = GeoPoint(latitude=lat, longitude=lon)
        if distance_between_points_m(anchor, retained) > 5:
            raise ProbeError("position_not_stable")
        self._record(
            dict(
                kind="stable_window",
                seconds=seconds,
                observation=value,
                new_samples=value["sequence"] - start_sequence,
                system_retained_fix=retained.model_dump(),
                retained_fix_is_new_sample=False,
            )
        )

    def _stop(self, *, final_state="stopped"):
        if self._transport is None:
            self._set(state="stopped", stop_confirmed=True)
            return
        if self._permit is not None:
            if self._uncertain:
                if getattr(self, "_recovery_binding_changed", False):
                    raise ProbeError("recovery_instance_changed")
                if not getattr(self, "_binding", None):
                    raise ProbeError("recovery_instance_unverified")
                self._transport.shutdown(
                    self._view["instance_index"],
                    expected_created_timestamp=self._binding["created_timestamp"],
                )
                self._set(device_verified=False, observation_state="stopped")
            elif self._transport.observer is not None:
                if self._view["writes"]:
                    self._stable_window(2.2)
                self._transport.stop_observation()
                self._record(
                    dict(
                        kind="stop_confirmed", producer_stopped=True, virtual_location_retained=True
                    )
                )
                self._set(observation_state="stopped")
            self._journal.update_replay(
                self._permit,
                generation=self._permit.marker["generation"] + 1,
                status="stopped",
                probe_pending=False,
            )
        if self._execution is not None:
            self._set(progress=_progress_view(self._execution.stop()))
        self._uncertain = False
        self._calibration = None
        self._set(state=final_state, stop_confirmed=True, error_code=None)
        self._release()

    def close(self):
        if not self._started:
            return
        self._closing.set()
        self._halt.set()
        self.thread.join(timeout=30)
        if self.thread.is_alive():
            self._set(state="needs_attention", stop_confirmed=False, error_code="stop_unconfirmed")
