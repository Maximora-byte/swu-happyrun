"""Exercise both regression sites under deterministic host capability failures."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "node",
    [
        "tests/agent/test_mumu_binding.py::test_private_output_refuses_outside_local_and_symlinks",
        "tests/delivery/test_android_ci_phase.py::test_symlink_rejected",
    ],
)
@pytest.mark.parametrize("failure", ["privilege", "io"])
def test_symlink_fixture_failure_classification(tmp_path, node, failure):
    root = Path(__file__).resolve().parents[2]
    plugin = tmp_path / "synthetic_symlink_failure.py"
    plugin.write_text(
        "import errno\n"
        "from pathlib import Path\n"
        "import pytest\n"
        "@pytest.fixture(autouse=True)\n"
        "def unavailable(monkeypatch):\n"
        "    def fail(*args, **kwargs):\n"
        "        error = OSError(errno.EIO, 'synthetic fixture failure')\n"
        + ("        error.winerror = 1314\n" if failure == "privilege" else "")
        + "        raise error\n"
        "    monkeypatch.setattr(Path, 'symlink_to', fail)\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(tmp_path), env.get("PYTHONPATH", "")])
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-rs", "-p", "synthetic_symlink_failure", node],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    output = result.stdout + result.stderr
    if failure == "privilege":
        assert result.returncode == 0, output
        assert "1 skipped" in output, output
        assert "WinError 1314" in output, output
    else:
        assert result.returncode == 1, output
        assert "1 failed" in output, output
        assert "synthetic fixture failure" in output, output
        assert "1 skipped" not in output, output
