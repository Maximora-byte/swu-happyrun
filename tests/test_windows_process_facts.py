"""Synthetic only: never inspect Windows processes or devices."""

import json
from types import SimpleNamespace

import pytest

from swu_happyrun.drivers.mumu import windows_process_facts as facts


class FakeAPI:
    def __init__(self, *, complete=True, denied=False, creation=100):
        self.complete, self.denied, self.creation = complete, denied, creation

    def enumerate(self, deadline):
        return [(17, 9)], self.complete

    def process(self, pid, deadline):
        if self.denied:
            raise PermissionError("private identifier must not leak")
        return self.creation, r"C:\private\program.exe", (5, 600)


def test_collect_identity_and_private_repr(monkeypatch):
    monkeypatch.setattr(facts.time, "monotonic", lambda: 1.0)
    result = facts._collect(FakeAPI(), 10)
    assert result.status == "complete"
    assert result.processes[0].identity == (17, 100)
    assert result.processes[0].executable_file_identity == (5, 600)
    assert "private" not in repr(result)
    assert "600" not in repr(result.processes[0])


def test_access_denied_never_exit(monkeypatch):
    monkeypatch.setattr(facts.time, "monotonic", lambda: 1.0)
    result = facts._collect(FakeAPI(denied=True), 10)
    assert result.status == "partial"
    assert result.processes[0].status == "denied"
    assert result.processes[0].identity is None


def test_pid_reuse_distinct_identity(monkeypatch):
    monkeypatch.setattr(facts.time, "monotonic", lambda: 1.0)
    a = facts._collect(FakeAPI(creation=100), 10).processes[0]
    b = facts._collect(FakeAPI(creation=101), 10).processes[0]
    assert a.identity != b.identity


def test_partial_snapshot_and_absent_pid_are_not_exit(monkeypatch):
    monkeypatch.setattr(facts.time, "monotonic", lambda: 1.0)
    result = facts._collect(FakeAPI(complete=False), 10)
    assert result.status == "partial"
    assert not hasattr(result, "exited")


def test_deadline_collect_stops_without_calling_api(monkeypatch):
    monkeypatch.setattr(facts.time, "monotonic", lambda: 10.0)
    result = facts._collect(None, 10)
    assert result.status == "unknown"
    assert result.code == "process_facts_timeout"


def test_process_cap_is_partial(monkeypatch):
    monkeypatch.setattr(facts.time, "monotonic", lambda: 1.0)
    api = FakeAPI()
    api.enumerate = lambda deadline: ([(i, 0) for i in range(facts.MAX_PROCESSES + 1)], True)
    result = facts._collect(api, 10)
    assert len(result.processes) == facts.MAX_PROCESSES
    assert result.status == "partial"


def test_helper_capture_receives_absolute_cleanup_deadline(monkeypatch):
    monkeypatch.setattr(facts, "_is_windows", lambda: True)
    monkeypatch.setattr(facts.time, "monotonic", lambda: 1.0)
    payload = facts._encode(facts._collect(FakeAPI(), 10))
    seen = {}

    def capture(path, *args, **kwargs):
        seen.update(kwargs)
        kwargs["evidence"].snapshot = SimpleNamespace(
            cleanup_code="confirmed", output_complete=True
        )
        return payload, b"", 0

    monkeypatch.setattr(facts, "_run_bounded_bytes", capture)
    result = facts.query_process_facts(4)
    assert result.status == "complete"
    assert seen["cleanup_deadline_monotonic"] == 4
    assert seen["timeout"] <= 3 - facts.CLEANUP_RESERVE


def test_helper_timeout_discards_untrusted_bytes(monkeypatch):
    monkeypatch.setattr(facts, "_is_windows", lambda: True)
    monkeypatch.setattr(facts.time, "monotonic", lambda: 1.0)

    def capture(*args, **kwargs):
        raise facts.ProbeError("command_timeout")

    monkeypatch.setattr(facts, "_run_bounded_bytes", capture)
    result = facts.query_process_facts(10)
    assert result.status == "unknown"
    assert result.processes == ()
    assert result.code == "process_facts_timeout"
    assert not result.cleanup_confirmed


@pytest.mark.parametrize("deadline", [float("nan"), float("inf"), -1, True, "10"])
def test_invalid_deadline_never_spawns(monkeypatch, deadline):
    monkeypatch.setattr(facts, "_run_bounded_bytes", lambda *a, **k: pytest.fail("spawn"))
    assert facts.query_process_facts(deadline).status == "unknown"


def test_malformed_wire_unknown(monkeypatch):
    monkeypatch.setattr(facts, "_is_windows", lambda: True)
    monkeypatch.setattr(facts.time, "monotonic", lambda: 1.0)

    def capture(*args, **kwargs):
        kwargs["evidence"].snapshot = SimpleNamespace(
            cleanup_code="confirmed", output_complete=True
        )
        return json.dumps({"status": "complete", "processes": []}).encode(), b"", 0

    monkeypatch.setattr(facts, "_run_bounded_bytes", capture)
    assert facts.query_process_facts(10).status == "unknown"


class NativeKernel:
    """Only the read API surface: adding process control would break tests."""

    def __init__(self, *, denied=False):
        self.denied = denied
        self.closed = []
        self.access = []
        self.opens = []
        self.drive_type = 3
        self.filesystem = "NTFS"
        self.reparse_paths = set()
        self.reparse_handles = set()

    def OpenProcess(self, access, inherit, pid):
        self.access.append((access, inherit, pid))
        return None if self.denied else 123

    def GetProcessTimes(self, handle, creation, exit_time, kernel, user):
        creation._obj.dwHighDateTime = 1
        creation._obj.dwLowDateTime = 3
        return True

    def QueryFullProcessImageNameW(self, handle, flags, buffer, size):
        buffer.value = r"C:\private\program.exe"
        size._obj.value = len(buffer.value)
        return True

    def GetDriveTypeW(self, root):
        return self.drive_type

    def GetVolumeInformationByHandleW(
        self, root, volume, volume_size, serial, maximum, flags, fs, fs_size
    ):
        fs.value = self.filesystem
        return True

    def GetFileAttributesW(self, path):
        return 0x400 if path in self.reparse_paths else (0x10 if not path.endswith(".exe") else 0)

    def CreateFileW(self, path, access, sharing, security, disposition, flags, template):
        assert access == 0x80 and sharing == 1 and disposition == 3
        assert flags & 0x00200000
        self.opens.append(path)
        return 456 if path.endswith(".exe") else 699 + len(self.opens)

    def GetFileInformationByHandle(self, handle, info):
        info._obj.attributes = 0 if handle == 456 else 0x10
        if handle in self.reparse_handles:
            info._obj.attributes |= 0x400
        info._obj.volume = 5
        info._obj.index_high = 2
        info._obj.index_low = 7
        return True

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return True


def test_native_queries_use_read_only_handles_and_close_them(monkeypatch):
    monkeypatch.setattr(facts.time, "monotonic", lambda: 1.0)
    kernel = NativeKernel()
    api = object.__new__(facts._WinAPI)
    api.kernel = kernel
    creation, path, identity = api.process(17, 10)
    assert creation == (1 << 32) | 3
    assert identity == (5, (2 << 32) | 7)
    assert path == r"C:\private\program.exe"
    assert kernel.access == [(0x1000, False, 17)]
    assert kernel.closed == [456, 701, 700, 123]


def test_native_access_denied_is_not_exit(monkeypatch):
    monkeypatch.setattr(facts.time, "monotonic", lambda: 1.0)
    monkeypatch.setattr(facts.ct, "get_last_error", lambda: 5, raising=False)
    api = object.__new__(facts._WinAPI)
    api.kernel = NativeKernel(denied=True)
    with pytest.raises(PermissionError, match="^process_facts_denied$"):
        api.process(17, 10)
    assert api.kernel.closed == []


def test_native_deadline_closes_existing_handle_without_file_query(monkeypatch):
    ticks = iter([1.0, 10.0])
    monkeypatch.setattr(facts.time, "monotonic", lambda: next(ticks))
    api = object.__new__(facts._WinAPI)
    api.kernel = NativeKernel()
    with pytest.raises(OSError, match="^process_facts_timeout$"):
        api.process(17, 10)
    assert api.kernel.closed == [123]


def test_native_failed_file_query_closes_all_handles(monkeypatch):
    monkeypatch.setattr(facts.time, "monotonic", lambda: 1.0)
    monkeypatch.setattr(facts.ct, "get_last_error", lambda: 5, raising=False)
    api = object.__new__(facts._WinAPI)
    api.kernel = NativeKernel()
    original = api.kernel.GetFileInformationByHandle
    api.kernel.GetFileInformationByHandle = lambda handle, info: (
        False if handle == 456 else original(handle, info)
    )
    with pytest.raises(PermissionError):
        api.process(17, 10)
    assert api.kernel.closed == [456, 701, 700, 123]


def test_native_partial_enumeration_is_not_complete(monkeypatch):
    monkeypatch.setattr(facts.time, "monotonic", lambda: 1.0)
    monkeypatch.setattr(facts.ct, "get_last_error", lambda: 5, raising=False)
    api = object.__new__(facts._WinAPI)
    api.kernel = NativeKernel()
    api.kernel.CreateToolhelp32Snapshot = lambda flags, pid: 999

    def first(handle, entry):
        entry._obj.th32ProcessID = 17
        entry._obj.th32ParentProcessID = 9
        return True

    api.kernel.Process32FirstW = first
    api.kernel.Process32NextW = lambda *args: False
    assert api.enumerate(10) == ([(17, 9)], False)
    assert api.kernel.closed == [999]


def test_payload_cap_does_not_emit_partial_valid_json(monkeypatch):
    monkeypatch.setattr(facts, "MAX_PAYLOAD_BYTES", 300)
    result = facts.ProcessFactsSnapshot(
        "complete", (facts.ProcessFact(1, 0, 100, "C:\\" + "x" * 400, (5, 600), "ok"),), "ok"
    )
    decoded = facts._decode(facts._encode(result))
    assert decoded.status == "unknown"
    assert decoded.processes == ()


def test_valid_bytes_cannot_override_unconfirmed_cleanup(monkeypatch):
    monkeypatch.setattr(facts, "_is_windows", lambda: True)
    monkeypatch.setattr(facts.time, "monotonic", lambda: 1.0)
    payload = facts._encode(facts._collect(FakeAPI(), 10))

    def capture(*args, **kwargs):
        kwargs["evidence"].snapshot = SimpleNamespace(
            cleanup_code="unconfirmed", output_complete=True
        )
        return payload, b"", 0

    monkeypatch.setattr(facts, "_run_bounded_bytes", capture)
    result = facts.query_process_facts(4)
    assert result.status == "unknown"
    assert not result.cleanup_confirmed


def test_total_path_storage_is_capped(monkeypatch):
    monkeypatch.setattr(facts.time, "monotonic", lambda: 1.0)
    monkeypatch.setattr(facts, "MAX_TOTAL_PATH_CHARS", 30, raising=False)
    api = FakeAPI()
    api.enumerate = lambda deadline: ([(1, 0), (2, 0), (3, 0)], True)
    result = facts._collect(api, 10)
    assert result.status == "partial"
    assert len(result.processes) == 1


def test_source_helper_bootstrap_works_without_caller_import_path(monkeypatch, tmp_path):
    if facts.os.name == "nt":
        pytest.skip("Synthetic non-Windows helper only; no real Windows inspection")
    monkeypatch.setattr(facts, "_is_windows", lambda: True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    decoded = []
    original_decode = facts._decode

    def decode(raw):
        decoded.append(raw)
        return original_decode(raw)

    monkeypatch.setattr(facts, "_decode", decode)
    result = facts.query_process_facts(facts.time.monotonic() + 3)
    assert result.status == "unknown"
    # A missing/wrong package import would emit stderr/fail, not valid helper IPC.
    assert result.code == "process_facts_unavailable"
    assert result.cleanup_confirmed
    assert len(decoded) == 1


@pytest.mark.parametrize("drive_type", [0, 1, 2, 4, 5, 6])
def test_native_non_fixed_drive_never_opens_image(monkeypatch, drive_type):
    monkeypatch.setattr(facts.time, "monotonic", lambda: 1.0)
    api = object.__new__(facts._WinAPI)
    api.kernel = NativeKernel()
    api.kernel.drive_type = drive_type
    with pytest.raises(OSError):
        api.process(17, 10)
    assert api.kernel.opens == []
    assert api.kernel.closed == [123]


@pytest.mark.parametrize("path", ["C:\\", "C:\\private", r"C:\private\program.exe"])
def test_native_reparse_path_never_opens_image(monkeypatch, path):
    monkeypatch.setattr(facts.time, "monotonic", lambda: 1.0)
    api = object.__new__(facts._WinAPI)
    api.kernel = NativeKernel()
    api.kernel.reparse_paths.add(path)
    with pytest.raises(OSError):
        api.process(17, 10)
    assert r"C:\private\program.exe" not in api.kernel.opens
    assert api.kernel.closed[-1] == 123


@pytest.mark.parametrize("handle", [700, 701, 456])
def test_native_reparse_race_detected_on_open_handle(monkeypatch, handle):
    monkeypatch.setattr(facts.time, "monotonic", lambda: 1.0)
    api = object.__new__(facts._WinAPI)
    api.kernel = NativeKernel()
    api.kernel.reparse_handles.add(handle)
    with pytest.raises(OSError):
        api.process(17, 10)
    assert handle in api.kernel.closed
    if handle != 456:
        assert r"C:\private\program.exe" not in api.kernel.opens


def test_native_unsupported_filesystem_stays_unknown(monkeypatch):
    monkeypatch.setattr(facts.time, "monotonic", lambda: 1.0)
    api = object.__new__(facts._WinAPI)
    api.kernel = NativeKernel()
    api.kernel.filesystem = "ReFS"
    with pytest.raises(OSError):
        api.process(17, 10)
    assert r"C:\private\program.exe" not in api.kernel.opens


def test_native_ancestor_cap_prevents_path_reads(monkeypatch):
    monkeypatch.setattr(facts.time, "monotonic", lambda: 1.0)
    monkeypatch.setattr(facts, "MAX_PATH_COMPONENTS", 2, raising=False)
    api = object.__new__(facts._WinAPI)
    api.kernel = NativeKernel()
    with pytest.raises(OSError):
        api.process(17, 10)
    assert api.kernel.opens == []
