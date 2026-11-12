"""Bounded public build evidence from an explicitly disposable official AVD only."""

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

PROPERTIES = {
    "fingerprint": "ro.build.fingerprint",
    "build_id": "ro.build.id",
    "sdk": "ro.build.version.sdk",
    "release": "ro.build.version.release",
}


def prop(serial, name):
    try:
        result = subprocess.run(
            ["adb", "-s", serial, "shell", "getprop", name],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
            check=True,
        )
        value = result.stdout.strip()
        return value if re.fullmatch(r"[A-Za-z0-9._:/+,-]{1,512}", value) else None
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return None


def collect(env):
    serial = env.get("ANDROID_SERIAL", "")
    api = env.get("HAPPYRUN_ANDROID_API")
    if (
        env.get("HAPPYRUN_DISPOSABLE_EMULATOR") != "1"
        or not re.fullmatch(r"emulator-[0-9]+", serial)
        or api not in {"31", "35"}
    ):
        raise ValueError("disposable_avd_required")
    if prop(serial, "ro.kernel.qemu") != "1":
        raise ValueError("qemu_required")
    tag = "default" if api == "31" else "google_apis"
    revision = None
    try:
        source = (
            Path(env["ANDROID_HOME"])
            / f"system-images/android-{api}/{tag}/x86_64/source.properties"
        ).read_text(encoding="utf-8")
        match = re.search(r"(?m)^Pkg\.Revision\s*=\s*([0-9.]{1,32})\s*$", source)
        if match:
            revision = match[1]
    except (KeyError, OSError, UnicodeError):
        pass
    fields = {key: prop(serial, name) for key, name in PROPERTIES.items()}
    fields["system_image_revision"] = revision
    return {
        "scope": "disposable_official_avd_public_build_only",
        "system_image": f"system-images;android-{api};{tag};x86_64",
        "fields": {
            key: {"status": "observed" if value is not None else "unknown", "value": value}
            for key, value in fields.items()
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = collect(os.environ)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
