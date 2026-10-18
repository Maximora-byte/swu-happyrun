"""Persisted host namespace; device reads never reveal raw serials or local paths."""

import os
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from swu_happyrun.drivers.command import ProbeError


def _validate_host_id(value: str) -> str:
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError
    except ValueError:
        raise ProbeError("host_identity_invalid") from None
    return value


def _namespace_path() -> Path:
    override = os.environ.get("SWU_HAPPYRUN_HOST_ID_FILE")
    if override:
        return Path(override)
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "swu-happyrun" / "host-id"


def load_host_id(path: Path | None = None) -> str:
    """Create a random namespace once. Never rotate unreadable/corrupt identities.

    Exclusive creation prevents competing agents replacing an existing identity.
    A reader observing an incomplete concurrent write fails closed and may retry.
    All agents controlling one host must share this file, including overrides.
    """
    path = path if path is not None else _namespace_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("x", encoding="ascii", newline="\n") as file:
                file.write(str(uuid4()) + "\n")
                file.flush()
                os.fsync(file.fileno())
        except FileExistsError:
            pass
        return _validate_host_id(path.read_text(encoding="ascii").strip())
    except (OSError, UnicodeError):
        raise ProbeError("host_identity_unavailable") from None


def device_id(backend: str, identifier: str, *, host_id: str | None = None) -> str:
    namespace = load_host_id() if host_id is None else _validate_host_id(host_id)
    return str(uuid5(NAMESPACE_URL, f"swu-happyrun:{namespace}:{backend}:{identifier}"))
