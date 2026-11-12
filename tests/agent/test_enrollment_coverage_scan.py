"""Metadata-only coverage and race tests for the fixed bounded scanner."""

import importlib
import importlib.util
import os
import sqlite3
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from swu_happyrun.drivers.mumu.enrollment_inspection import RootInspection
from swu_happyrun.drivers.mumu.enrollment_storage import LiveStagingObservation
from swu_happyrun.drivers.mumu.instance_attribution import FileIdentity

MODULE = "swu_happyrun.drivers.mumu.enrollment_coverage"


def scanner():
    assert importlib.util.find_spec(MODULE) is not None, "bounded coverage scanner is missing"
    return importlib.import_module(MODULE)


def freeze_directory_times(monkeypatch, *paths):
    """Keep directory timestamps unchanged while preserving fresh identity/type."""
    real_lstat = Path.lstat
    times = {path: (real_lstat(path).st_mtime_ns, real_lstat(path).st_ctime_ns) for path in paths}

    def frozen(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        if path not in times:
            return info
        return SimpleNamespace(
            st_mode=info.st_mode,
            st_dev=info.st_dev,
            st_ino=info.st_ino,
            st_mtime_ns=times[path][0],
            st_ctime_ns=times[path][1],
            st_file_attributes=getattr(info, "st_file_attributes", 0),
        )

    monkeypatch.setattr(Path, "lstat", frozen)


def hook_payload(monkeypatch, module, hook):
    """Distinguish inventory descent from read-only membership observations."""
    if hasattr(module, "_payload_entries"):
        original = module._payload_entries
        monkeypatch.setattr(
            module,
            "_payload_entries",
            lambda directory, session: hook(directory.path, lambda: original(directory, session)),
        )
    else:
        original = os.scandir
        monkeypatch.setattr(os, "scandir", lambda path: hook(path, lambda: original(path)))


class HookedScan:
    """Wrap real directory metadata, with deterministic filesystem race boundaries."""

    def __init__(self, iterator, before_next=lambda: None, after_entry=lambda entry: None):
        self.iterator = iterator
        self.before_next = before_next
        self.after_entry = after_entry

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self.iterator.close()

    def __iter__(self):
        return self

    def __next__(self):
        self.before_next()
        entry = next(self.iterator)
        self.after_entry(entry)
        return entry


@pytest.mark.parametrize("mutation", ["add", "remove", "replace"])
def test_pending_membership_change_with_frozen_times_prevents_payload_descent(
    tmp_path, monkeypatch, mutation
):
    module = scanner()
    pending = tmp_path / "pending"
    pending.mkdir()
    (tmp_path / "trigger").touch()
    original_member = pending / "original.db"
    replacement = tmp_path.parent / f"{tmp_path.name}-replacement"
    if mutation != "add":
        original_member.touch()
    if mutation == "replace":
        replacement.touch()
        assert replacement.lstat().st_ino != original_member.lstat().st_ino
    freeze_directory_times(monkeypatch, tmp_path, pending)
    yielded = []
    descended = []
    changed = False

    def mutate():
        nonlocal changed
        if pending in yielded and not changed:
            changed = True
            if mutation == "add":
                (pending / "hidden.db").touch()
            elif mutation == "remove":
                original_member.unlink()
            else:
                os.replace(replacement, original_member)

    def hooked(path, original):
        descended.append(path)
        if path == tmp_path:
            return HookedScan(original(), mutate, lambda entry: yielded.append(Path(entry.path)))
        return original()

    hook_payload(monkeypatch, module, hooked)
    result = module.scan(tmp_path)
    assert changed
    assert pending not in descended
    assert "directory_changed" in result.errors
    assert str(pending) in result.exclusions
    assert result.candidate_journals == ()


def test_finished_membership_change_with_frozen_times_is_rejected(tmp_path, monkeypatch):
    module = scanner()
    children = (tmp_path / "first", tmp_path / "second")
    for child in children:
        child.mkdir()
    freeze_directory_times(monkeypatch, tmp_path, *children)
    scanned = []

    def hooked(path, original):
        if path != tmp_path:
            if scanned:
                (scanned[0] / "late.db").touch()
            scanned.append(path)
        return original()

    hook_payload(monkeypatch, module, hooked)
    result = module.scan(tmp_path)
    assert len(scanned) == 2
    assert "directory_changed" in result.errors
    assert str(scanned[0]) in result.exclusions
    assert result.candidate_journals == ()


def test_cross_root_membership_change_with_frozen_times_is_rejected(tmp_path, monkeypatch):
    module = scanner()
    first = tmp_path / "first"
    nested = first / "nested"
    nested.mkdir(parents=True)
    second = tmp_path / "second"
    second.mkdir()
    freeze_directory_times(monkeypatch, first, nested, second)
    session = module._ScanSession()
    assert module.scan(first, _session=session).errors == ()
    (nested / "late.db").touch()
    assert module.scan(second, _session=session).errors == ()
    with pytest.raises(ValueError, match="directory_changed"):
        module.revalidate(session)


def test_all_metadata_attempts_share_fixed_work_cap_and_close_on_exhaustion(tmp_path, monkeypatch):
    module = scanner()
    (tmp_path / "file").touch()
    file_info = (tmp_path / "file").lstat()
    calls = {"lstat": 0, "open": 0, "next": 0, "close": 0}
    real_lstat = Path.lstat

    def counted_lstat(path, *args, **kwargs):
        calls["lstat"] += 1
        if path.parent == tmp_path and path.name.startswith("synthetic-"):
            return file_info
        return real_lstat(path, *args, **kwargs)

    class Repeating:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

        def __iter__(self):
            return self

        def __next__(self):
            calls["next"] += 1
            return SimpleNamespace(path=str(tmp_path / f"synthetic-{calls['next']}"))

        def close(self):
            calls["close"] += 1

    def repeated(path):
        calls["open"] += 1
        return Repeating()

    monkeypatch.setattr(Path, "lstat", counted_lstat)
    monkeypatch.setattr(os, "scandir", repeated)
    result = module.scan(tmp_path)
    assert calls["lstat"] + calls["open"] + calls["next"] == module.MAX_ENTRIES
    assert calls["close"] == calls["open"]
    assert result.errors == ("scan_limit_reached",)
    assert str(tmp_path) in result.exclusions


def test_empty_root_and_cross_root_checks_share_one_counted_session(tmp_path, monkeypatch):
    module = scanner()
    roots = (tmp_path / "first", tmp_path / "second")
    for root in roots:
        root.mkdir()
    real_scandir, real_lstat = os.scandir, Path.lstat
    calls = {"lstat": 0, "open": 0, "next": 0}

    def counted_lstat(path, *args, **kwargs):
        calls["lstat"] += 1
        return real_lstat(path, *args, **kwargs)

    def counted_next():
        calls["next"] += 1

    def counted_scandir(path):
        calls["open"] += 1
        return HookedScan(real_scandir(path), before_next=counted_next)

    monkeypatch.setattr(Path, "lstat", counted_lstat)
    monkeypatch.setattr(os, "scandir", counted_scandir)
    session = module._ScanSession()
    for root in roots:
        assert module.scan(root, _session=session).errors == ()
    before_final = session.work_used
    module.revalidate(session)
    assert session.work_used == sum(calls.values()) > before_final > 0
    # Each root has four membership stages plus one actual payload iterator.
    assert calls["open"] == calls["next"] == 10


def test_scope_final_work_exhaustion_preserves_all_unswept_paths_without_further_io(
    tmp_path, monkeypatch
):
    module = scanner()
    roots = (tmp_path / "first", tmp_path / "second")
    for root in roots:
        root.mkdir()
    session = module._ScanSession()
    reports = [module.scan(root, _session=session) for root in roots]
    assert all(not report.errors for report in reports)
    # Simulate earlier charged work leaving exactly one metadata attempt.
    session.work_used = module.MAX_ENTRIES - 1
    calls = []
    real_lstat = Path.lstat

    def counted_lstat(path, *args, **kwargs):
        calls.append(path)
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", counted_lstat)
    monkeypatch.setattr(os, "scandir", lambda path: pytest.fail("open after exhaustion"))
    with pytest.raises(module._WorkLimit, match="scan_limit_reached"):
        module.revalidate(session)
    assert len(calls) == 1
    corrected = module._with_failures(reports, session)
    for root, report in zip(roots, corrected, strict=True):
        assert report.errors == ("scan_limit_reached",)
        assert str(root) in report.exclusions
    refused = module.scan(tmp_path / "another", _session=session)
    assert refused.errors == ("scan_limit_reached",)
    assert len(calls) == 1


def test_disappearing_member_does_not_turn_existing_root_into_missing(tmp_path, monkeypatch):
    module = scanner()
    member = tmp_path / "vanished"
    member.touch()
    real_lstat = Path.lstat

    def vanished(path, *args, **kwargs):
        if path == member:
            raise FileNotFoundError("member vanished during membership observation")
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", vanished)
    result = module.scan(tmp_path)
    assert not result.missing
    assert "root_inspection_failed" in result.errors


def test_missing_root_never_enumerates_out_of_scope_parent(tmp_path, monkeypatch):
    module = scanner()
    session = module._ScanSession()
    monkeypatch.setattr(os, "scandir", lambda path: pytest.fail("out-of-scope parent enumerated"))
    result = module.scan(tmp_path / "absent", _session=session)
    assert result.missing
    assert result.errors == ()
    module.revalidate(session)
    assert session.work_used > 0


def windows_cached_scandir(monkeypatch, *, zero_identity=True, cached_times_path=None):
    """Install Windows-style DirEntry metadata over real filesystem enumeration."""
    real_scandir = os.scandir
    changed_times = False

    class CachedEntry:
        def __init__(self, entry):
            nonlocal changed_times
            self.path = entry.path
            self.entry = entry
            self.cached = None
            if Path(self.path) == cached_times_path and not changed_times:
                changed_times = True
                info = Path(self.path).lstat()
                self.cached = self.metadata(info)
                os.utime(
                    cached_times_path,
                    ns=(info.st_atime_ns, info.st_mtime_ns + 2_000_000_000),
                )

        def metadata(self, info):
            # Windows DirEntry.stat reports zero identity values and can retain
            # earlier enumeration times. These are not the Path.lstat domain.
            return SimpleNamespace(
                st_mode=info.st_mode,
                st_dev=0 if zero_identity else info.st_dev,
                st_ino=0 if zero_identity else info.st_ino,
                st_nlink=0 if zero_identity else info.st_nlink,
                st_mtime_ns=info.st_mtime_ns,
                st_ctime_ns=info.st_ctime_ns,
                st_file_attributes=getattr(info, "st_file_attributes", 0),
            )

        def stat(self, *, follow_symlinks=True):
            assert not follow_symlinks
            if self.cached is None:
                self.cached = self.metadata(self.entry.stat(follow_symlinks=False))
            return self.cached

    class CachedScan(HookedScan):
        def __next__(self):
            return CachedEntry(super().__next__())

    monkeypatch.setattr(os, "scandir", lambda path: CachedScan(real_scandir(path)))


@pytest.mark.parametrize("zero_identity,cached_times", [(True, False), (False, True), (True, True)])
def test_scandir_cache_is_not_compared_with_fresh_path_metadata(
    tmp_path, monkeypatch, zero_identity, cached_times
):
    module = scanner()
    nested = tmp_path / "nested"
    nested.mkdir()
    journal = nested / "history.db"
    journal.touch()
    windows_cached_scandir(
        monkeypatch, zero_identity=zero_identity, cached_times_path=nested if cached_times else None
    )
    result = module.scan(tmp_path)
    assert result.errors == ()
    assert result.entry_count == 2
    assert result.candidate_journals == (str(journal),)
    assert result.directory_identities == tuple(
        (str(path), (path.lstat().st_dev, path.lstat().st_ino))
        for path in sorted((tmp_path, nested))
    )


def test_scan_continues_same_directory_beyond_two_pages_without_opening_files(
    tmp_path, monkeypatch
):
    module = scanner()
    for index in range(902):
        (tmp_path / f"file-{index}").touch()
    journal = tmp_path / "history.sqlite"
    journal.write_bytes(b"not opened")
    real_scandir = os.scandir
    opened = []

    def tracked(path):
        opened.append(path)
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", tracked)
    monkeypatch.setattr(os, "open", lambda *a, **k: pytest.fail("file opened"))
    monkeypatch.setattr(Path, "open", lambda *a, **k: pytest.fail("file opened"))
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: pytest.fail("SQLite opened"))
    result = module.scan(tmp_path)
    assert type(result) is RootInspection
    assert result.errors == ()
    assert result.entry_count == result.file_count == 903
    assert result.candidate_journals == (str(journal),)
    # Baseline, pre-descent, one retained payload iterator, and root-final.
    assert opened == [tmp_path] * 4


def test_scan_retains_pending_subtrees_and_scans_eight_levels(tmp_path):
    module = scanner()
    nested = tmp_path
    for _ in range(module.MAX_DEPTH):
        nested /= "child"
        nested.mkdir()
    (nested / "enrollment-proof.json").touch()
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    for index in range(451):
        (sibling / f"file-{index}").touch()
    result = module.scan(tmp_path)
    assert result.errors == ()
    assert result.entry_count == 461
    assert result.file_count == 452
    assert result.state_artifacts == (str(nested / "enrollment-proof.json"),)


def test_depth_exhaustion_is_incomplete_and_does_not_descend(tmp_path, monkeypatch):
    module = scanner()
    nested = tmp_path
    for _ in range(module.MAX_DEPTH + 1):
        nested /= "child"
        nested.mkdir()
    (nested / "unobserved.db").touch()
    real_scandir = os.scandir

    def guarded(path):
        assert path != nested, "scanner descended beyond the fixed depth"
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", guarded)
    result = module.scan(tmp_path)
    assert "scan_depth_reached" in result.errors
    assert str(nested) in result.exclusions
    assert result.candidate_journals == ()


@pytest.mark.parametrize("count,budget", [(450, 450), (901, 900), (0, 0)])
def test_reaching_even_an_exact_entry_budget_is_incomplete(tmp_path, count, budget):
    module = scanner()
    for index in range(count):
        (tmp_path / str(index)).touch()
    result = module.scan(tmp_path, budget)
    assert result.entry_count == min(count, budget)
    assert "scan_limit_reached" in result.errors
    assert result.exclusions == (str(tmp_path),)


def test_exact_cap_retains_current_directory_and_pending_subtrees(tmp_path):
    module = scanner()
    pending = tmp_path / "pending"
    pending.mkdir()
    (pending / "unseen.db").touch()
    result = module.scan(tmp_path, 1)
    assert result.entry_count == 1
    assert "scan_limit_reached" in result.errors
    assert set(result.exclusions) == {str(tmp_path), str(pending)}
    assert result.candidate_journals == ()


def test_midscan_failure_retains_current_directory_and_pending_subtrees(tmp_path, monkeypatch):
    module = scanner()
    pending = tmp_path / "pending"
    pending.mkdir()
    (pending / "unseen.db").touch()
    yielded = False

    def fail_after_entry():
        if yielded:
            raise PermissionError("enumeration interrupted")

    def mark_yielded(entry):
        nonlocal yielded
        yielded = True

    hook_payload(
        monkeypatch,
        module,
        lambda path, original: (
            HookedScan(original(), fail_after_entry, mark_yielded)
            if path == tmp_path
            else original()
        ),
    )
    result = module.scan(tmp_path)
    assert "root_access_denied" in result.errors
    assert set(result.exclusions) == {str(tmp_path), str(pending)}
    assert result.candidate_journals == ()


def test_failed_descent_retains_pending_paths_but_not_finished_root(tmp_path, monkeypatch):
    module = scanner()
    children = (tmp_path / "first", tmp_path / "second")
    for child in children:
        child.mkdir()

    def deny_descent(path, original):
        if path != tmp_path:
            raise PermissionError("child inaccessible")
        return original()

    hook_payload(monkeypatch, module, deny_descent)
    result = module.scan(tmp_path)
    assert "root_access_denied" in result.errors
    assert set(result.exclusions) == {str(child) for child in children}


def test_fixed_total_cap_cannot_be_expanded_by_a_caller(tmp_path, monkeypatch):
    module = scanner()
    assert (module.PAGE_ENTRIES, module.MAX_PAGES, module.MAX_ENTRIES, module.MAX_DEPTH) == (
        450,
        64,
        28800,
        8,
    )
    (tmp_path / "file").touch()
    real_scandir = os.scandir
    real_lstat = Path.lstat
    info = (tmp_path / "file").lstat()
    consumed = 0

    class RepeatingScan(HookedScan):
        def __next__(self):
            nonlocal consumed
            consumed += 1
            return SimpleNamespace(path=str(tmp_path / f"synthetic-{consumed}"))

    def repeated(path):
        result = RepeatingScan(real_scandir(path))
        return result

    monkeypatch.setattr(os, "scandir", repeated)
    monkeypatch.setattr(
        Path,
        "lstat",
        lambda path, *a, **k: (
            info
            if path.parent == tmp_path and path.name.startswith("synthetic-")
            else real_lstat(path, *a, **k)
        ),
    )
    result = module.scan(tmp_path, module.MAX_ENTRIES + 1)
    # The separate fixed work ceiling stops an endless baseline even when the
    # caller requests a larger logical cap. No payload traversal was reached.
    assert result.entry_count == 0
    assert 0 < consumed < module.MAX_ENTRIES
    assert "scan_limit_reached" in result.errors


def test_remaining_budget_keeps_global_page_boundary(tmp_path, monkeypatch):
    module = scanner()
    (tmp_path / "first").touch()
    (tmp_path / "second").touch()
    real_lstat = Path.lstat
    changed = False

    def mutate(entry):
        nonlocal changed
        if not changed:
            changed = True
            (tmp_path / "late.db").touch()

    def observed_lstat(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        if path == tmp_path and changed:
            # This test concerns the global page boundary once metadata changes
            # are observable, not Windows directory timestamp visibility timing.
            return SimpleNamespace(
                st_mode=info.st_mode,
                st_dev=info.st_dev,
                st_ino=info.st_ino,
                st_mtime_ns=info.st_mtime_ns + 2_000_000_000,
                st_ctime_ns=info.st_ctime_ns,
                st_file_attributes=getattr(info, "st_file_attributes", 0),
            )
        return info

    hook_payload(
        monkeypatch,
        module,
        lambda path, original: HookedScan(original(), after_entry=mutate),
    )
    monkeypatch.setattr(Path, "lstat", observed_lstat)
    # Earlier roots consumed 449 entries. The shared page ends after this one,
    # not after an additional 450 entries in this root.
    result = module.scan(tmp_path, module.MAX_ENTRIES - 449)
    assert result.entry_count == 1
    assert "directory_changed" in result.errors
    assert result.exclusions == (str(tmp_path),)


@pytest.mark.parametrize("replace_directory", [False, True])
def test_pending_directory_change_is_rejected_before_descent(
    tmp_path, monkeypatch, replace_directory
):
    module = scanner()
    pending = tmp_path / "pending"
    pending.mkdir()
    (tmp_path / "trigger").touch()
    yielded = []
    changed = False
    descended = []

    def mutate():
        nonlocal changed
        if changed or pending not in yielded:
            return
        changed = True
        if replace_directory:
            pending.rename(tmp_path / "old")
            pending.mkdir()
        (pending / "hidden.db").touch()

    def hooked(path, original):
        if path == tmp_path:
            return HookedScan(original(), mutate, lambda entry: yielded.append(Path(entry.path)))
        descended.append(path)
        return original()

    hook_payload(monkeypatch, module, hooked)
    result = module.scan(tmp_path)
    assert changed
    assert pending not in descended
    assert "directory_changed" in result.errors
    assert str(pending / "hidden.db") not in result.candidate_journals


@pytest.mark.parametrize("replace_directory", [False, True])
def test_already_scanned_directory_is_revalidated_at_end(tmp_path, monkeypatch, replace_directory):
    module = scanner()
    for name in ("first", "second"):
        (tmp_path / name).mkdir()
    scanned = []

    def hooked(path, original):
        if path != tmp_path:
            if scanned:
                previous = scanned[0]
                if replace_directory:
                    previous.rename(tmp_path / "old")
                    previous.mkdir()
                (previous / "late.db").touch()
            scanned.append(path)
        return original()

    hook_payload(monkeypatch, module, hooked)
    result = module.scan(tmp_path)
    assert len(scanned) == 2
    assert "directory_changed" in result.errors
    assert result.candidate_journals == ()


def test_substitution_at_directory_open_is_rejected_before_enumerating(tmp_path, monkeypatch):
    module = scanner()
    pending = tmp_path / "pending"
    pending.mkdir()
    real_scandir = os.scandir
    replaced = False

    def hooked(path):
        nonlocal replaced
        if path == pending:
            replaced = True
            pending.rename(tmp_path / "old")
            pending.mkdir()
            (pending / "substitute.db").touch()
            return HookedScan(
                real_scandir(path), lambda: pytest.fail("replacement directory enumerated")
            )
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", hooked)
    result = module.scan(tmp_path)
    assert replaced
    assert "directory_changed" in result.errors


def test_redirected_entries_are_not_followed(tmp_path, symlink_or_skip):
    module = scanner()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "hidden.db").touch()
    root = tmp_path / "root"
    root.mkdir()
    link = root / "redirect"
    symlink_or_skip(link, outside, target_is_directory=True)
    result = module.scan(root)
    assert "path_redirected" in result.errors
    assert result.exclusions == (str(link),)
    assert result.candidate_journals == ()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO unsupported")
def test_special_file_is_rejected_without_opening(tmp_path, monkeypatch):
    module = scanner()
    fifo = tmp_path / "unreadable.db"
    os.mkfifo(fifo)
    monkeypatch.setattr(os, "open", lambda *a, **k: pytest.fail("special file opened"))
    result = module.scan(tmp_path)
    assert "unsupported_file_kind" in result.errors
    assert result.exclusions == (str(fifo),)
    assert result.candidate_journals == ()


def test_missing_root_keeps_safe_parent_observations_without_creation(tmp_path):
    module = scanner()
    session = module._ScanSession()
    missing = tmp_path / "missing"
    result = module.scan(missing, _session=session)
    assert result.missing
    assert result.errors == ()
    assert result.entry_count == 0
    assert not missing.exists()
    missing.mkdir()
    with pytest.raises(ValueError, match="directory_changed"):
        module.revalidate(session)


def test_unreadable_root_is_sanitized(tmp_path, monkeypatch):
    module = scanner()

    def denied(path):
        raise PermissionError("private filesystem details")

    monkeypatch.setattr(os, "scandir", denied)
    result = module.scan(tmp_path)
    assert "root_inspection_failed" in result.errors
    assert "root_access_denied" in result.errors
    assert "private filesystem details" not in str(result.errors)


def test_live_staging_uses_only_exact_enumerated_owned_metadata(tmp_path, monkeypatch):
    module = scanner()
    stage = tmp_path / ".owned.staged"
    stage.touch()
    live = LiveStagingObservation(
        stage,
        FileIdentity.from_stat(stage.stat()),
        FileIdentity.from_stat(tmp_path.stat()),
        0,
    )
    real_scandir = os.scandir
    real_lstat = Path.lstat

    def checked_lstat(path, *args, **kwargs):
        assert path != stage, "exclusive staging file stat by name"
        return real_lstat(path, *args, **kwargs)

    class Unstatable:
        def __init__(self, entry):
            self.path = entry.path

        def stat(self, **kwargs):
            pytest.fail("exclusive staging file stat by name")

    class StagingScan(HookedScan):
        def __next__(self):
            return Unstatable(super().__next__())

    monkeypatch.setattr(os, "scandir", lambda path: StagingScan(real_scandir(path)))
    monkeypatch.setattr(Path, "lstat", checked_lstat)
    result = module.scan(tmp_path, _live_staging=(live,))
    assert result.errors == ()
    assert result.entry_count == result.file_count == 1
    assert result.candidate_journals == result.state_artifacts == ()


@pytest.mark.parametrize(
    "invalid", ["name", "parent", "size", "kind", "identity_domain", "parent_domain"]
)
def test_invalid_live_staging_metadata_fails_closed(tmp_path, invalid):
    module = scanner()
    stage = tmp_path / ("journal.db" if invalid == "name" else ".owned.staged")
    stage.touch()
    live = LiveStagingObservation(
        stage,
        FileIdentity.from_stat(stage.stat()),
        FileIdentity.from_stat(tmp_path.stat()),
        0,
    )
    if invalid == "parent":
        live = replace(live, parent_identity=FileIdentity("python_stat", 9999, 9999))
    elif invalid == "size":
        live = replace(live, size=-1)
    elif invalid == "kind":
        live = replace(live, file_type="directory")
    elif invalid in {"identity_domain", "parent_domain"}:
        field = "identity" if invalid == "identity_domain" else "parent_identity"
        identity = getattr(live, field)
        wrong_domain = SimpleNamespace(
            domain="win32_legacy_ntfs",
            volume=identity.volume,
            file_index=identity.file_index,
        )
        live = replace(live, **{field: wrong_domain})
    result = module.scan(tmp_path, _live_staging=(live,))
    assert "root_inspection_failed" in result.errors


def test_cross_root_observations_detect_later_nested_changes(tmp_path):
    module = scanner()
    first = tmp_path / "first"
    nested = first / "nested"
    nested.mkdir(parents=True)
    second = tmp_path / "second"
    second.mkdir()
    session = module._ScanSession()
    assert module.scan(first, _session=session).errors == ()
    assert module.scan(second, _session=session).errors == ()
    (nested / "late.db").touch()
    with pytest.raises(ValueError, match="directory_changed"):
        module.revalidate(session)


def test_result_retains_only_traversed_directory_identities(tmp_path):
    module = scanner()
    nested = tmp_path / "nested"
    nested.mkdir()
    session = module._ScanSession()
    result = module.scan(tmp_path, _session=session)
    assert result.directory_identities == tuple(
        (str(path), (path.stat().st_dev, path.stat().st_ino)) for path in sorted((tmp_path, nested))
    )
    absent = module.scan(tmp_path / "absent")
    assert absent.directory_identities == ()
