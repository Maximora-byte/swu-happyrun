"""Synthetic Windows ACL policy tests, not Windows execution acceptance."""

from pathlib import Path

import pytest

from swu_happyrun.drivers.mumu import windows_private as win

SID = "S-1-5-21-1-2-3-1001"


def test_protected_current_user_only_acl_accepted():
    win.validate_sddl(f"O:{SID}D:P(A;OICI;FA;;;{SID})", SID, protected=True)


@pytest.mark.parametrize(
    "sddl",
    [
        f"O:{SID}D:(A;OICI;FA;;;{SID})",
        f"O:{SID}D:P(A;;FA;;;WD)",
        f"O:SYD:P(A;;FA;;;{SID})",
        f"O:{SID}D:P",
        f"O:{SID}D:NO_ACCESS_CONTROL",
        f"O:{SID}D:P(A;;FA;;;{SID})(A;;FR;;;BU)",
        f"O:{SID}D:P(XA;;FA;;;{SID};condition)",
        f"O:{SID}D:P(A;IO;FA;;;{SID})",
    ],
)
def test_broad_missing_or_unknown_acl_rejected(sddl):
    with pytest.raises(win.WindowsPrivacyError):
        win.validate_sddl(sddl, SID, protected=True)


def test_inherited_file_acl_only_current_user_accepted():
    win.validate_sddl(f"O:{SID}D:AI(A;ID;FA;;;{SID})", SID, protected=False)


def test_api_failure_never_means_private(monkeypatch, tmp_path):
    class FailedAPI:
        def __init__(self):
            raise OSError("sensitive path")

    monkeypatch.setattr(win, "_WinAPI", FailedAPI)
    with pytest.raises(win.WindowsPrivacyError, match="^private_acl_unverified$"):
        win.verify_directory(tmp_path)


def test_provision_never_changes_existing_directory(monkeypatch, tmp_path):
    class UnusedAPI:
        def __init__(self):
            pytest.fail("existing directory must not reach ACL modification")

    monkeypatch.setattr(win, "_WinAPI", UnusedAPI)
    with pytest.raises(win.WindowsPrivacyError, match="^private_directory_exists$"):
        win.provision_private_directory(tmp_path)


def test_nonwindows_api_fails_closed():
    import os

    if os.name != "nt":
        with pytest.raises(win.WindowsPrivacyError, match="^private_acl_unverified$"):
            win.verify_directory(Path("synthetic"))


def test_store_windows_uses_native_acl_not_posix_mode(tmp_path, monkeypatch):
    from swu_happyrun.drivers.mumu import private_evidence as store_module

    monkeypatch.setattr(store_module, "_PLATFORM", "nt")
    seen = []
    monkeypatch.setattr(win, "verify_directory", lambda path: seen.append(path) or (3, 4))
    store = store_module.PrivateEvidenceStore(tmp_path)
    assert seen == [tmp_path]
    assert store._identity == (3, 4)


def test_windows_store_checks_acl_before_writing_and_keeps_once(tmp_path, monkeypatch):
    from contextlib import contextmanager

    from swu_happyrun.drivers.mumu import private_evidence as store_module

    class API:
        def security(self, path):
            assert path.read_bytes() == b""  # no private bytes before ACL verification
            return f"O:{SID}D:AI(A;ID;FA;;;{SID})"

    @contextmanager
    def verified(path, identity=None):
        yield API(), SID, (3, 4)

    monkeypatch.setattr(store_module, "_PLATFORM", "nt")
    monkeypatch.setattr(win, "verify_directory", lambda path: (3, 4))
    monkeypatch.setattr(win, "verified_directory", verified)
    store = store_module.PrivateEvidenceStore(tmp_path)
    store.claim_intent("location")
    assert (tmp_path / "location.intent").read_bytes() == b"attempt_reserved_v1\n"
    with pytest.raises(store_module.PrivateEvidenceError, match="^intent_exists$"):
        store.claim_intent("location")


def test_windows_store_bad_file_acl_stays_empty(tmp_path, monkeypatch):
    from contextlib import contextmanager

    from swu_happyrun.drivers.mumu import private_evidence as store_module

    class API:
        def security(self, path):
            return f"O:{SID}D:AI(A;ID;FA;;;WD)"

    @contextmanager
    def verified(path, identity=None):
        yield API(), SID, (3, 4)

    monkeypatch.setattr(store_module, "_PLATFORM", "nt")
    monkeypatch.setattr(win, "verify_directory", lambda path: (3, 4))
    monkeypatch.setattr(win, "verified_directory", verified)
    store = store_module.PrivateEvidenceStore(tmp_path)
    with pytest.raises(store_module.PrivateEvidenceError, match="^private_acl_unverified$"):
        store.put_once("command.stdout.bin", b"synthetic-private-data")
    assert (tmp_path / "command.stdout.bin").read_bytes() == b""


def test_native_security_query_error_fails_closed():
    class Advapi:
        def GetNamedSecurityInfoW(self, *args):
            return 5  # ERROR_ACCESS_DENIED

    api = object.__new__(win._WinAPI)
    api.advapi = Advapi()
    with pytest.raises(win.WindowsPrivacyError, match="^private_acl_unverified$"):
        api.security(Path("synthetic-private-path"))


def test_native_reparse_swap_rejected_after_handle_open():
    class Kernel:
        calls = 0
        closed = []

        def GetFileAttributesW(self, path):
            self.calls += 1
            return 0x10 if self.calls == 1 else 0x410

        def CreateFileW(self, *args):
            return 99

        def CloseHandle(self, handle):
            self.closed.append(handle)
            return True

    api = object.__new__(win._WinAPI)
    api.kernel = Kernel()
    with pytest.raises(win.WindowsPrivacyError, match="^private_acl_unverified$"):
        api.guard(Path("synthetic"))
    assert api.kernel.closed == [99]


def test_provision_rejects_relative_before_native_creation(monkeypatch):
    class UnusedAPI:
        def __init__(self):
            pytest.fail("invalid destination must not reach native mutation")

    monkeypatch.setattr(win, "_WinAPI", UnusedAPI)
    with pytest.raises(win.WindowsPrivacyError, match="^private_directory_invalid$"):
        win.provision_private_directory(Path("relative-private"))


def test_native_provision_supplies_protected_inheritable_current_user_dacl():
    import ctypes as ct

    class Advapi:
        descriptor = None

        def ConvertStringSecurityDescriptorToSecurityDescriptorW(self, sddl, revision, out, size):
            self.descriptor = sddl
            assert revision == 1
            ct.cast(out, ct.POINTER(ct.c_void_p))[0] = ct.c_void_p(123)
            return True

    class Kernel:
        freed = []
        created = []

        def CreateDirectoryW(self, path, attrs):
            attributes = ct.cast(attrs, ct.POINTER(win._SecurityAttributes)).contents
            assert attributes.lpSecurityDescriptor == 123
            assert not attributes.bInheritHandle
            self.created.append(path)
            return True

        def LocalFree(self, pointer):
            self.freed.append(pointer.value)

    api = object.__new__(win._WinAPI)
    api.advapi = Advapi()
    api.kernel = Kernel()
    api.create_private_directory(Path("synthetic"), SID)
    assert api.advapi.descriptor == f"O:{SID}D:P(A;OICI;FA;;;{SID})"
    assert api.kernel.created == ["synthetic"]
    assert api.kernel.freed == [123]


def _native_alias_api(
    *,
    owner=SID,
    trustee=SID,
    rights="FA",
    mask=0x1F01FF,
    ace_type=0,
    ace_flags=3,
    fail_owner=False,
    fail_sid=False,
    ace_size=20,
    ace_offset=8,
    acl_count=1,
    sid_count=1,
    sddl_flags="P",
    sddl_inheritance="OICI",
):
    """Native memory fixtures: SDDL aliases never carry the asserted identity."""
    import ctypes as ct
    import struct

    # Minimal SID bytes, only interpreted by our fake native SID conversion.
    ace_bytes = (
        struct.pack("<BBHI", ace_type, ace_flags, ace_size, mask)
        + bytes([1, sid_count])
        + bytes(10)
    )
    owner_sid = ct.create_string_buffer(bytes(12))
    acl = ct.create_string_buffer(struct.pack("<BBHHH", 2, 0, 28, acl_count, 0) + ace_bytes)
    strings = []

    def out_pointer(out, address):
        ct.cast(out, ct.POINTER(ct.c_void_p))[0] = address

    class Advapi:
        def GetNamedSecurityInfoW(self, path, kind, info, a, b, c, d, out):
            out_pointer(out, 123)
            return 0

        def GetSecurityDescriptorLength(self, descriptor):
            return 128

        def ConvertSecurityDescriptorToStringSecurityDescriptorW(self, sd, rev, info, out, size):
            text = ct.create_unicode_buffer(
                f"O:LAD:{sddl_flags}(A;{sddl_inheritance};{rights};;;LA)"
            )
            strings.append(text)
            out_pointer(out, ct.addressof(text))
            ct.cast(size, ct.POINTER(win.wt.DWORD))[0] = len(text)
            return True

        def GetSecurityDescriptorOwner(self, sd, out, defaulted):
            out_pointer(out, ct.addressof(owner_sid))
            return not fail_owner

        def GetSecurityDescriptorDacl(self, sd, present, out, defaulted):
            ct.cast(present, ct.POINTER(win.wt.BOOL))[0] = True
            out_pointer(out, ct.addressof(acl))
            return True

        def IsValidAcl(self, pointer):
            return True

        def GetAce(self, pointer, index, out):
            assert index == 0
            out_pointer(out, ct.addressof(acl) + ace_offset)
            return True

        def IsValidSid(self, pointer):
            return not fail_sid

        def GetLengthSid(self, pointer):
            return 12

        def ConvertSidToStringSidW(self, pointer, out):
            address = pointer.value if isinstance(pointer, ct.c_void_p) else pointer
            text = ct.create_unicode_buffer(
                owner if address == ct.addressof(owner_sid) else trustee
            )
            strings.append(text)
            out_pointer(out, ct.addressof(text))
            return True

    class Kernel:
        def LocalFree(self, pointer):
            pass

    api = object.__new__(win._WinAPI)
    api.advapi, api.kernel = Advapi(), Kernel()
    return api


def test_native_la_rendering_canonicalizes_actual_owner_and_ace_sid():
    admin_sid = "S-1-5-21-1-2-3-500"
    api = _native_alias_api(owner=admin_sid, trustee=admin_sid)
    result = api.security(Path("synthetic"))
    assert result == f"O:{admin_sid}D:P(A;OICI;FA;;;{admin_sid})"
    win.validate_sddl(result, admin_sid, protected=True)


@pytest.mark.parametrize(
    "changes",
    [
        {"owner": "S-1-5-21-9-8-7-500"},
        {"trustee": "S-1-5-21-9-8-7-500"},
        {"trustee": "S-1-1-0"},
        {"rights": "FR"},
        {"mask": 0x120089},
        {"ace_type": 9},
        {"ace_flags": 8},
        {"fail_owner": True},
        {"fail_sid": True},
        {"ace_size": 1024},
        {"ace_size": 8},
        {"ace_offset": 1},
        {"acl_count": 2},
        {"sid_count": 15},
    ],
)
def test_native_alias_does_not_authorize_wrong_identity_or_rights(changes):
    api = _native_alias_api(**changes)
    with pytest.raises(win.WindowsPrivacyError, match="^private_acl_unverified$"):
        win.validate_sddl(api.security(Path("synthetic")), SID, protected=True)


def test_literal_la_is_not_an_identity_grant():
    with pytest.raises(win.WindowsPrivacyError, match="^private_acl_unverified$"):
        win.validate_sddl("O:LAD:P(A;OICI;FA;;;LA)", "S-1-5-21-1-2-3-500", protected=True)


def test_native_windows_provision_verify_and_inherited_file_acl(tmp_path, monkeypatch):
    """Real Windows API regression; no emulator, device, or synthetic ACL backend."""
    import os

    from swu_happyrun.drivers.mumu.private_evidence import PrivateEvidenceStore

    if os.name != "nt":
        pytest.skip("requires real Windows ACL APIs")
    root = tmp_path / "native-private"
    win.provision_private_directory(root)
    win.verify_directory(root)
    store = PrivateEvidenceStore(root)
    # Capture the native file ACL shape while the CRT-created fd remains open.
    # This distinguishes a sharing error from a default-owner/inheritance issue.
    diagnostics = {}
    original_security = win._WinAPI.security

    def observed_security(api, path):
        if path.name == "command.stdout.bin":
            diagnostics.update(_native_acl_shape(api, path, api.current_sid()))
        return original_security(api, path)

    monkeypatch.setattr(win._WinAPI, "security", observed_security)
    try:
        store.put_once("command.stdout.bin", b"synthetic-native-acl-regression")
    except RuntimeError:
        import json

        pytest.fail(
            "native_file_acl_shape=" + json.dumps(diagnostics, sort_keys=True), pytrace=False
        )
    api = win._WinAPI()
    sid = api.current_sid()
    directory_sddl = api.security(root)
    file_sddl = api.security(root / "command.stdout.bin")
    win.validate_sddl(directory_sddl, sid, protected=True)
    win.validate_sddl(file_sddl, sid, protected=False)
    assert (root / "command.stdout.bin").read_bytes() == b"synthetic-native-acl-regression"
    store.claim_intent("launch")
    with pytest.raises(RuntimeError, match="^intent_exists$"):
        PrivateEvidenceStore(root).claim_intent("launch")


def test_native_inherited_file_alias_is_canonicalized():
    api = _native_alias_api(ace_flags=16, sddl_flags="AI", sddl_inheritance="ID")
    result = api.security(Path("synthetic"))
    assert result == f"O:{SID}D:AI(A;ID;FA;;;{SID})"
    win.validate_sddl(result, SID, protected=False)


def _native_acl_shape(api, path, current_sid):
    """CI diagnosis only: fixed stages, numbers and equality booleans, never raw ACL/SIDs."""
    import ctypes as ct
    import struct

    result = {
        "stage": "query",
        "query_status": None,
        "owner_equals_current": None,
        "control": None,
        "aces": [],
    }
    descriptor = ct.c_void_p()
    status = api.advapi.GetNamedSecurityInfoW(
        str(path), 1, 5, None, None, None, None, ct.byref(descriptor)
    )
    result["query_status"] = int(status)
    if status != 0 or not descriptor.value:
        return result
    try:
        result["stage"] = "descriptor"
        if not 0 < api.advapi.GetSecurityDescriptorLength(descriptor) <= 65536:
            return result
        result["stage"] = "control"
        function = api.advapi.GetSecurityDescriptorControl
        function.argtypes = [ct.c_void_p, ct.c_void_p, ct.c_void_p]
        function.restype = win.wt.BOOL
        control, revision = ct.c_uint16(), win.wt.DWORD()
        if not function(descriptor, ct.byref(control), ct.byref(revision)):
            return result
        result["control"] = int(control.value)
        result["stage"] = "owner"
        owner, defaulted = ct.c_void_p(), win.wt.BOOL()
        if not api.advapi.GetSecurityDescriptorOwner(
            descriptor, ct.byref(owner), ct.byref(defaulted)
        ):
            return result
        result["owner_equals_current"] = api._sid_text(owner) == current_sid
        result["stage"] = "dacl"
        acl, present = ct.c_void_p(), win.wt.BOOL()
        if not api.advapi.GetSecurityDescriptorDacl(
            descriptor, ct.byref(present), ct.byref(acl), ct.byref(defaulted)
        ):
            return result
        if not present.value or not acl.value or not api.advapi.IsValidAcl(acl):
            return result
        _, _, size, count, _ = struct.unpack("<BBHHH", ct.string_at(acl, 8))
        if not (8 <= size <= 65535 and 0 < count <= 32):
            return result
        result["stage"] = "ace"
        for index in range(count):
            pointer = ct.c_void_p()
            if not api.advapi.GetAce(acl, index, ct.byref(pointer)):
                return result
            if not pointer.value or not acl.value + 8 <= pointer.value <= acl.value + size - 8:
                return result
            kind, flags, ace_size, mask = struct.unpack("<BBHI", ct.string_at(pointer, 8))
            shape = {
                "type": int(kind),
                "flags": int(flags),
                "mask": int(mask),
                "trustee_equals_current": None,
            }
            result["aces"].append(shape)
            if kind != 0 or not 16 <= ace_size <= acl.value + size - pointer.value:
                return result
            sid_pointer = ct.c_void_p(pointer.value + 8)
            sid_revision, count = ct.string_at(sid_pointer, 2)
            if sid_revision != 1 or count > 15 or 8 + 4 * count != ace_size - 8:
                return result
            shape["trustee_equals_current"] = api._sid_text(sid_pointer) == current_sid
        result["stage"] = "complete"
        return result
    except (win.WindowsPrivacyError, OSError, AttributeError, ValueError):
        return result
    finally:
        api.kernel.LocalFree(descriptor)


def test_native_diagnostic_query_failure_has_no_sensitive_values():
    import json

    class Advapi:
        def GetNamedSecurityInfoW(self, *args):
            return 32  # ERROR_SHARING_VIOLATION

    api = object.__new__(win._WinAPI)
    api.advapi = Advapi()
    result = _native_acl_shape(api, Path("private-synthetic-path"), SID)
    assert result == {
        "stage": "query",
        "query_status": 32,
        "owner_equals_current": None,
        "control": None,
        "aces": [],
    }
    assert SID not in json.dumps(result)
    assert "private-synthetic-path" not in json.dumps(result)


def test_native_diagnostic_reports_only_shape_and_identity_equality():
    import ctypes as ct
    import json

    class Control:
        def __call__(self, descriptor, control, revision):
            ct.cast(control, ct.POINTER(ct.c_uint16))[0] = 0x8004
            return True

    api = _native_alias_api(owner="S-1-5-32-544")
    api.advapi.GetSecurityDescriptorControl = Control()
    result = _native_acl_shape(api, Path("private-synthetic-path"), SID)
    assert result == {
        "stage": "complete",
        "query_status": 0,
        "owner_equals_current": False,
        "control": 0x8004,
        "aces": [{"type": 0, "flags": 3, "mask": 0x1F01FF, "trustee_equals_current": True}],
    }
    encoded = json.dumps(result)
    assert SID not in encoded
    assert "S-1-5-32-544" not in encoded
    assert "private-synthetic-path" not in encoded
