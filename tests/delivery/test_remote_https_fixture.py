"""Real local OpenSSL/TLS checks; these do not substitute for Android tests."""

import importlib.util
import shutil
import ssl
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "remote_fixture", ROOT / "scripts/remote_https_fixture.py"
)
assert SPEC and SPEC.loader
FIXTURE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIXTURE)


@pytest.fixture(scope="module")
def certificates(tmp_path_factory):
    if shutil.which("openssl") is None:
        pytest.skip("official OpenSSL unavailable; no TLS result claimed")
    return FIXTURE.issue_certificates(tmp_path_factory.mktemp("remote-qa-ca"))


def test_real_https_server_and_authentication(tmp_path, certificates):
    with FIXTURE.server_fixture(tmp_path, certificates) as fixture:
        with FIXTURE.trusted_client(certificates["ca.pem"]) as client:
            origin = fixture["origin"]
            assert client.get(origin + "/api/v1/ready").status_code == 200
            assert client.get(origin + "/api/v1/jobs").status_code == 401
            response = client.post(
                origin + "/api/v1/devices",
                headers={"Authorization": "Bearer " + fixture["admin_token"]},
                json={"device_id": fixture["device_id"], "agent_id": fixture["agent_id"]},
            )
            assert response.status_code in {200, 201}
        assert fixture["evidence"].records
        assert fixture["agent_token"] not in repr(fixture["evidence"].records)
        assert fixture["admin_token"] not in repr(fixture["evidence"].records)


@pytest.mark.parametrize("certificate", ["wrong", "other"])
def test_tls_negative_fails_before_http(tmp_path, certificates, certificate):
    with FIXTURE.server_fixture(tmp_path, certificates, certificate) as fixture:
        with FIXTURE.trusted_client(certificates["ca.pem"]) as client:
            with pytest.raises(httpx.ConnectError):
                client.get(fixture["origin"] + "/api/v1/ready")
        assert fixture["evidence"].records == []


def test_system_trust_does_not_trust_test_ca(tmp_path, certificates):
    with FIXTURE.server_fixture(tmp_path, certificates) as fixture:
        with httpx.Client(
            verify=ssl.create_default_context(), trust_env=False, timeout=5
        ) as client:
            with pytest.raises(httpx.ConnectError):
                client.get(fixture["origin"] + "/api/v1/ready")
        assert fixture["evidence"].records == []


def test_report_rejects_credentials(tmp_path):
    with pytest.raises(ValueError):
        FIXTURE.redact_report(tmp_path / "report.json", {"agent_token": "synthetic"})
    assert not (tmp_path / "report.json").exists()


def test_certificate_chain_passes_strict_tls_verification(tmp_path, certificates):
    context = ssl.create_default_context(cafile=str(certificates["ca.pem"]))
    context.verify_flags |= ssl.VERIFY_X509_STRICT
    with FIXTURE.server_fixture(tmp_path, certificates) as fixture:
        with httpx.Client(verify=context, trust_env=False, timeout=5) as client:
            assert client.get(fixture["origin"] + "/api/v1/ready").status_code == 200
