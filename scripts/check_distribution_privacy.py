"""Reject Android local state/signing material in Python distributions."""

import argparse
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "artifacts",
        nargs="*",
        type=Path,
        help="Exact wheel/sdist files; omit to check both kinds under ./dist",
    )
    args = parser.parse_args()
    if args.artifacts:
        paths = args.artifacts
    else:
        wheels = list(Path("dist").glob("*.whl"))
        sources = list(Path("dist").glob("*.tar.gz"))
        if not wheels or not sources:
            parser.error("Missing wheel or source distribution")
        paths = wheels + sources
    for path in paths:
        if not path.is_file() or not (path.name.endswith(".whl") or path.name.endswith(".tar.gz")):
            parser.error("Expected an existing wheel or source distribution file")
    for path in paths:
        if path.name.endswith(".whl"):
            with zipfile.ZipFile(path) as archive:
                check(archive.namelist())
        else:
            with tarfile.open(path) as archive:
                check(archive.getnames())
    print(f"Distribution Android privacy checks passed: {len(paths)} artifacts")


if __name__ == "__main__":
    main()
