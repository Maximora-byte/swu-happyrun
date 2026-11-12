"""Reject temporary TLS trust in every user-distributable Android variant."""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ANDROID = "{http://schemas.android.com/apk/res/android}"


def check(apk: Path, analyzer: str, *, qa: bool, ca: Path):
    result = subprocess.run(
        [analyzer, "manifest", "print", str(apk)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    check_manifest(apk, result.stdout, qa=qa, ca=ca)


def check_manifest(apk: Path, manifest_xml: str, *, qa: bool, ca: Path):
    """Apply unchanged trust guards to an already captured manifest."""
    app = ET.fromstring(manifest_xml).find("application")
    if app is None or app.get(ANDROID + "usesCleartextTraffic") != "false":
        raise ValueError("APK must explicitly disallow cleartext")
    config = app.get(ANDROID + "networkSecurityConfig")
    with zipfile.ZipFile(apk) as archive:
        names = archive.namelist()
        qa_resources = [name for name in names if "remote_qa" in name]
        for name in names:
            data = archive.read(name)
            if re.search(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----", data):
                raise ValueError("Private key must never be packaged")
            if not qa and b"-----BEGIN CERTIFICATE-----" in data:
                raise ValueError("User APK contains a bundled PEM trust anchor")
        if qa:
            if app.get(ANDROID + "debuggable") != "true" or config is None:
                raise ValueError("QA-only trust requires debuggable test APK")
            anchors = [name for name in qa_resources if "remote_qa_ca" in name]
            if (
                len(anchors) != 1
                or hashlib.sha256(archive.read(anchors[0])).digest()
                != hashlib.sha256(ca.read_bytes()).digest()
            ):
                raise ValueError(
                    "QA certificate resource must match this job's temporary public CA"
                )
        elif config is not None or qa_resources:
            raise ValueError("User APK contains temporary test trust")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--analyzer", required=True)
    parser.add_argument("--ca", type=Path, required=True)
    parser.add_argument("--qa", type=Path, required=True)
    parser.add_argument("ordinary", nargs="+", type=Path)
    args = parser.parse_args()
    for apk in args.ordinary:
        check(apk, args.analyzer, qa=False, ca=args.ca)
    check(args.qa, args.analyzer, qa=True, ca=args.ca)
    print("Temporary trust isolated from all ordinary APKs")


if __name__ == "__main__":
    main()
