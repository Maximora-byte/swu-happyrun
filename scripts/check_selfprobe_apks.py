"""Inspect built APKs with official SDK tools; never infer actual ART activation."""

import argparse
import json
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ANDROID = "{http://schemas.android.com/apk/res/android}"
ENTRY = "org.happyrun.app.selfprobe.SelfDiagnosticModule"


def verify_manifest(xml, optional):
    root = ET.fromstring(xml)
    assert root.attrib["package"] == "org.happyrun.app"
    assert not root.findall("uses-permission")
    metadata = {
        node.attrib[ANDROID + "name"]: node.attrib for node in root.findall("application/meta-data")
    }
    module = {name for name in metadata if name.startswith("xposed")}
    if optional:
        assert module == {"xposedmodule", "xposeddescription", "xposedminversion", "xposedscope"}
        assert metadata["xposedmodule"][ANDROID + "value"] == "true"
        assert metadata["xposedminversion"][ANDROID + "value"] == "82"
        assert metadata["xposedscope"].get(ANDROID + "resource") in {
            "@array/happyrun_self_probe_scope",
            "@org.happyrun.app:array/happyrun_self_probe_scope",
        }, "Scope metadata must point to the exact array inspected below"
    else:
        assert not module


def verify_classes(output, optional):
    classes = {
        line.split()[-1]
        for line in (raw.strip() for raw in output.splitlines())
        if line.startswith("C ") and line.split()[1] == "d"
    }
    assert classes, "SDK tool returned no defined classes"
    assert not any(name.startswith("de.robv.android.xposed.") for name in classes)
    assert (ENTRY in classes) == optional


def verify_scope_value(value):
    # Only documented-looking exact single values are accepted; never concatenate entries.
    value = value.strip()
    if value == "org.happyrun.app":
        return
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        raise AssertionError(f"Unexpected scope rendering: {value!r}") from None
    assert parsed == ["org.happyrun.app"], f"Unexpected scope rendering: {value!r}"


def inspect(apk, optional, analyzer):
    def run(*args):
        return subprocess.check_output([analyzer, *args, str(apk)], text=True, timeout=120)

    verify_manifest(run("manifest", "print"), optional)
    verify_classes(run("dex", "packages", "--defined-only"), optional)
    with zipfile.ZipFile(apk) as archive:
        if optional:
            assert archive.read("assets/xposed_init").decode().strip() == ENTRY
        else:
            assert "assets/xposed_init" not in archive.namelist()
    if optional:
        configs = run("resources", "configs", "--type", "array").splitlines()
        assert configs
        for config in configs:
            value = run(
                "resources",
                "value",
                "--config",
                config.strip(),
                "--type",
                "array",
                "--name",
                "happyrun_self_probe_scope",
            ).strip()
            verify_scope_value(value)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apkanalyzer", required=True)
    parser.add_argument("--debug", type=Path, required=True)
    parser.add_argument("--optional", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    inspect(args.debug, False, args.apkanalyzer)
    inspect(args.optional, True, args.apkanalyzer)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps({"static_apk_checks": "passed", "art_activation": "not_tested"}) + "\n"
    )
