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
        def create_private_file(self, path, sid):
            import os

            assert sid == SID
            return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)

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
        def create_private_file(self, path, sid):
            path.touch(exist_ok=False)
            raise win.WindowsPrivacyError("private_acl_unverified")

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


def test_native_windows_provision_verify_and_explicit_file_acl(tmp_path, monkeypatch):
    """Real Windows API regression; no emulator, device, or synthetic ACL backend."""
    import os

    from swu_happyrun.drivers.mumu.private_evidence import PrivateEvidenceStore

    if os.name != "nt":
        pytest.skip("requires real Windows ACL APIs")
    root = tmp_path / "native-private"
    win.provision_private_directory(root)
    win.verify_directory(root)
    store = PrivateEvidenceStore(root)
    verified_handles = []
    transferred_handles = []
    transferred_identities = []
    original_security_handle = win._WinAPI.security_handle
    original_transfer = win._open_osfhandle

    def observed_security_handle(api, handle):
        result = original_security_handle(api, handle)
        win.validate_sddl(result, api.current_sid(), protected=True)
        verified_handles.append(handle)
        return result

    def observed_transfer(handle):
        assert handle in verified_handles
        fd = original_transfer(handle)
        transferred_handles.append(handle)
        info = os.fstat(fd)
        transferred_identities.append((info.st_dev, info.st_ino))
        return fd

    monkeypatch.setattr(win._WinAPI, "security_handle", observed_security_handle)
    monkeypatch.setattr(win, "_open_osfhandle", observed_transfer)
    store.put_once("command.stdout.bin", b"synthetic-native-acl-regression")
    assert verified_handles == transferred_handles
    file_info = (root / "command.stdout.bin").stat()
    assert transferred_identities == [(file_info.st_dev, file_info.st_ino)]
    api = win._WinAPI()
    sid = api.current_sid()
    directory_sddl = api.security(root)
    file_sddl = api.security(root / "command.stdout.bin")
    win.validate_sddl(directory_sddl, sid, protected=True)
    win.validate_sddl(file_sddl, sid, protected=True)
    assert (root / "command.stdout.bin").read_bytes() == b"synthetic-native-acl-regression"
    store.claim_intent("launch")
    with pytest.raises(RuntimeError, match="^intent_exists$"):
        PrivateEvidenceStore(root).claim_intent("launch")


def test_native_inherited_file_alias_is_canonicalized():
    api = _native_alias_api(ace_flags=16, sddl_flags="AI", sddl_inheritance="ID")
    result = api.security(Path("synthetic"))
    assert result == f"O:{SID}D:AI(A;ID;FA;;;{SID})"
    win.validate_sddl(result, SID, protected=False)


def _native_creation_api(
    monkeypatch, *, status=0, invalid_owner=False, transfer_error=False, file_attributes=0x80
):
    import ctypes as ct
    import struct

    calls = []

    class Advapi:
        def ConvertStringSecurityDescriptorToSecurityDescriptorW(self, sddl, revision, out, size):
            calls.append(("descriptor", sddl))
            ct.cast(out, ct.POINTER(ct.c_void_p))[0] = 123
            return True

    class Kernel:
        def CreateFileW(self, path, access, sharing, attributes, disposition, flags, template):
            attr = ct.cast(attributes, ct.POINTER(win._SecurityAttributes)).contents
            calls.append(("create", access, sharing, disposition, flags, attr.lpSecurityDescriptor))
            return ct.c_void_p(-1).value if status else 99

        def GetFileType(self, handle):
            assert handle == 99
            return 1

        def GetFileInformationByHandle(self, handle, out):
            data = [file_attributes] + [0] * 12
            data[10] = 1
            ct.memmove(out, struct.pack("<13I", *data), 52)
            calls.append(("file_info", handle))
            return True

        def CloseHandle(self, handle):
            calls.append(("close", handle))
            return True

        def LocalFree(self, pointer):
            calls.append(("free", pointer.value))

    api = object.__new__(win._WinAPI)
    api.advapi, api.kernel = Advapi(), Kernel()

    def security_handle(handle):
        calls.append(("security_handle", handle))
        return f"O:{'S-1-5-32-544' if invalid_owner else SID}D:P(A;;FA;;;{SID})"

    api.security_handle = security_handle

    def transfer(handle):
        calls.append(("transfer", handle))
        if transfer_error:
            raise OSError("synthetic private path")
        return 777

    monkeypatch.setattr(win, "_open_osfhandle", transfer, raising=False)
    monkeypatch.setattr(win.ct, "get_last_error", lambda: status, raising=False)
    return api, calls


def test_native_file_create_sets_exact_owner_and_verifies_same_handle(monkeypatch):
    api, calls = _native_creation_api(monkeypatch)
    assert api.create_private_file(Path("synthetic"), SID) == 777
    assert calls[0] == ("descriptor", f"O:{SID}D:P(A;;FA;;;{SID})")
    create = next(row for row in calls if row[0] == "create")
    assert create[3] == 1  # CREATE_NEW, never overwrite/reopen
    assert create[1] & 0x20000  # READ_CONTROL for handle ACL query
    assert calls.index(("security_handle", 99)) < calls.index(("transfer", 99))
    assert ("close", 99) not in calls  # ownership transferred exactly once


@pytest.mark.parametrize("status", [80, 183])
def test_native_file_exists_refuses_without_transfer(monkeypatch, status):
    api, calls = _native_creation_api(monkeypatch, status=status)
    with pytest.raises(FileExistsError):
        api.create_private_file(Path("synthetic"), SID)
    assert not any(row[0] in {"transfer", "close"} for row in calls)


@pytest.mark.parametrize(
    "changes",
    [
        {"invalid_owner": True},
        {"transfer_error": True},
        {"file_attributes": 0x400},
        {"file_attributes": 0x10},
        {"status": 5},
    ],
)
def test_native_creation_failure_never_transfers_unverified_handle(monkeypatch, changes):
    api, calls = _native_creation_api(monkeypatch, **changes)
    with pytest.raises(win.WindowsPrivacyError, match="^private_acl_unverified$"):
        api.create_private_file(Path("synthetic"), SID)
    assert calls.count(("close", 99)) == (0 if changes.get("status") else 1)
    if not changes.get("transfer_error"):
        assert ("transfer", 99) not in calls


def test_native_security_handle_queries_exact_handle_not_path():
    import ctypes as ct

    api = _native_alias_api()
    calls = []

    def query(handle, kind, info, a, b, c, d, out):
        calls.append((handle, kind, info))
        ct.cast(out, ct.POINTER(ct.c_void_p))[0] = 123
        return 0

    def no_path(*args):
        pytest.fail("handle verification must not reopen a path")

    api.advapi.GetSecurityInfo = query
    api.advapi.GetNamedSecurityInfoW = no_path
    result = api.security_handle(99)
    assert calls == [(99, 1, 5)]
    win.validate_sddl(result, SID, protected=True)


def test_windows_native_intent_validation_failure_is_never_retryable(tmp_path, monkeypatch):
    from contextlib import contextmanager

    from swu_happyrun.drivers.mumu import private_evidence as store_module

    class API:
        def create_private_file(self, path, sid):
            # Models CREATE_NEW succeeding before a failing handle ACL check.
            path.touch(exist_ok=False)
            raise win.WindowsPrivacyError("private_acl_unverified")

    @contextmanager
    def verified(path, identity=None):
        yield API(), SID, (3, 4)

    monkeypatch.setattr(store_module, "_PLATFORM", "nt")
    monkeypatch.setattr(win, "verify_directory", lambda path: (3, 4))
    monkeypatch.setattr(win, "verified_directory", verified)
    store = store_module.PrivateEvidenceStore(tmp_path)
    with pytest.raises(store_module.PrivateEvidenceError, match="^private_acl_unverified$"):
        store.claim_intent("launch")
    assert (tmp_path / "launch.intent").read_bytes() == b""
    with pytest.raises(store_module.PrivateEvidenceError, match="^intent_exists$"):
        store_module.PrivateEvidenceStore(tmp_path).claim_intent("launch")
