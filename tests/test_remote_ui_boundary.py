"""Source boundary checks; these do not claim Android lifecycle execution."""

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "android/app/src/main"
A = "{http://schemas.android.com/apk/res/android}"


def test_token_field_is_not_saved_or_autofilled():
    root = ET.parse(MAIN / "res/layout/activity_remote_agent.xml").getroot()
    token = next(e for e in root.iter() if e.get(A + "id") == "@+id/remote_token")
    assert token.get(A + "saveEnabled") == "false"
    assert token.get(A + "importantForAutofill") == "noExcludeDescendants"
    assert token.get(A + "inputType") == "textPassword"


def test_activity_is_private_and_network_security_retained():
    root = ET.parse(MAIN / "AndroidManifest.xml").getroot()
    app = root.find("application")
    assert app.get(A + "usesCleartextTraffic") == "false"
    assert app.get(A + "allowBackup") == "false"
    remote = next(e for e in app.findall("activity") if e.get(A + "name") == ".RemoteAgentActivity")
    assert remote.get(A + "exported") == "false"
    assert any(
        e.get(A + "name") == "android.permission.INTERNET" for e in root.findall("uses-permission")
    )


def test_no_automatic_connect_and_no_token_preferences():
    source = (MAIN / "java/org/happyrun/app/RemoteAgentActivity.java").read_text()
    assert source.count("connectOnce()") == 2  # listener and definition only
    assert '.putString("token"' not in source
    assert '.putString("endpoint"' in source
    assert 'gate.leave();\n        token.setText("");' in source
    assert "driver.stop();\n            client.close();" in source
    assert "SystemClock.elapsedRealtimeNanos()" in source
    assert "worker.shutdownNow" not in source  # do not interrupt bounded stop report
    assert "getMessage()" not in source


def test_storage_initialization_and_wire_clock_fail_closed():
    source = (MAIN / "java/org/happyrun/app/RemoteAgentActivity.java").read_text()
    assert "catch (java.io.IOException storageFailure)" in source
    assert source.count("gate.block();") == 2
    assert source.count("Instant.now().truncatedTo(java.time.temporal.ChronoUnit.MICROS)") == 2
