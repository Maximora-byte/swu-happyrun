"""Real localhost TLS, synthetic ephemeral test material only; never a device test."""

import importlib
import ssl
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


def fixture_module():
    assert (ROOT / "scripts/mumu_https_fixture.py").exists(), "separate bound-host fixture required"
    return importlib.import_module("mumu_https_fixture")


@pytest.fixture
def certificates():
    from remote_https_fixture import issue_certificates

    with tempfile.TemporaryDirectory(prefix="mumu-synthetic-tls-") as directory:
        yield issue_certificates(Path(directory))


def test_real_tls_fixture_natural_cleanup_and_exact_host(tmp_path, certificates):
    m = fixture_module()
    from remote_https_fixture import trusted_client

    certs = certificates
    with m.local_fixture(
        tmp_path / "case", certs["server.pem"], certs["server.key"], "127.0.0.1", 0, "normal"
    ) as fixture:
        with trusted_client(certs["ca.pem"]) as client:
            response = client.get(fixture["origin"] + "/api/v1/health")
            assert response.status_code == 200
            assert fixture["origin"] == fixture["android_origin"]
            assert fixture["origin"].startswith("https://127.0.0.1:")
        server = fixture["server"]
        thread = fixture["thread"]
    assert server.should_exit and not thread.is_alive()


def test_wrong_key_never_starts_fixture(tmp_path, certificates):
    m = fixture_module()
    certs = certificates
    with pytest.raises(ssl.SSLError):
        with m.local_fixture(
            tmp_path / "case", certs["server.pem"], certs["wrong.key"], "127.0.0.1", 0, "normal"
        ):
            pytest.fail("mismatched key reached body")


def test_wildcard_host_rejected_without_touching_files(tmp_path):
    m = fixture_module()
    with pytest.raises(ValueError):
        with m.local_fixture(
            tmp_path / "case", tmp_path / "missing", tmp_path / "missing", "0.0.0.0", 0, "normal"
        ):
            pytest.fail("wildcard accepted")
    assert not (tmp_path / "case").exists()
