"""Portable fixture classification tests; no elevated OS permissions required."""

import errno
from pathlib import Path

import pytest


def test_supported_symlink_calls_real_creation(tmp_path, symlink_or_skip):
    target = tmp_path / "target"
    target.write_text("synthetic")
    link = tmp_path / "link"
    symlink_or_skip(link, target)
    assert link.is_symlink()
    assert link.read_text() == "synthetic"


@pytest.mark.parametrize(
    "error",
    [
        OSError(errno.ENOSYS, "unsupported"),
        OSError(errno.EOPNOTSUPP, "unsupported"),
        NotImplementedError(),
    ],
)
def test_explicit_unsupported_skips(monkeypatch, tmp_path, error, symlink_or_skip):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(Path, "symlink_to", fail)
    with pytest.raises(pytest.skip.Exception, match="symlink fixture unavailable"):
        symlink_or_skip(tmp_path / "link", tmp_path / "target")


def test_windows_1314_skips_precisely(monkeypatch, tmp_path, symlink_or_skip):
    error = OSError("synthetic privilege failure")
    error.winerror = 1314

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(Path, "symlink_to", fail)
    with pytest.raises(pytest.skip.Exception, match="WinError 1314"):
        symlink_or_skip(tmp_path / "link", tmp_path / "target")


@pytest.mark.parametrize("code", [errno.EIO, errno.EACCES, errno.EPERM, errno.ENOENT])
def test_other_io_errors_still_fail(monkeypatch, tmp_path, code, symlink_or_skip):
    error = OSError(code, "synthetic unexpected I/O")

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(Path, "symlink_to", fail)
    with pytest.raises(OSError) as observed:
        symlink_or_skip(tmp_path / "link", tmp_path / "target")
    assert observed.value is error


def test_supported_operation_is_not_skipped(monkeypatch, tmp_path, symlink_or_skip):
    calls = []
    monkeypatch.setattr(Path, "symlink_to", lambda link, target: calls.append((link, target)))
    link, target = tmp_path / "link", tmp_path / "target"
    symlink_or_skip(link, target)
    assert calls == [(link, target)]


def test_other_windows_error_is_not_skipped(monkeypatch, tmp_path, symlink_or_skip):
    error = OSError(errno.EACCES, "synthetic access denied")
    error.winerror = 5

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(Path, "symlink_to", fail)
    with pytest.raises(OSError) as observed:
        symlink_or_skip(tmp_path / "link", tmp_path / "target")
    assert observed.value is error
