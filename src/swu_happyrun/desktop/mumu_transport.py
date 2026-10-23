"""Local, single-point MuMu channel and independent own-APK GPS observation.

This transport does not implement a school driver or enroll the existing agent.
Vendor process exit is only command delivery; a fresh GPS sample proves readback.
"""

import json
import math
import re
import secrets
import subprocess
import tempfile
import time

from swu_happyrun.drivers.command import ProbeError, _run_bounded_bytes
from swu_happyrun.drivers.mumu.commands_684 import MuMu684Commands
from swu_happyrun.drivers.mumu.discovery import discover_installations, host_version

PACKAGE = "org.happyrun.app"
CONTINUOUS_TEST = "org.happyrun.app.observation.ContinuousLocationTest#testObserveWhenRequested"


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate_key")
        value[key] = item
    return value


def _json(raw):
    if len(raw) > 65536:
        raise ProbeError("observation_payload_invalid")
    try:
        return json.loads(
            raw.decode("utf-8-sig"),
            object_pairs_hook=_unique,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
    except (ValueError, UnicodeError, RecursionError):
        raise ProbeError("observation_payload_invalid") from None


def decode_observation(raw, *, nonce, boot_id):
    value = _json(raw)
    expected = {
        "schema",
        "nonce",
        "boot_id",
        "sequence",
        "state",
        "error_code",
        "window_start_ns",
        "reported_at_ns",
        "sample",
    }
    if type(value) is not dict or set(value) != expected:
        raise ProbeError("observation_payload_invalid")
    if (
        type(value["schema"]) is not int
        or value["schema"] != 1
        or value["nonce"] != nonce
        or value["boot_id"] != boot_id
        or value["state"] not in {"starting", "observing", "stopped", "error"}
        or any(
            type(value[k]) is not int or not 0 <= value[k] < 2**63
            for k in ("sequence", "window_start_ns", "reported_at_ns")
        )
        or value["reported_at_ns"] < value["window_start_ns"]
        or (
            value["error_code"] is not None
            and (
                type(value["error_code"]) is not str
                or re.fullmatch(r"[a-z_]{1,80}", value["error_code"]) is None
            )
        )
        or (value["state"] == "error") != (value["error_code"] is not None)
    ):
        raise ProbeError("observation_correlation_invalid")
    sample = value["sample"]
    if sample is not None:
        if (
            type(sample) is not dict
            or set(sample) != {"latitude", "longitude", "accuracy", "elapsed_realtime_ns"}
            or any(
                type(sample[k]) not in (int, float) or not math.isfinite(sample[k])
                for k in ("latitude", "longitude", "accuracy")
            )
            or abs(sample["latitude"]) > 90
            or abs(sample["longitude"]) > 180
            or sample["accuracy"] < 0
            or type(sample["elapsed_realtime_ns"]) is not int
            or not value["window_start_ns"]
            <= sample["elapsed_realtime_ns"]
            <= value["reported_at_ns"]
            or value["sequence"] < 1
        ):
            raise ProbeError("observation_sample_invalid")
    elif value["sequence"] != 0:
        raise ProbeError("observation_sample_invalid")
    return value


def decode_delivery(raw):
    """Exact tool response observed on 6.8.4.0; never a location receipt."""
    value = _json(raw)
    if (
        type(value) is not dict
        or set(value) != {"errcode", "errmsg"}
        or type(value["errcode"]) is not int
        or value["errcode"] != 0
        or value["errmsg"] != ""
    ):
        raise ProbeError("write_ack_unconfirmed")


def decode_retained_location(raw):
    """Read the system's retained fix; this is explicitly NOT a new GPS sample."""
    inside, count, values = False, 0, []
    for line in raw.splitlines():
        if re.fullmatch(rb"    [a-zA-Z0-9_]+ provider:", line):
            inside = line == b"    gps provider:"
            count += int(inside)
        elif inside and line.startswith(b"      last location="):
            match = re.match(
                rb"      last location=Location\[gps ([+-]?[0-9]+(?:\.[0-9]+)?),"
                rb"([+-]?[0-9]+(?:\.[0-9]+)?) ",
                line,
            )
            if match is None:
                raise ProbeError("held_location_unavailable")
            values.append(tuple(float(item) for item in match.groups()))
    if (
        count != 1
        or len(values) != 1
        or not all(math.isfinite(v) for v in values[0])
        or abs(values[0][0]) > 90
        or abs(values[0][1]) > 180
    ):
        raise ProbeError("held_location_unavailable")
    return values[0]


class LocalMuMuTransport:
    def __init__(self):
        paths = discover_installations()
        if len(paths) != 1:
            raise ProbeError("mumu_not_found" if not paths else "installation_selection_required")
        self.manager = paths[0]
        self.host_version = host_version(self.manager)
        if self.host_version != "6.8.4.0":
            raise ProbeError("transport_version_unverified")
        self.adb = self.manager.with_name("adb.exe")
        if not self.adb.is_file():
            raise ProbeError("executable_missing")
        self.binding = None
        self.observer = None
        self._output = None
        self.nonce = None
        self._report_anchor = None
        self.last_delivery = None

    @staticmethod
    def _run(path, *args, timeout=5):
        out, _err, code = _run_bounded_bytes(path, *args, timeout=timeout)
        if code:
            raise ProbeError("command_failed")
        return out

    def inventory(self):
        data = _json(self._run(self.manager, "info", "--vmindex", "all"))
        if not isinstance(data, dict):
            raise ProbeError("instance_response_invalid")
        result = []
        for key, value in data.items():
            if not isinstance(value, dict) or str(value.get("index")) != key:
                raise ProbeError("instance_response_invalid")
            result.append(
                dict(
                    index=key,
                    name=str(value.get("name", key))[:128],
                    running=value.get("is_android_started") is True,
                    android_version=str(value.get("android_version", "")),
                )
            )
        return result

    def inspect_identity(self, index):
        if not isinstance(index, str) or re.fullmatch(r"[0-9]{1,8}", index) is None:
            raise ProbeError("instance_index_invalid")
        value = _json(self._run(self.manager, "info", "--vmindex", index))
        if (
            not isinstance(value, dict)
            or str(value.get("index")) != index
            or type(value.get("error_code")) is not int
            or value["error_code"] != 0
            or type(value.get("created_timestamp")) is not int
            or value["created_timestamp"] <= 0
            or type(value.get("is_android_started")) is not bool
            or type(value.get("is_process_started")) is not bool
        ):
            raise ProbeError("instance_response_invalid")
        return value

    def _info(self, index):
        value = self.inspect_identity(index)
        if (
            value.get("is_android_started") is not True
            or value.get("is_process_started") is not True
            or value.get("adb_host_ip") != "127.0.0.1"
            or type(value.get("adb_port")) is not int
            or not 1 <= value["adb_port"] <= 65535
            or type(value.get("pid")) is not int
            or value["pid"] <= 0
        ):
            raise ProbeError("instance_not_ready")
        return value

    def connect(self, index):
        value = self._info(index)
        self.serial = f"127.0.0.1:{value['adb_port']}"
        self._run(self.adb, "connect", self.serial)
        sdk = self._adb("shell", "getprop", "ro.build.version.sdk").strip()
        if sdk != b"35":
            raise ProbeError("transport_version_unverified")
        self.android_api = 35
        if self._adb("shell", "getprop", "sys.boot_completed").strip() != b"1":
            raise ProbeError("android_boot_not_ready")
        boot = self._boot()
        info = self.manager.stat()
        self.binding = dict(
            index=index,
            serial=self.serial,
            boot_id=boot,
            created_timestamp=value["created_timestamp"],
            pid=value["pid"],
            manager_identity=[info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns],
        )
        return dict(self.binding)

    def _adb(self, *args, timeout=5):
        return self._run(self.adb, "-s", self.serial, *args, timeout=timeout)

    def _boot(self):
        value = self._adb("shell", "cat", "/proc/sys/kernel/random/boot_id").decode("ascii").strip()
        if re.fullmatch(r"[a-zA-Z0-9-]{1,128}", value) is None:
            raise ProbeError("boot_unavailable")
        return value

    def assert_current(self):
        if self.binding is None:
            raise ProbeError("binding_required")
        value = self._info(self.binding["index"])
        info = self.manager.stat()
        if (
            value["created_timestamp"] != self.binding["created_timestamp"]
            or value["pid"] != self.binding["pid"]
            or f"127.0.0.1:{value['adb_port']}" != self.serial
            or [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]
            != self.binding["manager_identity"]
            or self._boot() != self.binding["boot_id"]
        ):
            raise ProbeError("binding_changed")

    def write_location(self, point):
        self.assert_current()
        args = MuMu684Commands(self.host_version, 35, self.binding["index"]).location(
            longitude=point.longitude, latitude=point.latitude
        )
        raw = self._run(self.manager, *args, timeout=5)
        self.last_delivery = raw
        # Delivery is not readback. Unexpected vendor output is ambiguous.
        decode_delivery(raw)

    def prepare_probe(self, guard):
        """Readiness of the real GPS service, distinct from the MuMu boot flag."""
        self.assert_current()
        guard()
        output = self._adb(
            "shell", "am", "start", "-W", "-n", PACKAGE + "/.MainActivity", timeout=10
        )
        if b"Status: ok" not in output or b"Error" in output:
            raise ProbeError("own_activity_start_failed")
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            guard()
            raw = self._adb("shell", "dumpsys", "location")
            if re.search(rb"(?m)^[ \t]+gps provider:[ \t]*\r?$", raw):
                self.assert_current()
                return
            time.sleep(0.3)
        raise ProbeError("gps_provider_not_ready")

    def start_observation(self, root):
        self.assert_current()
        self.nonce = secrets.token_hex(16)
        self._report_anchor = None
        self.report_file = f"files/continuous-{self.nonce}.json"
        self.stop_file = f"files/continuous-{self.nonce}.stop"
        self._output = tempfile.TemporaryFile(dir=root)
        args = [
            str(self.adb),
            "-s",
            self.serial,
            "shell",
            "am",
            "instrument",
            "-w",
            "-r",
            "-e",
            "class",
            CONTINUOUS_TEST,
            "-e",
            "continuousNonce",
            self.nonce,
            "-e",
            "continuousDurationMs",
            "1800000",
            f"{PACKAGE}.test/android.test.InstrumentationTestRunner",
        ]
        self.observer = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=self._output,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            try:
                report = self.read_observation()
                if report["state"] == "observing":
                    return
                if report["state"] == "error":
                    raise ProbeError(report["error_code"])
            except ProbeError as error:
                if error.code != "command_failed":
                    raise
            if self.observer.poll() is not None:
                raise ProbeError("observation_start_failed")
            time.sleep(0.15)
        raise ProbeError("observation_start_timeout")

    def read_observation(self):
        raw = self._adb("exec-out", "run-as", PACKAGE, "cat", self.report_file)
        # Some adb builds return exit 0 even when run-as/cat failed.
        if not raw.lstrip().startswith(b"{"):
            raise ProbeError("command_failed")
        value = decode_observation(raw, nonce=self.nonce, boot_id=self.binding["boot_id"])
        if value["state"] == "observing":
            if self.observer.poll() is not None:
                raise ProbeError("observation_ended")
            now = time.monotonic()
            if self._report_anchor is None:
                self._report_anchor = now, value["reported_at_ns"]
            elapsed = now - self._report_anchor[0]
            device_elapsed = (value["reported_at_ns"] - self._report_anchor[1]) / 1e9
            if abs(elapsed - device_elapsed) > 2:
                raise ProbeError("observation_stale")
        return value

    def stop_observation(self):
        if self.observer is None:
            return
        self._adb("exec-out", "run-as", PACKAGE, "touch", self.stop_file)
        try:
            self.observer.wait(timeout=6)
        except subprocess.TimeoutExpired:
            raise ProbeError("observation_cleanup_unconfirmed") from None
        report = self.read_observation()
        self._output.seek(0)
        output = self._output.read(65537)
        if (
            self.observer.returncode != 0
            or len(output) > 65536
            or b"OK (1 test)" not in output
            or b"INSTRUMENTATION_CODE: -1" not in output
            or b"FAILURES!!!" in output
            or report["state"] != "stopped"
        ):
            raise ProbeError("observation_cleanup_unconfirmed")
        self._adb("exec-out", "run-as", PACKAGE, "rm", "-f", self.stop_file, self.report_file)
        self._output.close()
        self._output = None
        self.observer = None

    def read_retained_location(self):
        return decode_retained_location(self._adb("shell", "dumpsys", "location"))

    def shutdown(self, index, *, expected_created_timestamp):
        """Explicit recovery only: a stopped VM ends old device-side work."""
        initial = self.inspect_identity(index)
        if (
            str(initial.get("index")) != index
            or initial.get("created_timestamp") != expected_created_timestamp
        ):
            raise ProbeError("recovery_instance_changed")
        if (
            initial.get("is_process_started") is not False
            or initial.get("is_android_started") is not False
        ):
            self._run(self.manager, "control", "--vmindex", index, "shutdown", timeout=10)
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            value = self.inspect_identity(index)
            if (
                str(value.get("index")) != index
                or value.get("created_timestamp") != expected_created_timestamp
            ):
                raise ProbeError("recovery_instance_changed")
            if (
                value.get("is_process_started") is False
                and value.get("is_android_started") is False
            ):
                if self.observer is not None:
                    try:
                        self.observer.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        raise ProbeError("observation_cleanup_unconfirmed") from None
                    self.observer = None
                if self._output is not None:
                    self._output.close()
                    self._output = None
                return
            time.sleep(0.25)
        raise ProbeError("stop_unconfirmed")
