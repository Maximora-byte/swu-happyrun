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
