"""Check the shipped package hashes before installing; never scans user data."""

import hashlib
import json
from pathlib import Path


def main():
    root = Path(__file__).absolute().parent
    manifest = json.loads((root / "SHA256SUMS.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not 1 <= len(manifest) <= 100:
        raise ValueError("package_manifest_invalid")
    for name, digest in manifest.items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or ":" in name:
            raise ValueError("package_manifest_invalid")
        path = root / relative
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("package_hash_mismatch")
    print("HappyRun package hashes verified.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, TypeError):
        print("Package verification failed. Use the original complete delivery folder.")
        raise SystemExit(2) from None
