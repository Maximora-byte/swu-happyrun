"""Bounded, non-authorizing discovery of original local state.

This module never opens SQLite, creates a host identity, acquires a writable lock,
or invokes MuMu. ``existing`` is an inventory result, NOT a claim that the current
SQL state/reservation is safe. A declaration of scan scope is not an approval pin.
The full dataclasses contain private paths; only ``public_summary`` is log-safe.
"""

import hashlib
import os
import re
import stat
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from swu_happyrun.drivers.command import ProbeError
from swu_happyrun.drivers.identity import _namespace_path, device_id

MAX_SCAN_ENTRIES = 450
MAX_SCAN_DEPTH = 4
MAX_SCAN_ROOTS = 32
_UNCHECKED = (
    "historical_launch_arguments",
    "historical_configuration_sources",
    "custom_roots_and_other_disks",
    "other_accounts",
    "legacy_writers",
)


@dataclass(frozen=True, repr=False)
class DiscoveryScope:
    roots: tuple[Path, ...]
    journal_arguments: tuple[Path, ...] = ()
    working_directories: tuple[Path, ...] = ()
    configuration_sources: tuple[Path, ...] = ()
    unchecked_categories: tuple[str, ...] = _UNCHECKED
    declared_complete: bool = False


@dataclass(frozen=True, repr=False)
class RootInspection:
    path: str
    identity_domain: str
    identity: tuple[int, int] | None
    entry_count: int
    file_count: int
    exclusions: tuple[str, ...]
    errors: tuple[str, ...]
    candidate_journals: tuple[str, ...]
    state_artifacts: tuple[str, ...]
    missing: bool = False


@dataclass(frozen=True, repr=False)
class EnrollmentInspection:
    status: str
    reasons: tuple[str, ...]
    roots: tuple[RootInspection, ...] = field(repr=False)
    identity_sources: dict = field(repr=False)
    scope: DiscoveryScope = field(repr=False)
    observed_at: str
    unchecked_categories: tuple[str, ...]
    host_id: str | None = field(default=None, repr=False)
    device_id: str | None = field(default=None, repr=False)
    runtime_state: str = "unverified"
    launch_allowed: bool = False

    def public_summary(self):
        return {
            "status": self.status,
            "reason_codes": self.reasons,
            "root_count": len(self.roots),
            "entries_checked": sum(root.entry_count for root in self.roots),
            "unchecked_category_count": len(self.unchecked_categories),
            "runtime_state": self.runtime_state,
            "launch_allowed": False,
        }


def _identity(info):
    return info.st_dev, info.st_ino


def _chain(path):
    if not path.is_absolute() or ".." in path.parts or str(path).startswith(("//", "\\\\")):
        raise ValueError("path_invalid")
    result = []
    for item in [*reversed(path.parents), path]:
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("path_redirected")
        if item != path and not stat.S_ISDIR(info.st_mode):
            raise ValueError("path_invalid")
        result.append((str(item), _identity(info)))
    return tuple(result)


def _read(path, cap, *, prefix=False):
    before = _chain(path)
    initial = path.lstat()
    if not stat.S_ISREG(initial.st_mode) or _identity(initial) != before[-1][1]:
        raise ValueError("file_kind_invalid")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or _identity(info) != before[-1][1]:
            raise ValueError("file_changed")
        if not prefix and info.st_size > cap:
            raise ValueError("file_oversized")
        value = os.read(fd, cap if prefix else cap + 1)
        after = os.fstat(fd)
        if (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ) or _chain(path) != before:
            raise ValueError("file_changed")
        if not prefix and (len(value) > cap or len(value) != info.st_size):
            raise ValueError("file_oversized")
        return value
    finally:
        os.close(fd)


def read_existing_host_id() -> str:
    """Read the authoritative existing namespace without implicit bootstrap."""
    try:
        value = _read(_namespace_path(), 128).decode("ascii").strip()
    except (OSError, ValueError, UnicodeError):
        raise ProbeError("host_identity_unavailable") from None
    try:
        if str(UUID(value)) != value:
            raise ValueError
    except ValueError:
        raise ProbeError("host_identity_invalid") from None
    return value


def _scan(root, budget=MAX_SCAN_ENTRIES):
    journals, artifacts, errors, exclusions = [], [], [], []
    entries = files = 0
    identity = None
    missing = False
    try:
        try:
            baseline = _chain(root)
        except FileNotFoundError:
            # Missing descendants are observations, not evidence of a complete
            # historical scope. Validate the nearest existing parent without writes.
            parent = root.parent
            while not parent.exists() and parent != parent.parent:
                parent = parent.parent
            _chain(parent)
            baseline = None
            missing = True
        if baseline is not None:
            root_info = root.lstat()
            if not stat.S_ISDIR(root_info.st_mode):
                raise ValueError("root_not_directory")
            identity = _identity(root_info)
            pending = [(root, 0)]
            while pending and entries < budget:
                directory, depth = pending.pop()
                directory_before = _chain(directory)
                directory_times = directory.stat()
                with os.scandir(directory) as iterator:
                    for entry in iterator:
                        entries += 1
                        path = Path(entry.path)
                        info = entry.stat(follow_symlinks=False)
                        if stat.S_ISLNK(info.st_mode) or (
                            getattr(info, "st_file_attributes", 0) & 0x400
                        ):
                            exclusions.append(str(path))
                            errors.append("path_redirected")
                        elif stat.S_ISDIR(info.st_mode):
                            if depth >= MAX_SCAN_DEPTH:
                                exclusions.append(str(path))
                                errors.append("scan_depth_reached")
                            else:
                                pending.append((path, depth + 1))
                        elif stat.S_ISREG(info.st_mode):
                            files += 1
                            name = path.name.lower()
                            if name.endswith((".sqlite", ".sqlite3", ".db")):
                                journals.append(str(path))
                            if (
                                name.startswith(("device-", "replay-", "enrollment-"))
                                or name.endswith(("-wal", "-shm", "-journal"))
                                or name == "mumu-experiment-registration.json"
                            ):
                                artifacts.append(str(path))
                        else:
                            exclusions.append(str(path))
                            errors.append("unsupported_file_kind")
                        if entries >= budget:
                            errors.append("scan_limit_reached")
                            break
                directory_after = directory.stat()
                if _chain(directory) != directory_before or (
                    directory_times.st_mtime_ns,
                    directory_times.st_ctime_ns,
                ) != (directory_after.st_mtime_ns, directory_after.st_ctime_ns):
                    errors.append("directory_changed")
            root_after = root.stat()
            if _chain(root) != baseline or (root_info.st_mtime_ns, root_info.st_ctime_ns) != (
                root_after.st_mtime_ns,
                root_after.st_ctime_ns,
            ):
                errors.append("root_changed")
    except PermissionError:
        errors.extend(("root_inspection_failed", "root_access_denied"))
    except (OSError, ValueError):
        errors.append("root_inspection_failed")
    return RootInspection(
        str(root),
        "python_stat",
        identity,
        entries,
        files,
        tuple(exclusions),
        tuple(sorted(set(errors))),
        tuple(journals),
        tuple(artifacts),
        missing,
    )


def inspect_enrollment(
    scope: DiscoveryScope,
    *,
    manager: Path,
    instance_index: str,
    expected_journal: Path | None = None,
) -> EnrollmentInspection:
    """Inspect a declared scope; no result grants initialization or execution.

    Explicit journal arguments and each known working directory's local directory
    join the scan roots. Historical configuration *contents* are not guessed or
    interpreted: the scope declaration must enumerate their effective paths.
    A missing selected historical journal is unknown, never a fresh namespace.
    """
    reasons = []
    host_value = product_id = None
    host = _namespace_path()
    default_root = Path(
        os.environ.get(
            "LOCALAPPDATA" if os.name == "nt" else "XDG_CONFIG_HOME",
            str(Path.home() / ("AppData/Local" if os.name == "nt" else ".config")),
        )
    )
    sources = {
        "host_path": str(host),
        "host_override": os.environ.get("SWU_HAPPYRUN_HOST_ID_FILE"),
        "default_host_path": str(default_root / "swu-happyrun/host-id"),
        "LOCALAPPDATA": os.environ.get("LOCALAPPDATA"),
        "XDG_CONFIG_HOME": os.environ.get("XDG_CONFIG_HOME"),
        "manager_path": str(manager),
        "instance_index": instance_index,
    }
    try:
        if type(instance_index) is not str or not re.fullmatch(
            r"0|[1-9][0-9]{0,8}", instance_index
        ):
            raise ValueError
        host_value = _read(host, 128).decode("ascii").strip()
        if str(UUID(host_value)) != host_value:
            raise ValueError
        _chain(manager)
        if not stat.S_ISREG(manager.lstat().st_mode):
            raise ValueError
        identifier = f"{os.path.normcase(str(manager.resolve()))}:{instance_index}"
        product_id = device_id("mumu", identifier, host_id=host_value)
        sources["host_identity_domain"] = "python_stat"
        sources["host_identity"] = _identity(host.lstat())
        sources["manager_identity"] = _identity(manager.lstat())
    except (OSError, ValueError, UnicodeError):
        reasons.append("identity_unavailable")
    unchecked = tuple(scope.unchecked_categories)
    if not scope.declared_complete or unchecked:
        reasons.append("historical_scope_incomplete")
    for config in scope.configuration_sources:
        try:
            _chain(config)
            if not stat.S_ISREG(config.lstat().st_mode):
                raise ValueError
        except (OSError, ValueError):
            reasons.append("configuration_source_unavailable")
    root_paths = [host.parent, default_root / "swu-happyrun", *scope.roots]
    root_paths.extend(Path(path).parent for path in scope.journal_arguments)
    root_paths.extend(Path(path) / "local" for path in scope.working_directories)
    if expected_journal is not None:
        root_paths.append(Path(expected_journal).parent)
    # Preserve lexical paths; resolving them could hide a symlink or path alias.
    root_paths = tuple(dict.fromkeys(Path(path) for path in root_paths))
    if not root_paths:
        reasons.append("scan_scope_empty")
    if len(root_paths) > MAX_SCAN_ROOTS:
        reasons.append("root_limit_reached")
        sources["omitted_roots"] = tuple(str(path) for path in root_paths[MAX_SCAN_ROOTS:])
        root_paths = root_paths[:MAX_SCAN_ROOTS]
    collected = []
    budget = MAX_SCAN_ENTRIES
    for root in root_paths:
        if budget <= 0:
            reasons.append("scan_limit_reached")
            collected.append(
                RootInspection(
                    str(root),
                    "python_stat",
                    None,
                    0,
                    0,
                    (str(root),),
                    ("scan_not_attempted",),
                    (),
                    (),
                )
            )
            continue
        observation = _scan(root, budget)
        budget -= observation.entry_count
        collected.append(observation)
    roots = tuple(collected)
    reasons.extend(error for root in roots for error in root.errors)
    journals = set(path for root in roots for path in root.candidate_journals)
    artifacts = set(path for root in roots for path in root.state_artifacts)
    if len(journals) > 1:
        reasons.append("multiple_journals")
    status = "unknown"
    if journals:
        selected = str(expected_journal) if expected_journal is not None else None
        if len(journals) != 1 or selected not in journals or product_id is None:
            reasons.append("journal_mapping_unverified")
        else:
            journal = Path(selected)
            lock = journal.parent / f"device-{hashlib.sha256(product_id.encode()).hexdigest()}.lock"
            try:
                header = _read(journal, 100, prefix=True)
                if (
                    len(header) != 100
                    or header[:16] != b"SQLite format 3\x00"
                    or header[18:20] != b"\x01\x01"
                ):
                    raise ValueError
                # Header checks reject obvious truncation/corruption without
                # claiming SQLite integrity or safe mutable runtime state.
                page_size = int.from_bytes(header[16:18], "big")
                page_size = 65536 if page_size == 1 else page_size
                size = journal.stat().st_size
                if (
                    page_size < 512
                    or page_size > 65536
                    or page_size & (page_size - 1)
                    or size < page_size
                    or size % page_size
                    or header[21:24] != bytes((64, 32, 32))
                ):
                    raise ValueError
                _chain(lock)
                if not stat.S_ISREG(lock.lstat().st_mode) or lock.stat().st_size != 1:
                    raise ValueError
                # No locks or mutable SQL rows are inspected or declared clear.
                if artifacts - {str(lock)}:
                    reasons.append("state_artifacts_require_review")
                if not reasons:
                    status = "existing"
            except (OSError, ValueError):
                reasons.append("historical_state_unverified")
    else:
        if expected_journal is not None or scope.journal_arguments:
            reasons.append("declared_journal_missing")
        if artifacts:
            reasons.append("orphan_state_artifacts")
        if not reasons:
            status = "first_use_review_required"
    if reasons:
        status = "unknown"
    return EnrollmentInspection(
        status,
        tuple(sorted(set(reasons))),
        roots,
        sources,
        scope,
        datetime.now(UTC).isoformat(),
        unchecked,
        host_value,
        product_id,
    )
