"""Controlled single-command MuMu 6.8.4 experiment, not a registered driver.

The caller owns durable session intent and the device lock. Its final authority
callback must check that intent, cancellation and generation under its shared
lock. A successful process exit is only command delivery: no vendor application
acknowledgement or queue/stop semantics have been established for this version.
"""

import hashlib
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite
from pathlib import Path

from swu_happyrun.core.clock import Clock
from swu_happyrun.core.models import GeoPoint
from swu_happyrun.drivers.base import DriverError
from swu_happyrun.drivers.command import ProbeError, _run_bounded_bytes, run_readonly
from swu_happyrun.drivers.mumu.binding import MumuBinding
from swu_happyrun.drivers.mumu.commands_684 import MuMu684Commands

MAX_ACTION_SECONDS = 5.0  # Local execution policy, not a vendor timing guarantee.


class NativeWriteError(DriverError):
    """Fixed failure codes, retaining the primary error if cleanup is uncertain."""

    def __init__(self, reason_code: str, *, primary_code: str | None = None):
        self.primary_code = primary_code
        super().__init__(reason_code)


@dataclass(frozen=True)
class CommandDelivery:
    """Local process evidence only. No sample values, arguments or device IDs."""

    command_completed: bool
    stdout_bytes: int
    stderr_bytes: int
    stdout_sha256: str
    stderr_sha256: str


class MuMuNative684:
    """Single-command controlled entry; all normal driver capabilities stay closed.

    No coordinate transformation or gyro-unit claim is made. Input numbers are
    raw vendor arguments. A new instance cannot establish recovery quiescence;
    the caller must retain unresolved durable intent across process restarts.
    """

    def __init__(
        self,
        manager: Path,
        binding: MumuBinding,
        *,
        adb: Path,
        binding_check: Callable[[], None],
        authorization_check: Callable[[], None],
        clock: Clock,
    ) -> None:
        if not isinstance(binding, MumuBinding) or binding.host_version != "6.8.4.0":
            raise DriverError("transport_version_unverified")
        if binding.package != "org.happyrun.app":
            raise DriverError("own_target_required")
        if not callable(binding_check) or not callable(authorization_check):
            raise DriverError("execution_guard_required")
        self._manager, self._adb = Path(manager), Path(adb)
        self._binding = binding
        self._binding_check, self._authorization_check = binding_check, authorization_check
        self._clock = clock
        self._closed = threading.Event()
        self.last_delivery: CommandDelivery | None = None
        # API35 here selects the encoder; actual SDK is read before any write.
        self._commands = MuMu684Commands(binding.host_version, 35, binding.instance_index)

    @property
    def capabilities(self) -> tuple[()]:
        return ()

    def write_location(self, point: GeoPoint, *, deadline: float) -> None:
        if not isinstance(point, GeoPoint):
            raise DriverError("command_value_invalid")
        self._write(
            self._commands.location(longitude=point.longitude, latitude=point.latitude),
            deadline=deadline,
        )

    def write_gyro(self, sample: tuple[float, float, float], *, deadline: float) -> None:
        if type(sample) is not tuple or len(sample) != 3:
            raise DriverError("command_value_invalid")
        self._write(self._commands.gyro(x=sample[0], y=sample[1], z=sample[2]), deadline=deadline)

    def _remaining(self, deadline: float, wall_deadline: float) -> float:
        if self._closed.is_set():
            raise DriverError("writer_closed")
        remaining = min(deadline - self._clock.monotonic(), wall_deadline - time.monotonic())
        if remaining <= 0:
            raise DriverError("write_deadline_expired")
        return remaining

    def _write(self, args: tuple[str, ...], *, deadline: float) -> None:
        if type(deadline) not in (int, float):
            raise DriverError("write_deadline_invalid")
        try:
            valid = isfinite(deadline)
        except OverflowError:
            valid = False
        if not valid:
            raise DriverError("write_deadline_invalid")
        wall_deadline = time.monotonic() + MAX_ACTION_SECONDS
        self._remaining(deadline, wall_deadline)
        self._binding_check()
        self._authorization_check()
        remaining = self._remaining(deadline, wall_deadline)
        try:
            sdk = run_readonly(
                self._adb,
                "-s",
                self._binding.adb_serial,
                "shell",
                "getprop",
                "ro.build.version.sdk",
                timeout=remaining,
            )
        except ProbeError as exc:
            code = {
                "command_cleanup_unconfirmed": "write_cleanup_unconfirmed",
                "command_capture_busy": "write_busy",
            }.get(exc.code, "android_api_probe_failed")
            raise NativeWriteError(code, primary_code=exc.primary_code or exc.code) from None
        if sdk.strip() != "35":
            raise DriverError("transport_version_unverified")

        # This may perform read-only ADB capture. Do not recurse into the shared
        # process guard: only the final local authorization check runs inside it.
        self._binding_check()

        def final_check():
            self._authorization_check()
            self._remaining(deadline, wall_deadline)

        try:
            stdout, stderr, returncode = _run_bounded_bytes(
                self._manager,
                *args,
                timeout=self._remaining(deadline, wall_deadline),
                before_spawn=final_check,
                cancel_event=self._closed,
            )
        except ProbeError as exc:
            mapping = {
                "command_timeout": "write_timeout",
                "command_cancelled": "write_cancelled_unconfirmed",
                "command_output_limit": "write_output_limit",
                "command_capture_busy": "write_busy",
                "command_cleanup_unconfirmed": "write_cleanup_unconfirmed",
                "command_reader_failed": "write_capture_failed",
                "command_unavailable": "write_unavailable",
                "executable_missing": "executable_missing",
            }
            raise NativeWriteError(
                mapping.get(exc.code, "write_capture_failed"),
                primary_code=exc.primary_code,
            ) from None
        finally:
            # No reset or automatic retry after an invocation attempt, even when
            # interrupted or the capture's outcome/cleanup is unknown.
            self._closed.set()
        if returncode != 0:
            raise DriverError("write_failed_unconfirmed")
        try:
            stdout.decode("utf-8", errors="strict")
            stderr.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise DriverError("write_encoding_invalid") from None
        self.last_delivery = CommandDelivery(
            True,
            len(stdout),
            len(stderr),
            hashlib.sha256(stdout).hexdigest(),
            hashlib.sha256(stderr).hexdigest(),
        )
        raise DriverError("write_ack_unconfirmed")

    def stop(self) -> None:
        # Wake any active write without waiting on its lock; its own independent
        # cleanup budget applies. Close both channels even before the first write.
        self._closed.set()
        # Neither child exit, reader EOF, nor a newly constructed empty instance
        # proves that MuMu's queue is empty. No documented stop command is known.
        raise DriverError("stop_unconfirmed")
