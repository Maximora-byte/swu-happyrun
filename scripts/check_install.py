"""Install the built wheel in a fresh core-only environment and import outside src/."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    wheels = list((root / "dist").glob("swu_happyrun-*.whl"))
    if len(wheels) != 1:
        raise SystemExit("Expected exactly one wheel; clean dist and run uv build")
    with tempfile.TemporaryDirectory(prefix="swu-install-") as temp:
        folder = Path(temp)
        python = folder / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        subprocess.run(["uv", "venv", "--python", sys.executable, temp], check=True)
        subprocess.run(
            ["uv", "pip", "install", "--python", str(python), str(wheels[0])], check=True
        )
        subprocess.run(
            [
                str(python),
                "-I",
                "-c",
                "from swu_happyrun.core.models import JobSpec; "
                "from swu_happyrun.core.clock import SystemClock; "
                "import swu_happyrun.drivers.mumu.discovery; "
                "import importlib.util; "
                "assert importlib.util.find_spec('fastapi') is None; "
                "assert importlib.util.find_spec('httpx') is None; "
                "print('Core-only installed wheel imports successfully')",
            ],
            check=True,
            cwd=temp,
        )


if __name__ == "__main__":
    main()
