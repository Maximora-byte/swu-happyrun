"""Keep location foreground support confined to the optional own probe."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "foreground_apk_check", ROOT / "scripts/check_selfprobe_apks.py"
)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def manifest(optional):
    name = "selfProbe" if optional else "main"
    xml = (ROOT / f"android/app/src/{name}/AndroidManifest.xml").read_text(encoding="utf-8")
    return xml.replace("<manifest ", '<manifest package="org.happyrun.app" ')


def test_optional_service_is_nonexported_typed_and_not_in_ordinary_build():
    import xml.etree.ElementTree as ET

    attr = "{http://schemas.android.com/apk/res/android}"
    root = ET.fromstring(manifest(True))
    services = root.findall("application/service")
    assert len(services) == 1
    assert services[0].get(attr + "name") == "org.happyrun.app.selfprobe.ProbeLocationService"
    assert services[0].get(attr + "exported") == "false"
    assert services[0].get(attr + "foregroundServiceType") == "location"
    assert not ET.fromstring(manifest(False)).findall("application/service")


@pytest.mark.parametrize("optional", [False, True])
def test_background_permission_and_exported_services_rejected(optional):
    xml = manifest(optional)
    for injected in (
        '<uses-permission android:name="android.permission.ACCESS_BACKGROUND_LOCATION" />',
        '<uses-permission android:name="android.permission.FOREGROUND_SERVICE_CAMERA" />',
    ):
        with pytest.raises(AssertionError):
            checker.verify_manifest(
                xml.replace("<application>", injected + "<application>")
                if "<application>" in xml
                else xml.replace("<application ", injected + "<application "),
                optional,
            )
    injected = '<service android:name="foreign.Service" android:exported="true" />'
    with pytest.raises(AssertionError):
        checker.verify_manifest(
            xml.replace("</application>", injected + "</application>"), optional
        )


def test_valid_optional_service_passes_compiled_manifest_checker():
    xml = manifest(True)
    checker.verify_manifest(xml, True)
    for old, new in (
        ('android:exported="false"', 'android:exported="true"'),
        ('android:foregroundServiceType="location"', 'android:foregroundServiceType="camera"'),
    ):
        with pytest.raises(AssertionError):
            checker.verify_manifest(xml.replace(old, new), True)


def test_compiled_location_type_binds_exact_numeric_flag():
    xml = manifest(True).replace(
        'android:foregroundServiceType="location"', 'android:foregroundServiceType="0x8"'
    )
    checker.verify_manifest(xml, True)
    for flag in ("0x10", "0xc", "8junk"):
        with pytest.raises(AssertionError):
            checker.verify_manifest(
                xml.replace('foregroundServiceType="0x8"', f'foregroundServiceType="{flag}"'), True
            )
