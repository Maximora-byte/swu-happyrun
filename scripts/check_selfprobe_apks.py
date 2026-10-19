"""Inspect built APKs with official SDK tools; never infer actual ART activation."""

import argparse
import json
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ANDROID = "{http://schemas.android.com/apk/res/android}"
ENTRY = "org.happyrun.app.selfprobe.SelfDiagnosticModule"


def verify_manifest(xml, optional, scope_id=None):
    root = ET.fromstring(xml)
    assert root.attrib["package"] == "org.happyrun.app"
    assert [node.attrib[ANDROID + "name"] for node in root.findall("uses-permission")] in (
        [],
        ["android.permission.INTERNET"],
    )
    assert not root.findall("uses-permission-sdk-23")
    metadata = {
        node.attrib[ANDROID + "name"]: node.attrib for node in root.findall("application/meta-data")
    }
    module = {name for name in metadata if name.startswith("xposed")}
    if optional:
        assert module == {"xposedmodule", "xposeddescription", "xposedminversion", "xposedscope"}
        assert metadata["xposedmodule"][ANDROID + "value"] == "true"
        assert metadata["xposedminversion"][ANDROID + "value"] == "82"
        reference = metadata["xposedscope"].get(ANDROID + "resource", "")
        symbolic = reference in {
            "@array/happyrun_self_probe_scope",
            "@org.happyrun.app:array/happyrun_self_probe_scope",
        }
        numeric = re.fullmatch(r"@(?:ref/)?(?:0x)?([0-9a-fA-F]{8})", reference)
        assert symbolic or (
            numeric is not None and scope_id is not None and int(numeric.group(1), 16) == scope_id
        ), f"Scope metadata is not bound to the verified resource: {reference!r}"
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


def verify_resource_table(output):
    """Bind the compiled resource ID to its exact name and every configuration value."""
    lines = [line.rstrip() for line in output.splitlines() if line.strip()]
    packages = [line for line in lines if line.startswith("Package ")]
    assert packages == ["Package name=org.happyrun.app id=7f"]
    resources = []
    for index, line in enumerate(lines):
        match = re.fullmatch(r"    resource (0x[0-9a-fA-F]{8}) (\S+)", line)
        if match:
            resources.append((index, int(match.group(1), 16), match.group(2)))
    targets = [entry for entry in resources if entry[2] == "array/happyrun_self_probe_scope"]
    assert len(targets) == 1, "Exactly one named scope array required"
    start, scope_id, _ = targets[0]
    assert sum(entry[1] == scope_id for entry in resources) == 1
    end = start + 1
    while end < len(lines) and lines[end].startswith("      "):
        end += 1
    block = lines[start + 1 : end]
    assert block and len(block) % 2 == 0
    configs = set()
    for i in range(0, len(block), 2):
        config = re.fullmatch(r"      \(([^)]*)\) \(array\) size=1", block[i])
        assert config and config.group(1) not in configs
        configs.add(config.group(1))
        assert block[i + 1].startswith("        [")
        verify_scope_value(block[i + 1].strip())
    assert "" in configs, "Default scope configuration required"
    return scope_id


def inspect(apk, optional, analyzer, aapt2):
    def run(*args):
        return subprocess.check_output(
            [analyzer, *args, str(apk)], text=True, encoding="utf-8", timeout=120
        )

    scope_id = None
    if optional:
        table = subprocess.check_output(
            [aapt2, "dump", "resources", str(apk)], text=True, encoding="utf-8", timeout=120
        )
        scope_id = verify_resource_table(table)
    verify_manifest(run("manifest", "print"), optional, scope_id)
    verify_classes(run("dex", "packages", "--defined-only"), optional)
    with zipfile.ZipFile(apk) as archive:
        if optional:
            assert archive.read("assets/xposed_init").decode().strip() == ENTRY
        else:
            assert "assets/xposed_init" not in archive.namelist()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apkanalyzer", required=True)
    parser.add_argument("--aapt2", required=True)
    parser.add_argument("--debug", type=Path, required=True)
    parser.add_argument("--optional", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    inspect(args.debug, False, args.apkanalyzer, args.aapt2)
    inspect(args.optional, True, args.apkanalyzer, args.aapt2)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps({"static_apk_checks": "passed", "art_activation": "not_tested"}) + "\n"
    )
