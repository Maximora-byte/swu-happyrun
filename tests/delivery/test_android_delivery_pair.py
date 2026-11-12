"""Fail closed for mismatched ordinary APK/test delivery metadata."""

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "delivery_pair", Path(__file__).parents[2] / "scripts/check_android_delivery_pair.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
APP = """<manifest xmlns:android="http://schemas.android.com/apk/res/android"
package="org.happyrun.app" android:versionCode="1" android:versionName="0.1">
<application/></manifest>"""
TEST = """<manifest xmlns:android="http://schemas.android.com/apk/res/android"
package="org.happyrun.app.test"><instrumentation android:targetPackage="org.happyrun.app"
android:name="android.test.InstrumentationTestRunner"/></manifest>"""


def test_valid_pair_metadata():
    assert MODULE.manifests(APP, TEST)["version_code"] == "1"
    assert MODULE.certificate("Signer #1 certificate SHA-256 digest: " + "a" * 64) == "a" * 64


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "Signer #1 certificate SHA-256 digest: invalid",
        "Signer #1 certificate SHA-256 digest: "
        + "a" * 64
        + "\nSigner #2 certificate SHA-256 digest: "
        + "b" * 64,
    ],
)
def test_missing_or_multiple_signers_fail(bad):
    with pytest.raises(ValueError):
        MODULE.certificate(bad)


@pytest.mark.parametrize(
    "app,test",
    [
        (
            APP.replace(
                "<application/>", '<application android:networkSecurityConfig="@xml/test"/>'
            ),
            TEST,
        ),
        (APP, TEST.replace('targetPackage="org.happyrun.app"', 'targetPackage="another.app"')),
        (APP, TEST.replace("android.test.InstrumentationTestRunner", "unknown.Runner")),
        (APP.replace('package="org.happyrun.app"', 'package="unknown.app"'), TEST),
    ],
)
def test_wrong_target_or_test_trust_fails(app, test):
    with pytest.raises(ValueError):
        MODULE.manifests(app, test)


def test_different_valid_certificates_fail():
    with pytest.raises(ValueError, match="certificates differ"):
        MODULE.same_certificate(
            [
                "Signer #1 certificate SHA-256 digest: " + "a" * 64,
                "Signer #1 certificate SHA-256 digest: " + "b" * 64,
            ]
        )


def test_missing_version_is_rejected():
    with pytest.raises(ValueError, match="version"):
        MODULE.manifests(APP.replace('android:versionCode="1"', ""), TEST)
