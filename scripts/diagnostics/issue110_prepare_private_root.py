"""One explicit Windows private-directory preparation, not evidence collection.

Run with CPython x64 -I -S -B. This creates only one new top-level directory,
with a protected DACL supplied to CreateDirectoryW. No repair, retry, cleanup
of filesystem residue, receipt files, or observer integration. Trusted-owner
concurrency is not eliminated by held no-delete-sharing handles. An interruption
can leave a directory behind; absence of a success report never permits retry.
"""

import argparse
import ctypes as ct
import hashlib
import json
import os
import platform
import struct
import sys
import types
from pathlib import Path

HELPER_SHA256 = "e48d7aa1a4b0a9c2e209b6a027c587b5a6ec353fc2e11e15aba1fb60eba4e388"
TRUSTED_INSTALLER = "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"
FULL = 0x1F01FF


def runtime_valid():
    return (
        os.name == "nt"
        and sys.implementation.name == "cpython"
        and ct.sizeof(ct.c_void_p) == 8
        and platform.machine().upper() == "AMD64"
        and sys.flags.isolated == 1
        and sys.flags.no_site == 1
        and sys.dont_write_bytecode
    )


def load_helper():
    path = Path(__file__).with_name("issue110_local_acl.py")
    stream = path.open("rb")
    completed = False
    try:
        source = stream.read(65537)
        if len(source) > 65536:
            raise ValueError("helper_rejected")
        completed = True
    finally:
        try:
            stream.close()
        except Exception:
            if completed:
                raise
    if hashlib.sha256(source).hexdigest() != HELPER_SHA256:
        raise ValueError("helper_rejected")
    module = types.ModuleType("_issue110_pinned_readonly_acl")
    exec(compile(source, str(path), "exec"), module.__dict__)
    return module


def mapped_rights(mask):
    mapped = mask & 0x0FFFFFFF
    for generic, rights in (
        (0x80000000, 0x120089),
        (0x40000000, 0x120116),
        (0x20000000, 0x1200A0),
        (0x10000000, FULL),
    ):
        if mask & generic:
            mapped |= rights
    if mapped & ~FULL:
        raise ValueError("acl_rejected")
    return mapped


def check_descriptor(helper, data, user, *, private):
    owner, entries, _ = helper._descriptor(data)
    trusted = helper.TRUSTED | {user, TRUSTED_INSTALLER}
    if private:
        control = struct.unpack_from("<H", data, 2)[0]
        expected = {(user, FULL, 3), ("S-1-5-18", FULL, 3), ("S-1-5-32-544", FULL, 3)}
        if (
            owner != user
            or not control & 0x1000
            or len(entries) != 3
            or len(expected) != 3
            or set(entries) != expected
        ):
            raise ValueError("acl_rejected")
    elif owner not in trusted:
        raise ValueError("acl_rejected")
    for trustee, mask, flags in entries:
        mapped = mapped_rights(mask)
        # IO entries do not affect the root, but must still parse and map safely.
        if not private and trustee not in trusted and not flags & 8 and mapped & ~0x1200AD:
            raise ValueError("acl_rejected")


def build_descriptor(helper, user):
    def encode_sid(value):
        parts = value.split("-")
        if len(parts) < 4 or parts[:2] != ["S", "1"] or len(parts) > 18:
            raise ValueError("identity_rejected")
        raw = bytes([1, len(parts) - 3]) + int(parts[2]).to_bytes(6, "big")
        raw += b"".join(struct.pack("<I", int(part)) for part in parts[3:])
        if helper._sid(raw, 0, len(raw))[0] != value:
            raise ValueError("identity_rejected")
        return raw

    if user in helper.TRUSTED | {TRUSTED_INSTALLER}:
        raise ValueError("identity_rejected")
    owner = encode_sid(user)
    aces = b""
    for trustee in (user, "S-1-5-18", "S-1-5-32-544"):
        raw = encode_sid(trustee)
        aces += struct.pack("<BBHI", 0, 3, 8 + len(raw), FULL) + raw
    acl = struct.pack("<BBHHH", 2, 0, 8 + len(aces), 3, 0) + aces
    data = struct.pack("<BBHIIII", 1, 0, 0x9004, 20, 0, 0, 20 + len(owner)) + owner + acl
    check_descriptor(helper, data, user, private=True)
    return data


class SecurityAttributes(ct.Structure):
    _fields_ = [
        ("nLength", ct.c_uint32),
        ("lpSecurityDescriptor", ct.c_void_p),
        ("bInheritHandle", ct.c_int32),
    ]


class Native:
    def __init__(self, helper):
        self.helper = helper
        self.cleanup_failed = False
        self.kernel = ct.WinDLL("kernel32", use_last_error=True)
        self.advapi = ct.WinDLL("advapi32", use_last_error=True)
        P, U, B = ct.c_void_p, ct.c_uint32, ct.c_int32
        for dll, name, args, result in (
            (self.kernel, "GetCurrentThread", [], P),
            (self.kernel, "GetCurrentProcess", [], P),
            (self.kernel, "CloseHandle", [P], B),
            (self.kernel, "CreateDirectoryW", [ct.c_wchar_p, ct.POINTER(SecurityAttributes)], B),
            (
                self.kernel,
                "GetVolumeInformationByHandleW",
                [P, ct.c_wchar_p, U, P, P, P, ct.c_wchar_p, U],
                B,
            ),
            (self.advapi, "OpenThreadToken", [P, U, B, P], B),
            (self.advapi, "OpenProcessToken", [P, U, P], B),
            (self.advapi, "GetTokenInformation", [P, ct.c_int32, P, U, P], B),
            (self.advapi, "IsValidSid", [P], B),
            (self.advapi, "IsValidSecurityDescriptor", [P], B),
        ):
            function = getattr(dll, name)
            function.argtypes, function.restype = args, result
        self.user_sid = self.effective_user()
        self.reader = helper.Native()
        if self.reader.user_sid != self.user_sid:
            raise ValueError("identity_rejected")

    def _close_token(self, token, *, completed):
        try:
            self.close(token)
        except Exception:
            self.cleanup_failed = True
            if completed:
                raise

    def effective_user(self):
        token = ct.c_void_p()
        if self.advapi.OpenThreadToken(self.kernel.GetCurrentThread(), 8, True, ct.byref(token)):
            try:
                raise ValueError("impersonation_rejected")
            finally:
                self._close_token(token, completed=False)
        if ct.get_last_error() != 1008:
            raise ValueError("identity_rejected")
        if not self.advapi.OpenProcessToken(self.kernel.GetCurrentProcess(), 8, ct.byref(token)):
            raise ValueError("identity_rejected")
        completed = False
        try:
            kind, needed = ct.c_uint32(), ct.c_uint32()
            if (
                not self.advapi.GetTokenInformation(token, 8, ct.byref(kind), 4, ct.byref(needed))
                or needed.value != 4
                or kind.value != 1
            ):
                raise ValueError("identity_rejected")
            probe = self.advapi.GetTokenInformation(token, 1, None, 0, ct.byref(needed))
            if probe or ct.get_last_error() != 122 or not 16 <= needed.value <= 65536:
                raise ValueError("identity_rejected")
            buffer = ct.create_string_buffer(needed.value)
            if not self.advapi.GetTokenInformation(
                token, 1, buffer, len(buffer), ct.byref(needed)
            ) or not 16 <= needed.value <= len(buffer):
                raise ValueError("identity_rejected")
            offset = (ct.c_void_p.from_buffer(buffer).value or 0) - ct.addressof(buffer)
            if offset < 16:
                raise ValueError("identity_rejected")
            user, raw = self.helper._sid(buffer.raw[: needed.value], offset, needed.value)
            if not self.advapi.IsValidSid(
                ct.create_string_buffer(raw)
            ) or user in self.helper.TRUSTED | {TRUSTED_INSTALLER}:
                raise ValueError("identity_rejected")
            completed = True
            return user
        finally:
            self._close_token(token, completed=completed)

    def volume(self, handle):
        name, flags = ct.create_unicode_buffer(32), ct.c_uint32()
        if (
            not self.kernel.GetVolumeInformationByHandleW(
                handle, None, 0, None, None, ct.byref(flags), name, len(name)
            )
            or name.value != "NTFS"
            or not flags.value & 8
        ):
            raise ValueError("volume_rejected")

    def descriptor(self, user):
        data = build_descriptor(self.helper, user)
        if not self.advapi.IsValidSecurityDescriptor(ct.create_string_buffer(data)):
            raise ValueError("descriptor_rejected")
        return data

    def create(self, path, descriptor):
        buffer = ct.create_string_buffer(descriptor)
        attributes = SecurityAttributes(ct.sizeof(SecurityAttributes), ct.addressof(buffer), False)
        succeeded = bool(self.kernel.CreateDirectoryW(path, ct.byref(attributes)))
        return succeeded, 0 if succeeded else ct.get_last_error()

    def drive_mapping(self, root):
        return self.reader.drive_mapping(root)

    def open_directory(self, path):
        return self.reader.open_directory(path)

    def inspect(self, handle):
        return self.reader.inspect(handle)

    def close(self, handle):
        if not self.kernel.CloseHandle(handle):
            raise ValueError("cleanup_failed")


def prepare(path):
    result = {
        "status": "preflight_failed",
        "creation_attempted": False,
        "creation_succeeded": False,
        "verified": False,
        "cleanup": "complete",
    }
    handles, api = [], None
    try:
        if not runtime_valid():
            result["status"] = "runtime_rejected"
            return result
        helper = load_helper()
        pieces = helper.components(path)
        if len(pieces) != 2 or len(pieces[1][3:]) > 255:
            raise ValueError("path_rejected")
        result["cleanup"] = "unknown"
        api = Native(helper)
        result["cleanup"] = "complete"
        user = api.user_sid
        mapping = api.drive_mapping(pieces[0])
        root = api.open_directory(pieces[0])
        handles.append(root)
        api.volume(root)

        def inspect(handle, private):
            attributes, identity, data = api.inspect(handle)
            if not attributes & 0x10 or attributes & 0x400:
                raise ValueError("directory_rejected")
            check_descriptor(helper, data, user, private=private)
            return identity

        root_id = inspect(root, False)
        descriptor = api.descriptor(user)
        if (
            api.drive_mapping(pieces[0]) != mapping
            or inspect(root, False) != root_id
            or api.effective_user() != user
        ):
            raise ValueError("preflight_changed")
        result["creation_attempted"] = True
        result["creation_succeeded"] = "unknown"
        result["status"] = "creation_unknown"
        succeeded, error = api.create(path, descriptor)
        result["creation_succeeded"] = succeeded
        if not succeeded:
            result["status"] = "already_exists" if error in (80, 183) else "creation_failed"
            return result
        result["status"] = "verification_failed"
        child = api.open_directory(path)
        handles.append(child)
        child_id = inspect(child, True)
        if (
            child_id == root_id
            or api.drive_mapping(pieces[0]) != mapping
            or inspect(root, False) != root_id
            or inspect(child, True) != child_id
            or api.effective_user() != user
        ):
            raise ValueError("verification_changed")
        result["verified"] = True
        result["status"] = "prepared"
    except Exception:
        pass  # Fixed enums only, never raw native errors, paths or SIDs.
    finally:
        close_failed = False
        for handle in reversed(handles):
            result["cleanup"] = "unknown"
            try:
                api.close(handle)
            except Exception:
                close_failed = True
        if handles:
            result["cleanup"] = "failed" if close_failed else "complete"
        if api is not None and api.cleanup_failed:
            result["cleanup"] = "failed"
        if result["cleanup"] != "complete" and result["status"] == "prepared":
            result["status"] = "cleanup_failed"
    return result


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "argument_rejected\n")


def main(argv=None):
    parser = SafeParser(description=__doc__)
    parser.add_argument("--private-root", required=True)
    args = parser.parse_args(argv)
    result = prepare(args.private_root)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "prepared" else 1


if __name__ == "__main__":
    raise SystemExit(main())
