"""Public synthetic fixtures only. No Windows API executes in this suite."""

import ctypes as ct
import importlib.util
import json
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).parents[2] / "scripts/diagnostics/issue110_prepare_private_root.py"
USER = "S-1-5-21-101-202-303-1001"
OTHER = "S-1-5-11"


@pytest.fixture
def m():
    assert SOURCE.exists(), "standalone preparation implementation is missing"
    spec = importlib.util.spec_from_file_location("prepare_test", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sid(value):
    parts = [int(p) for p in value.split("-")[1:]]
    return (
        bytes([parts[0], len(parts) - 2])
        + parts[1].to_bytes(6, "big")
        + b"".join(struct.pack("<I", p) for p in parts[2:])
    )


def sd(owner=USER, entries=None, control=0x9004):
    if entries is None:
        entries = [(USER, 0x1F01FF, 3), ("S-1-5-18", 0x1F01FF, 3), ("S-1-5-32-544", 0x1F01FF, 3)]
    raw_owner = sid(owner)
    aces = b"".join(
        struct.pack("<BBHI", 0, flags, 8 + len(sid(who)), mask) + sid(who)
        for who, mask, flags in entries
    )
    acl = struct.pack("<BBHHH", 2, 0, 8 + len(aces), len(entries), 0) + aces
    return struct.pack("<BBHIIII", 1, 0, control, 20, 0, 0, 20 + len(raw_owner)) + raw_owner + acl


class FakeAPI:
    def __init__(self):
        self.user_sid = USER
        self.cleanup_failed = False
        self.created = []
        self.closed = []
        self.mapping = "volume"
        self.root_sd = sd()
        self.child_sd = sd()
        self.attrs = 0x10
        self.result = (True, 0)
        self.identities = []

    def effective_user(self):
        return USER

    def drive_mapping(self, root):
        return self.mapping

    def volume(self, handle):
        return None

    def open_directory(self, path):
        return "root" if len(path) == 3 else "child"

    def inspect(self, handle):
        identity = self.identities.pop(0) if self.identities else handle
        return self.attrs, identity, self.root_sd if handle == "root" else self.child_sd

    def descriptor(self, user):
        return sd()

    def create(self, path, descriptor):
        self.created.append((path, descriptor))
        return self.result

    def close(self, handle):
        self.closed.append(handle)


def run(m, monkeypatch, api):
    monkeypatch.setattr(m, "runtime_valid", lambda: True)
    monkeypatch.setattr(m, "Native", lambda helper: api)
    return m.prepare("C:\\PublicFixture")


def test_success_exact_descriptor_and_single_create(m, monkeypatch):
    api = FakeAPI()
    result = run(m, monkeypatch, api)
    assert result == {
        "status": "prepared",
        "creation_attempted": True,
        "creation_succeeded": True,
        "verified": True,
        "cleanup": "complete",
    }
    assert api.created == [("C:\\PublicFixture", sd())]
    assert api.closed == ["child", "root"]


@pytest.mark.parametrize(
    "path",
    [
        "C:\\a\\b",
        "C:\\",
        "C:\\CON.txt",
        "\\\\server\\x",
        "C:\\x.",
        "C:\\..",
        "C:relative",
        "C:\\a:b",
    ],
)
def test_path_invalid_before_native(m, monkeypatch, path):
    monkeypatch.setattr(m, "runtime_valid", lambda: True)
    monkeypatch.setattr(m, "Native", lambda _: pytest.fail("native called"))
    assert m.prepare(path)["creation_attempted"] is False


def test_wrong_flags_before_any_native(m, monkeypatch):
    monkeypatch.setattr(m, "runtime_valid", lambda: False)
    monkeypatch.setattr(m, "load_helper", lambda: pytest.fail("helper loaded"))
    assert m.prepare("C:\\PublicFixture")["status"] == "runtime_rejected"


@pytest.mark.parametrize(
    "owner,mask,flags",
    [
        (OTHER, 0x1200A9, 0),
        (USER, 0x40, 0),
        (USER, 0x40000, 0),
        (USER, 0x80000, 0),
        (USER, 0x10000, 0),
        (USER, 0x40000000, 0),
    ],
)
def test_unsafe_root_no_creation(m, monkeypatch, owner, mask, flags):
    api = FakeAPI()
    api.root_sd = sd(owner, [(OTHER, mask, flags)])
    assert run(m, monkeypatch, api)["creation_attempted"] is False
    assert api.created == []


def test_root_ti_exact_and_foreign_create_child_allowed(m, monkeypatch):
    api = FakeAPI()
    api.root_sd = sd(
        m.TRUSTED_INSTALLER, [(m.TRUSTED_INSTALLER, 0x1F01FF, 0), (OTHER, 0x1200AD, 0)]
    )
    assert run(m, monkeypatch, api)["verified"] is True


@pytest.mark.parametrize(
    "control,entries",
    [
        (0x8004, None),
        (
            0x9004,
            [(USER, 0x1F01FF, 0x13), ("S-1-5-18", 0x1F01FF, 3), ("S-1-5-32-544", 0x1F01FF, 3)],
        ),
        (0x9004, [(USER, 0x10000000, 3)]),
        (0x9004, [(USER, 0x1F01FF, 3)]),
    ],
)
def test_created_descriptor_not_exact_leaves_residue(m, monkeypatch, control, entries):
    api = FakeAPI()
    api.child_sd = sd(entries=entries, control=control)
    result = run(m, monkeypatch, api)
    assert result["creation_succeeded"] is True and result["verified"] is False
    assert result["status"] == "verification_failed"
    assert api.closed == ["child", "root"]


@pytest.mark.parametrize("code", [80, 183, 5])
def test_create_false_no_retry(m, monkeypatch, code):
    api = FakeAPI()
    api.result = (False, code)
    result = run(m, monkeypatch, api)
    assert result["creation_succeeded"] is False
    assert result["status"] == ("already_exists" if code in (80, 183) else "creation_failed")
    assert len(api.created) == 1


def test_create_exception_unknown_sanitized(m, monkeypatch):
    api = FakeAPI()

    def fail(*args):
        raise OSError("sensitive path and SID")

    api.create = fail
    result = run(m, monkeypatch, api)
    assert result["creation_attempted"] is True and result["creation_succeeded"] == "unknown"
    assert "sensitive" not in json.dumps(result)


def test_cleanup_preserves_primary_failure(m, monkeypatch):
    api = FakeAPI()
    api.result = (False, 183)

    def fail(handle):
        raise OSError("close failed")

    api.close = fail
    result = run(m, monkeypatch, api)
    assert result["status"] == "already_exists" and result["cleanup"] == "failed"


def test_cancel_not_swallowed_and_all_handles_closed(m, monkeypatch):
    api = FakeAPI()

    def cancel(*args):
        raise KeyboardInterrupt

    api.create = cancel
    with pytest.raises(KeyboardInterrupt):
        run(m, monkeypatch, api)
    assert api.closed == ["root"]


def test_identity_change_prevents_create(m, monkeypatch):
    api = FakeAPI()
    api.identities = ["one", "two"]
    assert run(m, monkeypatch, api)["creation_attempted"] is False


def test_reparse_prevents_create(m, monkeypatch):
    api = FakeAPI()
    api.attrs |= 0x400
    assert run(m, monkeypatch, api)["creation_attempted"] is False


def test_build_descriptor_exact(m):
    helper = m.load_helper()
    assert m.build_descriptor(helper, USER) == sd()


def test_standalone_preparation_exists():
    assert SOURCE.is_file(), "standalone preparation implementation is missing"


def native(m, monkeypatch, *, thread=False, thread_error=1008, kind=1):
    helper = m.load_helper()
    obj = m.Native.__new__(m.Native)
    obj.helper = helper
    obj.cleanup_failed = False
    closed = []
    error = [thread_error]
    monkeypatch.setattr(ct, "get_last_error", lambda: error[0], raising=False)

    def open_token(process, access, pointer):
        ct.cast(pointer, ct.POINTER(ct.c_void_p))[0] = 77
        return True

    def thread_token(thread_handle, access, as_self, pointer):
        assert access == 8 and as_self is True
        if thread:
            open_token(None, access, pointer)
        return thread

    def info(token, info_class, buffer, size, needed):
        required = ct.cast(needed, ct.POINTER(ct.c_uint32))
        if info_class == 8:
            required[0] = 4
            ct.cast(buffer, ct.POINTER(ct.c_uint32))[0] = kind
            return True
        raw = sid(USER)
        required[0] = 16 + len(raw)
        if buffer is None:
            error[0] = 122
            return False
        ct.c_void_p.from_buffer(buffer).value = ct.addressof(buffer) + 16
        ct.memmove(ct.addressof(buffer) + 16, raw, len(raw))
        return True

    obj.kernel = SimpleNamespace(
        GetCurrentThread=lambda: -2,
        GetCurrentProcess=lambda: -1,
        CloseHandle=lambda handle: closed.append(handle.value) or True,
    )
    obj.advapi = SimpleNamespace(
        OpenThreadToken=thread_token,
        OpenProcessToken=open_token,
        GetTokenInformation=info,
        IsValidSid=lambda p: True,
    )
    return obj, closed


def test_native_primary_token_without_impersonation(m, monkeypatch):
    obj, closed = native(m, monkeypatch)
    assert obj.effective_user() == USER
    assert closed == [77]


@pytest.mark.parametrize(
    "thread,error,kind", [(True, 1008, 1), (False, 5, 1), (False, 1008, 2), (False, 1008, 0)]
)
def test_native_identity_rejects_impersonation_errors_unknown_type(
    m, monkeypatch, thread, error, kind
):
    obj, closed = native(m, monkeypatch, thread=thread, thread_error=error, kind=kind)
    with pytest.raises(ValueError):
        obj.effective_user()
    assert closed == ([] if error == 5 else [77])


@pytest.mark.parametrize(
    "filesystem,flags,okay", [("NTFS", 8, True), ("ReFS", 8, False), ("NTFS", 0, False)]
)
def test_native_volume_function_boundary(m, monkeypatch, filesystem, flags, okay):
    obj, _ = native(m, monkeypatch)

    def volume(handle, label, label_size, serial, component, out_flags, name, name_size):
        assert handle == 41 and label is None and name_size == 32
        name.value = filesystem
        ct.cast(out_flags, ct.POINTER(ct.c_uint32))[0] = flags
        return True

    obj.kernel.GetVolumeInformationByHandleW = volume
    if okay:
        obj.volume(41)
    else:
        with pytest.raises(ValueError):
            obj.volume(41)


def test_native_create_security_attributes_lifetime(m, monkeypatch):
    obj, _ = native(m, monkeypatch)
    calls = []
    data = sd()

    def create(path, pointer):
        attrs = ct.cast(pointer, ct.POINTER(m.SecurityAttributes)).contents
        assert attrs.nLength == ct.sizeof(m.SecurityAttributes) == 24
        assert attrs.bInheritHandle == 0
        assert ct.string_at(attrs.lpSecurityDescriptor, len(data)) == data
        calls.append(path)
        return True

    obj.kernel.CreateDirectoryW = create
    assert obj.create("C:\\PublicFixture", data) == (True, 0)
    assert calls == ["C:\\PublicFixture"]


def test_close_error_during_cancel_preserves_cancel(m, monkeypatch):
    api = FakeAPI()
    cancellation = KeyboardInterrupt()

    def cancel(*args):
        raise cancellation

    def close(handle):
        api.closed.append(handle)
        raise OSError("private")

    api.create, api.close = cancel, close
    with pytest.raises(KeyboardInterrupt) as caught:
        run(m, monkeypatch, api)
    assert caught.value is cancellation
    assert api.closed == ["root"]


def test_open_after_create_failure_preserves_created(m, monkeypatch):
    api = FakeAPI()

    def open_dir(path):
        if len(path) != 3:
            raise OSError("private")
        return "root"

    api.open_directory = open_dir
    result = run(m, monkeypatch, api)
    assert result["creation_succeeded"] is True and result["verified"] is False


def test_cleanup_failure_after_verified_not_success(m, monkeypatch):
    api = FakeAPI()

    def close(handle):
        api.closed.append(handle)
        raise OSError("private")

    api.close = close
    result = run(m, monkeypatch, api)
    assert result["creation_succeeded"] is True and result["verified"] is True
    assert result["status"] == "cleanup_failed"
    assert api.closed == ["child", "root"]


def test_mapping_change_zero_create(m, monkeypatch):
    api = FakeAPI()
    mappings = iter(["one", "two"])
    api.drive_mapping = lambda root: next(mappings)
    assert run(m, monkeypatch, api)["creation_attempted"] is False


def test_root_unknown_ti_prefix_not_trusted(m, monkeypatch):
    api = FakeAPI()
    api.root_sd = sd(m.TRUSTED_INSTALLER + "-1")
    assert run(m, monkeypatch, api)["creation_attempted"] is False


def test_helper_hash_checked_before_execution(m, monkeypatch):
    monkeypatch.setattr(m, "HELPER_SHA256", "0" * 64)
    with pytest.raises(ValueError, match="helper_rejected"):
        m.load_helper()


def test_cli_argument_error_does_not_echo_private_path(m, capsys):
    with pytest.raises(SystemExit):
        m.main(["--private-root", "C:\\PublicFixture", "--secret-value"])
    captured = capsys.readouterr()
    assert "PublicFixture" not in captured.err and "secret-value" not in captured.err


def test_native_initialization_uncertain_cleanup_not_claimed_complete(m, monkeypatch):
    monkeypatch.setattr(m, "runtime_valid", lambda: True)

    def failed(helper):
        raise OSError("token close failed")

    monkeypatch.setattr(m, "Native", failed)
    result = m.prepare("C:\\PublicFixture")
    assert result["cleanup"] == "unknown"
    assert result["creation_attempted"] is False


@pytest.mark.parametrize("size", [0, 15, 65537])
def test_native_token_bounds_rejected(m, monkeypatch, size):
    obj, closed = native(m, monkeypatch)
    original = obj.advapi.GetTokenInformation

    def info(token, kind, buffer, length, needed):
        if kind == 8:
            return original(token, kind, buffer, length, needed)
        ct.cast(needed, ct.POINTER(ct.c_uint32))[0] = size
        return False

    errors = iter([1008, 122])
    monkeypatch.setattr(ct, "get_last_error", lambda: next(errors))
    obj.advapi.GetTokenInformation = info
    with pytest.raises(ValueError):
        obj.effective_user()
    assert closed == [77]


def test_native_descriptor_validated_before_create(m, monkeypatch):
    obj, _ = native(m, monkeypatch)
    seen = []

    def valid(pointer):
        seen.append(ct.string_at(pointer, len(sd())))
        return True

    obj.advapi.IsValidSecurityDescriptor = valid
    assert obj.descriptor(USER) == sd()
    assert seen == [sd()]
    obj.advapi.IsValidSecurityDescriptor = lambda pointer: False
    with pytest.raises(ValueError):
        obj.descriptor(USER)


@pytest.mark.parametrize("user", ["S-1-5-18", "S-1-5-32-544", "S-01-5-21-1", "S-1-5"])
def test_descriptor_rejects_nonordinary_or_malformed_user(m, user):
    with pytest.raises(ValueError):
        m.build_descriptor(m.load_helper(), user)


def test_identity_recheck_before_create(m, monkeypatch):
    api = FakeAPI()
    api.effective_user = lambda: OTHER
    assert run(m, monkeypatch, api)["creation_attempted"] is False


def test_child_identity_changes_during_verification(m, monkeypatch):
    api = FakeAPI()
    api.identities = ["root", "root", "child", "root", "changed"]
    result = run(m, monkeypatch, api)
    assert result["creation_succeeded"] is True and result["verified"] is False


@pytest.mark.parametrize(
    "mask,flags,allowed",
    [(0x40, 8, True), (0x2000000, 8, False), (0x80000000, 0, True), (0x10000000, 0, False)],
)
def test_root_io_and_generic_rights_are_bounded(m, monkeypatch, mask, flags, allowed):
    api = FakeAPI()
    api.root_sd = sd(USER, [(OTHER, mask, flags)])
    assert run(m, monkeypatch, api)["verified"] is allowed


def test_runtime_gate_requires_all_flags_and_cpython_x64_windows(m, monkeypatch):
    monkeypatch.setattr(m, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(m.platform, "machine", lambda: "AMD64")
    runtime = SimpleNamespace(
        implementation=SimpleNamespace(name="cpython"),
        flags=SimpleNamespace(isolated=1, no_site=1),
        dont_write_bytecode=True,
    )
    monkeypatch.setattr(m, "sys", runtime)
    assert m.runtime_valid()
    runtime.flags.isolated = 0
    assert not m.runtime_valid()
    runtime.flags.isolated, runtime.flags.no_site = 1, 0
    assert not m.runtime_valid()
    runtime.flags.no_site, runtime.dont_write_bytecode = 1, False
    assert not m.runtime_valid()
    runtime.dont_write_bytecode, runtime.implementation.name = True, "pypy"
    assert not m.runtime_valid()
    runtime.implementation.name = "cpython"
    monkeypatch.setattr(m.platform, "machine", lambda: "ARM64")
    assert not m.runtime_valid()


def test_native_token_cleanup_preserves_primary_exception(m, monkeypatch):
    obj, _ = native(m, monkeypatch, kind=2)
    obj.kernel.CloseHandle = lambda handle: False
    with pytest.raises(ValueError, match="identity_rejected"):
        obj.effective_user()
    assert obj.cleanup_failed is True


def test_native_bindings_use_fixed_width_types_and_no_token_changes(m, monkeypatch):
    class Function:
        def __call__(self, *args):
            pytest.fail("unexpected native execution")

    class DLL:
        def __init__(self):
            self.functions = {}

        def __getattr__(self, name):
            return self.functions.setdefault(name, Function())

    dlls = {"kernel32": DLL(), "advapi32": DLL()}
    monkeypatch.setattr(ct, "WinDLL", lambda name, **kwargs: dlls[name], raising=False)
    helper = SimpleNamespace(Native=lambda: SimpleNamespace(user_sid=USER))
    monkeypatch.setattr(m.Native, "effective_user", lambda self: USER)
    api = m.Native(helper)
    assert api.kernel.CreateDirectoryW.argtypes == [ct.c_wchar_p, ct.POINTER(m.SecurityAttributes)]
    assert api.advapi.OpenThreadToken.argtypes == [
        ct.c_void_p,
        ct.c_uint32,
        ct.c_int32,
        ct.c_void_p,
    ]
    assert set(dlls["advapi32"].functions) == {
        "OpenThreadToken",
        "OpenProcessToken",
        "GetTokenInformation",
        "IsValidSid",
        "IsValidSecurityDescriptor",
    }


def test_token_close_failure_not_hidden_by_callers_handled_exception(m, monkeypatch):
    obj, _ = native(m, monkeypatch)
    obj.kernel.CloseHandle = lambda handle: False
    try:
        raise RuntimeError("already handled by caller")
    except RuntimeError:
        with pytest.raises(ValueError, match="cleanup_failed"):
            obj.effective_user()


def test_helper_read_is_bounded_and_cancel_survives_close_error(m, monkeypatch):
    cancellation = KeyboardInterrupt()

    class Stream:
        def read(self, size):
            assert size == 65537
            raise cancellation

        def close(self):
            raise OSError("private close error")

    monkeypatch.setattr(m.Path, "open", lambda *args, **kwargs: Stream())
    with pytest.raises(KeyboardInterrupt) as caught:
        m.load_helper()
    assert caught.value is cancellation


def test_helper_oversized_read_rejected(m, monkeypatch):
    class Stream:
        def read(self, size):
            assert size == 65537
            return b"x" * size

        def close(self):
            pass

    monkeypatch.setattr(m.Path, "open", lambda *args, **kwargs: Stream())
    with pytest.raises(ValueError, match="helper_rejected"):
        m.load_helper()


def test_close_state_unknown_before_interrupted_close(m, monkeypatch):
    api = FakeAPI()
    observed = []

    def close(handle):
        import inspect

        observed.append(inspect.currentframe().f_back.f_locals["result"]["cleanup"])
        raise KeyboardInterrupt

    api.close = close
    with pytest.raises(KeyboardInterrupt):
        run(m, monkeypatch, api)
    assert observed == ["unknown"]
