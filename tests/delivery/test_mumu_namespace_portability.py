"""Keep real JVM core coverage when host symlink fixtures are unavailable."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("failure", ["privilege", "enosys", "eopnotsupp", "io"])
def test_namespace_symlink_capability_is_separate_from_core(tmp_path, failure):
    if shutil.which("java") is None:
        pytest.skip("JVM unavailable; not Android validation")
    root = Path(__file__).resolve().parents[2]
    plugin = tmp_path / "synthetic_namespace_symlink_failure.py"
    error_code = {"enosys": "ENOSYS", "eopnotsupp": "EOPNOTSUPP"}.get(failure, "EIO")
    plugin.write_text(
        "import errno\n"
        "from pathlib import Path\n"
        "import pytest\n"
        "@pytest.fixture(autouse=True)\n"
        "def unavailable(monkeypatch):\n"
        "    def fail(*args, **kwargs):\n"
        f"        error = OSError(errno.{error_code}, 'synthetic fixture failure')\n"
        + ("        error.winerror = 1314\n" if failure == "privilege" else "")
        + "        raise error\n"
        "    monkeypatch.setattr(Path, 'symlink_to', fail)\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(tmp_path), env.get("PYTHONPATH", "")])
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-rs",
            "-p",
            "synthetic_namespace_symlink_failure",
            "tests/delivery/test_mumu_namespace_jvm.py",
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
    )
    output = result.stdout + result.stderr
    if "JDK compiler unavailable" in output:
        pytest.skip("JDK compiler unavailable")
    assert "1 passed" in output, output
    if failure == "io":
        assert result.returncode == 1, output
        assert "3 failed" in output, output
        assert "synthetic fixture failure" in output, output
        assert "skipped" not in output, output
    else:
        assert result.returncode == 0, output
        assert "3 skipped" in output, output
        reason = "WinError 1314" if failure == "privilege" else "explicitly unsupported"
        assert reason in output, output
