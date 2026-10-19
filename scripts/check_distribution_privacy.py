"""Reject Android local state/signing material in Python distributions."""

import tarfile
import zipfile
from pathlib import Path, PurePosixPath


def check(names):
    for name in names:
        parts = PurePosixPath(name).parts
        if (
            any(part in {".gradle", ".kotlin", "build", "qa"} for part in parts)
            or PurePosixPath(name).name == "local.properties"
            or name.endswith((".apk", ".jks", ".keystore"))
        ):
            raise SystemExit(f"Private/generated Android path in distribution: {name}")


if __name__ == "__main__":
    wheels = list(Path("dist").glob("*.whl"))
    sources = list(Path("dist").glob("*.tar.gz"))
    if not wheels or not sources:
        raise SystemExit("Missing wheel or source distribution")
    for path in wheels:
        with zipfile.ZipFile(path) as archive:
            check(archive.namelist())
    for path in sources:
        with tarfile.open(path) as archive:
            check(archive.getnames())
    print("Distribution Android privacy checks passed")
