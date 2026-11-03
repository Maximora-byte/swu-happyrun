"""Bounded legacy-state admission for the separate, local-only trajectory tool.

Old physical writers are closed in this release. Reopening one requires a shared
physical guard and migration. Existing registered/custom runtime state is never
silently adopted or repaired by this tool.
"""

import json
import os
import re
import stat
from itertools import islice
from pathlib import Path
from uuid import UUID, uuid4

from swu_happyrun.desktop.workspace import _check_path
from swu_happyrun.drivers.command import ProbeError
from swu_happyrun.drivers.identity import _namespace_path, _validate_host_id, load_host_id


def host_namespace():
    from swu_happyrun.drivers.mumu.enrollment import _local_app_data

    default = (
        _local_app_data() / "swu-happyrun" / "host-id" if os.name == "nt" else _namespace_path()
    )
    selected = _namespace_path().absolute()
    _check_path(selected)
    _check_path(default)
    if os.environ.get("SWU_HAPPYRUN_HOST_ID_FILE"):
        try:
            value = _validate_host_id(selected.read_text(encoding="ascii").strip())
            if (
                default.exists()
                and _validate_host_id(default.read_text(encoding="ascii").strip()) != value
            ):
                raise ProbeError("host_namespace_conflict")
        except (OSError, UnicodeError):
            raise ProbeError("host_identity_unavailable") from None
        return value, selected
    # First-use creation is only at the original default; no unreadable identity
    # is replaced and changing --data-dir cannot select another namespace.
    return load_host_id(default), default


def _binding_path(path):
    path = Path(path).absolute()
    _check_path(path)
    normalized = Path(os.path.normcase(str(path.resolve())))
    _check_path(normalized)
    return normalized


def _strict_binding_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError

    _check_path(path)
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 4096:
        raise ValueError
    with path.open("rb") as stream:
        raw = stream.read(4097)
    if len(raw) > 4096:
        raise ValueError
    return json.loads(raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=reject_constant)


def _read_host_binding(path):
    try:
        value = _strict_binding_json(path)
        if (
            type(value) is not dict
            or set(value) != {"schema", "namespace", "namespace_file", "manager_path"}
            or type(value["schema"]) is not int
            or value["schema"] != 1
            or type(value["namespace"]) is not str
            or str(UUID(value["namespace"])) != value["namespace"]
            or any(
                type(value[key]) is not str
                or not Path(value[key]).is_absolute()
                or str(_binding_path(value[key])) != value[key]
                for key in ("namespace_file", "manager_path")
            )
        ):
            raise ValueError
    except (OSError, ValueError, TypeError, AttributeError):
        raise ProbeError("host_binding_invalid") from None
    # This check MUST precede host_namespace(), whose default path may create a
    # missing identity. Losing the original pinned source never rotates identity.
    source = Path(value["namespace_file"])
    try:
        _check_path(source)
        metadata = source.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 256:
            raise ValueError
        with source.open("rb") as stream:
            raw = stream.read(257)
        if len(raw) > 256:
            raise ValueError
        namespace = _validate_host_id(raw.decode("ascii").strip())
        if namespace != value["namespace"]:
            raise ValueError
    except (OSError, ValueError, UnicodeError, ProbeError):
        raise ProbeError("host_identity_unavailable") from None
    return value, source


def _allow_initial_host_binding(root):
    """Only strictly stopped, attributable own replay state can predate a pin."""
    try:
        entries = list(islice(root.iterdir(), 1001))
        if len(entries) > 1000:
            raise ValueError
        markers = []
        locks = []
        has_journal = False
        for entry in entries:
            _check_path(entry)
            name = entry.name
            lower = name.lower()
            if lower.startswith("replay-"):
                match = re.fullmatch(r"replay-([0-9a-f]{64})\.json", name)
                value = _strict_binding_json(entry)
                if (
                    match is None
                    or type(value) is not dict
                    or set(value)
                    != {
                        "schema",
                        "owner",
                        "device_digest",
                        "session_id",
                        "status",
                        "generation",
                        "probe_pending",
                    }
                    or type(value["schema"]) is not int
                    or value["schema"] != 1
                    or value["owner"] != "local_virtual_replay"
                    or value["device_digest"] != match[1]
                    or value["status"] != "stopped"
                    or type(value["session_id"]) is not str
                    or str(UUID(value["session_id"])) != value["session_id"]
                    or type(value["generation"]) is not int
                    or value["generation"] < 1
                    or value["probe_pending"] is not False
                ):
                    raise ValueError
                markers.append(match[1])
            elif lower.startswith("device-"):
                match = re.fullmatch(r"device-([0-9a-f]{64})\.lock", name)
                if match is None or not stat.S_ISREG(entry.lstat().st_mode):
                    raise ValueError
                locks.append(match[1])
            elif lower.startswith("journal.sqlite"):
                if name not in {
                    "journal.sqlite",
                    "journal.sqlite-wal",
                    "journal.sqlite-shm",
                    "journal.sqlite-journal",
                } or not stat.S_ISREG(entry.lstat().st_mode):
                    raise ValueError
                has_journal = True
            elif lower.endswith((".sqlite", ".sqlite3", ".db")):
                raise ValueError
        if ((has_journal or locks) and not markers) or not set(locks).issubset(markers):
            raise ValueError
    except (OSError, ValueError, TypeError, AttributeError):
        raise ProbeError("host_binding_missing") from None


def pinned_host_namespace(current_root, manager_path):
    """Immutably bind the canonical journal to its original host source and manager."""
    try:
        root = _binding_path(current_root)
        manager = _binding_path(manager_path)
        pin = root / "host-binding.json"
        _check_path(pin)
    except (OSError, ValueError):
        raise ProbeError("host_binding_invalid") from None
    try:
        pin.lstat()
        pin_exists = True
    except FileNotFoundError:
        pin_exists = False
    except OSError:
        raise ProbeError("host_binding_invalid") from None
    if pin_exists:
        existing, source = _read_host_binding(pin)
        # Reject a newly selected path before host_namespace can create a new
        # default identity. A copied UUID at a different source is migration.
        try:
            from swu_happyrun.drivers.mumu.enrollment import _local_app_data

            selected = (
                _namespace_path()
                if os.environ.get("SWU_HAPPYRUN_HOST_ID_FILE") or os.name != "nt"
                else _local_app_data() / "swu-happyrun" / "host-id"
            )
            if (
                str(_binding_path(selected)) != existing["namespace_file"]
                or str(manager) != existing["manager_path"]
            ):
                raise ProbeError("host_binding_changed")
        except (OSError, ValueError):
            raise ProbeError("host_binding_changed") from None
    else:
        _allow_initial_host_binding(root)
        existing = source = None
    namespace, actual_source = host_namespace()
    try:
        actual_source = _binding_path(actual_source)
    except (OSError, ValueError):
        raise ProbeError("host_identity_unavailable") from None
    expected = {
        "schema": 1,
        "namespace": namespace,
        "namespace_file": str(actual_source),
        "manager_path": str(manager),
    }
    if existing is not None:
        if existing != expected:
            raise ProbeError("host_binding_changed")
        return namespace, source
    raw = json.dumps(expected, sort_keys=True, separators=(",", ":")).encode("utf-8")
    try:
        with pin.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        # A racing writer owns the pin; partial/corrupt reads fail closed.
        existing, source = _read_host_binding(pin)
        if existing != expected:
            raise ProbeError("host_binding_changed") from None
        return namespace, source
    except OSError:
        raise ProbeError("host_binding_invalid") from None
    return namespace, actual_source


def legacy_roots(namespace_file):
    roots = {namespace_file.parent, Path.cwd() / "local"}
    source = Path(__file__).resolve().parents[3]
    roots.add(source / "local")
    git = source / ".git"
    if git.is_file():
        try:
            text = git.read_text(encoding="utf-8").strip()
            if text.startswith("gitdir: "):
                directory = Path(text[8:]).resolve()
                common_file = directory / "commondir"
                common = (directory / common_file.read_text(encoding="utf-8").strip()).resolve()
                roots.add(common.parent / "local")
        except (OSError, UnicodeError):
            raise ProbeError("legacy_scope_unavailable") from None
    return tuple(roots)


def require_clean_legacy_scope(roots, *, current_root):
    """Read direct default state only; test temp trees are intentionally excluded.

    Any legacy SQLite journal is unsupported until independently migrated, even
    if its attribution/intent status cannot be determined. Explicit legacy
    enrollment/configuration likewise blocks. This is not an all-disks census.
    """
    for root in roots:
        root = Path(root).absolute()
        if root == current_root.absolute():
            continue
        _check_path(root)
        if not root.exists():
            continue
        try:
            entries = list(root.iterdir())
            if len(entries) > 1000:
                raise ProbeError("legacy_scope_unavailable")
            for entry in entries:
                name = entry.name.lower()
                if (
                    name
                    in {
                        "mumu-experiment-registration.json",
                        "control-v1",
                        "agent.json",
                        "agent-config.json",
                        "reviewed-scope-v1.json",
                    }
                    or name.endswith((".sqlite", ".sqlite3", ".db"))
                    or name.startswith(("replay-", "device-"))
                ):
                    raise ProbeError("legacy_runtime_requires_review")
        except OSError:
            raise ProbeError("legacy_scope_unavailable") from None


def remember_legacy_roots(current_root, roots):
    """Retain discovered default roots when switching source/package launches."""
    path = current_root / "legacy-roots.json"
    lock = current_root / "legacy-roots.lock"
    _check_path(path)
    _check_path(lock)
    with lock.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            known = set()
            if path.exists():
                if path.stat().st_size > 32768:
                    raise ProbeError("legacy_scope_unavailable")
                try:
                    value = json.loads(path.read_bytes())
                    if (
                        type(value) is not dict
                        or set(value) != {"schema", "roots"}
                        or type(value["schema"]) is not int
                        or value["schema"] != 1
                        or type(value["roots"]) is not list
                        or len(value["roots"]) > 32
                        or any(
                            type(item) is not str or not Path(item).is_absolute()
                            for item in value["roots"]
                        )
                    ):
                        raise ValueError
                    known.update(Path(item) for item in value["roots"])
                except (ValueError, TypeError, UnicodeError):
                    raise ProbeError("legacy_scope_unavailable") from None
            known.update(Path(item).absolute() for item in roots)
            if len(known) > 32:
                raise ProbeError("legacy_scope_unavailable")
            for item in known:
                _check_path(item)
            temporary = current_root / ("legacy-roots-" + str(uuid4()) + ".tmp")
            try:
                with temporary.open("x", encoding="utf-8") as output:
                    json.dump({"schema": 1, "roots": sorted(map(str, known))}, output)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
            return tuple(known)
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
