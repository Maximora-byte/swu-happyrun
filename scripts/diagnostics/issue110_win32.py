"""Windows-only owned process lifetime for the fixed issue 110 CDB supervisor.

Not a general debugger API. CPython's _winapi performs the same CreateProcess
marshalling used by subprocess; only documented Job/handle APIs use ctypes.
"""

import ctypes
import os
import re
import subprocess
import sys
import time
from ctypes import wintypes as w


class Limits(ctypes.Structure):
    _fields_ = [
        ("process_time", ctypes.c_int64),
        ("job_time", ctypes.c_int64),
        ("flags", w.DWORD),
        ("min_working", ctypes.c_size_t),
        ("max_working", ctypes.c_size_t),
        ("active_limit", w.DWORD),
        ("affinity", ctypes.c_size_t),
        ("priority", w.DWORD),
        ("scheduling", w.DWORD),
    ]


class IO(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            "read_ops",
            "write_ops",
            "other_ops",
            "read_bytes",
            "write_bytes",
            "other_bytes",
        )
    ]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("basic", Limits),
        ("io", IO),
        ("process_memory", ctypes.c_size_t),
        ("job_memory", ctypes.c_size_t),
        ("peak_process", ctypes.c_size_t),
        ("peak_job", ctypes.c_size_t),
    ]


class Accounting(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_int64)
        for name in ("user_time", "kernel_time", "period_user", "period_kernel")
    ] + [
        ("faults", w.DWORD),
        ("total", w.DWORD),
        ("active", w.DWORD),
        ("terminated", w.DWORD),
    ]


class Session:
    def __init__(self):
        if sys.platform != "win32" or ctypes.sizeof(ctypes.c_void_p) != 8:
            raise OSError("windows_x64_required")
        import _winapi
        import msvcrt

        self.api, self.crt = _winapi, msvcrt
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([ctypes.c_void_p, w.LPCWSTR], w.HANDLE),
            "SetInformationJobObject": ([w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD], w.BOOL),
            "AssignProcessToJobObject": ([w.HANDLE, w.HANDLE], w.BOOL),
            "TerminateJobObject": ([w.HANDLE, w.UINT], w.BOOL),
            "QueryInformationJobObject": (
                [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p],
                w.BOOL,
            ),
            "ResumeThread": ([w.HANDLE], w.DWORD),
            "OpenProcess": ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            "GetExitCodeProcess": ([w.HANDLE, ctypes.POINTER(w.DWORD)], w.BOOL),
            "WaitForSingleObject": ([w.HANDLE, w.DWORD], w.DWORD),
            "CloseHandle": ([w.HANDLE], w.BOOL),
        }
        for name, (args, result) in signatures.items():
            call = getattr(self.kernel, name)
            call.argtypes, call.restype = args, result

    def checked(self, ok):
        if not ok:
            raise OSError("owned_process_api_failed")
        return ok

    def exit_code(self, handle):
        if not handle:
            return None
        wait = self.kernel.WaitForSingleObject(handle, 0)
        if wait == 258:  # WAIT_TIMEOUT; 259 is also a valid final process exit code.
            return None
        if wait != 0:
            raise OSError("process_wait_failed")
        code = w.DWORD()
        self.checked(self.kernel.GetExitCodeProcess(handle, ctypes.byref(code)))
        return code.value

    def cleanup(self, job):
        self.checked(self.kernel.TerminateJobObject(job, 0xE0000110))
        limit = time.monotonic() + 5
        info = Accounting()
        while time.monotonic() < limit:
            self.checked(
                self.kernel.QueryInformationJobObject(
                    job, 1, ctypes.byref(info), ctypes.sizeof(info), None
                )
            )
            if info.active == 0:
                return True
            time.sleep(0.05)
        return False

    def run(self, argv, cwd, env, raw_path, nonce, deadline, *, capture_seconds, max_output):
        job = process = thread = child = None
        reader = writer = None
        child_exit = debugger_exit = child_pid = None
        reason, cleaned, raw = "api_error", False, ""
        started = time.monotonic()
        capture_deadline = None
        unassigned_stopped = True
        prefix = "SWU_" + nonce + "_"
        try:
            job = self.checked(self.kernel.CreateJobObjectW(None, None))
            limits = ExtendedLimits()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE only.
            self.checked(
                self.kernel.SetInformationJobObject(
                    job, 9, ctypes.byref(limits), ctypes.sizeof(limits)
                )
            )
            reader, writer = os.pipe()
            os.set_inheritable(reader, True)
            with raw_path.open("wb") as output:
                os.set_inheritable(output.fileno(), True)
                startup = subprocess.STARTUPINFO()
                startup.dwFlags = subprocess.STARTF_USESTDHANDLES
                startup.hStdInput = self.crt.get_osfhandle(reader)
                startup.hStdOutput = startup.hStdError = self.crt.get_osfhandle(output.fileno())
                startup.lpAttributeList = {"handle_list": [startup.hStdInput, startup.hStdOutput]}
                process, thread, debugger_pid, _ = self.api.CreateProcess(
                    argv[0],
                    subprocess.list2cmdline(argv),
                    None,
                    None,
                    True,
                    0x4 | 0x400,  # CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT
                    env,
                    str(cwd),
                    startup,
                )
                # Never allow CDB to launch its child before containment exists.
                try:
                    self.checked(self.kernel.AssignProcessToJobObject(job, process))
                except OSError:
                    unassigned_stopped = False
                    self.api.TerminateProcess(process, 0xE0000110)
                    unassigned_stopped = self.kernel.WaitForSingleObject(process, 5000) == 0
                    raise
                if self.kernel.ResumeThread(thread) == 0xFFFFFFFF:
                    raise OSError("resume_failed")
                self.api.CloseHandle(thread)
                thread = None
                os.close(reader)
                reader = None
                os.set_inheritable(output.fileno(), False)
                with raw_path.open("rb") as stream:
                    data = b""
                    while True:
                        data += stream.read(max_output + 1 - len(data))
                        raw = data.decode("utf-8", errors="replace").replace("\r\n", "\n")
                        if len(data) > max_output:
                            reason = "output_limit"
                            break
                        if child is None:
                            matches = re.findall(
                                r"^" + prefix + r"READY ([0-9a-fA-F]{1,8})$", raw, re.M
                            )
                            if len(matches) > 1:
                                reason = "handshake_failed"
                                break
                            if matches:
                                child_pid = int(matches[0], 16)
                                if child_pid in (0, os.getpid(), debugger_pid):
                                    reason = "handshake_failed"
                                    break
                                # This is the initial-breakpoint target, before Python executes.
                                child = self.checked(
                                    self.kernel.OpenProcess(0x1000 | 0x100000, False, child_pid)
                                )
                                os.write(writer, b"g\n")
                            elif time.monotonic() - started >= 15:
                                reason = "handshake_timeout"
                                break
                        if prefix + "BEGIN\n" in raw and capture_deadline is None:
                            capture_deadline = min(deadline, time.monotonic() + capture_seconds)
                        child_exit = self.exit_code(child)
                        debugger_exit = self.exit_code(process)
                        if debugger_exit is not None:
                            # Allow a short target-teardown race, never beyond the group deadline.
                            teardown_deadline = min(
                                deadline, capture_deadline or deadline, time.monotonic() + 1
                            )
                            while (
                                child
                                and child_exit is None
                                and time.monotonic() < teardown_deadline
                            ):
                                time.sleep(0.05)
                                child_exit = self.exit_code(child)
                            # One final read after the writer is gone, including END/report output.
                            data += stream.read(max_output + 1 - len(data))
                            raw = data.decode("utf-8", errors="replace").replace("\r\n", "\n")
                            child_exit = self.exit_code(child)
                            reason = "exited" if len(data) <= max_output else "output_limit"
                            break
                        if time.monotonic() >= deadline:
                            reason = "timeout"
                            break
                        if capture_deadline and time.monotonic() >= capture_deadline:
                            reason = "capture_timeout"
                            break
                        time.sleep(0.05)
        except (OSError, ValueError):
            reason = "api_error"
        finally:
            # Sample genuine statuses before cleanup; termination's injected exit is never evidence.
            try:
                child_exit = self.exit_code(child)
                debugger_exit = self.exit_code(process)
            except OSError:
                reason = "exit_query_failed"
            if job:
                try:
                    cleaned = self.cleanup(job) and unassigned_stopped
                except OSError:
                    cleaned = False
            for handle in (child, thread, process, job):
                if handle:
                    self.kernel.CloseHandle(handle)
            for fd in (reader, writer):
                if fd is not None:
                    os.close(fd)
        return raw, child_exit, debugger_exit, reason, cleaned, child_pid
