"""Fixed-policy metadata inventory with internal, non-authorizing continuation.

The 450-entry pages share a live scandir iterator and a bounded pending stack.
Neither continuation state nor an adjustable scan policy is accepted from a
caller. Directory identities and change times are pinned when discovered, before
descent, and again at completion. No journal or other file contents are opened.
"""

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from .enrollment_inspection import RootInspection, _chain, _identity

PAGE_ENTRIES = 450
MAX_PAGES = 64
MAX_ENTRIES = PAGE_ENTRIES * MAX_PAGES
MAX_DEPTH = 8


@dataclass(frozen=True, repr=False)
class _Directory:
    path: Path
    depth: int
    chain: tuple
    times: tuple[int, int]


@dataclass(frozen=True, repr=False)
class _Missing:
    path: Path


def _times(info):
    return info.st_mtime_ns, info.st_ctime_ns


def _capture(path, depth, discovered=None):
    chain = _chain(path)
    info = path.lstat()
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


def _verify(observation):
    try:
        if isinstance(observation, _Missing):
            try:
                _chain(observation.path)
            except FileNotFoundError:
                return
            raise ValueError("directory_changed")
        if _capture(observation.path, observation.depth) != observation:
            raise ValueError("directory_changed")
    except (OSError, ValueError):
        raise ValueError("directory_changed") from None


def revalidate(observations):
    """Recheck private output observations across roots; never skip scan work."""
    for observation in observations:
        _verify(observation)


def scan(root, budget=MAX_ENTRIES, *, _live_staging=(), _observations=None):
    """Return the existing non-authorizing inventory using a fixed total cap.

    ``budget`` is the remaining aggregate entry allowance, not a policy override.
    ``_observations`` is an internal output sink for final cross-root validation.
    Missing roots retain v1 semantics only while their safe existing parent and
    missing-path observation remain unchanged.
    """
    journals, artifacts, errors, exclusions = [], [], [], []
    observed, traversed = [], []
    pending = []
    unfinished = root
    entries = files = 0
    identity = None
    missing = False
    try:
        if type(budget) is not int or budget < 0:
            raise ValueError("scan_budget_invalid")
        budget = min(budget, MAX_ENTRIES)
        offset = MAX_ENTRIES - budget
        try:
            baseline = _capture(root, 0)
        except FileNotFoundError:
            parent = root.parent
            while True:
                try:
                    existing = _capture(parent, 0)
                    break
                except FileNotFoundError:
                    if parent == parent.parent:
                        raise
                    parent = parent.parent
            observed.extend((existing, _Missing(root)))
            missing = True
            baseline = None
            unfinished = None
        if baseline is not None:
            identity = baseline.chain[-1][1]
            observed.append(baseline)
            pending = [baseline]
            while pending and entries < budget:
                directory = pending.pop()
                unfinished = directory.path
                _verify(directory)
                with os.scandir(directory.path) as iterator:
                    # Recheck after opening, before enumerating, so substitution
                    # at the open boundary cannot adopt a different directory.
                    _verify(directory)
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
                            path = Path(entry.path)
                            live = next((item for item in _live_staging if item.path == path), None)
                            if live is not None:
                                # Same exact, still-owned handle metadata as v1.
                                # The filename must actually be enumerated.
                                if (
                                    not path.name.startswith(".")
                                    or not path.name.endswith(".staged")
                                    or live.file_type != "regular"
                                    or live.size < 0
                                    or (
                                        live.parent_identity.volume,
                                        live.parent_identity.file_index,
                                    )
                                    != directory.chain[-1][1]
                                ):
                                    raise ValueError("live_staging_invalid")
                                files += 1
                                continue
                            # DirEntry metadata is cached and reports zero file
                            # identities on Windows. Observe the path without
                            # following links, in the same fresh lstat domain as
                            # _chain/_capture and later directory validation.
                            info = path.lstat()
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
                                    child = _capture(path, directory.depth + 1, info)
                                    observed.append(child)
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
                        # Page transitions retain both the iterator and pending
                        # children, while checking the current directory again.
                        _verify(directory)
                if exhausted:
                    unfinished = None
            if entries >= budget:
                # Conservatively incomplete even when the exact last entry may
                # also be the directory's end; never read past the fixed cap.
                errors.append("scan_limit_reached")
    except PermissionError:
        errors.extend(("root_inspection_failed", "root_access_denied"))
    except (OSError, ValueError) as error:
        errors.append("root_inspection_failed")
        if str(error) == "directory_changed":
            errors.append("directory_changed")
    finally:
        # These paths are evidence of work left incomplete, never caller-chosen
        # exemptions. Keep both the interrupted iterator and discovered subtrees.
        if unfinished is not None:
            exclusions.append(str(unfinished))
        exclusions.extend(str(item.path) for item in pending)
        # Include already-finished and pending directories, not only ancestors
        # of the last entry. A later subtree scan may mutate an earlier one.
        for observation in observed:
            try:
                _verify(observation)
            except ValueError:
                errors.append("directory_changed")
                exclusions.append(str(observation.path))
        if _observations is not None:
            _observations.extend(observed)
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
