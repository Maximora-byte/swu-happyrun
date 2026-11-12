"""Read-only Windows process facts, never MuMu ownership or exit confirmation.

The fixed Python helper isolates potentially blocking Win32 calls. Shared capture
owns/cleans up only this helper, never enumerated processes. The caller supplies
one absolute monotonic deadline, including helper cleanup. OS scheduling/process
creation cannot provide hard real-time guarantees; overruns fail closed.

A missing PID is NOT exit evidence, even in a complete snapshot. Parent PID is
only a Toolhelp snapshot hint (the parent itself can have exited/reused its PID).
File identity describes the file opened at the reported path, not an attestation
of the executable image loaded in memory. All identities are private evidence.

Native references:
https://learn.microsoft.com/en-us/windows/win32/api/tlhelp32/ns-tlhelp32-processentry32w
https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes
https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfileinformationbyhandle
"""

from __future__ import annotations

import ctypes as ct
import json
import math
import os
import sys
import time
from ctypes import wintypes as wt
from dataclasses import dataclass, field, replace
from pathlib import Path, PureWindowsPath

from swu_happyrun.drivers.command import CaptureEvidence, ProbeError, _run_bounded_bytes

MAX_PROCESSES = 512
MAX_PATH_CHARS = 32768
MAX_TOTAL_PATH_CHARS = 65536
MAX_PATH_COMPONENTS = 64
MAX_PAYLOAD_BYTES = 512 * 1024
MAX_QUERY_SECONDS = 5.0
CLEANUP_RESERVE = 0.5
_CODES = {"ok", "process_facts_partial", "process_facts_timeout", "process_facts_unavailable"}


@dataclass(frozen=True)
class ProcessFact:
    pid: int = field(repr=False)
    parent_pid: int = field(repr=False)
    creation_time_100ns: int | None = field(default=None, repr=False)
    executable_path: str | None = field(default=None, repr=False)
    executable_file_identity: tuple[int, int] | None = field(default=None, repr=False)
    status: str = "unknown"

    @property
    def identity(self) -> tuple[int, int] | None:
        return None if self.creation_time_100ns is None else (self.pid, self.creation_time_100ns)


@dataclass(frozen=True)
class ProcessFactsSnapshot:
    status: str
    processes: tuple[ProcessFact, ...] = field(default=(), repr=False)
    code: str = "process_facts_unavailable"
    started_monotonic: float = 0.0
    finished_monotonic: float = 0.0
    cleanup_confirmed: bool = False


def _is_windows():
    return os.name == "nt"


def _unknown(started, code="process_facts_unavailable", *, cleanup=False):
    return ProcessFactsSnapshot(
        "unknown",
        code=code,
        started_monotonic=started,
        finished_monotonic=time.monotonic(),
        cleanup_confirmed=cleanup,
    )


def query_process_facts(deadline: float) -> ProcessFactsSnapshot:
    """Return bounded private facts or explicit unknown, never raise raw OS data.

    No caller-selected command, process executable, or shell is executed. A
    complete result means enumeration and requested facts completed, not that a
    process group belongs to MuMu or that an absent process has stopped.
    """
    started = time.monotonic()
    if type(deadline) not in (int, float):
        return _unknown(started)
    try:
        if not math.isfinite(deadline) or deadline <= started:
            return _unknown(started, "process_facts_timeout")
    except OverflowError:
        return _unknown(started)
    if not _is_windows():
        return _unknown(started)
    deadline = min(deadline, started + MAX_QUERY_SECONDS)
    work_deadline = deadline - CLEANUP_RESERVE
    if time.monotonic() >= work_deadline:
        return _unknown(started, "process_facts_timeout")
    evidence = CaptureEvidence()
    try:
        raw, stderr, rc = _run_bounded_bytes(
            Path(sys.executable),
            "-I",
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "from swu_happyrun.drivers.mumu.windows_process_facts import _helper; _helper()",
            str(Path(__file__).resolve().parents[3]),
            repr(work_deadline),
            timeout=work_deadline - time.monotonic(),
            cleanup_deadline_monotonic=deadline,
            evidence=evidence,
        )
        snapshot = evidence.snapshot
        if (
            rc != 0
            or stderr
            or snapshot is None
            or not snapshot.output_complete
            or snapshot.cleanup_code != "confirmed"
            or len(raw) > MAX_PAYLOAD_BYTES
        ):
            return _unknown(
                started, cleanup=bool(snapshot and snapshot.cleanup_code == "confirmed")
            )
        result = _decode(raw)
        if time.monotonic() >= deadline:
            return _unknown(started, "process_facts_timeout", cleanup=True)
        return replace(
            result,
            started_monotonic=started,
            finished_monotonic=time.monotonic(),
            cleanup_confirmed=True,
        )
    except (
        ProbeError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        OverflowError,
        RecursionError,
    ) as exc:
        cleanup = bool(evidence.snapshot and evidence.snapshot.cleanup_code == "confirmed")
        timed_out = isinstance(exc, ProbeError) and (
            exc.code == "command_timeout" or exc.primary_code == "command_timeout"
        )
        code = "process_facts_timeout" if timed_out else "process_facts_unavailable"
        return _unknown(started, code, cleanup=cleanup)


def _collect(api, deadline):
    started = time.monotonic()
    if started >= deadline:
        return _unknown(started, "process_facts_timeout")
    try:
        rows, complete = api.enumerate(deadline)
    except (OSError, ValueError):
        return _unknown(started)
    complete = complete and len(rows) <= MAX_PROCESSES
    records = []
    path_chars = 0
    for pid, parent in rows[:MAX_PROCESSES]:
        if time.monotonic() >= deadline:
            return ProcessFactsSnapshot(
                "partial", tuple(records), "process_facts_timeout", started, time.monotonic()
            )
        try:
            creation, path, file_id = api.process(pid, deadline)
            path_chars += len(path)
            if path_chars > MAX_TOTAL_PATH_CHARS:
                complete = False
                break
            record = ProcessFact(pid, parent, creation, path, file_id, "ok")
        except PermissionError:
            record = ProcessFact(pid, parent, status="denied")
            complete = False
        except (OSError, ValueError):
            record = ProcessFact(pid, parent)
            complete = False
        records.append(record)
    if time.monotonic() >= deadline:
        complete = False
    return ProcessFactsSnapshot(
        "complete" if complete else "partial",
        tuple(records),
        "ok" if complete else "process_facts_partial",
        started,
        time.monotonic(),
    )


def _encode(result):
    raw = json.dumps(
        {
            "version": 1,
            "status": result.status,
            "code": result.code,
            "processes": [
                [
                    p.pid,
                    p.parent_pid,
                    p.creation_time_100ns,
                    p.executable_path,
                    p.executable_file_identity,
                    p.status,
                ]
                for p in result.processes
            ],
        },
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")
    if len(raw) > MAX_PAYLOAD_BYTES:
        return _encode(_unknown(0))
    return raw


def _integer(value, maximum):
    return type(value) is int and 0 <= value <= maximum


def _decode(raw):
    data = json.loads(raw)
    if type(data) is not dict or set(data) != {"version", "status", "code", "processes"}:
        raise ValueError("process_facts_unavailable")
    status, code, rows = data["status"], data["code"], data["processes"]
    if (
        type(data["version"]) is not int
        or data["version"] != 1
        or status not in {"complete", "partial", "unknown"}
        or code not in _CODES
        or type(rows) is not list
        or len(rows) > MAX_PROCESSES
    ):
        raise ValueError("process_facts_unavailable")
    records, seen = [], set()
    for row in rows:
        if type(row) is not list or len(row) != 6:
            raise ValueError("process_facts_unavailable")
        pid, parent, creation, path, identity, state = row
        if (
            not _integer(pid, 2**32 - 1)
            or not _integer(parent, 2**32 - 1)
            or pid in seen
            or state not in {"ok", "denied", "unknown"}
        ):
            raise ValueError("process_facts_unavailable")
        seen.add(pid)
        if state == "ok":
            if (
                not _integer(creation, 2**64 - 1)
                or creation == 0
                or type(path) is not str
                or not 0 < len(path) < MAX_PATH_CHARS
                or "\0" in path
                or not PureWindowsPath(path).is_absolute()
                or type(identity) is not list
                or len(identity) != 2
                or not _integer(identity[0], 2**32 - 1)
                or not _integer(identity[1], 2**64 - 1)
                or identity[1] == 0
            ):
                raise ValueError("process_facts_unavailable")
            identity = tuple(identity)
        elif any(value is not None for value in (creation, path, identity)):
            raise ValueError("process_facts_unavailable")
        records.append(ProcessFact(pid, parent, creation, path, identity, state))
    if (
        status == "complete"
        and (code != "ok" or any(p.status != "ok" for p in records))
        or status == "unknown"
        and records
        or status != "complete"
        and code == "ok"
    ):
        raise ValueError("process_facts_unavailable")
    return ProcessFactsSnapshot(status, tuple(records), code)


class _ProcessEntry(ct.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ct.c_size_t),
        ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", wt.LONG),
        ("dwFlags", wt.DWORD),
        ("szExeFile", wt.WCHAR * 260),
    ]


class _FileInformation(ct.Structure):
    _fields_ = [
        ("attributes", wt.DWORD),
        ("creation", wt.FILETIME),
        ("access", wt.FILETIME),
        ("write", wt.FILETIME),
        ("volume", wt.DWORD),
        ("size_high", wt.DWORD),
        ("size_low", wt.DWORD),
        ("links", wt.DWORD),
        ("index_high", wt.DWORD),
        ("index_low", wt.DWORD),
    ]


class _WinAPI:
    def __init__(self):
        if not _is_windows():
            raise OSError("process_facts_unavailable")
        self.kernel = ct.WinDLL("kernel32", use_last_error=True)
        p = ct.c_void_p
        signatures = {
            "CreateToolhelp32Snapshot": ([wt.DWORD, wt.DWORD], wt.HANDLE),
            "Process32FirstW": ([wt.HANDLE, p], wt.BOOL),
            "Process32NextW": ([wt.HANDLE, p], wt.BOOL),
            "OpenProcess": ([wt.DWORD, wt.BOOL, wt.DWORD], wt.HANDLE),
            "GetProcessTimes": ([wt.HANDLE, p, p, p, p], wt.BOOL),
            "QueryFullProcessImageNameW": ([wt.HANDLE, wt.DWORD, wt.LPWSTR, p], wt.BOOL),
            "CreateFileW": (
                [wt.LPCWSTR, wt.DWORD, wt.DWORD, p, wt.DWORD, wt.DWORD, wt.HANDLE],
                wt.HANDLE,
            ),
            "GetFileInformationByHandle": ([wt.HANDLE, p], wt.BOOL),
            "GetDriveTypeW": ([wt.LPCWSTR], wt.UINT),
            "GetFileAttributesW": ([wt.LPCWSTR], wt.DWORD),
            "GetVolumeInformationByHandleW": (
                [wt.HANDLE, wt.LPWSTR, wt.DWORD, p, p, p, wt.LPWSTR, wt.DWORD],
                wt.BOOL,
            ),
            "CloseHandle": ([wt.HANDLE], wt.BOOL),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.kernel, name)
            function.argtypes, function.restype = args, result

    @staticmethod
    def _require(ok):
        if not ok:
            if ct.get_last_error() == 5:
                raise PermissionError("process_facts_denied")
            raise OSError("process_facts_unavailable")

    @staticmethod
    def _check(deadline):
        if time.monotonic() >= deadline:
            raise OSError("process_facts_timeout")

    def enumerate(self, deadline):
        self._check(deadline)
        handle = self.kernel.CreateToolhelp32Snapshot(2, 0)  # TH32CS_SNAPPROCESS only
        self._require(handle not in {None, ct.c_void_p(-1).value})
        try:
            entry = _ProcessEntry()
            entry.dwSize = ct.sizeof(entry)
            rows = []
            ok = self.kernel.Process32FirstW(handle, ct.byref(entry))
            while ok:
                if time.monotonic() >= deadline or len(rows) >= MAX_PROCESSES:
                    return rows, False
                rows.append((int(entry.th32ProcessID), int(entry.th32ParentProcessID)))
                ok = self.kernel.Process32NextW(handle, ct.byref(entry))
            return rows, ct.get_last_error() == 18  # ERROR_NO_MORE_FILES only
        finally:
            self.kernel.CloseHandle(handle)

    def process(self, pid, deadline):
        self._check(deadline)
        handle = self.kernel.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION only
        self._require(handle)
        try:
            times = [wt.FILETIME() for _ in range(4)]
            self._require(self.kernel.GetProcessTimes(handle, *(ct.byref(t) for t in times)))
            creation = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
            self._check(deadline)
            buffer, size = ct.create_unicode_buffer(MAX_PATH_CHARS), wt.DWORD(MAX_PATH_CHARS)
            self._require(self.kernel.QueryFullProcessImageNameW(handle, 0, buffer, ct.byref(size)))
            self._require(0 < size.value < MAX_PATH_CHARS and creation > 0)
            path = buffer[: size.value]
            return creation, path, self._file_identity(path, deadline)

        finally:
            self.kernel.CloseHandle(handle)

    def _file_identity(self, path, deadline):
        """Only local NTFS, holding every non-reparse component against mutation.

        FILE_SHARE_READ only deliberately rejects existing write/delete handles;
        inability to hold a stable chain is unknown, never a reason to relax it.
        """
        parsed = PureWindowsPath(path)
        if (
            len(path) < 3
            or path[0] not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
            or path[1:3] != ":\\"
            or "/" in path
            or "\0" in path
            or any(
                part in {".", ".."} or ":" in part or part.endswith((".", " "))
                for part in path[3:].split("\\")
            )
            or len(parsed.parts) > MAX_PATH_COMPONENTS
        ):
            raise OSError("process_facts_unavailable")
        self._check(deadline)
        if self.kernel.GetDriveTypeW(parsed.anchor) != 3:  # DRIVE_FIXED only
            raise OSError("process_facts_unavailable")
        handles = []
        try:
            paths = [*reversed(parsed.parents), parsed]
            for index, component in enumerate(paths):
                self._check(deadline)
                attrs = self.kernel.GetFileAttributesW(str(component))
                if attrs == 0xFFFFFFFF or attrs & 0x400:
                    raise OSError("process_facts_unavailable")
                self._check(deadline)
                is_directory = index < len(paths) - 1
                flags = 0x00200000 | (0x02000000 if is_directory else 0)
                handle = self.kernel.CreateFileW(str(component), 0x80, 1, None, 3, flags, None)
                self._require(handle not in {None, ct.c_void_p(-1).value})
                handles.append(handle)
                self._check(deadline)
                info = _FileInformation()
                self._require(self.kernel.GetFileInformationByHandle(handle, ct.byref(info)))
                if info.attributes & 0x400 or bool(info.attributes & 0x10) != is_directory:
                    raise OSError("process_facts_unavailable")
                if index == 0:
                    self._check(deadline)
                    filesystem = ct.create_unicode_buffer(32)
                    self._require(
                        self.kernel.GetVolumeInformationByHandleW(
                            handle, None, 0, None, None, None, filesystem, len(filesystem)
                        )
                    )
                    # Legacy 64-bit file index is not universally unique on ReFS.
                    if filesystem.value != "NTFS":
                        raise OSError("process_facts_unavailable")
                if not is_directory:
                    file_index = (info.index_high << 32) | info.index_low
                    if file_index == 0:
                        raise OSError("process_facts_unavailable")
                    self._check(deadline)
                    return int(info.volume), file_index
            raise OSError("process_facts_unavailable")
        finally:
            for handle in reversed(handles):
                self.kernel.CloseHandle(handle)


def _helper():
    """Fixed private IPC entrypoint; no public CLI, no raw exceptions/stderr."""
    try:
        deadline = float(sys.argv[2])
        if not math.isfinite(deadline):
            raise ValueError
        result = _collect(_WinAPI(), min(deadline, time.monotonic() + MAX_QUERY_SECONDS))
        sys.stdout.buffer.write(_encode(result))
        sys.stdout.buffer.flush()
    except Exception:
        # Raw exception messages can contain paths. Parent sees only unavailable.
        sys.stdout.buffer.write(_encode(_unknown(time.monotonic())))
        sys.stdout.buffer.flush()
