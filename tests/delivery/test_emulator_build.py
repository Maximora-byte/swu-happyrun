import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "emulator_build", ROOT / "scripts/check_emulator_build.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def environment(tmp_path):
    return {
        "HAPPYRUN_DISPOSABLE_EMULATOR": "1",
        "ANDROID_SERIAL": "emulator-5554",
        "HAPPYRUN_ANDROID_API": "31",
        "ANDROID_HOME": str(tmp_path),
    }


@pytest.mark.parametrize(
    "key,value",
    [
        ("ANDROID_SERIAL", "user-device"),
        ("HAPPYRUN_DISPOSABLE_EMULATOR", "0"),
        ("HAPPYRUN_ANDROID_API", "30"),
    ],
)
def test_guard_rejects_before_any_query(monkeypatch, tmp_path, key, value):
    env = environment(tmp_path)
    env[key] = value
    monkeypatch.setattr(MODULE, "prop", lambda *args: pytest.fail("must not query"))
    with pytest.raises(ValueError):
        MODULE.collect(env)


def test_non_qemu_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(MODULE, "prop", lambda *args: "0")
    with pytest.raises(ValueError, match="qemu_required"):
        MODULE.collect(environment(tmp_path))


def test_only_fixed_public_properties_and_revision(monkeypatch, tmp_path):
    source = tmp_path / "system-images/android-31/default/x86_64/source.properties"
    source.parent.mkdir(parents=True)
    source.write_text("Pkg.Revision=5\nPrivate=excluded\n", encoding="utf-8")
    queried = []

    def run(command, **kwargs):
        assert command[:5] == ["adb", "-s", "emulator-5554", "shell", "getprop"]
        assert len(command) == 6 and kwargs["timeout"] == 5
        queried.append(command[-1])
        return SimpleNamespace(stdout="1" if command[-1] == "ro.kernel.qemu" else "synthetic-build")

    monkeypatch.setattr(MODULE.subprocess, "run", run)
    result = MODULE.collect(environment(tmp_path))
    assert queried == ["ro.kernel.qemu", *MODULE.PROPERTIES.values()]
    assert result["fields"]["system_image_revision"] == {"status": "observed", "value": "5"}
    assert "excluded" not in json.dumps(result)
    assert "emulator-5554" not in json.dumps(result)


def test_missing_values_are_explicit_unknown(monkeypatch, tmp_path):
    monkeypatch.setattr(
        MODULE, "prop", lambda serial, name: "1" if name == "ro.kernel.qemu" else None
    )
    fields = MODULE.collect(environment(tmp_path))["fields"]
    assert all(value == {"status": "unknown", "value": None} for value in fields.values())


@pytest.mark.parametrize("value", ["private value\nextra", "x" * 513, ""])
def test_unbounded_or_free_text_not_recorded(monkeypatch, value):
    monkeypatch.setattr(MODULE.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=value))
    assert MODULE.prop("emulator-5554", "ro.build.id") is None


def test_failed_query_has_no_exception_message(monkeypatch):
    def failed(*args, **kwargs):
        raise subprocess.TimeoutExpired("private-object", 5)

    monkeypatch.setattr(MODULE.subprocess, "run", failed)
    assert MODULE.prop("emulator-5554", "ro.build.id") is None


def test_capture_before_install_and_exact_artifact():
    script = (ROOT / "scripts/android_emulator_test.sh").read_text(encoding="utf-8")
    assert script.index("check_emulator_build.py") < script.index("adb install -r")
    workflow = (ROOT / ".github/workflows/checks.yml").read_text(encoding="utf-8")
    assert workflow.count("qa/android/emulator-build.json") == 2
