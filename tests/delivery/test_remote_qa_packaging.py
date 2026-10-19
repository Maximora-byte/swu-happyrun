"""Synthetic APK zip fixtures: test trust is isolated; no Android pass is inferred."""

import importlib.util
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "qa_packaging", ROOT / "scripts/check_remote_qa_packaging.py"
)
assert SPEC and SPEC.loader
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


def apk(tmp_path, files):
    path = tmp_path / "synthetic.apk"
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return path


def manifest(monkeypatch, extra=""):
    xml = (
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android">'
        '<application android:usesCleartextTraffic="false" ' + extra + "/></manifest>"
    )
    monkeypatch.setattr(CHECK.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=xml))


def test_ordinary_has_no_test_trust(tmp_path, monkeypatch):
    manifest(monkeypatch)
    CHECK.check(
        apk(tmp_path, {"classes.dex": b"synthetic"}),
        "official-analyzer",
        qa=False,
        ca=tmp_path / "unused",
    )


@pytest.mark.parametrize(
    "files",
    [
        {"res/raw/remote_qa_ca.pem": b"public synthetic"},
        {"assets/renamed": b"-----BEGIN PRIVATE KEY-----"},
        {"assets/renamed": b"-----BEGIN RSA PRIVATE KEY-----"},
        {"assets/renamed": b"-----BEGIN CERTIFICATE-----"},
    ],
)
def test_ordinary_rejects_qa_or_key_material(tmp_path, monkeypatch, files):
    manifest(monkeypatch)
    with pytest.raises(ValueError):
        CHECK.check(apk(tmp_path, files), "official-analyzer", qa=False, ca=tmp_path / "unused")


def test_ordinary_rejects_network_override(tmp_path, monkeypatch):
    manifest(monkeypatch, 'android:networkSecurityConfig="@xml/anything"')
    with pytest.raises(ValueError):
        CHECK.check(apk(tmp_path, {}), "official-analyzer", qa=False, ca=tmp_path / "unused")


def test_qa_requires_this_job_ca_and_debuggable(tmp_path, monkeypatch):
    ca = tmp_path / "public.pem"
    ca.write_bytes(b"-----BEGIN CERTIFICATE-----synthetic")
    path = apk(tmp_path, {"res/raw/remote_qa_ca.pem": ca.read_bytes()})
    manifest(
        monkeypatch,
        'android:debuggable="true" android:networkSecurityConfig="@xml/remote_qa_network_security"',
    )
    CHECK.check(path, "official-analyzer", qa=True, ca=ca)
    ca.write_bytes(b"other job")
    with pytest.raises(ValueError):
        CHECK.check(path, "official-analyzer", qa=True, ca=ca)


def test_one_gate_shared_by_six_job_matrix(tmp_path):
    legacy = (ROOT / ".github/workflows/checks.yml").read_text(encoding="utf-8")
    remote = (ROOT / ".github/workflows/android-remote-https.yml").read_text(encoding="utf-8")
    for workflow in (legacy, remote):
        assert "run: python scripts/check_ci_kvm.py" in workflow
        assert "github.event.before == 'b4ca97743f64a52b4981fbcf338899de008b52bc'" in workflow
        assert "github.ref == 'refs/heads/dot/android-foreground-agent'" in workflow
        assert "github.event.after == github.sha" in workflow
    assert "remoteQa" in remote and "app-release-unsigned.apk" in remote
    artifact = remote.split("path: |", 1)[1].split("if-no-files-found", 1)[0]
    assert ".apk" not in artifact and ".pem" not in artifact and ".key" not in artifact
    assert "HAPPYRUN_ANDROID_APK" in remote
