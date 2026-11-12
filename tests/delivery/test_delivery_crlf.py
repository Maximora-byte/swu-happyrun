"""Windows machine-output line endings, with exact private capture evidence."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import check_local_https_delivery as delivery
from check_android_delivery_pair import certificate, same_certificate

DIGEST = "ab" * 32
LINE = "Signer #1 certificate SHA-256 digest: " + DIGEST


def captured(text, **kwargs):
    raw = text.encode("utf-8")
    return delivery.run([sys.executable, "-c", f"import os; os.write(1, {raw!r})"], **kwargs)


@pytest.mark.parametrize("ending", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_sdk_signer_text_normalizes_only_line_endings(ending, tmp_path):
    # Representative SDK35 verbose layout; signer digest is a synthetic identity.
    text = ending.join(
        [
            "Verifies",
            "Verified using v1 scheme (JAR signing): false",
            "Verified using v2 scheme (APK Signature Scheme v2): true",
            "Number of signers: 1",
            "Signer #1 certificate DN: CN=Android Debug",
            LINE,
            "Signer #1 certificate SHA-1 digest: " + "cd" * 20,
            "",
        ]
    )
    evidence = tmp_path / "private"
    output = captured(text, private_evidence=evidence)
    assert output == text.replace("\r\n", "\n")
    assert certificate(output) == DIGEST
    assert same_certificate([output, LINE + "\n"]) == DIGEST
    assert (evidence / "stdout.bin").read_bytes() == text.encode()
    report = json.loads((evidence / "capture.json").read_text(encoding="utf-8"))
    assert report["stdout"] == {
        "size": len(text.encode()),
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
    }


@pytest.mark.parametrize(
    "bad",
    [
        LINE + "\r",
        LINE + "\r\r\n",
        LINE + " \r\n",
        LINE + "\t\r\n",
        " " + LINE + "\r\n",
        LINE + " unexpected\r\n",
        LINE[:-1] + "g\r\n",
        LINE[:-1] + "\r\n",
        LINE + "\u2028",
        LINE + "\x00\r\n",
        LINE + "\r\n" + LINE + "\r\n",
        LINE + "\r\n" + LINE.replace("#1", "#2") + "\r\n",
    ],
    ids=[
        "cr",
        "crcrlf",
        "space",
        "tab",
        "indent",
        "suffix",
        "nonhex",
        "short",
        "unicode-separator",
        "nul",
        "duplicate",
        "multiple",
    ],
)
def test_signer_malformed_or_ambiguous_output_still_rejected(bad):
    with pytest.raises(ValueError, match="Exactly one verified APK signer"):
        certificate(captured(bad))


def test_different_valid_signers_still_reject_pair():
    with pytest.raises(ValueError, match="certificates differ"):
        same_certificate(
            [captured(LINE + "\r\n"), captured(LINE.replace(DIGEST, "cd" * 32) + "\r\n")]
        )


@pytest.mark.parametrize(
    "text",
    [
        '<?xml version="1.0"?>\r\n<manifest package="org.happyrun.app">\r\n</manifest>\r\n',
        "Package name=org.happyrun.app id=7f\r\n"
        "    resource 0x7f010001 xml/remote_qa_network_security\r\n",
        "-----BEGIN PUBLIC KEY-----\r\nYWJj\r\n-----END PUBLIC KEY-----\r\n",
        "abc\r\ndef\nghi\rjkl\r\r\n",
    ],
    ids=["xml", "resource", "openssl", "mixed"],
)
def test_machine_text_boundary_does_not_trim_or_translate_other_characters(text):
    assert captured(text) == text.replace("\r\n", "\n")
