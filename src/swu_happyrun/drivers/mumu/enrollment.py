"""Fixed control-root discovery and a fail-closed production admission boundary.

This first batch deliberately issues no execution capability. A design review,
static identity, original schema1 receipt, callable guard, or caller JSON is not
an independently pinned instance approval. Transactions and pin validation are
separate work. Do not turn inspection success into a permit here.
"""

import ctypes
import os
from pathlib import Path
from uuid import UUID

from swu_happyrun.drivers.base import DriverError


def _local_app_data() -> Path:
    """Read current-user Known Folder; no environment fallback and no creation."""
    if os.name != "nt":
        raise DriverError("enrollment_platform_unsupported")
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [
            ("data1", wintypes.DWORD),
            ("data2", wintypes.WORD),
            ("data3", wintypes.WORD),
            ("data4", ctypes.c_ubyte * 8),
        ]

    folder = GUID.from_buffer_copy(UUID("f1b32785-6fba-4fcf-9d55-7b8e7f157091").bytes_le)
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    ole = ctypes.WinDLL("ole32", use_last_error=True)
    query = shell.SHGetKnownFolderPath
    query.argtypes = [
        ctypes.POINTER(GUID),
        wintypes.DWORD,
        wintypes.HANDLE,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    query.restype = ctypes.c_long
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole.CoTaskMemFree.restype = None
    pointer = ctypes.c_void_p()
    try:
        if query(ctypes.byref(folder), 0, None, ctypes.byref(pointer)) != 0 or not pointer.value:
            raise DriverError("enrollment_control_root_unavailable")
        value = ctypes.wstring_at(pointer.value)
        path = Path(value)
        if not path.is_absolute() or value.startswith(("\\\\", "//")) or ".." in path.parts:
            raise DriverError("enrollment_control_root_unavailable")
        return path
    finally:
        if pointer.value:
            ole.CoTaskMemFree(pointer)


def resolve_control_root() -> Path:
    """Return the fixed location only, NOT ACL/NTFS validation or authority.

    Does not mkdir, open SQLite, acquire/create a lock, query a device, or accept
    any caller-supplied root. The future admission phase must validate the entire
    existing path chain, local NTFS and private ACL before mutable use.
    """
    return _local_app_data() / "swu-happyrun" / "control-v1"


def require_native_enrollment(candidate=None) -> None:
    """No production capability issuer exists in this inspection-only batch.

    Always reject, including a valid original schema1 snapshot. There is no
    environment flag, CLI argument, dictionary, boolean or synthetic permit.
    Must run before host bootstrap, mkdir, RunJournal/SQLite or native commands.
    Never insert this new-start gate into an already-started cleanup finally.
    """
    raise DriverError("enrollment_execution_not_ready")
