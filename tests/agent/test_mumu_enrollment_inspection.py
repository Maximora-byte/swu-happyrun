import hashlib
import os
import sqlite3
from uuid import uuid4

import pytest

from swu_happyrun.drivers.identity import device_id
from swu_happyrun.drivers.mumu.enrollment_inspection import DiscoveryScope, inspect_enrollment


@pytest.fixture
def setup(tmp_path, monkeypatch):
    host = tmp_path / "host-id"
    host.write_text(str(uuid4()) + "\n", encoding="ascii")
    monkeypatch.setenv("SWU_HAPPYRUN_HOST_ID_FILE", str(host))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    manager = tmp_path / "manager.exe"
    manager.write_bytes(b"fixture")
    root = tmp_path / "scan"
    root.mkdir()
    scope = DiscoveryScope(roots=(root,), declared_complete=True, unchecked_categories=())
    return host, manager, root, scope


def inspect(setup, **kwargs):
    _, manager, _, scope = setup
    return inspect_enrollment(scope, manager=manager, instance_index="0", **kwargs)


def snapshot(path):
    return [
        (str(p.relative_to(path)), p.stat().st_ino, p.read_bytes() if p.is_file() else None)
        for p in sorted(path.rglob("*"))
    ]


def test_empty_scan_zero_creation(setup, tmp_path, monkeypatch):
    before = snapshot(tmp_path)
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: pytest.fail("SQLite opened"))
    result = inspect(setup)
    assert result.status == "first_use_review_required"
    assert result.launch_allowed is False
    assert snapshot(tmp_path) == before
    assert str(tmp_path) not in repr(result)
    assert str(tmp_path) not in str(result.public_summary())


def test_missing_host_does_not_create(setup, tmp_path):
    setup[0].unlink()
    before = snapshot(tmp_path)
    assert inspect(setup).status == "unknown"
    assert snapshot(tmp_path) == before


def test_bad_host_remains_unchanged(setup):
    setup[0].write_text("bad", encoding="ascii")
    assert inspect(setup).status == "unknown"
    assert setup[0].read_text() == "bad"


def test_incomplete_declaration_not_first_use(setup):
    _, manager, root, _ = setup
    result = inspect_enrollment(DiscoveryScope(roots=(root,)), manager=manager, instance_index="0")
    assert result.status == "unknown"
    assert result.unchecked_categories


def test_exact_file_cap_is_incomplete(setup):
    for i in range(450):
        (setup[2] / f"f{i}").write_bytes(b"x")
    result = inspect(setup)
    assert result.status == "unknown"
    assert "scan_limit_reached" in result.reasons


def test_depth_limit_is_incomplete(setup):
    (setup[2] / "a/b/c/d/e").mkdir(parents=True)
    assert inspect(setup).status == "unknown"


def test_unknown_history_and_two_journals_fail_closed(setup):
    for name in ("a.sqlite", "b.sqlite"):
        db = sqlite3.connect(setup[2] / name)
        db.execute("CREATE TABLE example (id INT)")
        db.close()
    result = inspect(setup)
    assert result.status == "unknown"
    assert "multiple_journals" in result.reasons


def test_valid_existing_history_no_receipt_no_sqlite(setup, monkeypatch):
    host, manager, root, _ = setup
    journal = root / "agent.sqlite"
    db = sqlite3.connect(journal)
    db.execute("CREATE TABLE intents (id INT)")
    db.close()
    ident = device_id(
        "mumu", f"{os.path.normcase(str(manager.resolve()))}:0", host_id=host.read_text().strip()
    )
    (root / f"device-{hashlib.sha256(ident.encode()).hexdigest()}.lock").write_bytes(b"0")
    before = snapshot(root)
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: pytest.fail("SQLite opened"))
    result = inspect(setup, expected_journal=journal)
    assert result.status == "existing"
    assert result.runtime_state == "unverified"
    assert result.launch_allowed is False
    assert snapshot(root) == before


def test_any_reservation_preserved_and_unknown(setup):
    marker = setup[2] / "replay-fixture.json"
    marker.write_text('{"status":"stopped"}')
    assert inspect(setup).status == "unknown"
    assert marker.read_text() == '{"status":"stopped"}'


def test_missing_explicit_journal_does_not_become_history(setup):
    result = inspect(setup, expected_journal=setup[2] / "missing.sqlite")
    assert result.status == "unknown"


def test_symlink_does_not_follow(setup, tmp_path, symlink_or_skip):
    link = setup[2] / "link"
    symlink_or_skip(link, tmp_path, target_is_directory=True)
    assert inspect(setup).status == "unknown"


def test_host_helper_never_bootstraps(setup, monkeypatch):
    from swu_happyrun.drivers.command import ProbeError
    from swu_happyrun.drivers.mumu.enrollment_inspection import read_existing_host_id

    expected = setup[0].read_text().strip()
    assert read_existing_host_id() == expected
    setup[0].unlink()
    with pytest.raises(ProbeError) as error:
        read_existing_host_id()
    assert error.value.code == "host_identity_unavailable"
    assert not setup[0].exists()
    setup[0].write_text("not-a-uuid")
    with pytest.raises(ProbeError) as error:
        read_existing_host_id()
    assert error.value.code == "host_identity_invalid"


def test_denied_root_is_unknown(setup, monkeypatch):
    real = os.scandir

    def denied(path):
        if path == setup[2]:
            raise PermissionError("private path not to be disclosed")
        return real(path)

    monkeypatch.setattr(os, "scandir", denied)
    result = inspect(setup)
    assert result.status == "unknown"
    assert "root_inspection_failed" in result.reasons
    assert "private path" not in str(result.public_summary())


def test_no_write_flags_used(setup, monkeypatch):
    real = os.open

    def checked(path, flags, *args, **kwargs):
        assert not flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
        return real(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", checked)
    assert inspect(setup).status == "first_use_review_required"


def test_mutable_journal_content_not_pinned(setup):
    from swu_happyrun.agent.journal import RunJournal

    host, manager, root, _ = setup
    ident = device_id(
        "mumu", f"{os.path.normcase(str(manager.resolve()))}:0", host_id=host.read_text().strip()
    )
    journal = root / "agent.sqlite"
    with RunJournal(journal) as db:
        with db.device_lock(ident):
            pass
    before = inspect(setup, expected_journal=journal)
    assert before.status == "existing"
    with RunJournal(journal) as db:
        db.record_intent(str(uuid4()), 1, "start")
    after = inspect(setup, expected_journal=journal)
    # Inventory may still find the original file; it explicitly cannot assert
    # absence of starts, current SQL validity, reservation clearance or ready.
    assert after.status == "existing"
    assert after.runtime_state == "unverified"
    assert after.launch_allowed is False
    assert "sha256" not in after.identity_sources


def test_sidecars_and_zero_byte_lock_fail_closed(setup):
    host, manager, root, _ = setup
    journal = root / "agent.sqlite"
    db = sqlite3.connect(journal)
    db.execute("CREATE TABLE data (id INT)")
    db.close()
    ident = device_id(
        "mumu", f"{os.path.normcase(str(manager.resolve()))}:0", host_id=host.read_text().strip()
    )
    lock = root / f"device-{hashlib.sha256(ident.encode()).hexdigest()}.lock"
    lock.write_bytes(b"")
    assert inspect(setup, expected_journal=journal).status == "unknown"
    lock.write_bytes(b"0")
    (root / "agent.sqlite-wal").write_bytes(b"partial")
    assert inspect(setup, expected_journal=journal).status == "unknown"


def test_default_root_included_even_with_host_override(setup, monkeypatch):
    root = setup[2].parent / "alternate"
    root.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(root))
    monkeypatch.setenv("LOCALAPPDATA", str(root))
    expected = str(root / "swu-happyrun")
    assert expected in {entry.path for entry in inspect(setup).roots}


def test_manifest_script_zero_side_effects(setup, tmp_path, capsys, monkeypatch):
    import json
    import runpy
    import subprocess
    from pathlib import Path

    main = runpy.run_path(str(Path(__file__).parents[2] / "scripts/mumu_enrollment_inspect.py"))[
        "main"
    ]
    manifest = tmp_path / "manifest.json"
    value = {
        "schema": 1,
        "manager": str(setup[1]),
        "instance_index": "0",
        "expected_journal": None,
        "roots": [str(setup[2])],
        "journal_arguments": [],
        "working_directories": [],
        "configuration_sources": [],
        "unchecked_categories": [],
        "declared_complete": True,
    }
    manifest.write_text(json.dumps(value))
    before = snapshot(tmp_path)
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: pytest.fail("SQLite opened"))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("process started"))
    assert main(["--manifest", str(manifest)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "first_use_review_required"
    assert output["launch_allowed"] is False
    assert str(tmp_path) not in str(output)
    assert snapshot(tmp_path) == before
    value["unchecked_categories"] = ["other_accounts"]
    manifest.write_text(json.dumps(value))
    assert main(["--manifest", str(manifest)]) == 3
    assert json.loads(capsys.readouterr().out)["unchecked_category_count"] == 1


@pytest.mark.parametrize("content", ["{", '{"schema":1,"schema":1}', "[]", "null"])
def test_manifest_script_malformed(setup, tmp_path, capsys, content):
    import json
    import runpy
    from pathlib import Path

    main = runpy.run_path(str(Path(__file__).parents[2] / "scripts/mumu_enrollment_inspect.py"))[
        "main"
    ]
    manifest = tmp_path / "manifest.json"
    manifest.write_text(content)
    assert main(["--manifest", str(manifest)]) == 3
    output = json.loads(capsys.readouterr().out)
    assert output["reason_codes"] == ["manifest_invalid"]
    assert str(tmp_path) not in str(output)
    manifest.unlink()
    assert main(["--manifest", str(manifest)]) == 3
    assert not manifest.exists()
    capsys.readouterr()
    assert main(["--control-root", "secret"]) == 3
    assert "secret" not in capsys.readouterr().out


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO unsupported")
def test_fifo_host_rejected_before_open(setup, monkeypatch):
    from swu_happyrun.drivers.command import ProbeError
    from swu_happyrun.drivers.mumu.enrollment_inspection import read_existing_host_id

    setup[0].unlink()
    os.mkfifo(setup[0])
    real = os.open

    def checked(path, flags, *args, **kwargs):
        if path == setup[0]:
            pytest.fail("FIFO opened")
        return real(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", checked)
    with pytest.raises(ProbeError):
        read_existing_host_id()
    assert inspect(setup).status == "unknown"


def test_header_only_forgery_not_existing(setup):
    host, manager, root, _ = setup
    journal = root / "agent.sqlite"
    journal.write_bytes(b"SQLite format 3\x00" + b"\x10\x00\x01\x01" + b"\x00" * 80)
    ident = device_id(
        "mumu", f"{os.path.normcase(str(manager.resolve()))}:0", host_id=host.read_text().strip()
    )
    (root / f"device-{hashlib.sha256(ident.encode()).hexdigest()}.lock").write_bytes(b"0")
    assert inspect(setup, expected_journal=journal).status == "unknown"
