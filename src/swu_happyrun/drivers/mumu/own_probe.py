"""Private own-APK readback. Observation grants no injection or school capability."""

import json
import math
import re
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from swu_happyrun.drivers.command import ProbeError, run_readonly
from swu_happyrun.drivers.mumu.binding import MumuBinding

Channel = Literal["location", "gravity"]
_MAX_BYTES = 65536
_PACKAGE = "org.happyrun.app"
_TEST = "org.happyrun.app.observation.AndroidObservationTest#testPrivateReadbackWhenRequested"
_STATUSES = frozenset(
    {
        "permission_required",
        "no_samples",
        "observation_cleanup_unconfirmed",
        "location_provider_unsupported",
        "gravity_sensor_unsupported",
        "gravity_registration_failed",
        "observation_failed",
        "boot_unavailable",
        "self_probe_required",
        "private_write_failed",
        "private_request_invalid",
    }
)


@dataclass(frozen=True, repr=False)
class OwnSample:
    values: tuple[float, ...]
    elapsed_realtime_ns: int
    channel: Channel
    accuracy: float | int


@dataclass(frozen=True, repr=False)
class OwnObservation:
    """Validated private envelope; never a public report or execution authority."""

    nonce: str
    binding_digest: str
    boot_id: str
    channel: Channel
    duration_ms: int
    window_start_ns: int
    window_end_ns: int
    samples: tuple[OwnSample, ...]


class OwnProbe:
    capabilities: tuple = ()

    def __init__(
        self,
        adb: Path,
        binding: MumuBinding,
        *,
        binding_check: Callable[[], None],
        authorization_check: Callable[[], None],
    ):
        self._adb, self._binding = Path(adb), binding
        self._binding_check, self._authorization_check = binding_check, authorization_check
        self._lock = threading.Lock()
        self._uncertain = False

    def _guard(self):
        self._binding_check()
        self._authorization_check()

    def sample(self, channel: Channel, *, duration_ms: int) -> tuple[OwnSample, ...]:
        return self.sample_private(channel, duration_ms=duration_ms).samples

    def sample_private(self, channel: Channel, *, duration_ms: int) -> OwnObservation:
        """One existing bounded window, retaining its validated private correlation."""
        if self._binding.package != _PACKAGE:
            raise ProbeError("own_target_required")
        if channel not in ("location", "gravity"):
            raise ProbeError("channel_unsupported")
        if type(duration_ms) is not int or not 1 <= duration_ms <= 5000:
            raise ProbeError("observation_budget_invalid")
        if not self._lock.acquire(blocking=False):
            raise ProbeError("observation_busy")
        try:
            if self._uncertain:
                raise ProbeError("observation_recovery_required")
            self._guard()
            nonce = secrets.token_hex(16)
            private_file = f"files/owned-observation-{nonce}.json"
            instrumentation_ended = False
            primary_code = None
            # No caller-supplied shell fragments, package, method or output path.
            try:
                output = self._command(
                    (
                        "shell",
                        "am",
                        "instrument",
                        "-w",
                        "-r",
                        "-e",
                        "class",
                        _TEST,
                        "-e",
                        "ownedObservationChannel",
                        channel,
                        "-e",
                        "ownedObservationDurationMs",
                        str(duration_ms),
                        "-e",
                        "ownedObservationNonce",
                        nonce,
                        "-e",
                        "ownedObservationBinding",
                        self._binding.identity_digest,
                        f"{_PACKAGE}.test/android.test.InstrumentationTestRunner",
                    ),
                    timeout=duration_ms / 1000 + 10,
                )
                if (
                    b"OK (1 test)" not in output
                    or b"INSTRUMENTATION_CODE: -1" not in output
                    or re.search(
                        rb"FAILURES!!!|INSTRUMENTATION_FAILED|INSTRUMENTATION_ABORTED|shortMsg=",
                        output,
                    )
                ):
                    raise ProbeError("observation_failed")
                instrumentation_ended = True
                statuses = re.findall(
                    rb"^INSTRUMENTATION_STATUS: owned_observation=([a-z_]+)\r?$",
                    output,
                    re.MULTILINE,
                )
                if len(statuses) > 1:
                    raise ProbeError("observation_payload_invalid")
                if statuses and statuses[0].decode("ascii") in _STATUSES:
                    raise ProbeError(statuses[0].decode("ascii"))
                self._guard()
                raw = self._command(
                    ("exec-out", "run-as", _PACKAGE, "cat", private_file), timeout=5
                )
                observation = self._decode_private(raw, nonce, channel, duration_ms)
                self._guard()
            except BaseException as error:
                primary_code = (
                    (error.primary_code or error.code)
                    if isinstance(error, ProbeError)
                    else "observation_interrupted"
                )
                raise
            finally:
                try:
                    self._command(
                        ("exec-out", "run-as", _PACKAGE, "rm", "-f", private_file), timeout=5
                    )
                except BaseException as cleanup_error:
                    self._uncertain = True
                    if not isinstance(cleanup_error, Exception):
                        raise
                    raise ProbeError(
                        "private_cleanup_unconfirmed", primary_code=primary_code
                    ) from None
                if not instrumentation_ended:
                    # Killing adb cannot prove Android stopped or that it will not write later.
                    self._uncertain = True
                    raise ProbeError(
                        "private_cleanup_unconfirmed", primary_code=primary_code
                    ) from None
            return observation
        finally:
            self._lock.release()

    def _decode(self, raw: bytes, nonce: str, channel: Channel, duration_ms: int):
        return self._decode_private(raw, nonce, channel, duration_ms).samples

    def _decode_private(self, raw: bytes, nonce: str, channel: Channel, duration_ms: int):
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError
                result[key] = value
            return result

        try:
            if len(raw) > _MAX_BYTES:
                raise ValueError
            report = json.loads(
                raw.decode("utf-8", errors="strict"),
                object_pairs_hook=unique,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
            )
            expected = {
                "schema",
                "nonce",
                "binding_digest",
                "boot_id",
                "channel",
                "duration_ms",
                "window_start_ns",
                "window_end_ns",
                "cleanup_confirmed",
                "status",
                "samples",
            }
            if (
                type(report) is not dict
                or set(report) != expected
                or type(report["schema"]) is not int
                or report["schema"] != 1
            ):
                raise ValueError
        except (ValueError, UnicodeError, TypeError, RecursionError):
            raise ProbeError("observation_payload_invalid") from None
        if (
            report["nonce"] != nonce
            or report["binding_digest"] != self._binding.identity_digest
            or report["boot_id"] != self._binding.boot_id
            or report["channel"] != channel
            or type(report["duration_ms"]) is not int
            or report["duration_ms"] != duration_ms
        ):
            raise ProbeError("observation_correlation_invalid")
        if report["cleanup_confirmed"] is not True:
            raise ProbeError("observation_cleanup_unconfirmed")
        status = report["status"]
        if not isinstance(status, str) or status != "samples_observed":
            raise ProbeError(
                status if isinstance(status, str) and status in _STATUSES else "observation_failed"
            )
        start, end = report["window_start_ns"], report["window_end_ns"]
        if (
            type(start) is not int
            or type(end) is not int
            or not 0 <= start < end <= 2**63 - 1
            or end - start != duration_ms * 1_000_000
        ):
            raise ProbeError("observation_window_invalid")
        values = report["samples"]
        if type(values) is not list or not 1 <= len(values) <= 128:
            raise ProbeError("observation_sample_invalid")
        result = []
        previous = start - 1
        for sample in values:
            if type(sample) is not dict or set(sample) != {
                "channel",
                "elapsed_realtime_ns",
                "values",
                "accuracy",
            }:
                raise ProbeError("observation_sample_invalid")
            ts, points, accuracy = (
                sample["elapsed_realtime_ns"],
                sample["values"],
                sample["accuracy"],
            )

            def numeric(value):
                try:
                    return type(value) in (int, float) and math.isfinite(value)
                except OverflowError:
                    return False

            if (
                sample["channel"] != channel
                or type(ts) is not int
                or not previous < ts < end
                or ts < start
                or type(points) is not list
                or len(points) != (2 if channel == "location" else 3)
                or not all(numeric(v) for v in points)
                or not numeric(accuracy)
            ):
                raise ProbeError("observation_sample_invalid")
            if channel == "location":
                if abs(points[0]) > 90 or abs(points[1]) > 180 or accuracy < 0:
                    raise ProbeError("observation_sample_invalid")
                accuracy = float(accuracy)
            elif type(accuracy) is not int or accuracy not in (-1, 0, 1, 2, 3):
                raise ProbeError("observation_sample_invalid")
            result.append(OwnSample(tuple(float(v) for v in points), ts, channel, accuracy))
            previous = ts
        return OwnObservation(
            nonce,
            report["binding_digest"],
            report["boot_id"],
            channel,
            duration_ms,
            start,
            end,
            tuple(result),
        )

    @staticmethod
    def public_report(channel: Channel, samples: tuple[OwnSample, ...]) -> dict:
        if channel not in ("location", "gravity"):
            raise ProbeError("channel_unsupported")
        return dict(
            channel=channel,
            sample_count=len(samples),
            status="samples_observed" if samples else "no_samples",
            calibration="unknown",
            injection_stop="unconfirmed",
        )

    def _command(self, args: tuple[str, ...], *, timeout: float) -> bytes:
        """Reuse #87 bounded capture, never as an injection/write acknowledgment.

        This fixed own-probe path registers listeners and writes/deletes its own
        private temporary report. It does not authorize arbitrary device writes.
        UTF-8/newline normalization does not change JSON numeric sample values.
        """
        return run_readonly(
            self._adb, "-s", self._binding.adb_serial, *args, timeout=timeout
        ).encode("utf-8")
