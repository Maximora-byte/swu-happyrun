"""Fixed-policy metadata inventory with bounded membership revalidation.

Neither continuation state nor an adjustable scan policy is accepted from an
operator. Discovery, descent, root-final and scope-final membership observations
share one fixed metadata-work allowance; exhaustion is always incomplete. No
journal or other file contents are opened and no observation authorizes a run.
"""

import os
import stat
from dataclasses import dataclass, field, replace
from pathlib import Path

from .enrollment_inspection import RootInspection, _identity

PAGE_ENTRIES = 450
MAX_PAGES = 64
MAX_ENTRIES = PAGE_ENTRIES * MAX_PAGES
MAX_DEPTH = 8


class _WorkLimit(ValueError):
    def __init__(self):
        super().__init__("scan_limit_reached")


@dataclass(repr=False)
class _ScanSession:
    """Internal inspection-owned accounting, never a public resume cursor."""

    live_staging: tuple = ()
    work_used: int = 0
    logical_entries: int = 0
    observations: list = field(default_factory=list)
    failures: dict = field(default_factory=dict)
    finalized: bool = False

    @property
    def exhausted(self):
        return self.work_used >= MAX_ENTRIES

    def charge(self):
        if self.exhausted:
            raise _WorkLimit()
        self.work_used += 1

    def fail(self, root, code, path):
        codes, paths = self.failures.setdefault(str(root), (set(), set()))
        codes.add(code)
        paths.add(str(path))


@dataclass(frozen=True, repr=False)
class _Directory:
    path: Path
    depth: int
    chain: tuple
    times: tuple[int, int]
    # None means a metadata-only ancestor of a missing root, not a scoped root.
    members: tuple | None = None


@dataclass(frozen=True, repr=False)
class _Missing:
    path: Path


class _Entries:
    """Charge every open/next attempt, including EOF; always permit cleanup."""

    def __init__(self, path, session):
        self.session = session
        session.charge()
        self.iterator = os.scandir(path)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __iter__(self):
        return self

    def __next__(self):
        self.session.charge()
        return next(self.iterator)

    def close(self):
        self.iterator.close()


def _payload_entries(directory, session):
    """Actual inventory descent, distinct from membership-only observations."""
    return _Entries(directory.path, session)


def _lstat(path, session):
    session.charge()
    return path.lstat()


def _chain(path, session):
    if not path.is_absolute() or ".." in path.parts or str(path).startswith(("//", "\\\\")):
        raise ValueError("path_invalid")
    result = []
    for item in [*reversed(path.parents), path]:
        info = _lstat(item, session)
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("path_redirected")
        if item != path and not stat.S_ISDIR(info.st_mode):
            raise ValueError("path_invalid")
        result.append((str(item), _identity(info)))
    return tuple(result)


def _times(info):
    return info.st_mtime_ns, info.st_ctime_ns


def _capture(path, depth, session, discovered=None):
    chain = _chain(path, session)
    info = _lstat(path, session)
    if (
        not stat.S_ISDIR(info.st_mode)
        or getattr(info, "st_file_attributes", 0) & 0x400
        or _identity(info) != chain[-1][1]
        or (
            discovered is not None
            and (_identity(info), _times(info)) != (_identity(discovered), _times(discovered))
        )
    ):
        raise ValueError("directory_changed")
    return _Directory(path, depth, chain, _times(info))


def _verify(observation, session):
    """Metadata-only check; page boundaries never rewalk membership."""
    try:
        if isinstance(observation, _Missing):
            try:
                _chain(observation.path, session)
            except FileNotFoundError:
                return
            raise ValueError("directory_changed")
        current = _capture(observation.path, observation.depth, session)
        if (current.chain, current.times) != (observation.chain, observation.times):
            raise ValueError("directory_changed")
    except _WorkLimit:
        raise
    except (OSError, ValueError):
        raise ValueError("directory_changed") from None


def _live(path, directory, session):
    live = next((item for item in session.live_staging if item.path == path), None)
    if live is not None and (
        not path.name.startswith(".")
        or not path.name.endswith(".staged")
        or live.file_type != "regular"
        or live.size < 0
        or getattr(live.identity, "domain", None) != "python_stat"
        or getattr(live.parent_identity, "domain", None) != "python_stat"
        or (live.parent_identity.volume, live.parent_identity.file_index) != directory.chain[-1][1]
    ):
        raise ValueError("live_staging_invalid")
    return live


def _membership(directory, session):
    """Bounded, no-follow name/type/identity snapshot, with stable parent chain."""
    _verify(directory, session)
    members = {}
    with _Entries(directory.path, session) as iterator:
        _verify(directory, session)
        for entry in iterator:
            path = Path(entry.path)
            if path.name in members:
                raise ValueError("directory_changed")
            live = _live(path, directory, session)
            if live is not None:
                value = (stat.S_IFREG, (live.identity.volume, live.identity.file_index), False)
            else:
                # Use the same fresh no-follow metadata domain at every stage.
                info = _lstat(path, session)
                value = (
                    stat.S_IFMT(info.st_mode),
                    _identity(info),
                    bool(getattr(info, "st_file_attributes", 0) & 0x400),
                )
            members[path.name] = value
            if len(members) % PAGE_ENTRIES == 0:
                _verify(directory, session)
    _verify(directory, session)
    return tuple(sorted(members.items()))


def _pin(path, depth, session, discovered=None):
    directory = _capture(path, depth, session, discovered)
    return replace(directory, members=_membership(directory, session))


def _verify_membership(directory, session):
    if _membership(directory, session) != directory.members:
        raise ValueError("directory_changed")


def _validate(observations, session):
    """Finish each supplied observation once, with no I/O after exhaustion."""
    for index, (root, observation) in enumerate(observations):
        try:
            if isinstance(observation, _Directory) and observation.members is not None:
                _verify_membership(observation, session)
            else:
                _verify(observation, session)
            if session.exhausted:
                raise _WorkLimit()
        except _WorkLimit:
            for remaining_root, remaining in observations[index:]:
                session.fail(remaining_root, "scan_limit_reached", remaining.path)
            break
        except (OSError, ValueError):
            session.fail(root, "directory_changed", observation.path)


def revalidate(session):
    """One scope-final pass, sharing all roots' fixed work accounting."""
    if session.finalized:
        raise ValueError("scan_already_finalized")
    session.finalized = True
    _validate(session.observations, session)
    if session.exhausted:
        raise _WorkLimit()
    if session.failures:
        raise ValueError("directory_changed")


def _with_failures(roots, session):
    """Retain affected paths/reasons when scope-final validation is incomplete."""
    result = []
    for root in roots:
        codes, paths = session.failures.get(root.path, ((), ()))
        result.append(
            replace(
                root,
                errors=tuple(sorted(set(root.errors) | set(codes))),
                exclusions=tuple(sorted(set(root.exclusions) | set(paths))),
            )
        )
    return result


def scan(root, budget=MAX_ENTRIES, *, _live_staging=(), _session=None):
    """Metadata inventory; logical budget never expands the fixed work ceiling.

    The private session is created by inspect_enrollment and shared across all
    roots and final validation. Missing-root ancestors remain metadata-only.
    """
    session = _ScanSession(_live_staging) if _session is None else _session
    journals, artifacts, errors, exclusions = [], [], [], []
    observed, traversed, pending = [], [], []
    unfinished = root
    discovering = None
    entries = files = 0
    identity = None
    missing = False
    try:
        if session.exhausted:
            raise _WorkLimit()
        if session.finalized or type(budget) is not int or budget < 0:
            raise ValueError("scan_budget_invalid")
        budget = min(budget, MAX_ENTRIES - session.logical_entries)
        offset = MAX_ENTRIES - budget
        if budget == 0:
            raise _WorkLimit()
        try:
            baseline = _capture(root, 0, session)
        except FileNotFoundError:
            parent = root.parent
            while True:
                try:
                    existing = _capture(parent, 0, session)
                    break
                except FileNotFoundError:
                    if parent == parent.parent:
                        raise
                    parent = parent.parent
            observed.extend(((root, existing), (root, _Missing(root))))
            missing = True
            baseline = None
            unfinished = None
        if baseline is not None:
            identity = baseline.chain[-1][1]
            baseline = replace(baseline, members=_membership(baseline, session))
            observed.append((root, baseline))
            pending = [baseline]
            while pending and entries < budget:
                directory = pending.pop()
                unfinished = directory.path
                _verify_membership(directory, session)
                with _payload_entries(directory, session) as iterator:
                    _verify(directory, session)
                    traversed.append(directory)
                    exhausted = False
                    while entries < budget and not exhausted:
                        page_end = min(
                            ((offset + entries) // PAGE_ENTRIES + 1) * PAGE_ENTRIES - offset,
                            budget,
                        )
                        while entries < page_end:
                            try:
                                entry = next(iterator)
                            except StopIteration:
                                exhausted = True
                                break
                            entries += 1
                            session.logical_entries += 1
                            path = Path(entry.path)
                            live = _live(path, directory, session)
                            if live is not None:
                                files += 1
                                continue
                            info = _lstat(path, session)
                            if stat.S_ISLNK(info.st_mode) or (
                                getattr(info, "st_file_attributes", 0) & 0x400
                            ):
                                exclusions.append(str(path))
                                errors.append("path_redirected")
                            elif stat.S_ISDIR(info.st_mode):
                                if directory.depth >= MAX_DEPTH:
                                    exclusions.append(str(path))
                                    errors.append("scan_depth_reached")
                                else:
                                    discovering = path
                                    child = _pin(path, directory.depth + 1, session, info)
                                    discovering = None
                                    observed.append((root, child))
                                    pending.append(child)
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
                        _verify(directory, session)
                if exhausted:
                    unfinished = None
            if entries >= budget:
                errors.append("scan_limit_reached")
    except _WorkLimit:
        errors.append("scan_limit_reached")
    except PermissionError:
        errors.extend(("root_inspection_failed", "root_access_denied"))
    except (OSError, ValueError) as error:
        errors.append("root_inspection_failed")
        if str(error) == "directory_changed":
            errors.append("directory_changed")
    finally:
        if unfinished is not None:
            exclusions.append(str(unfinished))
        if discovering is not None:
            exclusions.append(str(discovering))
        exclusions.extend(str(item.path) for item in pending)
        # Root-final checks only this root, not all earlier roots again.
        _validate(observed, session)
        session.observations.extend(observed)
        if session.exhausted:
            errors.append("scan_limit_reached")
            exclusions.append(str(root))
        codes, paths = session.failures.get(str(root), ((), ()))
        errors.extend(codes)
        exclusions.extend(sorted(paths))
    return RootInspection(
        str(root),
        "python_stat",
        identity,
        entries,
        files,
        tuple(dict.fromkeys(exclusions)),
        tuple(sorted(set(errors))),
        tuple(journals),
        tuple(artifacts),
        missing,
        directory_identities=tuple(
            sorted((str(item.path), item.chain[-1][1]) for item in traversed)
        ),
    )
