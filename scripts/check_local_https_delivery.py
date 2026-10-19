"""Offline public-certificate and same-build APK verification; never accepts private keys."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from check_android_delivery_pair import ANDROID, certificate, manifests
from check_remote_qa_packaging import check

SOURCE_COMMIT = "9534f51efe3a557e6b4bda5605426e4004a34783"
SOURCE_TREE = "53d6858c01b982e1143436018d7201e934c4ee58"
ADAPTER_PATH = (
    "android/app/src/remoteQaAndroidTest/java/org/happyrun/app/remoteqa/"
    "RemoteMumuHttpsAcceptanceTest.java"
)
FILES = {
    "ordinary": ("ordinary.apk", "ordinary-test.apk"),
    "remoteQa": ("remoteQa.apk", "remoteQa-test.apk"),
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command, *, timeout=120):
    result = subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8", errors="strict", timeout=timeout
    )
    if result.returncode:
        raise ValueError("external_verification_failed")
    return result.stdout


def local_host(value):
    address = ipaddress.ip_address(value)
    networks = (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "127.0.0.0/8",
        "fc00::/7",
        "::1/128",
    )
    if not any(address in ipaddress.ip_network(n) for n in networks):
        raise ValueError("explicit_private_or_loopback_ip_required")
    return str(address)


def public_pem(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 16384:
        raise ValueError("public_certificate_file_required")
    data = path.read_bytes()
    if not re.fullmatch(
        rb"\s*-----BEGIN CERTIFICATE-----\r?\n[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE-----\s*", data
    ):
        raise ValueError("exactly_one_public_certificate_required")
    return data


def verify_certificates(ca, leaf, host, openssl):
    host = local_host(host)
    public_pem(ca)
    public_pem(leaf)
    if digest(ca) == digest(leaf):
        raise ValueError("ca_and_leaf_must_differ")
    keys = [run([openssl, "x509", "-in", str(path), "-noout", "-pubkey"]) for path in (ca, leaf)]
    if not all("-----BEGIN PUBLIC KEY-----" in key for key in keys) or keys[0] == keys[1]:
        raise ValueError("ca_and_leaf_public_keys_must_differ")
    for path, is_ca in ((ca, True), (leaf, False)):
        extensions = run(
            [
                openssl,
                "x509",
                "-in",
                str(path),
                "-noout",
                "-ext",
                "basicConstraints,keyUsage,extendedKeyUsage",
            ]
        )
        required = (
            ("CA:TRUE", "Certificate Sign")
            if is_ca
            else ("CA:FALSE", "Digital Signature", "TLS Web Server Authentication")
        )
        if any(item not in extensions for item in required):
            raise ValueError("certificate_constraints_missing")
        if ("CA:TRUE" in extensions) != is_ca:
            raise ValueError("certificate_role_mismatch")
    run([openssl, "x509", "-in", str(ca), "-noout", "-checkend", "0"])
    run([openssl, "x509", "-in", str(leaf), "-noout", "-checkend", "0"])
    run(
        [
            openssl,
            "verify",
            "-x509_strict",
            "-purpose",
            "sslserver",
            "-CAfile",
            str(ca),
            "-no-CApath",
            "-no-CAstore",
            "-verify_ip",
            host,
            str(leaf),
        ]
    )
    return host


def bind_reference(reference, name, table):
    if table.count("Package name=org.happyrun.app id=7f") != 1:
        raise ValueError("unexpected_resource_package")
    rows = re.findall(r"^    resource (0x[0-9a-fA-F]{8}) (\S+)\s*$", table, re.M)
    matches = [identifier.lower()[2:] for identifier, resource in rows if resource == name]
    if (
        len(matches) != 1
        or sum(identifier.lower()[2:] == matches[0] for identifier, _ in rows) != 1
    ):
        raise ValueError("resource_binding_ambiguous")
    if reference not in ("@" + name, "@" + matches[0], "@0x" + matches[0], "@ref/0x" + matches[0]):
        raise ValueError("resource_reference_mismatch")


def qa_manifest(app_xml, test_xml, table, config_xml):
    root = ET.fromstring(app_xml)
    app = root.find("application")
    if app is None or app.get(ANDROID + "debuggable") != "true":
        raise ValueError("qa_debug_only")
    bind_reference(
        app.get(ANDROID + "networkSecurityConfig"), "xml/remote_qa_network_security", table
    )
    # Reuse ordinary identity validation only after independently checking the QA trust reference.
    del app.attrib[ANDROID + "networkSecurityConfig"]
    identity = manifests(ET.tostring(root, encoding="unicode"), test_xml)
    config = ET.fromstring(config_xml)
    expected = ET.fromstring(
        """<network-security-config>
        <base-config cleartextTrafficPermitted="false"><trust-anchors>
        <certificates src="system" /></trust-anchors></base-config>
        <debug-overrides><trust-anchors><certificates src="@raw/remote_qa_ca" />
        </trust-anchors></debug-overrides></network-security-config>"""
    )
    nodes = config.findall("./debug-overrides/trust-anchors/certificates")
    if len(nodes) != 1:
        raise ValueError("qa_anchor_count")
    bind_reference(nodes[0].get("src"), "raw/remote_qa_ca", table)
    nodes[0].set("src", "@raw/remote_qa_ca")

    def shape(node):
        if (node.text or "").strip() or (node.tail or "").strip():
            raise ValueError("unexpected_xml_text")
        return node.tag, sorted(node.attrib.items()), [shape(child) for child in node]

    if shape(config) != shape(expected):
        raise ValueError("qa_network_policy_mismatch")
    return identity


def inspect_pairs(bundle, ca, *, apksigner, apkanalyzer, aapt2):
    pairs = {}
    for variant, names in FILES.items():
        app, test = (Path(bundle) / name for name in names)
        if any(not p.is_file() or p.is_symlink() for p in (app, test)):
            raise ValueError("missing_regular_apk")
        app_xml, test_xml = [run([apkanalyzer, "manifest", "print", str(p)]) for p in (app, test)]
        check(app, apkanalyzer, qa=variant == "remoteQa", ca=Path(ca))
        # Test APK must not embed keys or additional trust, in either group.
        import zipfile

        with zipfile.ZipFile(test) as archive:
            for name in archive.namelist():
                data = archive.read(name)
                if b"-----BEGIN " in data or "remote_qa" in name:
                    raise ValueError("test_apk_contains_trust_material")
        if variant == "ordinary":
            identity = manifests(app_xml, test_xml)
        else:
            identity = qa_manifest(
                app_xml,
                test_xml,
                run([aapt2, "dump", "resources", str(app)]),
                run(
                    [
                        apkanalyzer,
                        "resources",
                        "xml",
                        "--file",
                        "/res/xml/remote_qa_network_security.xml",
                        str(app),
                    ]
                ),
            )
        signers = [
            certificate(run([apksigner, "verify", "--verbose", "--print-certs", str(p)]))
            for p in (app, test)
        ]
        if signers[0] != signers[1]:
            raise ValueError("app_test_signature_mismatch")
        pairs[variant] = dict(
            identity,
            certificate_sha256=signers[0],
            app={"filename": names[0], "sha256": digest(app)},
            test={"filename": names[1], "sha256": digest(test)},
        )
    if pairs["ordinary"]["certificate_sha256"] != pairs["remoteQa"]["certificate_sha256"]:
        raise ValueError("build_group_signature_mismatch")
    return pairs


def verify_bundle(
    bundle_dir, ca_cert, server_cert, host, *, openssl, apksigner, apkanalyzer, aapt2
):
    bundle = Path(bundle_dir)
    allowed = {
        "ordinary.apk",
        "ordinary-test.apk",
        "remoteQa.apk",
        "remoteQa-test.apk",
        "ca.pem",
        "server.pem",
        "delivery.json",
        "SHA256SUMS",
    }
    if not bundle.is_dir() or bundle.is_symlink():
        raise ValueError("regular_bundle_directory_required")
    if any(p.name not in allowed or not p.is_file() or p.is_symlink() for p in bundle.iterdir()):
        raise ValueError("unexpected_bundle_entry")
    report = json.loads((bundle / "delivery.json").read_text(encoding="utf-8"))
    expected_fields = {
        "schema_version",
        "source",
        "tool_sha256",
        "validator_sha256",
        "host",
        "ca_sha256",
        "server_certificate_sha256",
        "adapter",
        "runtime_capabilities",
        "runtime_status",
        "temporary_debug_signature",
        "pairs",
    }
    if not isinstance(report, dict) or set(report) != expected_fields:
        raise ValueError("delivery_schema_fields_mismatch")
    if report.get("schema_version") != 1 or report.get("source") != {
        "commit": SOURCE_COMMIT,
        "tree": SOURCE_TREE,
    }:
        raise ValueError("unrecognized_product_source")
    if (
        report.get("runtime_status") != "not_run"
        or report.get("temporary_debug_signature") is not True
    ):
        raise ValueError("unexpected_runtime_or_signing_claim")
    for field in ("tool_sha256", "validator_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", report.get(field, "")):
            raise ValueError("invalid_tool_provenance")
    overlay = report.get("adapter")
    if overlay is None:
        if report.get("runtime_capabilities") != []:
            raise ValueError("adapter_capability_mismatch")
    else:
        if not isinstance(overlay, dict) or set(overlay) != {"source_commit", "files"}:
            raise ValueError("invalid_adapter_provenance")
        if not re.fullmatch(r"[0-9a-f]{40}", overlay.get("source_commit", "")):
            raise ValueError("invalid_adapter_commit")
        entries = overlay.get("files")
        if (
            not isinstance(entries, list)
            or len(entries) != 1
            or not isinstance(entries[0], dict)
            or set(entries[0]) != {"path", "sha256"}
            or entries[0].get("path") != ADAPTER_PATH
            or not re.fullmatch(r"[0-9a-f]{64}", entries[0].get("sha256", ""))
        ):
            raise ValueError("invalid_adapter_file")
        if report.get("runtime_capabilities") != ["mumu-own-simulation-v1"]:
            raise ValueError("adapter_capability_mismatch")
    host = verify_certificates(ca_cert, server_cert, host, openssl)
    if public_pem(bundle / "ca.pem") != public_pem(ca_cert) or public_pem(
        bundle / "server.pem"
    ) != public_pem(server_cert):
        raise ValueError("bundled_public_certificates_mismatch")
    if (
        report.get("host") != host
        or report.get("ca_sha256") != digest(ca_cert)
        or report.get("server_certificate_sha256") != digest(server_cert)
    ):
        raise ValueError("certificate_or_host_mismatch")
    if report.get("pairs") != inspect_pairs(
        bundle, ca_cert, apksigner=apksigner, apkanalyzer=apkanalyzer, aapt2=aapt2
    ):
        raise ValueError("artifact_metadata_mismatch")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "bundle",
        "ca-cert",
        "server-cert",
        "host",
        "openssl",
        "apksigner",
        "apkanalyzer",
        "aapt2",
    ):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    try:
        verify_bundle(
            args.bundle,
            args.ca_cert,
            args.server_cert,
            args.host,
            openssl=args.openssl,
            apksigner=args.apksigner,
            apkanalyzer=args.apkanalyzer,
            aapt2=args.aapt2,
        )
    except (ValueError, OSError, subprocess.SubprocessError, ET.ParseError):
        parser.exit(2, "Local delivery verification rejected; no runtime was executed.\n")
    print("Local delivery verified; runtime not_run")


if __name__ == "__main__":
    main()
