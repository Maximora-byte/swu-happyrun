"""ctypes calls are intercepted at the DLL boundary; never executes Windows APIs.

The structure-size expectations describe the x64 contract, not validated Windows
ABI behavior. These unittest assertions are also collected unchanged by pytest.
"""

import ctypes as ct
import hashlib
import importlib
import json
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts/diagnostics"
sys.path.insert(0, str(SCRIPTS))


def module():
    assert (SCRIPTS / "issue110_filter_host_win32.py").is_file(), "missing native bindings"
    return importlib.import_module("issue110_filter_host_win32")


class FakeKernel:
    """Official call boundary spy, not a second HostAPI implementation."""

    def __init__(self, n):
        self.n = n
        self.calls = []
        self.closed = []
        self.create_success = True
        self.partial_process, self.partial_thread = 101, 102
        self.unsupported = None
        self.create_error = None
        self.resume_result = 1
        self.image = r"C:\private\issue110-filter-probe-1\stage\issue110_filter_command_probe.exe"
        self.active = 0
        self.file_data = b"pinned bytes"
        self.offset = 0

    def CreateJobObjectW(self, attributes, name):
        self.calls.append(("job", attributes, name))
        return 10

    def SetInformationJobObject(self, job, kind, pointer, size):
        value = ct.cast(pointer, ct.POINTER(self.n.JOBOBJECT_EXTENDED_LIMIT_INFORMATION)).contents
        self.calls.append(
            (
                "limits",
                job,
                kind,
                size,
                value.BasicLimitInformation.LimitFlags,
                value.BasicLimitInformation.ActiveProcessLimit,
            )
        )
        return 1

    def InitializeProcThreadAttributeList(self, pointer, count, flags, size):
        if pointer is None:
            ct.cast(size, ct.POINTER(ct.c_size_t))[0] = 96
            return 0
        self.calls.append(("attributes", count, flags))
        return 1

    def UpdateProcThreadAttribute(self, pointer, flags, key, value, size, old, returned):
        handles = tuple(
            ct.cast(value, ct.POINTER(ct.c_void_p))[i]
            for i in range(size // ct.sizeof(ct.c_void_p))
        )
        self.calls.append(("attribute", key, size, handles))
        return 0 if self.unsupported == key else 1

    def DeleteProcThreadAttributeList(self, pointer):
        self.calls.append(("delete_attributes",))

    def GetHandleInformation(self, handle, flags):
        ct.cast(flags, ct.POINTER(ct.c_uint32))[0] = 1 if handle in (21, 22, 23, 24) else 0
        return 1

    def CreateProcessW(self, app, command, pa, ta, inherit, flags, env, cwd, start, process):
        startup = ct.cast(start, ct.POINTER(self.n.STARTUPINFOEXW)).contents
        self.calls.append(
            (
                "create",
                app,
                command.value,
                pa,
                ta,
                inherit,
                flags,
                cwd,
                startup.StartupInfo.cb,
                startup.StartupInfo.hStdInput,
                startup.StartupInfo.hStdOutput,
                startup.StartupInfo.hStdError,
                ct.wstring_at(env, 2),
            )
        )
        pi = ct.cast(process, ct.POINTER(self.n.PROCESS_INFORMATION)).contents
        pi.hProcess, pi.hThread, pi.dwProcessId = self.partial_process, self.partial_thread, 77
        if self.create_error:
            raise self.create_error
        return self.create_success

    def QueryFullProcessImageNameW(self, process, flags, path, length):
        path.value = self.image
        ct.cast(length, ct.POINTER(ct.c_uint32))[0] = len(self.image)
        return 1

    def ResumeThread(self, thread):
        self.calls.append(("resume", thread))
        return self.resume_result

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return 1

    def TerminateJobObject(self, job, code):
        self.calls.append(("terminate", job, code))
        return 1

    def QueryInformationJobObject(self, job, kind, data, size, returned):
        value = ct.cast(data, ct.POINTER(self.n.JOBOBJECT_BASIC_ACCOUNTING_INFORMATION)).contents
        value.ActiveProcesses = self.active
        return 1

    def WaitForSingleObject(self, handle, milliseconds):
        self.calls.append(("wait", handle, milliseconds))
        return 0

    def GetExitCodeProcess(self, handle, code):
        ct.cast(code, ct.POINTER(ct.c_uint32))[0] = 19
        return 1

    def CreateFileW(self, path, access, share, sa, disposition, flags, template):
        self.calls.append(("file", path, access, share, sa, disposition, flags))
        return 31

    def GetFileInformationByHandleEx(self, handle, kind, value, size):
        self.calls.append(("file_info", handle, kind))
        if kind == 18:
            info = ct.cast(value, ct.POINTER(self.n.FILE_ID_INFO)).contents
            info.VolumeSerialNumber = 5
            info.FileId.Identifier[0] = 6
        elif kind == 9:
            info = ct.cast(value, ct.POINTER(self.n.FILE_ATTRIBUTE_TAG_INFO)).contents
            info.FileAttributes = 0x80
        return 1

    def GetFinalPathNameByHandleW(self, handle, buffer, length, flags):
        buffer.value = "\\\\?\\" + self.image
        return len(buffer.value)

    def GetFileSizeEx(self, handle, size):
        ct.cast(size, ct.POINTER(ct.c_int64))[0] = len(self.file_data)
        return 1

    def SetFilePointerEx(self, handle, offset, out, method):
        self.offset = offset
        return 1

    def ReadFile(self, handle, data, size, count, overlapped):
        self.calls.append(("read", handle))
        raw = self.file_data[self.offset : self.offset + size]
        ct.memmove(data, raw, len(raw))
        self.offset += len(raw)
        ct.cast(count, ct.POINTER(ct.c_uint32))[0] = len(raw)
        return 1


class FileKernel(FakeKernel):
    """In-memory Win32 file objects with access/share/inheritance at call boundary."""

    def __init__(self, n):
        super().__init__(n)
        self.files, self.handles = {}, {}
        self.next_handle = 1000
        self.fail_flush = False

    def CreateFileW(self, path, access, share, sa, disposition, flags, template):
        inherited = (
            bool(ct.cast(sa, ct.POINTER(self.n.SECURITY_ATTRIBUTES)).contents.bInheritHandle)
            if sa
            else False
        )
        self.calls.append(("file", path, access, share, inherited, disposition, flags))
        if disposition == 1:
            if path in self.files:
                return self.n.INVALID_HANDLE_VALUE
            self.files[path] = {"data": bytearray(), "id": len(self.files) + 1}
        if path not in self.files:
            return self.n.INVALID_HANDLE_VALUE
        for item in self.handles.values():
            if item["path"] == path:
                if (
                    (access & 0x80000000 and not item["share"] & 1)
                    or (access & 0x40000000 and not item["share"] & 2)
                    or (item["access"] & 0x80000000 and not share & 1)
                    or (item["access"] & 0x40000000 and not share & 2)
                ):
                    return self.n.INVALID_HANDLE_VALUE
        h = self.next_handle
        self.next_handle += 1
        self.handles[h] = dict(path=path, access=access, share=share, inherited=inherited, offset=0)
        return h

    def GetHandleInformation(self, handle, flags):
        ct.cast(flags, ct.POINTER(ct.c_uint32))[0] = int(self.handles[handle]["inherited"])
        return 1

    def GetFileInformationByHandleEx(self, handle, kind, value, size):
        item = self.handles[handle]
        if not item["access"] & 0x80000080:
            return 0
        if kind == 18:
            info = ct.cast(value, ct.POINTER(self.n.FILE_ID_INFO)).contents
            info.VolumeSerialNumber = 1
            info.FileId.Identifier[0] = self.files[item["path"]]["id"]
        else:
            info = ct.cast(value, ct.POINTER(self.n.FILE_ATTRIBUTE_TAG_INFO)).contents
            info.FileAttributes = 0x80
        return 1

    def GetFinalPathNameByHandleW(self, handle, buffer, length, flags):
        buffer.value = "\\\\?\\" + self.handles[handle]["path"]
        return len(buffer.value)

    def GetFileSizeEx(self, handle, size):
        item = self.handles[handle]
        if not item["access"] & 0x80000080:
            return 0
        ct.cast(size, ct.POINTER(ct.c_int64))[0] = len(self.files[item["path"]]["data"])
        return 1

    def WriteFile(self, handle, data, size, count, overlapped):
        item = self.handles[handle]
        assert item["access"] & 0x40000000
        self.files[item["path"]]["data"].extend(data[:size])
        ct.cast(count, ct.POINTER(ct.c_uint32))[0] = size
        return 1

    def SetFilePointerEx(self, handle, offset, out, method):
        self.handles[handle]["offset"] = offset
        return 1

    def ReadFile(self, handle, buffer, size, count, overlapped):
        item = self.handles[handle]
        assert item["access"] & 0x80000000
        raw = bytes(self.files[item["path"]]["data"][item["offset"] : item["offset"] + size])
        item["offset"] += len(raw)
        ct.memmove(buffer, raw, len(raw))
        ct.cast(count, ct.POINTER(ct.c_uint32))[0] = len(raw)
        return 1

    def FlushFileBuffers(self, handle):
        self.calls.append(("flush", handle))
        return not self.fail_flush

    def CloseHandle(self, handle):
        self.closed.append(handle)
        del self.handles[handle]
        return 1


class AclConstructorDLLs:
    """Only DLL calls are faked; the real legacy Native constructor runs."""

    def __init__(self, *, valid_token=False, primary=None, close_error=None):
        self.opened, self.closed = [], []

        def open_token(process, access, output):
            self.opened.append((process, access))
            ct.cast(output, ct.POINTER(ct.c_void_p))[0] = 77
            return 1

        def token_information(token, kind, buffer, length, needed):
            if primary is not None:
                raise primary
            if not valid_token:
                return 1  # A successful size-only probe is invalid to Native.
            ct.cast(needed, ct.POINTER(ct.c_uint32))[0] = 28
            if buffer is None:
                return 0
            # TOKEN_USER points to the bounded synthetic S-1-5-21 at offset 16.
            ct.c_void_p.from_buffer(buffer).value = ct.addressof(buffer) + 16
            ct.memmove(ct.addressof(buffer) + 16, bytes.fromhex("010100000000000515000000"), 12)
            return 1

        def close_token(token):
            self.closed.append(token.value)
            if close_error is not None:
                raise close_error
            return int(valid_token)

        class DLL:
            def __init__(self, callbacks):
                self.callbacks = callbacks

            def __getattr__(self, name):
                # Functions, unlike bound methods, allow ctypes argtypes/restype.
                function = self.callbacks.get(name, lambda *args: 1)
                setattr(self, name, function)
                return function

        self.kernel = DLL({"GetCurrentProcess": lambda: -1, "CloseHandle": close_token})
        self.advapi = DLL(
            {"OpenProcessToken": open_token, "GetTokenInformation": token_information}
        )

    def load(self, name, **kwargs):
        return {"kernel32": self.kernel, "advapi32": self.advapi}[name]


class BoundBundle:
    """Only reservation/file binding behavior required by the real host backend."""

    def __init__(self, n, kernel):
        self.n, self.kernel = n, kernel
        self.expected = n.FileIdentity(5, bytes([6]) + bytes(15))
        self.checks = []

    def require_reservation(self, path):
        if path != r"C:\private\issue110-filter-probe-1":
            raise self.n.BundleError(self.n.Blocker.BUNDLE_REJECTED)
        self.checks.append(("reservation", path))

    def require_stage(self, path):
        self.checks.append(("stage", path))

    def image_binding(self, path):
        self.checks.append(("image", path))
        if path != self.kernel.image:
            raise ValueError("wrong image")
        return self.expected


class V6BundleFixture:
    """Subclass real binding only at disk/DLL boundaries, never invokes PowerShell."""

    def __new__(cls, n):
        class Fixture(n.WindowsBundleAPI):
            def __init__(self):
                super().__init__(_kernel=FakeKernel(n), _clock=lambda: 10.0)
                self.events, self.scripts, self.calls = [], [], 0
                self.helper_error = None
                self.late = False
                root = r"C:\private\issue110-filter-probe-1"
                self._directories[10] = (root, "filter_probe", n.FileIdentity(1, bytes(16)))
                self._source_roles = {31: "cdb", 32: "dbgeng", 33: "dbghelp"}
                self._pins = {
                    handle: (
                        n.ntpath.join(
                            self._tools_root(), role + (".exe" if role == "cdb" else ".dll")
                        ),
                        n.FileIdentity(1, bytes([handle]) + bytes(15)),
                    )
                    for handle, role in self._source_roles.items()
                }

            def _validate_held(self):
                pass

            def _create_directory(self, parent, name, role):
                self.events.append(("directory", parent, name, role))
                handle = 11 + len(self.events) - 1
                self._directories[handle] = (
                    n.ntpath.join(self._directories[parent][0], name),
                    role,
                    n.FileIdentity(1, bytes([handle]) + bytes(15)),
                )
                return handle

            def _system_root(self):
                return r"C:\Windows"

            def revalidate_pin(self, handle):
                role = self._source_roles[handle]
                return (
                    n.BoundFile(
                        self._pins[handle][1],
                        n.DEBUGGER_HASHES[role + (".exe" if role == "cdb" else ".dll")],
                    ),
                    n.VERSION,
                )

            def _new_file(self, path, *, inheritable, share=1):
                self.script_path = path
                self._pending.append(43)
                return 43

            def _identity(self, handle, *, directory=False):
                return n.FileIdentity(1, bytes([44]) + bytes(15))

            def _write(self, handle, data):
                self.scripts.append((self.script_path, data))

            def flush(self, handle):
                return True

            def _close_internal(self, handle):
                self._pending.remove(handle)

            def _open_pin(self, path):
                self._pins[44] = (path, n.FileIdentity(1, bytes([44]) + bytes(15)))
                return 44

            def pin_identity(self, handle):
                return self._pins[handle][1]

            def read_pin(self, handle, *, limit):
                return self.scripts[-1][1]

            def _load_v6(self):
                helper = types.SimpleNamespace()

                def run(env, deadline, *, receipt):
                    self.calls += 1
                    self.received_env, self.received_deadline = env, deadline
                    helper.Path(env["TEMP"]).parent.joinpath("verify-signatures.ps1").write_text(
                        "fixed v6 script", encoding="utf-8"
                    )
                    if self.helper_error:
                        raise self.helper_error
                    if self.late:
                        self._clock = lambda: deadline
                    return (
                        helper.Path(self._pins[31][0]),
                        [
                            {
                                "name": role + (".exe" if role == "cdb" else ".dll"),
                                "version": n.VERSION,
                                "sha256": n.DEBUGGER_HASHES[
                                    role + (".exe" if role == "cdb" else ".dll")
                                ],
                            }
                            for role in ("cdb", "dbgeng", "dbghelp")
                        ],
                    )

                helper.installed_debugger = run
                return helper

        return Fixture()


class NativeBindingTests(unittest.TestCase):
    def setup_api(self):
        n = module()
        k = FakeKernel(n)
        bundle = BoundBundle(n, k)
        api = n.WindowsHostAPI(bundle, _kernel=k, _clock=lambda: 10.0)
        return n, k, bundle, api

    def job_and_attributes(self, n, api):
        job = api.prepare_job(
            name=None,
            kill_on_close=True,
            active_process_limit=1,
            breakaway=False,
            inheritable=False,
            deadline=30,
        )
        grants = tuple(
            n.InheritedHandle(role, access, handle)
            for role, access, handle in (
                ("request", "read", 21),
                ("result", "write", 22),
                ("stdout", "write", 23),
                ("stderr", "write", 24),
            )
        )
        return job, api.prepare_attributes(job, grants, stdin=None, deadline=30)

    def create(self, api, attributes):
        return api.create_suspended(
            application_name=(
                r"C:\private\issue110-filter-probe-1\stage"
                r"\issue110_filter_command_probe.exe"
            ),
            working_directory=r"C:\private\issue110-filter-probe-1\stage",
            attributes=attributes,
            inherit_handles=True,
            suspended=True,
            stdin=None,
            deadline=25,
        )

    def test_job_and_handle_list_have_exact_x64_sizes_and_limits(self):
        n, k, _, api = self.setup_api()
        self.job_and_attributes(n, api)
        self.assertIn(("job", None, None), k.calls)
        self.assertIn(("limits", 10, 9, 144, 0x2008, 1), k.calls)
        self.assertIn(("attribute", 0x2000D, 8, (10,)), k.calls)
        self.assertIn(("attribute", 0x20002, 32, (21, 22, 23, 24)), k.calls)

    def test_unsupported_attribute_never_creates_and_deletes_attributes(self):
        n, k, _, api = self.setup_api()
        k.unsupported = 0x2000D
        _, attributes = self.job_and_attributes(n, api)
        self.assertIsNone(attributes)
        self.assertIn(("delete_attributes",), k.calls)
        self.assertFalse(any(c[0] == "create" for c in k.calls))

    def test_absolute_suspended_creation_and_identity_before_single_resume(self):
        n, k, bundle, api = self.setup_api()
        _, attributes = self.job_and_attributes(n, api)
        result = self.create(api, attributes)
        self.assertEqual((result.succeeded, result.process, result.thread), (True, 101, 102))
        creation = next(c for c in k.calls if c[0] == "create")
        self.assertEqual(creation[3:7], (None, None, True, 0x80404))
        self.assertEqual(creation[8:12], (112, None, 23, 24))
        self.assertEqual(creation[12], "\0\0")
        self.assertFalse(api.resume_once(result.thread, deadline=25))
        self.assertEqual(api.image_identity(result.process, deadline=25), bundle.expected)
        self.assertTrue(api.resume_once(result.thread, deadline=25))
        self.assertFalse(api.resume_once(result.thread, deadline=25))
        self.assertEqual(sum(c[0] == "resume" for c in k.calls), 1)
        with self.assertRaises(ValueError):
            self.create(api, attributes)

    def test_partial_failed_creation_preserves_both_original_handles(self):
        n, k, _, api = self.setup_api()
        _, attributes = self.job_and_attributes(n, api)
        k.create_success = False
        result = self.create(api, attributes)
        self.assertEqual(
            (result.succeeded, result.process, result.thread, result.child_pid),
            (False, 101, 102, 77),
        )
        self.assertEqual(k.closed, [])

    def test_one_cleanup_deadline_and_no_late_close_or_reset(self):
        n, k, _, api = self.setup_api()
        job, attributes = self.job_and_attributes(n, api)
        result = self.create(api, attributes)
        self.assertTrue(api.terminate_owned(job, result.process, deadline=15))
        self.assertTrue(api.close(result.thread, deadline=15))
        with self.assertRaises(ValueError):
            api.close(result.process, deadline=16)
        api._clock = lambda: 15.0
        self.assertIsNone(api.close(result.process, deadline=15))
        self.assertNotIn(result.process, k.closed)

    def test_read_pin_hashes_same_noninheritable_deny_write_delete_handle(self):
        n = module()
        k = FakeKernel(n)
        api = n.WindowsBundleAPI(_kernel=k, _clock=lambda: 10.0)
        pin = api._open_pin(k.image)
        self.assertIn(("file", k.image, 0x80000000, 1, None, 3, 0x00200000), k.calls)
        self.assertEqual(api.read_pin(pin, limit=64), b"pinned bytes")
        self.assertEqual(api.pin_identity(pin), n.FileIdentity(5, bytes([6]) + bytes(15)))
        self.assertEqual([c for c in k.calls if c[0] == "read"], [("read", pin)])

    def test_no_reviewed_build_or_dependency_facts_are_invented(self):
        n = module()
        k = FakeKernel(n)
        api = n.WindowsBundleAPI(_kernel=k)
        self.assertIsNone(api.reviewed_build_version(n.ReviewedBuild()))
        self.assertFalse(api.dependency_evidence(n.ReviewedBuild()).files)
        with self.assertRaises(n.BundleError):
            api.pin_source("exe", n.ReviewedBuild(), share_mode=1, inheritable=False)
        self.assertEqual(k.calls, [])

    def test_v6_uses_only_bound_private_environment_once_and_same_deadline(self):
        n = module()
        self.assertTrue(hasattr(n.WindowsBundleAPI, "_load_v6"), "missing bound V6 adapter")
        api = V6BundleFixture(n)
        value = api.verify_installed_v6((31, 32, 33), deadline=30)
        self.assertTrue(value.verified)
        self.assertIsNone(value.cleanup)
        self.assertEqual(api.events[0], ("directory", 10, "verifier", "verifier"))
        self.assertEqual(api.events[1], ("directory", 11, "temp", "verifier_temp"))
        self.assertEqual(api.received_deadline, 30)
        self.assertEqual(
            api.received_env["TEMP"], r"C:\private\issue110-filter-probe-1\verifier\temp"
        )
        self.assertNotIn("PYTHONPATH", api.received_env)
        self.assertEqual(
            api.scripts,
            [
                (
                    r"C:\private\issue110-filter-probe-1\verifier\verify-signatures.ps1",
                    b"fixed v6 script",
                )
            ],
        )
        self.assertEqual(api._pending, [11, 12, 44])
        with self.assertRaises(n.BundleError):
            api.verify_installed_v6((31, 32, 33), deadline=31)
        self.assertEqual(api.calls, 1)

    def test_v6_missing_reservation_or_wrong_order_never_invokes_helper(self):
        n = module()
        for missing in (True, False):
            self.assertTrue(hasattr(n.WindowsBundleAPI, "_load_v6"), "missing bound V6 adapter")
            api = V6BundleFixture(n)
            if missing:
                api._directories.clear()
            with self.assertRaises(n.BundleError):
                api.verify_installed_v6((31, 33, 32), deadline=30)
            self.assertEqual(api.calls, 0)

    def test_v6_preserves_unknown_cleanup_and_rejects_late_success(self):
        n = module()
        self.assertTrue(hasattr(n.WindowsBundleAPI, "_load_v6"), "missing bound V6 adapter")
        api = V6BundleFixture(n)
        api.helper_error = KeyboardInterrupt("synthetic cancellation")
        with self.assertRaises(KeyboardInterrupt) as raised:
            api.verify_installed_v6((31, 32, 33), deadline=30)
        self.assertIsNone(raised.exception.signature_cleanup)
        self.assertEqual(api.calls, 1)
        self.assertTrue(hasattr(n.WindowsBundleAPI, "_load_v6"), "missing bound V6 adapter")
        api = V6BundleFixture(n)
        api.late = True
        with self.assertRaises(n.BundleError):
            api.verify_installed_v6((31, 32, 33), deadline=30)
        self.assertEqual(api.calls, 1)

    def test_v6_loader_checks_exact_helper_hash_before_exec(self):
        n = module()
        api = n.WindowsBundleAPI(_kernel=FakeKernel(n))
        self.assertTrue(hasattr(api, "_load_v6"), "missing bound V6 adapter")
        helper = api._load_v6()
        self.assertTrue(callable(helper.installed_debugger))
        with patch.object(n.Path, "read_bytes", return_value=b"raise RuntimeError('not executed')"):
            with self.assertRaises(n.BundleError):
                api._load_v6()

    def test_actual_fixed_v6_helper_uses_bound_reads_and_exclusive_script(self):
        n = module()
        api = V6BundleFixture(n)
        helper = n.WindowsBundleAPI._load_v6()
        raw = bytearray(256)
        raw[:2] = b"MZ"
        raw[0x3C:0x40] = (128).to_bytes(4, "little")
        raw[128:134] = b"PE\0\0\x64\x86"
        raw = bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        api._load_v6 = lambda: helper
        api.read_pin = lambda handle, limit: raw if handle != 44 else api.scripts[-1][1]
        result = types.SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                [
                    {"name": name, "version": n.VERSION}
                    for name in ("cdb.exe", "dbgeng.dll", "dbghelp.dll")
                ]
            ),
            stderr=b"",
        )
        hashes = dict.fromkeys(("cdb.exe", "dbgeng.dll", "dbghelp.dll"), digest)
        with (
            patch.object(n, "DEBUGGER_HASHES", hashes),
            patch.object(helper.time, "monotonic", return_value=10.0),
            patch.object(helper.subprocess, "run", return_value=result) as run,
        ):
            value = api.verify_installed_v6((31, 32, 33), deadline=30)
        self.assertTrue(value.verified)
        self.assertEqual(run.call_count, 1)
        args, kwargs = run.call_args
        self.assertEqual(args[0][0], r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
        self.assertEqual(
            args[0][4], r"C:\private\issue110-filter-probe-1\verifier\verify-signatures.ps1"
        )
        self.assertEqual(args[0][5:], [api._pins[h][0] for h in (31, 32, 33)])
        self.assertNotIn("cdb.exe", args[0][0])
        self.assertGreater(len(api.scripts[0][1]), 1000)

    def test_reused_numeric_file_handle_is_closed_for_its_new_ownership(self):
        n = module()
        k = FakeKernel(n)
        api = n.WindowsBundleAPI(_kernel=k, _clock=lambda: 10.0)
        pin = api._open_pin(k.image)
        api._pending.append(pin)
        api._close_internal(pin)
        second = api._open_pin(k.image)
        self.assertTrue(api.close(second, deadline=15))
        self.assertEqual(k.closed, [31, 31])

    def test_creation_exception_preserves_partial_handles_without_retry(self):
        n, k, _, api = self.setup_api()
        _, attributes = self.job_and_attributes(n, api)
        k.create_error = OSError("synthetic foreign call failure")
        value = self.create(api, attributes)
        self.assertIsNone(value.succeeded)
        self.assertEqual((value.process, value.thread, value.child_pid), (101, 102, 77))
        with self.assertRaises(n.BundleError):
            self.create(api, attributes)
        self.assertEqual(sum(c[0] == "create" for c in k.calls), 1)

    def test_cancelled_creation_retains_partial_handles_for_shared_cleanup(self):
        n, k, _, api = self.setup_api()
        job, attributes = self.job_and_attributes(n, api)
        k.create_error = KeyboardInterrupt("synthetic cancellation")
        with self.assertRaises(KeyboardInterrupt):
            self.create(api, attributes)
        self.assertEqual(api._pending, [101, 102])
        self.assertTrue(api.drain_pending(deadline=15))
        self.assertTrue(api.close(job, deadline=15))
        self.assertCountEqual(k.closed, [101, 102, job])

    def test_invalid_suspend_count_never_retries_or_reports_resumed(self):
        n, k, _, api = self.setup_api()
        _, attributes = self.job_and_attributes(n, api)
        value = self.create(api, attributes)
        api.image_identity(value.process, deadline=25)
        k.resume_result = 2
        self.assertIsNone(api.resume_once(value.thread, deadline=25))
        self.assertFalse(api.resume_once(value.thread, deadline=25))
        self.assertEqual(sum(c[0] == "resume" for c in k.calls), 1)

    def test_exit_facts_are_never_taken_after_injected_termination(self):
        n, _, _, api = self.setup_api()
        job, attributes = self.job_and_attributes(n, api)
        value = self.create(api, attributes)
        self.assertEqual(api.poll_exit(value.process, deadline=25), n.ExitState(True, 19))
        self.assertTrue(api.terminate_owned(job, value.process, deadline=15))
        self.assertEqual(api.poll_exit(value.process, deadline=15), n.ExitState(None))

    def test_native_hash_and_full_version_revalidate_original_pin(self):
        n = module()
        k = FakeKernel(n)
        fixed = n.VS_FIXEDFILEINFO()
        fixed.dwSignature = 0xFEEF04BD
        fixed.dwFileVersionMS, fixed.dwFileVersionLS = (10 << 16), (26100 << 16) | 8249
        version = types.SimpleNamespace()
        version.GetFileVersionInfoSizeW = lambda path, unused: ct.sizeof(fixed)

        def read_version(path, unused, length, buffer):
            ct.memmove(buffer, ct.byref(fixed), ct.sizeof(fixed))
            return 1

        def query(buffer, root, pointer, length):
            ct.cast(pointer, ct.POINTER(ct.c_void_p))[0] = ct.addressof(buffer)
            ct.cast(length, ct.POINTER(ct.c_uint32))[0] = ct.sizeof(fixed)
            return 1

        version.GetFileVersionInfoW, version.VerQueryValueW = read_version, query
        self.assertTrue(
            hasattr(n.WindowsBundleAPI, "_version_api"), "missing fakeable version DLL boundary"
        )
        api = n.WindowsBundleAPI(_kernel=k)
        pin = api._open_pin(k.image)
        with patch.object(api, "_version_api", return_value=version):
            bound, full_version = api.revalidate_pin(pin)
        self.assertEqual(
            bound.sha256, "977d59924a4dfd9d4e93c74467f3253786327c8c28e69a75f30cf0429dab77c7"
        )
        self.assertEqual(full_version, "10.0.26100.8249")
        self.assertEqual({call[1] for call in k.calls if call[0] == "read"}, {pin})
        self.assertEqual(sum(call[0] == "file" for call in k.calls), 1)

    def test_transport_is_exclusive_with_only_four_minimal_inheritance_grants(self):
        n = module()
        k = FileKernel(n)
        api = n.WindowsHostAPI(BoundBundle(n, k), _kernel=k, _clock=lambda: 10.0)
        files = {
            role: {
                "volume_serial": 1,
                "file_id_hex": (bytes([i]) + bytes(15)).hex(),
                "sha256": str(i) * 64,
            }
            for i, role in enumerate(("exe", "dbgeng", "dbghelp"), 1)
        }
        request = json.dumps(
            {
                "schema": "swu.issue110.filter-request.v1",
                "mode": "fixed_no_target",
                "nonce": "a" * 32,
                "manifest_sha256": "b" * 64,
                "files": files,
            }
        ).encode()
        directory = r"C:\private\issue110-filter-probe-1"
        try:
            transport = api.exclusive_transport(directory, request, exclusive=True, deadline=25)
        except n.BundleError as error:
            self.fail("native transport rejected valid fake call boundary: " + str(error))
        self.assertEqual(len(k.handles), 7)
        self.assertEqual(
            {h for h, v in k.handles.items() if v["inherited"]},
            {
                transport.request_read,
                transport.result_write,
                transport.stdout_write,
                transport.stderr_write,
            },
        )
        self.assertEqual(k.handles[transport.request_read]["access"], 0x80000000)
        for h in (transport.result_write, transport.stdout_write, transport.stderr_write):
            self.assertEqual(k.handles[h]["access"], 0x40000080)
        self.assertEqual(api.read_result(transport.request_read, limit=16384, deadline=25), request)
        with self.assertRaises(n.BundleError):
            api.exclusive_transport(directory, request, exclusive=True, deadline=25)
        self.assertEqual(len(k.files), 4)
        self.assertEqual(api._pending, [])

    def test_intent_write_flush_failure_is_retained_for_single_cleanup(self):
        n = module()
        k = FileKernel(n)
        api = n.WindowsHostAPI(BoundBundle(n, k), _kernel=k, _clock=lambda: 10.0)
        k.fail_flush = True
        with self.assertRaises(n.BundleError):
            api.persist_create_intent(
                r"C:\private\issue110-filter-probe-1", b"intent", exclusive=True, deadline=25
            )
        self.assertEqual(len(api._pending), 1)
        k.fail_flush = False
        with self.assertRaises(n.BundleError):
            api.persist_create_intent(
                r"C:\private\issue110-filter-probe-1", b"intent", exclusive=True, deadline=25
            )
        self.assertEqual(len(k.files), 1)

    def test_reused_numeric_process_handle_keeps_new_creation_ownership(self):
        n, k, _, api = self.setup_api()
        pin = api._open_pin(k.image)
        api._pending.append(pin)
        api._close_internal(pin)
        _, attributes = self.job_and_attributes(n, api)
        k.partial_process = pin
        value = self.create(api, attributes)
        self.assertTrue(api.close(value.process, deadline=15))
        self.assertEqual(k.closed, [pin, pin])

    def test_python_system_dll_bindings_never_use_path_or_current_directory_search(self):
        n = module()

        class DLL:
            def __getattr__(self, name):
                def function(*args):
                    raise AssertionError("native function must not execute in this test")

                setattr(self, name, function)
                return function

        with (
            patch.object(n.os, "name", "nt"),
            patch.object(n.ct, "WinDLL", create=True, side_effect=lambda *a, **kw: DLL()) as load,
        ):
            n._kernel32()
            n.WindowsBundleAPI._version_api()
        self.assertEqual(load.call_args_list[0].kwargs, {"use_last_error": True, "winmode": 0x800})
        self.assertEqual(load.call_args_list[1].kwargs, {"use_last_error": True, "winmode": 0x800})

    def test_first_bundle_acquisition_drains_without_transferred_resource(self):
        from test_issue110_filter_bundle import FakeBundleAPI
        from test_issue110_filter_bundle import module as bundle_module

        b, n = bundle_module(), module()
        fixture = FakeBundleAPI(b)
        k = FakeKernel(n)
        k.GetHandleInformation = lambda *args: 0
        api = n.WindowsBundleAPI(_kernel=k, _clock=lambda: 10.0)
        api.reviewed_build_version = lambda build: "1.0.0.0"
        with self.assertRaises(b.BundleError) as caught:
            b.prepare_bundle(fixture.build, r"C:\private", 300.0, api)
        self.assertEqual(k.closed, [31])
        self.assertEqual(api._pending, [])
        self.assertEqual(api._cleanup_deadline, 15.0)
        self.assertIs(caught.exception.bundle_cleanup, True)

    def test_lazy_acl_constructor_double_failure_preserves_cleanup_unknown(self):
        from issue110_filter_supervisor import run_closed_pipeline
        from test_issue110_filter_bundle import FakeBundleAPI
        from test_issue110_filter_bundle import module as bundle_module

        acl = importlib.import_module("issue110_local_acl")
        b, n = bundle_module(), module()
        for primary in (None, KeyboardInterrupt("token cancellation"), SystemExit(9)):
            for close_error in (None, OSError("token close failure")):
                with self.subTest(primary=type(primary), close_error=type(close_error)):
                    fixture, k = FakeBundleAPI(b), FakeKernel(n)
                    original_info = k.GetFileInformationByHandleEx

                    def directory_info(handle, kind, value, size, *, original_info=original_info):
                        result = original_info(handle, kind, value, size)
                        if kind == 9:
                            ct.cast(
                                value, ct.POINTER(n.FILE_ATTRIBUTE_TAG_INFO)
                            ).contents.FileAttributes = 0x10
                        return result

                    k.GetFileInformationByHandleEx = directory_info
                    api = n.WindowsBundleAPI(_kernel=k, _clock=lambda: 10.0)
                    api.reviewed_build_version = lambda build: "1.0.0.0"  # Synthetic only.
                    dlls = AclConstructorDLLs(primary=primary, close_error=close_error)
                    with (
                        patch.object(acl.os, "name", "nt"),
                        patch.object(acl.ct, "WinDLL", create=True, side_effect=dlls.load),
                        patch.object(acl.ct, "get_last_error", create=True, return_value=122),
                        patch.object(
                            acl.ct, "WinError", create=True, return_value=OSError("fake WinError")
                        ),
                    ):
                        with self.assertRaises(
                            type(primary) if primary is not None else ValueError
                        ) as caught:
                            run_closed_pipeline(fixture.build, r"C:\private", api)
                    if primary is not None:
                        self.assertIs(caught.exception, primary)
                    else:
                        self.assertEqual(str(caught.exception), "token_unverified")
                    self.assertEqual(dlls.opened, [(-1, 8)])
                    self.assertEqual(dlls.closed, [77])
                    self.assertEqual(k.closed, [31])
                    self.assertEqual(api._pending, [])
                    self.assertEqual(api._cleanup_deadline, 15.0)
                    self.assertIsNone(caught.exception.bundle_cleanup)
                    obs = caught.exception.host_observation
                    self.assertIsNone(obs.host_owned_cleanup)
                    self.assertFalse(obs.create_intent)
                    self.assertFalse(obs.host_execution_attempted)
                    self.assertIsNone(obs.signature_cleanup)
                    self.assertIsNone(api.drain_pending(deadline=15.0))
                    self.assertEqual(dlls.closed, [77])  # Never retry unknown token close.
                    self.assertEqual(k.closed, [31])

    def test_successful_lazy_acl_constructor_does_not_invent_cleanup_uncertainty(self):
        acl, n = importlib.import_module("issue110_local_acl"), module()
        api = n.WindowsBundleAPI(_kernel=FakeKernel(n), _clock=lambda: 10.0)
        dlls = AclConstructorDLLs(valid_token=True)
        with (
            patch.object(acl.os, "name", "nt"),
            patch.object(acl.ct, "WinDLL", create=True, side_effect=dlls.load),
            patch.object(acl.ct, "get_last_error", create=True, return_value=122),
        ):
            helper = api._directory_api()
            self.assertIs(api._directory_api(), helper)
        self.assertEqual(helper.user_sid, "S-1-5-21")
        self.assertEqual(dlls.opened, [(-1, 8)])
        self.assertEqual(dlls.closed, [77])
        self.assertIs(api.drain_pending(deadline=15.0), True)
        self.assertEqual(dlls.closed, [77])

    def test_first_job_acquisition_drains_but_does_not_erase_unknown(self):
        from test_issue110_filter_supervisor import FilterSupervisorTests

        s, owner, _ = FilterSupervisorTests().fake()
        n = module()
        k = FakeKernel(n)
        k.GetHandleInformation = lambda *args: 0
        api = n.WindowsHostAPI(BoundBundle(n, k), _kernel=k, _clock=lambda: 10.0)
        observation = s.observe_once(owner, 300.0, api)
        self.assertEqual(k.closed, [10])
        self.assertEqual(api._pending, [])
        self.assertEqual(api._cleanup_deadline, 15.0)
        self.assertIsNone(observation.host_owned_cleanup)

    def test_first_bundle_pending_close_failure_is_unknown_and_not_retried(self):
        from test_issue110_filter_bundle import FakeBundleAPI
        from test_issue110_filter_bundle import module as bundle_module

        for secondary in (None, OSError("close failed"), KeyboardInterrupt(), SystemExit(7)):
            with self.subTest(secondary=type(secondary)):
                b, n = bundle_module(), module()
                fixture, k = FakeBundleAPI(b), FakeKernel(n)
                k.GetHandleInformation = lambda *args: 0

                def close(handle, *, k=k, secondary=secondary):
                    k.closed.append(handle)
                    if secondary is not None:
                        raise secondary
                    return 0

                k.CloseHandle = close
                api = n.WindowsBundleAPI(_kernel=k, _clock=lambda: 10.0)
                api.reviewed_build_version = lambda build: "1.0.0.0"
                with self.assertRaises(b.BundleError) as caught:
                    b.prepare_bundle(fixture.build, r"C:\private", 300.0, api)
                self.assertEqual(caught.exception.blocker.value, "io_failure")
                self.assertIsNone(caught.exception.bundle_cleanup)
                self.assertIsNone(api.drain_pending(deadline=15.0))
                self.assertEqual(k.closed, [31])
                self.assertEqual(api._pending, [])

    def test_pending_close_attempts_continue_after_cancel_without_retry_or_new_C(self):
        for secondary in (OSError("close failed"), KeyboardInterrupt(), SystemExit(8)):
            n, k, _, api = self.setup_api()
            api._pending.extend((31, 32))

            def close(handle, *, k=k, secondary=secondary):
                k.closed.append(handle)
                if handle == 31:
                    raise secondary
                return 1

            k.CloseHandle = close
            with self.assertRaises(type(secondary)) as caught:
                api.drain_pending(deadline=15.0)
            self.assertIs(caught.exception, secondary)
            self.assertEqual(k.closed, [31, 32])
            self.assertEqual(api._pending, [])
            self.assertIsNone(api.drain_pending(deadline=15.0))
            self.assertEqual(k.closed, [31, 32])
            with self.assertRaises(n.BundleError):
                api.drain_pending(deadline=16.0)

    def test_internal_transfer_close_unknown_stays_unknown_in_pending_drain(self):
        n, k, _, api = self.setup_api()
        api._pending.extend((31, 32))

        def close(handle):
            k.closed.append(handle)
            return 0 if handle == 31 else 1

        k.CloseHandle = close
        with self.assertRaises(n.BundleError) as caught:
            api._close_internal(31)
        self.assertEqual(caught.exception.blocker.value, "cleanup_unknown")
        self.assertIsNone(api.drain_pending(deadline=15.0))
        self.assertEqual(k.closed, [31, 32])
        self.assertIsNone(api.drain_pending(deadline=15.0))
        self.assertEqual(k.closed, [31, 32])

    def test_expired_drain_does_not_close_pending_handles_or_attributes(self):
        n, k, _, api = self.setup_api()
        primary = KeyboardInterrupt()

        def update(*args):
            raise primary

        k.UpdateProcThreadAttribute = update
        with self.assertRaises(KeyboardInterrupt):
            self.job_and_attributes(n, api)
        api._pending.append(31)
        api._clock = lambda: 15.0
        self.assertIsNone(api.drain_pending(deadline=15.0))
        self.assertEqual(k.closed, [])
        self.assertNotIn(("delete_attributes",), k.calls)
        self.assertEqual(api._pending, [31])
        with self.assertRaises(n.BundleError):
            api.drain_pending(deadline=20.0)

    def test_pending_attribute_storage_drains_but_transferred_storage_does_not(self):
        n, k, _, api = self.setup_api()
        primary = KeyboardInterrupt()

        def update(*args):
            raise primary

        k.UpdateProcThreadAttribute = update
        with self.assertRaises(KeyboardInterrupt) as caught:
            self.job_and_attributes(n, api)
        self.assertIs(caught.exception, primary)
        self.assertTrue(api.drain_pending(deadline=15.0))
        self.assertEqual(k.calls.count(("delete_attributes",)), 1)
        self.assertEqual(k.closed, [])  # Returned Job remains with its owner.
        self.assertTrue(api.drain_pending(deadline=15.0))
        self.assertEqual(k.calls.count(("delete_attributes",)), 1)
        n, k, _, api = self.setup_api()
        _, attributes = self.job_and_attributes(n, api)
        self.assertTrue(api.drain_pending(deadline=15.0))
        self.assertNotIn(("delete_attributes",), k.calls)
        self.assertTrue(api.close(attributes, deadline=15.0))
        self.assertEqual(k.calls.count(("delete_attributes",)), 1)
        self.assertIsNone(api.close(attributes, deadline=15.0))
        self.assertEqual(k.calls.count(("delete_attributes",)), 1)

    def test_uncertain_attribute_transfer_cleanup_is_not_retried_or_laundered(self):
        n, k, _, api = self.setup_api()
        k.unsupported = 0x2000D
        primary = KeyboardInterrupt()

        def delete(pointer):
            k.calls.append(("delete_attributes",))
            raise primary

        k.DeleteProcThreadAttributeList = delete
        with self.assertRaises(KeyboardInterrupt) as caught:
            self.job_and_attributes(n, api)
        self.assertIs(caught.exception, primary)
        self.assertIsNone(api.drain_pending(deadline=15.0))
        self.assertEqual(k.calls.count(("delete_attributes",)), 1)

    def test_portable_loader_fail_closed_and_owned_module(self):
        header = SCRIPTS / "issue110_filter_loader.hpp"
        self.assertTrue(header.is_file(), "missing trusted loader ownership boundary")
        compiler = shutil.which("g++")
        if not compiler:
            self.skipTest("portable C++ compiler unavailable; Windows remains unverified")
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "loader-test"
            result = subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-pedantic",
                    "-pthread",
                    "-I",
                    str(ROOT),
                    str(ROOT / "tests/delivery/issue110_filter_loader_test.cpp"),
                    str(SCRIPTS / "issue110_filter_loader.cpp"),
                    "-o",
                    str(binary),
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("portable loader checks passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
