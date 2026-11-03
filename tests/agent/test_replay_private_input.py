"""Replay inputs must be bounded regular files before device construction."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from swu_happyrun.drivers.base import DriverError
from swu_happyrun.drivers.mumu.virtual_replay import read_private_json


def test_private_input_preserves_json_and_duplicate_key_validation(tmp_path):
    source = tmp_path / "binding.json"
    source.write_text('{"name":"合成 fixture"}', encoding="utf-8")
    assert read_private_json(source) == {"name": "合成 fixture"}
    source.write_text('{"value":1,"value":2}', encoding="utf-8")
    with pytest.raises(ValueError):
        read_private_json(source)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFO regression")
def test_private_input_rejects_fifo_without_waiting_for_writer(tmp_path):
    source = tmp_path / "binding.json"
    os.mkfifo(source)
    script = """
from pathlib import Path
import sys
from swu_happyrun.drivers.base import DriverError
from swu_happyrun.drivers.mumu.virtual_replay import read_private_json
try:
    read_private_json(Path(sys.argv[1]))
except DriverError as error:
    assert error.reason_code == 'replay_input_invalid'
else:
    raise AssertionError('FIFO accepted')
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(source)],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_private_input_bounds_content_even_if_metadata_is_stale(tmp_path, monkeypatch):
    source = tmp_path / "binding.json"
    source.write_text("{}", encoding="utf-8")
    before = source.stat()
    source.write_bytes(b" " * 1_000_001 + b"{}")
    real_stat = Path.stat
    real_lstat = Path.lstat

    def stale_stat(path, *args, **kwargs):
        return before if path == source else real_stat(path, *args, **kwargs)

    def stale_lstat(path, *args, **kwargs):
        return before if path == source else real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stale_stat)
    monkeypatch.setattr(Path, "lstat", stale_lstat)
    monkeypatch.setattr(os, "fstat", lambda fd: before)
    with pytest.raises(DriverError, match="replay_input_invalid"):
        read_private_json(source)


def test_private_input_rejects_directory(tmp_path):
    with pytest.raises(DriverError, match="replay_input_invalid"):
        read_private_json(tmp_path)


def test_private_input_rejects_link(tmp_path):
    source = tmp_path / "binding.json"
    source.write_text(json.dumps({"binding": "synthetic"}), encoding="utf-8")
    link = tmp_path / "link.json"
    try:
        link.symlink_to(source)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(DriverError, match="replay_input_invalid"):
        read_private_json(link)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFO regression")
def test_private_input_rejects_fifo_swapped_after_inspection(tmp_path, monkeypatch):
    source = tmp_path / "binding.json"
    source.write_text("{}", encoding="utf-8")
    real_open = os.open

    def replace_with_fifo(path, flags, *args, **kwargs):
        if Path(path) == source:
            source.unlink()
            os.mkfifo(source)
            # Assert the bounded-open guard before actually opening the FIFO.
            assert flags & os.O_NONBLOCK
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", replace_with_fifo)
    with pytest.raises(DriverError, match="replay_input_invalid"):
        read_private_json(source)


def test_private_input_rejects_replaced_regular_file(tmp_path, monkeypatch):
    source = tmp_path / "binding.json"
    source.write_text("{}", encoding="utf-8")
    replacement = tmp_path / "replacement.json"
    replacement.write_text('{"changed":true}', encoding="utf-8")
    real_open = os.open

    def replace_before_open(path, flags, *args, **kwargs):
        if Path(path) == source:
            replacement.replace(source)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", replace_before_open)
    with pytest.raises(DriverError, match="replay_input_invalid"):
        read_private_json(source)


def test_private_input_allows_exact_byte_limit(tmp_path):
    source = tmp_path / "binding.json"
    source.write_bytes(b" " * 999_998 + b"{}")
    assert read_private_json(source) == {}
