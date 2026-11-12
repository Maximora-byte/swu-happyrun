"""Bind ordinary app/test APKs from one build to their verified signing identity."""

import argparse
import hashlib
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

ANDROID = "{http://schemas.android.com/apk/res/android}"


def certificate(output):
    values = re.findall(
        r"^Signer #\d+ certificate SHA-256 digest: ([0-9a-fA-F]{64})$", output, re.M
    )
    if len(values) != 1:
        raise ValueError("Exactly one verified APK signer is required")
    return values[0].lower()


def same_certificate(outputs):
    identities = [certificate(text) for text in outputs]
    if len(identities) != 2 or identities[0] != identities[1]:
        raise ValueError("App/test signing certificates differ")
    return identities[0]


def manifests(app_xml, test_xml):
    app, test = ET.fromstring(app_xml), ET.fromstring(test_xml)
    if app.attrib.get("package") != "org.happyrun.app":
        raise ValueError("Unexpected app package")
    if test.attrib.get("package") != "org.happyrun.app.test":
        raise ValueError("Unexpected test package")
    entries = test.findall("instrumentation")
    if len(entries) != 1 or entries[0].get(ANDROID + "targetPackage") != "org.happyrun.app":
        raise ValueError("Instrumentation target mismatch")
    if entries[0].get(ANDROID + "name") != "android.test.InstrumentationTestRunner":
        raise ValueError("Unexpected instrumentation runner")
    application = app.find("application")
    if application is None or ANDROID + "networkSecurityConfig" in application.attrib:
        raise ValueError("Ordinary app must not carry test trust configuration")
    version_code = app.get(ANDROID + "versionCode")
    version_name = app.get(ANDROID + "versionName")
    if not version_code or not version_code.isdigit() or not version_name:
        raise ValueError("Missing app version metadata")
    return {
        "app_package": app.attrib["package"],
        "test_package": test.attrib["package"],
        "version_code": app.get(ANDROID + "versionCode"),
        "version_name": app.get(ANDROID + "versionName"),
        "instrumentation_runner": entries[0].get(ANDROID + "name"),
    }


def run(command):
    return subprocess.run(command, check=True, capture_output=True, text=True, timeout=60).stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--test", type=Path, required=True)
    parser.add_argument("--apksigner", required=True)
    parser.add_argument("--apkanalyzer", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = manifests(
        run([args.apkanalyzer, "manifest", "print", str(args.app)]),
        run([args.apkanalyzer, "manifest", "print", str(args.test)]),
    )
    signed = [
        run([args.apksigner, "verify", "--verbose", "--print-certs", str(p)])
        for p in (args.app, args.test)
    ]
    report["certificate_sha256"] = same_certificate(signed)
    report["files"] = [
        {"role": role, "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for role, path in (("app", args.app), ("instrumentation", args.test))
    ]
    report["temporary_debug_signature"] = True
    report["device_acceptance"] = "not_tested_by_packaging_check"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    args.output.with_suffix(".signatures.txt").write_text(
        "APP\n" + signed[0] + "\nINSTRUMENTATION\n" + signed[1], encoding="utf-8"
    )
    args.output.with_suffix(".SHA256SUMS").write_text(
        "".join(f"{item['sha256']}  {item['path']}\n" for item in report["files"]), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
