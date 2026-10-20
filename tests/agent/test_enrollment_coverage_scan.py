"""Metadata-only coverage and race tests for the fixed bounded scanner."""

import importlib
import importlib.util
import os
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from swu_happyrun.drivers.mumu.enrollment_inspection import RootInspection
from swu_happyrun.drivers.mumu.enrollment_storage import LiveStagingObservation
from swu_happyrun.drivers.mumu.instance_attribution import FileIdentity

MODULE = "swu_happyrun.drivers.mumu.enrollment_coverage"


def scanner():
    assert importlib.util.find_spec(MODULE) is not None, "bounded coverage scanner is missing"
    return importlib.import_module(MODULE)


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
    assert opened == [tmp_path]


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
    real_scandir = os.scandir
    yielded = False

    def fail_after_entry():
        if yielded:
            raise PermissionError("enumeration interrupted")

    def mark_yielded(entry):
        nonlocal yielded
        yielded = True

    monkeypatch.setattr(
        os,
        "scandir",
        lambda path: HookedScan(real_scandir(path), fail_after_entry, mark_yielded),
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
    real_scandir = os.scandir

    def deny_descent(path):
        if path != tmp_path:
            raise PermissionError("child inaccessible")
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", deny_descent)
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
    consumed = 0

    class RepeatingScan(HookedScan):
        def __next__(self):
            nonlocal consumed
            consumed += 1
            return self.entry

    def repeated(path):
        result = RepeatingScan(real_scandir(path))
        result.entry = next(result.iterator)
        return result

    monkeypatch.setattr(os, "scandir", repeated)
    result = module.scan(tmp_path, module.MAX_ENTRIES + 1)
    assert result.entry_count == consumed == module.MAX_ENTRIES
    assert "scan_limit_reached" in result.errors


def test_remaining_budget_keeps_global_page_boundary(tmp_path, monkeypatch):
    module = scanner()
    (tmp_path / "first").touch()
    (tmp_path / "second").touch()
    real_scandir = os.scandir
    changed = False

    def mutate(entry):
        nonlocal changed
        if not changed:
            changed = True
            (tmp_path / "late.db").touch()

    monkeypatch.setattr(
        os, "scandir", lambda path: HookedScan(real_scandir(path), after_entry=mutate)
    )
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
    real_scandir = os.scandir
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

    def hooked(path):
        if path == tmp_path:
            return HookedScan(
                real_scandir(path), mutate, lambda entry: yielded.append(Path(entry.path))
            )
        descended.append(path)
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", hooked)
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
    real_scandir = os.scandir
    scanned = []

    def hooked(path):
        if path != tmp_path:
            if scanned:
                previous = scanned[0]
                if replace_directory:
                    previous.rename(tmp_path / "old")
                    previous.mkdir()
                (previous / "late.db").touch()
            scanned.append(path)
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", hooked)
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
    observations = []
    missing = tmp_path / "missing"
    result = module.scan(missing, _observations=observations)
    assert result.missing
    assert result.errors == ()
    assert result.entry_count == 0
    assert not missing.exists()
    module.revalidate(observations)
    missing.mkdir()
    with pytest.raises(ValueError, match="directory_changed"):
        module.revalidate(observations)


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

    class Unstatable:
        def __init__(self, entry):
            self.path = entry.path

        def stat(self, **kwargs):
            pytest.fail("exclusive staging file stat by name")

    class StagingScan(HookedScan):
        def __next__(self):
            return Unstatable(super().__next__())

    monkeypatch.setattr(os, "scandir", lambda path: StagingScan(real_scandir(path)))
    result = module.scan(tmp_path, _live_staging=(live,))
    assert result.errors == ()
    assert result.entry_count == result.file_count == 1
    assert result.candidate_journals == result.state_artifacts == ()


@pytest.mark.parametrize("invalid", ["name", "parent", "size", "kind"])
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
    result = module.scan(tmp_path, _live_staging=(live,))
    assert "root_inspection_failed" in result.errors


def test_cross_root_observations_detect_later_nested_changes(tmp_path):
    module = scanner()
    first = tmp_path / "first"
    nested = first / "nested"
    nested.mkdir(parents=True)
    second = tmp_path / "second"
    second.mkdir()
    observations = []
    assert module.scan(first, _observations=observations).errors == ()
    assert module.scan(second, _observations=observations).errors == ()
    module.revalidate(observations)
    (nested / "late.db").touch()
    with pytest.raises(ValueError, match="directory_changed"):
        module.revalidate(observations)


def test_result_retains_only_traversed_directory_identities(tmp_path):
    module = scanner()
    nested = tmp_path / "nested"
    nested.mkdir()
    observations = []
    result = module.scan(tmp_path, _observations=observations)
    assert result.directory_identities == tuple(
        (str(path), (path.stat().st_dev, path.stat().st_ino)) for path in sorted((tmp_path, nested))
    )
    absent = module.scan(tmp_path / "absent")
    assert absent.directory_identities == ()
