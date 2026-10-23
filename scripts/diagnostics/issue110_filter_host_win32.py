"""Internal, default-closed Win32 bindings for the accepted bundle/host seams.

No entry point constructs these APIs. No COM ABI or DbgEng call lives here.
Official declarations: processthreadsapi.h, jobapi2.h, winbase.h and winnt.h.
ctypes uses fixed DWORD/LONG widths and pointer-sized HANDLE/SIZE_T fields even
on non-Windows test hosts. Fake calls do not validate the actual Windows ABI.

A reviewed new EXE and exact Windows dependency admission are deliberately
absent. Their production gates stay unknown, not a user-populated allowlist.
Monitored deadlines and file budgets are NOT OS hard-wall/disk guarantees.
"""

import ctypes as ct
import hashlib
import io
import math
import ntpath
import os
import time
import types
from dataclasses import dataclass
from pathlib import Path

from issue110_debugger_config import VERSION
from issue110_debugger_config_local import DEBUGGER_HASHES
from issue110_filter_bundle import EXE_NAME, BundleError, SignatureVerification
from issue110_filter_contract import Blocker, BoundFile, FileIdentity, ReviewedBuild, parse_request
from issue110_filter_pe import PE_LIMIT, DependencyEvidence
from issue110_filter_supervisor import (
    CreationResult,
    ExitState,
    TransportHandles,
)
from issue110_filter_supervisor import (
    InheritedHandle as InheritedHandle,
)
from issue110_local_acl import FILTER_PROBE_CHILD, Native, check_descriptor, components

DWORD, BOOL, WORD = ct.c_uint32, ct.c_int32, ct.c_uint16
HANDLE, SIZE_T, ULONG_PTR = ct.c_void_p, ct.c_size_t, ct.c_size_t
INVALID_HANDLE_VALUE = ct.c_void_p(-1).value


class SECURITY_ATTRIBUTES(ct.Structure):
    _fields_ = [("nLength", DWORD), ("lpSecurityDescriptor", HANDLE), ("bInheritHandle", BOOL)]


class STARTUPINFOW(ct.Structure):
    _fields_ = [
        ("cb", DWORD),
        ("lpReserved", ct.c_wchar_p),
        ("lpDesktop", ct.c_wchar_p),
        ("lpTitle", ct.c_wchar_p),
        ("dwX", DWORD),
        ("dwY", DWORD),
        ("dwXSize", DWORD),
        ("dwYSize", DWORD),
        ("dwXCountChars", DWORD),
        ("dwYCountChars", DWORD),
        ("dwFillAttribute", DWORD),
        ("dwFlags", DWORD),
        ("wShowWindow", WORD),
        ("cbReserved2", WORD),
        ("lpReserved2", HANDLE),
        ("hStdInput", HANDLE),
        ("hStdOutput", HANDLE),
        ("hStdError", HANDLE),
    ]


class STARTUPINFOEXW(ct.Structure):
    _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", HANDLE)]


class PROCESS_INFORMATION(ct.Structure):
    _fields_ = [
        ("hProcess", HANDLE),
        ("hThread", HANDLE),
        ("dwProcessId", DWORD),
        ("dwThreadId", DWORD),
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ct.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ct.c_int64),
        ("PerJobUserTimeLimit", ct.c_int64),
        ("LimitFlags", DWORD),
        ("MinimumWorkingSetSize", SIZE_T),
        ("MaximumWorkingSetSize", SIZE_T),
        ("ActiveProcessLimit", DWORD),
        ("Affinity", ULONG_PTR),
        ("PriorityClass", DWORD),
        ("SchedulingClass", DWORD),
    ]


class IO_COUNTERS(ct.Structure):
    _fields_ = [
        (name, ct.c_uint64)
        for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ct.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", SIZE_T),
        ("JobMemoryLimit", SIZE_T),
        ("PeakProcessMemoryUsed", SIZE_T),
        ("PeakJobMemoryUsed", SIZE_T),
    ]


class JOBOBJECT_BASIC_ACCOUNTING_INFORMATION(ct.Structure):
    _fields_ = [
        (name, ct.c_int64)
        for name in (
            "TotalUserTime",
            "TotalKernelTime",
            "ThisPeriodTotalUserTime",
            "ThisPeriodTotalKernelTime",
        )
    ] + [
        (name, DWORD)
        for name in (
            "TotalPageFaultCount",
            "TotalProcesses",
            "ActiveProcesses",
            "TotalTerminatedProcesses",
        )
    ]


class FILE_ID_128(ct.Structure):
    _fields_ = [("Identifier", ct.c_ubyte * 16)]


class FILE_ID_INFO(ct.Structure):
    _fields_ = [("VolumeSerialNumber", ct.c_uint64), ("FileId", FILE_ID_128)]


class FILE_ATTRIBUTE_TAG_INFO(ct.Structure):
    _fields_ = [("FileAttributes", DWORD), ("ReparseTag", DWORD)]


class VS_FIXEDFILEINFO(ct.Structure):
    _fields_ = [
        (name, DWORD)
        for name in (
            "dwSignature",
            "dwStrucVersion",
            "dwFileVersionMS",
            "dwFileVersionLS",
            "dwProductVersionMS",
            "dwProductVersionLS",
            "dwFileFlagsMask",
            "dwFileFlags",
            "dwFileOS",
            "dwFileType",
            "dwFileSubtype",
            "dwFileDateMS",
            "dwFileDateLS",
        )
    ]


def _kernel32():
    if os.name != "nt" or ct.sizeof(HANDLE) != 8:
        raise BundleError(Blocker.UNSUPPORTED)
    kernel = ct.WinDLL("kernel32", use_last_error=True, winmode=0x800)
    P, W, U, B, S = HANDLE, ct.c_wchar_p, DWORD, BOOL, SIZE_T
    declarations = (
        ("CreateJobObjectW", [P, W], P),
        ("SetInformationJobObject", [P, ct.c_int32, P, U], B),
        ("QueryInformationJobObject", [P, ct.c_int32, P, U, P], B),
        ("InitializeProcThreadAttributeList", [P, U, U, P], B),
        ("UpdateProcThreadAttribute", [P, U, S, P, S, P, P], B),
        ("DeleteProcThreadAttributeList", [P], None),
        ("GetHandleInformation", [P, P], B),
        ("CreateProcessW", [W, W, P, P, B, U, P, W, P, P], B),
        ("QueryFullProcessImageNameW", [P, U, W, P], B),
        ("ResumeThread", [P], U),
        ("WaitForSingleObject", [P, U], U),
        ("GetExitCodeProcess", [P, P], B),
        ("TerminateJobObject", [P, U], B),
        ("CloseHandle", [P], B),
        ("CreateDirectoryW", [W, P], B),
        ("GetSystemWindowsDirectoryW", [W, U], U),
        ("CreateFileW", [W, U, U, P, U, U, P], P),
        ("GetFileInformationByHandleEx", [P, ct.c_int32, P, U], B),
        ("GetFinalPathNameByHandleW", [P, W, U, U], U),
        ("GetFileSizeEx", [P, P], B),
        ("SetFilePointerEx", [P, ct.c_int64, P, U], B),
        ("ReadFile", [P, P, U, P, P], B),
        ("WriteFile", [P, P, U, P, P], B),
        ("FlushFileBuffers", [P], B),
    )
    for name, args, result in declarations:
        function = getattr(kernel, name)  # Missing required API is unsupported; no fallback.
        function.argtypes, function.restype = args, result
    return kernel


def _require(value):
    if not value:
        raise BundleError(Blocker.IO_FAILURE)
    return value


def _handle(value):
    if value in (None, 0, INVALID_HANDLE_VALUE) or type(value) is bool:
        raise BundleError(Blocker.IO_FAILURE)
    return value


def _absolute(path):
    if (
        type(path) is not str
        or not 3 < len(path) < 8192
        or not ntpath.isabs(path)
        or len(ntpath.splitdrive(path)[0]) != 2
        or path[1:3] != ":\\"
        or "/" in path
        or "\0" in path
    ):
        raise BundleError(Blocker.BUNDLE_REJECTED)
    for part in path[3:].split("\\"):
        if not part or part in (".", "..") or part.endswith((".", " ")) or ":" in part:
            raise BundleError(Blocker.BUNDLE_REJECTED)
    return path


class _Files:
    def __init__(self, *, _kernel=None, _clock=time.monotonic):
        self.kernel = _kernel if _kernel is not None else _kernel32()
        self._clock = _clock
        self._cleanup_deadline = None
        self._pins = {}
        self._pending = []
        self._closed = set()
        self._cleanup_uncertain = False

    def now(self):
        value = self._clock()
        if type(value) not in (int, float) or not math.isfinite(value):
            raise BundleError(Blocker.DEADLINE)
        return value

    def _checkpoint(self, deadline):
        if (
            type(deadline) not in (int, float)
            or not math.isfinite(deadline)
            or self._cleanup_deadline is not None
            or self.now() >= deadline
        ):
            raise BundleError(Blocker.DEADLINE)

    def _bind_cleanup(self, deadline):
        if (
            type(deadline) not in (int, float)
            or not math.isfinite(deadline)
            or deadline > self.now() + 5
            or (self._cleanup_deadline is not None and deadline != self._cleanup_deadline)
        ):
            raise BundleError(Blocker.CLEANUP_UNKNOWN)
        self._cleanup_deadline = deadline

    def _inheritance(self, handle, expected):
        flags = DWORD()
        _require(self.kernel.GetHandleInformation(handle, ct.byref(flags)))
        if bool(flags.value & 1) is not expected:
            raise BundleError(Blocker.BUNDLE_REJECTED)

    def _identity(self, handle, *, directory=False):
        attributes = FILE_ATTRIBUTE_TAG_INFO()
        _require(
            self.kernel.GetFileInformationByHandleEx(
                handle, 9, ct.byref(attributes), ct.sizeof(attributes)
            )
        )
        if (
            attributes.FileAttributes & 0x400
            or bool(attributes.FileAttributes & 0x10) is not directory
        ):
            raise BundleError(Blocker.BUNDLE_REJECTED)
        identity = FILE_ID_INFO()
        _require(
            self.kernel.GetFileInformationByHandleEx(
                handle, 18, ct.byref(identity), ct.sizeof(identity)
            )
        )
        return FileIdentity(identity.VolumeSerialNumber, bytes(identity.FileId.Identifier))

    def _final_path(self, handle):
        buffer = ct.create_unicode_buffer(8192)
        length = self.kernel.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
        if not 4 < length < len(buffer) or not buffer.value.startswith("\\\\?\\"):
            raise BundleError(Blocker.BUNDLE_REJECTED)
        return buffer.value[4:]

    def _open_pin(self, path):
        path = _absolute(path)
        handle = _handle(self.kernel.CreateFileW(path, 0x80000000, 1, None, 3, 0x00200000, None))
        self._closed.discard(handle)  # Win32 may reuse a just-closed numeric value.
        self._pending.append(handle)
        self._inheritance(handle, False)
        identity = self._identity(handle)
        if self._final_path(handle) != path:
            raise BundleError(Blocker.BUNDLE_REJECTED)
        self._pins[handle] = (path, identity)
        self._pending.remove(handle)
        return handle

    def pin_identity(self, handle):
        path, expected = self._pins[handle]
        actual = self._identity(handle)
        if actual != expected or self._final_path(handle) != path:
            raise BundleError(Blocker.BUNDLE_REJECTED)
        return actual

    def _length(self, handle):
        size = ct.c_int64()
        _require(self.kernel.GetFileSizeEx(handle, ct.byref(size)))
        if size.value < 0:
            raise BundleError(Blocker.IO_FAILURE)
        return size.value

    def _read(self, handle, limit):
        size = self._length(handle)
        if type(limit) is not int or not 0 <= size <= limit <= PE_LIMIT:
            raise BundleError(Blocker.OUTPUT_LIMIT)
        _require(self.kernel.SetFilePointerEx(handle, 0, None, 0))
        data = bytearray()
        while len(data) < size:
            count = min(65536, size - len(data))
            buffer, read = ct.create_string_buffer(count), DWORD()
            _require(self.kernel.ReadFile(handle, buffer, count, ct.byref(read), None))
            if read.value != count:
                raise BundleError(Blocker.IO_FAILURE)
            data.extend(buffer.raw)
        if self._length(handle) != size:
            raise BundleError(Blocker.IO_FAILURE)
        return bytes(data)

    def read_pin(self, handle, *, limit):
        self.pin_identity(handle)
        data = self._read(handle, limit)
        self.pin_identity(handle)
        return data

    def _new_file(self, path, *, inheritable, share=1):
        sa = SECURITY_ATTRIBUTES(ct.sizeof(SECURITY_ATTRIBUTES), None, inheritable)
        # Metadata observation needs FILE_READ_ATTRIBUTES, never FILE_READ_DATA.
        handle = _handle(
            self.kernel.CreateFileW(
                _absolute(path),
                0x40000080,
                share,
                ct.byref(sa) if inheritable else None,
                1,
                0x00200000,
                None,
            )
        )
        self._closed.discard(handle)  # Win32 may reuse a just-closed numeric value.
        self._pending.append(handle)
        self._inheritance(handle, inheritable)
        self._identity(handle)
        if self._final_path(handle) != path:
            raise BundleError(Blocker.BUNDLE_REJECTED)
        return handle

    def _write(self, handle, data):
        if type(data) is not bytes:
            raise TypeError("bytes required")
        for offset in range(0, len(data), 65536):
            raw = data[offset : offset + 65536]
            count = DWORD()
            _require(self.kernel.WriteFile(handle, raw, len(raw), ct.byref(count), None))
            if count.value != len(raw):
                raise BundleError(Blocker.IO_FAILURE)
        if self._length(handle) != len(data):
            raise BundleError(Blocker.IO_FAILURE)

    def flush(self, handle):
        return bool(self.kernel.FlushFileBuffers(handle))

    def _close_internal(self, handle):
        # A transfer close has no new C. Record the attempt before the call:
        # exceptions/false returns must never cause a retry or a positive drain.
        self._closed.add(handle)
        if handle in self._pending:
            self._pending.remove(handle)
        try:
            if not self.kernel.CloseHandle(handle):
                raise BundleError(Blocker.CLEANUP_UNKNOWN)
        except BaseException:
            self._cleanup_uncertain = True
            raise

    def close(self, handle, *, deadline):
        self._bind_cleanup(deadline)
        if self.now() >= deadline or handle in self._closed:
            return None
        self._closed.add(handle)  # Never retry an uncertain close.
        self._pins.pop(handle, None)
        try:
            if not self.kernel.CloseHandle(handle):
                self._cleanup_uncertain = True
                return None
        except BaseException:
            self._cleanup_uncertain = True
            raise
        return True if self.now() < deadline else None

    def drain_pending(self, *, deadline):
        self._bind_cleanup(deadline)
        failure = None
        while self._pending:
            if self.now() >= deadline:
                self._cleanup_uncertain = True
                break
            handle = self._pending.pop(0)  # Remove before call; uncertain is final.
            try:
                if self.close(handle, deadline=deadline) is not True:
                    self._cleanup_uncertain = True
            except BaseException as error:
                self._cleanup_uncertain = True
                if failure is None or (
                    isinstance(failure, Exception) and not isinstance(error, Exception)
                ):
                    failure = error
        if failure is not None:
            raise failure
        return True if not self._cleanup_uncertain and self.now() < deadline else None


class WindowsBundleAPI(_Files):
    """No positive production build/dependency admission exists in this slice."""

    def __init__(self, *, _kernel=None, _clock=time.monotonic, _acl=None):
        super().__init__(_kernel=_kernel, _clock=_clock)
        self._acl = _acl
        self._directories = {}
        self._mapping = None
        self._reservation_attempted = self._stage_attempted = self._v6_attempted = False
        self._source_roles = {}

    def reviewed_build_version(self, build: ReviewedBuild):
        # Do not accept arbitrary matching-looking data or the old EXE hash.
        return None

    def dependency_evidence(self, build):
        return DependencyEvidence()

    def pin_dependency(self, reviewed, *, share_mode, inheritable):
        raise BundleError(Blocker.DEPENDENCIES_UNKNOWN)

    def pin_source(self, role, build, *, share_mode, inheritable):
        if share_mode != 1 or inheritable is not False:
            raise BundleError(Blocker.BUNDLE_REJECTED)
        # Independent exact build admission is required even for source-only
        # methods. A caller cannot bypass prepare_bundle by calling this method.
        if self.reviewed_build_version(build) is None or role == "exe":
            # No approved EXE location or manifest exists. Never infer one from
            # the current working directory, argv, old build or caller's data.
            raise BundleError(Blocker.BUILD_UNKNOWN)
        if role not in ("cdb", "dbgeng", "dbghelp"):
            raise BundleError(Blocker.BUNDLE_REJECTED)
        name = role + (".exe" if role == "cdb" else ".dll")
        handle = self._open_pin(ntpath.join(self._tools_root(), name))
        self._closed.discard(handle)  # Win32 may reuse a just-closed numeric value.
        self._pending.append(handle)
        bound, version = self.revalidate_pin(handle)
        if bound.sha256 != DEBUGGER_HASHES[name] or version != VERSION:
            raise BundleError(Blocker.BUNDLE_REJECTED)
        self._source_roles[handle] = role
        self._pending.remove(handle)
        return handle

    @staticmethod
    def _tools_root():
        # Same one installed location as the fixed V6 helper, not a search list.
        root = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        return ntpath.join(_absolute(root), "Windows Kits", "10", "Debuggers", "x64")

    def _system_root(self):
        value = ct.create_unicode_buffer(8192)
        size = self.kernel.GetSystemWindowsDirectoryW(value, len(value))
        if not 0 < size < len(value):
            raise BundleError(Blocker.BUNDLE_REJECTED)
        return _absolute(value.value)

    @staticmethod
    def _load_v6():
        path = Path(__file__).with_name("issue110_capture.py")
        raw = path.read_bytes()
        if len(raw) > 1024 * 1024 or hashlib.sha256(raw).hexdigest() != (
            "f516ac8b6079ee8afd40d2a54f8c9ad08d722c8bc0e8d49a89151b7e29915a13"
        ):
            raise BundleError(Blocker.SIGNATURE_REJECTED)
        helper = types.ModuleType("_issue110_fixed_v6")
        helper.__file__ = str(path)
        exec(compile(raw, str(path), "exec"), helper.__dict__)
        return helper

    def _directory_api(self):
        if self._acl is None:
            try:
                self._acl = Native()
            except BaseException:
                # Legacy construction may own a token whose close was unconfirmed.
                # No constructor cleanup receipt exists: preserve unknown, no retry.
                self._cleanup_uncertain = True
                raise
        return self._acl

    def open_directory(self, path, *, role):
        if role not in ("volume_root", "prepared_private_root"):
            raise BundleError(Blocker.BUNDLE_REJECTED)
        if role == "volume_root":
            if not isinstance(path, str) or len(path) != 3 or path[1:] != ":\\":
                raise BundleError(Blocker.BUNDLE_REJECTED)
        else:
            components(path, mode="prepared_top_level")
        # READ_CONTROL | FILE_READ_ATTRIBUTES. READ sharing only; not inherited.
        handle = _handle(self.kernel.CreateFileW(path, 0x20080, 1, None, 3, 0x02200000, None))
        self._closed.discard(handle)  # Win32 may reuse a just-closed numeric value.
        self._pending.append(handle)
        self._inheritance(handle, False)
        identity = self._identity(handle, directory=True)
        self._directories[handle] = (path, role, identity)
        self.validate_directory(handle, path=path, role=role)
        self._pending.remove(handle)
        return handle

    def validate_directory(self, handle, *, path, role):
        if self._directories.get(handle, ())[:2] != (path, role):
            raise BundleError(Blocker.BUNDLE_REJECTED)
        api = self._directory_api()
        attributes, identity, descriptor = api.inspect(handle)
        actual = FileIdentity(*identity)
        if (
            not attributes & 0x10
            or attributes & 0x400
            or actual != self._directories[handle][2]
            or self._final_path(handle) != path
        ):
            raise BundleError(Blocker.BUNDLE_REJECTED)
        check_descriptor(
            descriptor,
            api.user_sid,
            private=role != "volume_root",
            prepared=role in ("volume_root", "prepared_private_root"),
        )
        mapping = api.drive_mapping(path[:3])
        if self._mapping is None:
            self._mapping = mapping
        if self._mapping != mapping:
            raise BundleError(Blocker.BUNDLE_REJECTED)
        if role == "volume_root":
            api.volume(handle)
        return actual

    def _validate_held(self):
        for handle, (path, role, _) in self._directories.items():
            if handle in self._closed:
                raise BundleError(Blocker.BUNDLE_REJECTED)
            self.validate_directory(handle, path=path, role=role)

    def _create_directory(self, parent, name, role):
        self._validate_held()
        path = ntpath.join(self._directories[parent][0], name)
        # Exclusive CreateDirectoryW, with inherited ACL. No adopt/retry/repair.
        _require(self.kernel.CreateDirectoryW(path, None))
        handle = _handle(self.kernel.CreateFileW(path, 0x20080, 1, None, 3, 0x02200000, None))
        self._closed.discard(handle)  # Win32 may reuse a just-closed numeric value.
        self._pending.append(handle)
        identity = self._identity(handle, directory=True)
        self._inheritance(handle, False)
        self._directories[handle] = (path, role, identity)
        self._validate_held()
        self._pending.remove(handle)
        return handle

    def reserve_child(self, root, name, *, exclusive):
        if (
            self._reservation_attempted
            or exclusive is not True
            or name != FILTER_PROBE_CHILD
            or self._directories.get(root, (None, None))[1] != "prepared_private_root"
        ):
            raise BundleError(Blocker.RESERVATION_UNCERTAIN)
        self._reservation_attempted = True
        return self._create_directory(root, name, "filter_probe")

    def create_stage(self, child, *, exclusive):
        if (
            self._stage_attempted
            or exclusive is not True
            or self._directories.get(child, (None, None))[1] != "filter_probe"
        ):
            raise BundleError(Blocker.RESERVATION_UNCERTAIN)
        self._stage_attempted = True
        return self._create_directory(child, "stage", "stage")

    def _bound_directory(self, path, role):
        self._validate_held()
        found = [handle for handle, value in self._directories.items() if value[:2] == (path, role)]
        if len(found) != 1:
            raise BundleError(Blocker.BUNDLE_REJECTED)
        return found[0]

    def require_stage(self, path):
        self._bound_directory(path, "stage")

    def require_reservation(self, path):
        self._bound_directory(path, "filter_probe")

    def write_exclusive(self, child, name, data, *, exclusive):
        if (
            exclusive is not True
            or name != "attempt.json"
            or self._directories.get(child, (None, None))[1] != "filter_probe"
        ):
            raise BundleError(Blocker.RESERVATION_UNCERTAIN)
        self._validate_held()
        handle = self._new_file(ntpath.join(self._directories[child][0], name), inheritable=False)
        self._write(handle, data)
        self._validate_held()
        self._pending.remove(handle)
        return handle

    @staticmethod
    def _version_api():
        if os.name != "nt":
            raise BundleError(Blocker.UNSUPPORTED)
        version = ct.WinDLL("version", use_last_error=True, winmode=0x800)
        for name, args, result in (
            ("GetFileVersionInfoSizeW", [ct.c_wchar_p, HANDLE], DWORD),
            ("GetFileVersionInfoW", [ct.c_wchar_p, DWORD, DWORD, HANDLE], BOOL),
            ("VerQueryValueW", [HANDLE, ct.c_wchar_p, HANDLE, HANDLE], BOOL),
        ):
            function = getattr(version, name)
            function.argtypes, function.restype = args, result
        return version

    def revalidate_pin(self, handle):
        identity = self.pin_identity(handle)
        digest = hashlib.sha256(self.read_pin(handle, limit=PE_LIMIT)).hexdigest()
        path = self._pins[handle][0]
        version = self._version_api()
        size = version.GetFileVersionInfoSizeW(path, None)
        if not 0 < size <= 1024 * 1024:
            raise BundleError(Blocker.BUNDLE_REJECTED)
        data = ct.create_string_buffer(size)
        _require(version.GetFileVersionInfoW(path, 0, size, data))
        pointer, length = HANDLE(), DWORD()
        _require(version.VerQueryValueW(data, "\\", ct.byref(pointer), ct.byref(length)))
        start = pointer.value or 0
        if length.value < ct.sizeof(VS_FIXEDFILEINFO) or not (
            ct.addressof(data) <= start <= ct.addressof(data) + size - ct.sizeof(VS_FIXEDFILEINFO)
        ):
            raise BundleError(Blocker.BUNDLE_REJECTED)
        fixed = ct.cast(pointer, ct.POINTER(VS_FIXEDFILEINFO)).contents
        if fixed.dwSignature != 0xFEEF04BD:
            raise BundleError(Blocker.BUNDLE_REJECTED)
        full_version = ".".join(
            str(value)
            for value in (
                fixed.dwFileVersionMS >> 16,
                fixed.dwFileVersionMS & 0xFFFF,
                fixed.dwFileVersionLS >> 16,
                fixed.dwFileVersionLS & 0xFFFF,
            )
        )
        # Version APIs use a path, but the retained deny-write/delete pin and
        # original-path check bind it. SHA256 always reads the original handle.
        self.pin_identity(handle)
        return BoundFile(identity, digest), full_version

    def copy_exclusive(self, source, stage, name, *, exclusive, share_mode, inheritable):
        if (
            exclusive is not True
            or share_mode != 1
            or inheritable is not False
            or name not in (EXE_NAME, "dbgeng.dll", "dbghelp.dll")
            or self._directories.get(stage, (None, None))[1] != "stage"
        ):
            raise BundleError(Blocker.BUNDLE_REJECTED)
        self._validate_held()
        expected, version = self.revalidate_pin(source)
        raw = self.read_pin(source, limit=PE_LIMIT)
        path = ntpath.join(self._directories[stage][0], name)
        writer = self._new_file(path, inheritable=False)
        written_identity = self._identity(writer)
        self._write(writer, raw)
        _require(self.flush(writer))
        self._close_internal(writer)
        pin = self._open_pin(path)
        self._pending.append(pin)
        bound, copied_version = self.revalidate_pin(pin)
        if (
            bound.identity != written_identity
            or bound.sha256 != expected.sha256
            or copied_version != version
            or self.revalidate_pin(source) != (expected, version)
        ):
            raise BundleError(Blocker.BUNDLE_REJECTED)
        self._validate_held()
        self._pending.remove(pin)
        return pin

    def image_binding(self, path):
        self.require_stage(ntpath.dirname(path))
        if ntpath.basename(path) != EXE_NAME:
            raise BundleError(Blocker.IMAGE_MISMATCH)
        matching = [handle for handle, value in self._pins.items() if value[0] == path]
        if len(matching) != 1:
            raise BundleError(Blocker.IMAGE_MISMATCH)
        return self.revalidate_pin(matching[0])[0].identity

    def verify_installed_v6(self, pins, *, deadline):
        self._checkpoint(deadline)
        if self._v6_attempted:
            raise BundleError(Blocker.SIGNATURE_REJECTED)
        self._v6_attempted = True
        roles = ("cdb", "dbgeng", "dbghelp")
        if (
            type(pins) is not tuple
            or len(pins) != 3
            or tuple(self._source_roles.get(pin) for pin in pins) != roles
        ):
            raise BundleError(Blocker.SIGNATURE_REJECTED)
        children = [
            handle for handle, value in self._directories.items() if value[1] == "filter_probe"
        ]
        if len(children) != 1:
            raise BundleError(Blocker.RESERVATION_UNCERTAIN)
        self._validate_held()
        expected = []
        sources = {}
        for pin, role in zip(pins, roles, strict=True):
            self._checkpoint(deadline)
            name = role + (".exe" if role == "cdb" else ".dll")
            path = ntpath.join(self._tools_root(), name)
            if self._pins[pin][0] != path:
                raise BundleError(Blocker.SIGNATURE_REJECTED)
            bound, version = self.revalidate_pin(pin)
            if bound.sha256 != DEBUGGER_HASHES[name] or version != VERSION:
                raise BundleError(Blocker.SIGNATURE_REJECTED)
            sources[path] = pin
            expected.append({"name": name, "sha256": bound.sha256, "version": version})
        # New fixed internal roles, under THIS retained reservation only.
        self._checkpoint(deadline)
        verifier = self._create_directory(children[0], "verifier", "verifier")
        self._pending.append(verifier)
        self._checkpoint(deadline)
        temporary = self._create_directory(verifier, "temp", "verifier_temp")
        self._pending.append(temporary)
        verifier_path = self._directories[verifier][0]
        script_path = ntpath.join(verifier_path, "verify-signatures.ps1")
        self._checkpoint(deadline)
        system = self._system_root()
        environment = {
            "SystemRoot": system,
            "WINDIR": system,
            "PATH": ntpath.join(system, "System32"),
            "TEMP": self._directories[temporary][0],
            "TMP": self._directories[temporary][0],
        }
        api = self

        class BoundPath:
            # Adapt only this isolated, hash-verified helper's Path name. Its
            # fixed signature predicates/script remain byte-identical. Source
            # reads use the original pins; its single script write is exclusive.
            def __init__(self, value):
                self.path = ntpath.normpath(str(value))

            def __str__(self):
                return self.path

            def __fspath__(self):
                return self.path

            @property
            def parent(self):
                return BoundPath(ntpath.dirname(self.path))

            @property
            def name(self):
                return ntpath.basename(self.path)

            def __truediv__(self, other):
                return BoundPath(ntpath.join(self.path, str(other)))

            def joinpath(self, other):
                return self / other

            def is_file(self):
                return self.path in sources

            def open(self, mode):
                if mode != "rb" or self.path not in sources:
                    raise BundleError(Blocker.SIGNATURE_REJECTED)
                return io.BytesIO(api.read_pin(sources[self.path], limit=PE_LIMIT))

            def write_text(self, text, *, encoding):
                if self.path != script_path or encoding != "utf-8":
                    raise BundleError(Blocker.SIGNATURE_REJECTED)
                api._checkpoint(deadline)
                api._validate_held()
                raw = text.encode("utf-8")
                if len(raw) > 65536:
                    raise BundleError(Blocker.SIGNATURE_REJECTED)
                handle = api._new_file(script_path, inheritable=False)
                written_identity = api._identity(handle)
                api._write(handle, raw)
                _require(api.flush(handle))
                api._close_internal(handle)
                pin = api._open_pin(script_path)
                api._pending.append(pin)
                if (
                    api.pin_identity(pin) != written_identity
                    or api.read_pin(pin, limit=65536) != raw
                ):
                    raise BundleError(Blocker.SIGNATURE_REJECTED)
                api._validate_held()
                return len(text)

        try:
            self._checkpoint(deadline)
            helper = self._load_v6()
            helper.Path = BoundPath
            receipt = {}  # Private only. Original helper's raw outputs stay private.
            cdb, facts = helper.installed_debugger(environment, deadline, receipt=receipt)
            self._checkpoint(deadline)  # Equal/late cannot become verified.
            self._validate_held()
            if str(cdb) != self._pins[pins[0]][0] or facts != expected:
                raise BundleError(Blocker.SIGNATURE_REJECTED)
            for pin, item in zip(pins, expected, strict=True):
                bound, version = self.revalidate_pin(pin)
                if bound.sha256 != item["sha256"] or version != item["version"]:
                    raise BundleError(Blocker.SIGNATURE_REJECTED)
            self._checkpoint(deadline)
            # V6 subprocess.run observes its direct child, not every descendant.
            # Never substitute the separate host Job's cleanup for this fact.
            return SignatureVerification(True, None)
        except BaseException as error:
            try:
                error.signature_cleanup = None
            except Exception:
                pass
            raise


@dataclass(eq=False)
class _Attributes:
    buffer: object
    job: object
    grants: tuple
    job_list: object
    handle_list: object
    closed: bool = False
    used: bool = False
    transferred: bool = False


class WindowsHostAPI(_Files):
    def __init__(self, bundle_api, *, _kernel=None, _clock=time.monotonic):
        super().__init__(_kernel=_kernel, _clock=_clock)
        self.bundle = bundle_api
        self._jobs = set()
        self._attributes = []
        self._creation = None
        self._create_attempted = self._resume_attempted = False
        self._image_verified = False
        self._transport_attempted = self._intent_attempted = False
        self._terminated = False

    def prepare_job(
        self, *, name, kill_on_close, active_process_limit, breakaway, inheritable, deadline
    ):
        self._checkpoint(deadline)
        if (
            name is not None
            or kill_on_close is not True
            or active_process_limit != 1
            or breakaway is not False
            or inheritable is not False
            or self._jobs
        ):
            raise BundleError(Blocker.BUNDLE_REJECTED)
        job = _handle(self.kernel.CreateJobObjectW(None, None))
        self._closed.discard(job)
        self._pending.append(job)
        self._inheritance(job, False)
        limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        limits.BasicLimitInformation.LimitFlags = 0x2008  # KILL_ON_JOB_CLOSE | ACTIVE_PROCESS
        limits.BasicLimitInformation.ActiveProcessLimit = 1
        if not self.kernel.SetInformationJobObject(job, 9, ct.byref(limits), ct.sizeof(limits)):
            self._close_internal(job)
            return None
        self._jobs.add(job)
        self._pending.remove(job)
        return job

    def prepare_attributes(self, job, inheritance, *, stdin, deadline):
        self._checkpoint(deadline)
        if (
            job not in self._jobs
            or stdin is not None
            or self._attributes
            or tuple((grant.role, grant.access) for grant in inheritance)
            != (("request", "read"), ("result", "write"), ("stdout", "write"), ("stderr", "write"))
        ):
            raise BundleError(Blocker.BUNDLE_REJECTED)
        values = tuple(_handle(grant.handle) for grant in inheritance)
        if len(set(values)) != 4 or job in values:
            raise BundleError(Blocker.BUNDLE_REJECTED)
        for handle in values:
            self._inheritance(handle, True)
        self._inheritance(job, False)
        size = SIZE_T()
        if self.kernel.InitializeProcThreadAttributeList(None, 2, 0, ct.byref(size)):
            return None
        if not 0 < size.value <= 65536:
            return None
        buffer = ct.create_string_buffer(size.value)
        if not self.kernel.InitializeProcThreadAttributeList(buffer, 2, 0, ct.byref(size)):
            return None
        jobs, handles = (HANDLE * 1)(job), (HANDLE * 4)(*values)
        attributes = _Attributes(buffer, job, inheritance, jobs, handles)
        # Retain storage: the attribute API borrows lpValue until list deletion.
        self._attributes.append(attributes)
        try:
            for key, data in ((0x2000D, jobs), (0x20002, handles)):
                if not self.kernel.UpdateProcThreadAttribute(
                    buffer, 0, key, data, ct.sizeof(data), None, None
                ):
                    attributes.closed = True
                    self.kernel.DeleteProcThreadAttributeList(buffer)
                    return None
        except BaseException:
            # A deletion already attempted is uncertain and must not be retried.
            # Otherwise retain the known storage for the owner's single C.
            if attributes.closed:
                self._cleanup_uncertain = True
            raise
        attributes.transferred = True
        return attributes

    def exclusive_transport(self, directory, request, *, exclusive, deadline):
        self._checkpoint(deadline)
        if self._transport_attempted or exclusive is not True:
            raise BundleError(Blocker.RESERVATION_UNCERTAIN)
        parse_request(request)
        self._transport_attempted = True
        self.bundle.require_reservation(directory)
        path = ntpath.join(directory, "request.json")
        writer = self._new_file(path, inheritable=False)
        expected = self._identity(writer)
        self._write(writer, request)
        _require(self.flush(writer))
        self._close_internal(writer)
        sa = SECURITY_ATTRIBUTES(ct.sizeof(SECURITY_ATTRIBUTES), None, True)
        reader = _handle(
            self.kernel.CreateFileW(path, 0x80000000, 1, ct.byref(sa), 3, 0x00200000, None)
        )
        self._closed.discard(reader)
        self._pending.append(reader)
        self._inheritance(reader, True)
        if (
            self._identity(reader) != expected
            or self._final_path(reader) != path
            or self._read(reader, 16384) != request
        ):
            raise BundleError(Blocker.BUNDLE_REJECTED)
        _require(self.kernel.SetFilePointerEx(reader, 0, None, 0))
        writers, readers = [], []
        for name in ("result.capsule", "stdout.log", "stderr.log"):
            self._checkpoint(deadline)
            self.bundle.require_reservation(directory)
            path = ntpath.join(directory, name)
            writer = self._new_file(path, inheritable=True)
            writers.append(writer)
            reader_out = _handle(
                self.kernel.CreateFileW(path, 0x80000000, 3, None, 3, 0x00200000, None)
            )
            self._closed.discard(reader_out)
            self._pending.append(reader_out)
            self._inheritance(reader_out, False)
            if (
                self._identity(reader_out) != self._identity(writer)
                or self._final_path(reader_out) != path
            ):
                raise BundleError(Blocker.BUNDLE_REJECTED)
            readers.append(reader_out)
        self.bundle.require_reservation(directory)
        result = TransportHandles(reader, *writers, *readers)
        for handle in result.owned:
            self._pending.remove(handle)
        return result

    def persist_create_intent(self, directory, record, *, exclusive, deadline):
        self._checkpoint(deadline)
        if self._intent_attempted or exclusive is not True:
            raise BundleError(Blocker.RESERVATION_UNCERTAIN)
        self._intent_attempted = True
        self.bundle.require_reservation(directory)
        handle = self._new_file(ntpath.join(directory, "invocation.json"), inheritable=False)
        self._write(handle, record)
        _require(self.flush(handle))
        self.bundle.require_reservation(directory)
        self._close_internal(handle)
        return True

    def create_suspended(
        self,
        *,
        application_name,
        working_directory,
        attributes,
        inherit_handles,
        suspended,
        stdin,
        deadline,
    ):
        self._checkpoint(deadline)
        if (
            self._create_attempted
            or attributes not in self._attributes
            or attributes.closed
            or attributes.used
            or inherit_handles is not True
            or suspended is not True
            or stdin is not None
            or _absolute(application_name) != ntpath.join(_absolute(working_directory), EXE_NAME)
        ):
            raise BundleError(Blocker.CREATE_UNCERTAIN)
        self.bundle.require_stage(working_directory)
        self._create_attempted = attributes.used = True
        startup = STARTUPINFOEXW()
        startup.StartupInfo.cb = ct.sizeof(startup)
        startup.StartupInfo.dwFlags = 0x100  # STARTF_USESTDHANDLES; no stdin.
        startup.StartupInfo.hStdInput = None
        startup.StartupInfo.hStdOutput = attributes.grants[2].handle
        startup.StartupInfo.hStdError = attributes.grants[3].handle
        startup.lpAttributeList = ct.cast(attributes.buffer, HANDLE)
        # Routing only, no target/script/command or enable flag. The blocked
        # child main ignores it. Any future child entry must validate the fixed
        # protocol and the exact four inherited handles, never open output paths.
        command = ct.create_unicode_buffer(
            '"'
            + application_name
            + '" '
            + " ".join(str(grant.handle) for grant in attributes.grants)
        )
        environment = ct.create_unicode_buffer("\0\0", 2)  # No PATH/Kits/user settings.
        pi = PROCESS_INFORMATION()
        succeeded = None
        try:
            succeeded = bool(
                self.kernel.CreateProcessW(
                    application_name,
                    command,
                    None,
                    None,
                    True,
                    0x80404,
                    environment,
                    working_directory,
                    ct.byref(startup),
                    ct.byref(pi),
                )
            )
        except Exception:
            # A foreign-function error can still have populated original handles.
            succeeded = None
        except BaseException:
            for handle in (pi.hProcess, pi.hThread):
                if handle:
                    self._closed.discard(handle)
                    self._pending.append(handle)
            raise
        for handle in (pi.hProcess, pi.hThread):
            if handle:
                self._closed.discard(handle)
        result = CreationResult(
            succeeded, pi.hProcess or None, pi.hThread or None, pi.dwProcessId or None
        )
        self._creation = result
        return result  # Never close or replace partial original handles here.

    def image_identity(self, process, *, deadline):
        self._checkpoint(deadline)
        if self._creation is None or process != self._creation.process:
            raise BundleError(Blocker.IMAGE_MISMATCH)
        path, size = ct.create_unicode_buffer(8192), DWORD(8192)
        _require(self.kernel.QueryFullProcessImageNameW(process, 0, path, ct.byref(size)))
        if not 0 < size.value < len(path):
            raise BundleError(Blocker.IMAGE_MISMATCH)
        identity = self.bundle.image_binding(path.value)
        self._image_verified = True
        return identity

    def resume_once(self, thread, *, deadline):
        self._checkpoint(deadline)
        if (
            self._creation is None
            or self._creation.succeeded is not True
            or thread != self._creation.thread
            or not self._image_verified
            or self._resume_attempted
        ):
            return False
        self._resume_attempted = True
        # Previous suspend count must be exactly one. Any other result is not
        # evidence of the intended single transition; do not issue another call.
        count = self.kernel.ResumeThread(thread)
        return True if count == 1 else (False if count == 0xFFFFFFFF else None)

    def poll_exit(self, process, *, deadline):
        if self._creation is None or process != self._creation.process or self._terminated:
            return ExitState(None)
        signal = self.kernel.WaitForSingleObject(process, 0)
        if signal == 0x102:
            return ExitState(False)
        if signal != 0:
            return ExitState(None)
        code = DWORD()
        if not self.kernel.GetExitCodeProcess(process, ct.byref(code)):
            return ExitState(True)
        return ExitState(True, code.value)

    def wait(self, process, *, deadline):
        if self._creation is None or process != self._creation.process:
            return None
        milliseconds = min(0xFFFFFFFE, max(0, math.floor((deadline - self.now()) * 1000)))
        result = self.kernel.WaitForSingleObject(process, milliseconds)
        return True if result == 0 else (False if result == 0x102 else None)

    def read_length(self, handle, *, deadline):
        return self._length(handle)

    def read_result(self, handle, *, limit, deadline):
        return self._read(handle, limit)

    def terminate_owned(self, job, process, *, deadline):
        self._bind_cleanup(deadline)
        if job not in self._jobs or (
            process is not None and (self._creation is None or process != self._creation.process)
        ):
            return None
        if self.now() >= deadline or self._terminated:
            return None
        self._terminated = True
        if not self.kernel.TerminateJobObject(job, 0xE110):
            return None
        if process is not None and self.wait(process, deadline=deadline) is not True:
            return None
        # Kill submission is not completion. Query until the owned Job is empty,
        # always using this C, never naturalizing the injected termination code.
        while self.now() < deadline:
            info = JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
            if not self.kernel.QueryInformationJobObject(
                job, 1, ct.byref(info), ct.sizeof(info), None
            ):
                return None
            if info.ActiveProcesses == 0:
                return True
            time.sleep(min(0.01, max(0, deadline - self.now())))
        return None

    def _bind_cleanup(self, deadline):
        super()._bind_cleanup(deadline)
        if hasattr(self.bundle, "_bind_cleanup"):
            self.bundle._bind_cleanup(deadline)

    def close(self, handle, *, deadline):
        self._bind_cleanup(deadline)
        if not isinstance(handle, _Attributes):
            return super().close(handle, deadline=deadline)
        if handle not in self._attributes or handle.closed or self.now() >= deadline:
            return None
        handle.closed = True
        try:
            self.kernel.DeleteProcThreadAttributeList(handle.buffer)
        except BaseException:
            self._cleanup_uncertain = True
            raise
        return True if self.now() < deadline else None

    def drain_pending(self, *, deadline):
        self._bind_cleanup(deadline)
        failure = None
        # Only untransferred storage. Returned resources are closed by the owner.
        for attributes in self._attributes:
            if attributes.transferred or attributes.closed:
                continue
            try:
                if self.close(attributes, deadline=deadline) is not True:
                    self._cleanup_uncertain = True
            except BaseException as error:
                self._cleanup_uncertain = True
                if failure is None or (
                    isinstance(failure, Exception) and not isinstance(error, Exception)
                ):
                    failure = error
        try:
            complete = super().drain_pending(deadline=deadline)
        except BaseException as error:
            if failure is None or (
                isinstance(failure, Exception) and not isinstance(error, Exception)
            ):
                failure = error
            complete = None
        if failure is not None:
            raise failure
        return complete
