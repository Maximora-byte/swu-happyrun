"""Conservative native Windows private-directory policy; no chmod ACL claims.

Reference APIs and SDDL grammar:
https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-getnamedsecurityinfow
https://learn.microsoft.com/en-us/windows/win32/secauthz/security-descriptor-string-format
https://learn.microsoft.com/en-us/windows/win32/api/sddl/nf-sddl-convertstringsecuritydescriptortosecuritydescriptorw

Only the current token user may have an allow ACE. Unsupported ACL representations
fail closed instead of attempting a permissive effective-access interpretation.
No existing permissions are ever changed. Windows execution still needs acceptance.
"""

from __future__ import annotations

import ctypes as ct
import os
import re
from contextlib import contextmanager
from ctypes import wintypes as wt
from pathlib import Path


class WindowsPrivacyError(RuntimeError):
    pass


def validate_sddl(sddl: str, sid: str, *, protected: bool) -> None:
    """Accept only an owner-matching, bounded, current-user-only full-access DACL."""
    if not re.fullmatch(r"S-1-(?:\d+-){1,14}\d+", sid) or len(sddl) > 65536:
        raise WindowsPrivacyError("private_acl_unverified")
    match = re.fullmatch(r"O:" + re.escape(sid) + r"D:([A-Z]*)(\(.*\))", sddl)
    if match is None:
        raise WindowsPrivacyError("private_acl_unverified")
    flags, aces = match.groups()
    if flags not in {"", "AI", "P", "PAI"} or (protected and "P" not in flags):
        raise WindowsPrivacyError("private_acl_unverified")
    parts = re.findall(r"\([^()]*\)", aces)
    if not parts or "".join(parts) != aces or len(parts) > 32:
        raise WindowsPrivacyError("private_acl_unverified")
    for ace in parts:
        fields = ace[1:-1].split(";")
        if len(fields) != 6:
            raise WindowsPrivacyError("private_acl_unverified")
        kind, inheritance, rights, object_guid, inherited_guid, trustee = fields
        if (
            kind != "A"
            or trustee != sid
            or object_guid
            or inherited_guid
            or inheritance not in {"", "OI", "CI", "OICI", "ID", "OICIID"}
            or rights not in {"FA", "0x1f01ff"}
        ):
            raise WindowsPrivacyError("private_acl_unverified")


class _SecurityAttributes(ct.Structure):
    _fields_ = [
        ("nLength", wt.DWORD),
        ("lpSecurityDescriptor", ct.c_void_p),
        ("bInheritHandle", wt.BOOL),
    ]


class _WinAPI:
    """Small typed ctypes boundary; all variable-size results have hard caps."""

    def __init__(self):
        if os.name != "nt":
            raise WindowsPrivacyError("private_acl_unverified")
        self.kernel = ct.WinDLL("kernel32", use_last_error=True)
        self.advapi = ct.WinDLL("advapi32", use_last_error=True)
        P = ct.c_void_p
        self._bind(self.kernel, "GetCurrentProcess", [], wt.HANDLE)
        self._bind(self.kernel, "GetCurrentThread", [], wt.HANDLE)
        self._bind(self.kernel, "CloseHandle", [wt.HANDLE], wt.BOOL)
        self._bind(self.kernel, "LocalFree", [P], P)
        self._bind(self.kernel, "GetFileAttributesW", [wt.LPCWSTR], wt.DWORD)
        self._bind(self.kernel, "CreateDirectoryW", [wt.LPCWSTR, P], wt.BOOL)
        self._bind(
            self.kernel,
            "CreateFileW",
            [wt.LPCWSTR, wt.DWORD, wt.DWORD, P, wt.DWORD, wt.DWORD, wt.HANDLE],
            wt.HANDLE,
        )
        self._bind(self.advapi, "OpenProcessToken", [wt.HANDLE, wt.DWORD, P], wt.BOOL)
        self._bind(self.advapi, "OpenThreadToken", [wt.HANDLE, wt.DWORD, wt.BOOL, P], wt.BOOL)
        self._bind(
            self.advapi, "GetTokenInformation", [wt.HANDLE, ct.c_int, P, wt.DWORD, P], wt.BOOL
        )
        self._bind(self.advapi, "ConvertSidToStringSidW", [P, P], wt.BOOL)
        self._bind(
            self.advapi,
            "GetNamedSecurityInfoW",
            [wt.LPWSTR, ct.c_int, wt.DWORD, P, P, P, P, P],
            wt.DWORD,
        )
        self._bind(self.advapi, "GetSecurityDescriptorLength", [P], wt.DWORD)
        self._bind(
            self.advapi,
            "ConvertSecurityDescriptorToStringSecurityDescriptorW",
            [P, wt.DWORD, wt.DWORD, P, P],
            wt.BOOL,
        )
        self._bind(
            self.advapi,
            "ConvertStringSecurityDescriptorToSecurityDescriptorW",
            [wt.LPCWSTR, wt.DWORD, P, P],
            wt.BOOL,
        )

    @staticmethod
    def _bind(library, name, args, result):
        function = getattr(library, name)
        function.argtypes = args
        function.restype = result

    @staticmethod
    def _require(ok):
        if not ok:
            raise WindowsPrivacyError("private_acl_unverified")

    def current_sid(self) -> str:
        token = wt.HANDLE()
        if not self.advapi.OpenThreadToken(
            self.kernel.GetCurrentThread(), 8, True, ct.byref(token)
        ):
            self._require(ct.get_last_error() == 1008)  # ERROR_NO_TOKEN only
            self._require(
                self.advapi.OpenProcessToken(self.kernel.GetCurrentProcess(), 8, ct.byref(token))
            )
        try:
            buffer = ct.create_string_buffer(65536)
            needed = wt.DWORD()
            self._require(
                self.advapi.GetTokenInformation(token, 1, buffer, len(buffer), ct.byref(needed))
            )
            self._require(0 < needed.value <= len(buffer))
            sid_pointer = ct.cast(buffer, ct.POINTER(ct.c_void_p))[0]
            text = wt.LPWSTR()
            self._require(self.advapi.ConvertSidToStringSidW(sid_pointer, ct.byref(text)))
            try:
                result = text.value
                self._require(result is not None and len(result) < 256)
                return result
            finally:
                self.kernel.LocalFree(text)
        finally:
            self.kernel.CloseHandle(token)

    def security(self, path: Path) -> str:
        descriptor = ct.c_void_p()
        status = self.advapi.GetNamedSecurityInfoW(
            str(path), 1, 5, None, None, None, None, ct.byref(descriptor)
        )
        self._require(status == 0 and descriptor.value)
        try:
            self._require(0 < self.advapi.GetSecurityDescriptorLength(descriptor) <= 65536)
            text = wt.LPWSTR()
            length = wt.DWORD()
            self._require(
                self.advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW(
                    descriptor, 1, 5, ct.byref(text), ct.byref(length)
                )
            )
            try:
                self._require(0 < length.value <= 65536)
                result = text.value
                self._require(result is not None)
                return result
            finally:
                self.kernel.LocalFree(text)
        finally:
            self.kernel.LocalFree(descriptor)

    def guard(self, path: Path):
        attrs = self.kernel.GetFileAttributesW(str(path))
        self._require(attrs != 0xFFFFFFFF and not attrs & 0x400 and attrs & 0x10)
        # No FILE_SHARE_DELETE: keep each ancestor stable through file creation.
        handle = self.kernel.CreateFileW(str(path), 0x80, 3, None, 3, 0x02200000, None)
        self._require(handle not in {None, ct.c_void_p(-1).value})
        attrs = self.kernel.GetFileAttributesW(str(path))
        if attrs == 0xFFFFFFFF or attrs & 0x400 or not attrs & 0x10:
            self.kernel.CloseHandle(handle)
            raise WindowsPrivacyError("private_acl_unverified")
        return handle

    def create_private_directory(self, path: Path, sid: str):
        descriptor = ct.c_void_p()
        self._require(
            self.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                f"O:{sid}D:P(A;OICI;FA;;;{sid})", 1, ct.byref(descriptor), None
            )
        )
        try:
            attributes = _SecurityAttributes(ct.sizeof(_SecurityAttributes), descriptor, False)
            self._require(self.kernel.CreateDirectoryW(str(path), ct.byref(attributes)))
        finally:
            self.kernel.LocalFree(descriptor)


@contextmanager
def verified_directory(root: Path, identity=None):
    """Hold non-delete-sharing ancestor handles while using the verified root."""
    handles = []
    api = None
    try:
        api = _WinAPI()
        if not root.is_absolute() or ".." in root.parts or str(root).startswith("\\\\"):
            raise WindowsPrivacyError("private_directory_invalid")
        for path in [*reversed(root.parents), root]:
            handles.append(api.guard(path))
        sid = api.current_sid()
        validate_sddl(api.security(root), sid, protected=True)
        info = root.stat(follow_symlinks=False)
        actual = (info.st_dev, info.st_ino)
        if identity is not None and identity != actual:
            raise WindowsPrivacyError("private_directory_changed")
        yield api, sid, actual
    except (OSError, AttributeError, ValueError):
        raise WindowsPrivacyError("private_acl_unverified") from None
    finally:
        if api is not None:
            for handle in reversed(handles):
                api.kernel.CloseHandle(handle)


def verify_directory(root: Path):
    with verified_directory(root) as (_, _, identity):
        return identity


def provision_private_directory(root: Path) -> None:
    """Explicit opt-in: create one new private directory; never chmod existing paths."""
    if not root.is_absolute() or ".." in root.parts or str(root).startswith("\\\\"):
        raise WindowsPrivacyError("private_directory_invalid")
    if root.exists() or root.is_symlink():
        raise WindowsPrivacyError("private_directory_exists")
    handles = []
    api = None
    try:
        api = _WinAPI()
        for path in reversed(root.parents):
            handles.append(api.guard(path))
        api.create_private_directory(root, api.current_sid())
        verify_directory(root)
    except (OSError, AttributeError, ValueError):
        raise WindowsPrivacyError("private_acl_unverified") from None
    finally:
        if api is not None:
            for handle in reversed(handles):
                api.kernel.CloseHandle(handle)
