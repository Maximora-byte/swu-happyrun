"""Read-only, deliberately restrictive Windows directory gate for one local probe.

No ACL provisioning. Held no-delete-sharing handles impede rename/deletion, not
WRITE_DAC or trusted-principal concurrency. This is not a universal TOCTOU guard.
Only bounded ordinary allow ACEs are supported; unsupported evidence is rejected.
The opt-in prepared_top_level layout checks the held NTFS volume root, the exact
protected prepared ACL, and the inherited private sample child independently.
"""

import ctypes as ct
import ntpath
import os
import re
import struct
from pathlib import Path

CHILD = "issue110-local-config-1"
FILTER_PROBE_CHILD = "issue110-filter-probe-1"
MAX_SECURITY = 65536
TRUSTED = {"S-1-5-18", "S-1-5-32-544"}
TRUSTED_INSTALLER = "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"


def components(value, *, mode="generic"):
    if mode not in ("generic", "prepared_top_level"):
        raise ValueError("private_path_unverified")
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z]:\\[-A-Za-z0-9_.\\]+", value):
        raise ValueError("private_path_unverified")
    pieces = value[3:].split("\\")
    if any(
        part in {"", ".", ".."}
        or part.endswith(".")
        or re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]", part.split(".")[0], re.I)
        for part in pieces
    ):
        raise ValueError("private_path_unverified")
    result = [value[:3]]
    for piece in pieces:
        result.append(ntpath.join(result[-1], piece))
    if mode == "prepared_top_level" and len(result) != 2:
        raise ValueError("private_path_unverified")
    return result


def _sid(data, offset, end):
    if not 0 <= offset <= end - 8 or data[offset] != 1 or data[offset + 1] > 15:
        raise ValueError("acl_unverified")
    length = 8 + 4 * data[offset + 1]
    if offset + length > end:
        raise ValueError("acl_unverified")
    raw = data[offset : offset + length]
    authority = int.from_bytes(raw[2:8], "big")
    parts = [str(struct.unpack_from("<I", raw, i)[0]) for i in range(8, length, 4)]
    return "-".join(["S", "1", str(authority), *parts]), raw


def _descriptor(data):
    if not isinstance(data, bytes) or not 20 <= len(data) <= MAX_SECURITY:
        raise ValueError("acl_unverified")
    revision, _, control, owner, group, sacl, dacl = struct.unpack_from("<BBHIIII", data)
    if revision != 1 or control & 0x8004 != 0x8004 or group or sacl or not owner or not dacl:
        raise ValueError("acl_unverified")
    if owner < 20 or owner % 4 or dacl < 20 or dacl % 4 or dacl + 8 > len(data):
        raise ValueError("acl_unverified")
    owner_sid, owner_raw = _sid(data, owner, len(data))
    revision, reserved, size, count, reserved2 = struct.unpack_from("<BBHHH", data, dacl)
    if (
        revision not in (2, 4)
        or reserved
        or reserved2
        or size < 8
        or size % 4
        or dacl + size > len(data)
        or not 1 <= count <= 64
    ):
        raise ValueError("acl_unverified")
    if not (owner + len(owner_raw) <= dacl or dacl + size <= owner):
        raise ValueError("acl_unverified")
    entries, sid_bytes = [], [owner_raw]
    cursor, end = dacl + 8, dacl + size
    for _ in range(count):
        if cursor + 8 > end:
            raise ValueError("acl_unverified")
        kind, flags, size = struct.unpack_from("<BBH", data, cursor)
        if kind != 0 or flags & ~0x1F or size < 16 or size % 4 or cursor + size > end:
            raise ValueError("acl_unverified")
        mask = struct.unpack_from("<I", data, cursor + 4)[0]
        trustee, raw = _sid(data, cursor + 8, cursor + size)
        if size != 8 + len(raw):
            raise ValueError("acl_unverified")
        entries.append((trustee, mask, flags))
        sid_bytes.append(raw)
        cursor += size
    return owner_sid, entries, sid_bytes


def check_descriptor(data, user_sid, *, private, prepared=False):
    owner, entries, _ = _descriptor(data)
    trusted = TRUSTED | {user_sid}
    if prepared and private:
        expected = {(who, 0x1F01FF, 3) for who in trusted}
        if (
            owner != user_sid
            or not struct.unpack_from("<H", data, 2)[0] & 0x1000
            or len(expected) != 3
            or len(entries) != 3
            or set(entries) != expected
        ):
            raise ValueError("acl_unverified")
    elif prepared:
        trusted = trusted | {TRUSTED_INSTALLER}
    if owner not in trusted:
        raise ValueError("acl_unverified")
    user_inheritance = False
    for trustee, mask, flags in entries:
        mapped = mask & 0x0FFFFFFF
        for generic, rights in (
            (0x80000000, 0x120089),
            (0x40000000, 0x120116),
            (0x20000000, 0x1200A0),
            (0x10000000, 0x1F01FF),
        ):
            if mask & generic:
                mapped |= rights
        if mapped & ~0x1F01FF:
            raise ValueError("acl_unverified")
        if trustee == user_sid and mapped == 0x1F01FF and flags & 3 == 3 and not flags & 12:
            user_inheritance = True
        ancestor_rights = 0x1200AD if prepared else 0x1200A9
        if trustee not in trusted and (private or (not flags & 8 and mapped & ~ancestor_rights)):
            raise ValueError("acl_unverified")
    if private and not user_inheritance:
        raise ValueError("acl_unverified")
    return True


class Native:
    """All native calls are lazy and read-only; off-Windows use is rejected."""

    def __init__(self):
        if os.name != "nt":
            raise ValueError("windows_required")
        self.kernel = ct.WinDLL("kernel32", use_last_error=True)
        self.advapi = ct.WinDLL("advapi32", use_last_error=True)
        P, U, B = ct.c_void_p, ct.c_uint32, ct.c_int32
        for dll, name, args, result in (
            (self.kernel, "CreateFileW", [ct.c_wchar_p, U, U, P, U, U, P], P),
            (self.kernel, "CloseHandle", [P], B),
            (self.kernel, "GetFileInformationByHandle", [P, P], B),
            (self.kernel, "GetFileInformationByHandleEx", [P, ct.c_int32, P, U], B),
            (
                self.kernel,
                "GetVolumeInformationByHandleW",
                [P, ct.c_wchar_p, U, P, P, P, ct.c_wchar_p, U],
                B,
            ),
            (self.kernel, "GetDriveTypeW", [ct.c_wchar_p], U),
            (self.kernel, "QueryDosDeviceW", [ct.c_wchar_p, ct.c_wchar_p, U], U),
            (self.kernel, "GetCurrentProcess", [], P),
            (self.kernel, "GetModuleFileNameW", [P, ct.c_wchar_p, U], U),
            (self.advapi, "OpenProcessToken", [P, U, P], B),
            (self.advapi, "GetTokenInformation", [P, ct.c_int32, P, U, P], B),
            (self.advapi, "GetKernelObjectSecurity", [P, U, P, U, P], B),
            (self.advapi, "IsValidSid", [P], B),
        ):
            function = getattr(dll, name)
            function.argtypes, function.restype = args, result
        token = P()
        self._require(
            self.advapi.OpenProcessToken(self.kernel.GetCurrentProcess(), 8, ct.byref(token))
        )
        completed = False
        try:
            needed = U()
            probe = self.advapi.GetTokenInformation(token, 1, None, 0, ct.byref(needed))
            if probe or ct.get_last_error() != 122 or not 16 <= needed.value <= MAX_SECURITY:
                raise ValueError("token_unverified")
            buffer = ct.create_string_buffer(needed.value)
            self._require(
                self.advapi.GetTokenInformation(token, 1, buffer, len(buffer), ct.byref(needed))
            )
            if not 16 <= needed.value <= len(buffer):
                raise ValueError("token_unverified")
            pointer = ct.c_void_p.from_buffer(buffer).value
            offset = (pointer or 0) - ct.addressof(buffer)
            if offset < 16:
                raise ValueError("token_unverified")
            self.user_sid, raw = _sid(buffer.raw[: needed.value], offset, needed.value)
            if not self.advapi.IsValidSid(ct.create_string_buffer(raw)):
                raise ValueError("token_unverified")
            completed = True
        finally:
            try:
                self.close(token)
            except Exception:
                if completed:
                    raise

    @staticmethod
    def _require(value):
        if not value:
            raise ct.WinError(ct.get_last_error())
        return value

    def open_directory(self, path):
        handle = self.kernel.CreateFileW(str(path), 0x20080, 3, None, 3, 0x02200000, None)
        if handle in (None, ct.c_void_p(-1).value):
            raise ct.WinError(ct.get_last_error())
        return handle

    def information(self, handle):
        # BY_HANDLE_FILE_INFORMATION is thirteen 32-bit DWORDs (52 bytes).
        info = (ct.c_uint32 * 13)()
        self._require(self.kernel.GetFileInformationByHandle(handle, info))
        return info[0], self.identity(handle)

    def identity(self, handle):
        info = ct.create_string_buffer(24)
        self._require(self.kernel.GetFileInformationByHandleEx(handle, 18, info, len(info)))
        return struct.unpack_from("<Q", info.raw)[0], info.raw[8:24]

    def file_identity(self, path):
        handle = self.open_directory(path)
        completed = False
        try:
            attributes, identity = self.information(handle)
            if attributes & (0x10 | 0x400):
                raise ValueError("interpreter_identity_unverified")
            completed = True
            return identity
        finally:
            try:
                self.close(handle)
            except Exception:
                if completed:
                    raise

    def drive_mapping(self, root):
        if self.kernel.GetDriveTypeW(root) != 3:
            raise ValueError("drive_mapping_unverified")
        buffer = ct.create_unicode_buffer(32768)
        length = self.kernel.QueryDosDeviceW(root[:2], buffer, len(buffer))
        if not 0 < length < len(buffer):
            raise ValueError("drive_mapping_unverified")
        text = buffer[:length]
        if not text.endswith("\0") or not re.fullmatch(
            r"\\Device\\HarddiskVolume[0-9]+", text.rstrip("\0")
        ):
            raise ValueError("drive_mapping_unverified")
        return text.rstrip("\0")

    def volume(self, handle):
        name, flags = ct.create_unicode_buffer(32), ct.c_uint32()
        if (
            not self.kernel.GetVolumeInformationByHandleW(
                handle, None, 0, None, None, ct.byref(flags), name, len(name)
            )
            or name.value != "NTFS"
            or not flags.value & 8  # FILE_PERSISTENT_ACLS
        ):
            raise ValueError("private_directory_unverified")

    def inspect(self, handle):
        attributes, identity = self.information(handle)
        needed = ct.c_uint32()
        probe = self.advapi.GetKernelObjectSecurity(handle, 5, None, 0, ct.byref(needed))
        if probe or ct.get_last_error() != 122 or not 20 <= needed.value <= MAX_SECURITY:
            raise ValueError("acl_unverified")
        buffer = ct.create_string_buffer(needed.value)
        self._require(
            self.advapi.GetKernelObjectSecurity(handle, 5, buffer, len(buffer), ct.byref(needed))
        )
        if not 20 <= needed.value <= len(buffer):
            raise ValueError("acl_unverified")
        data = buffer.raw[: needed.value]
        for raw in _descriptor(data)[2]:
            if not self.advapi.IsValidSid(ct.create_string_buffer(raw)):
                raise ValueError("acl_unverified")
        return attributes, identity, data

    def module_path(self, handle):
        buffer = ct.create_unicode_buffer(32768)
        length = self.kernel.GetModuleFileNameW(handle, buffer, len(buffer))
        if not 0 < length < len(buffer):
            raise ValueError("interpreter_identity_unverified")
        return buffer.value

    def close(self, handle):
        self._require(self.kernel.CloseHandle(handle))


class PrivateDirectory:
    def __init__(
        self, root, api, *, forbidden_identity=None, mode="generic", child_role="sample_child"
    ):
        if child_role not in {"sample_child", "filter_probe"} or (
            child_role == "filter_probe" and mode != "prepared_top_level"
        ):
            raise ValueError("private_directory_unverified")
        self.components = components(root, mode=mode)
        self.roles = (
            ("volume_root", "prepared_private_root")
            if mode == "prepared_top_level"
            else tuple(
                "private" if index == len(self.components) - 1 else "ancestor"
                for index in range(len(self.components))
            )
        )
        child = FILTER_PROBE_CHILD if child_role == "filter_probe" else CHILD
        self.path = Path(ntpath.join(root, child))
        self.child_role = child_role
        self.api = api
        self.forbidden_identity = forbidden_identity
        self.handles = []

    def _check(self, handle, role):
        if role not in (
            "ancestor",
            "private",
            "volume_root",
            "prepared_private_root",
            "sample_child",
            "filter_probe",
        ):
            raise ValueError("private_directory_unverified")
        attributes, identity, data = self.api.inspect(handle)
        if not attributes & 0x10 or attributes & 0x400 or identity == self.forbidden_identity:
            raise ValueError("private_directory_unverified")
        if role == "volume_root":
            self.api.volume(handle)
        check_descriptor(
            data,
            self.api.user_sid,
            private=role in {"private", "prepared_private_root", "sample_child", "filter_probe"},
            prepared=role in {"volume_root", "prepared_private_root"},
        )
        return identity

    def __enter__(self):
        completed = False
        try:
            self.mapping = self.api.drive_mapping(self.components[0])
            for component, role in zip(self.components, self.roles, strict=True):
                handle = self.api.open_directory(component)
                self.handles.append((handle, None, role))
                identity = self._check(handle, role)
                self.handles[-1] = (handle, identity, role)
            os.mkdir(
                str(self.path)
            )  # Exclusive fixed child, inherited ACL, no fallback or removal.
            handle = self.api.open_directory(str(self.path))
            self.handles.append((handle, None, self.child_role))
            identity = self._check(handle, self.child_role)
            self.handles[-1] = (handle, identity, self.child_role)
            self.revalidate()
            completed = True
            return self
        finally:
            if not completed:
                self.__exit__(Exception, None, None)

    def revalidate(self):
        if self.api.drive_mapping(self.components[0]) != self.mapping:
            raise ValueError("drive_mapping_unverified")
        for handle, identity, role in self.handles:
            if self._check(handle, role) != identity:
                raise ValueError("private_directory_unverified")

    def __exit__(self, kind, error, traceback):
        failure = None
        for handle, _, _ in reversed(self.handles):
            try:
                self.api.close(handle)
            except Exception as close_error:
                if failure is None:
                    failure = close_error
        self.handles.clear()
        if kind is None and failure is not None:
            raise failure
        return False
