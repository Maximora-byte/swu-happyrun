import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location(
    "local_delivery", SCRIPTS / "check_local_https_delivery.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize(
    "host", ["example.com", "8.8.8.8", "0.0.0.0", "::", "10.0.0.1:443", "user@127.0.0.1"]
)
def test_reject_non_explicit_local_ip(host):
    with pytest.raises(ValueError):
        module.local_host(host)


@pytest.mark.parametrize(
    "host", ["127.0.0.1", "192.168.1.2", "10.10.2.3", "172.16.1.2", "::1", "fd00::1"]
)
def test_explicit_local_ip(host):
    assert module.local_host(host) == host


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"-----BEGIN PRIVATE KEY-----x",
        b"-----BEGIN CERTIFICATE-----\nYWJj\n-----END CERTIFICATE-----\nsecret",
    ],
)
def test_only_public_certificate(tmp_path, data):
    path = tmp_path / "cert.pem"
    path.write_bytes(data)
    with pytest.raises(ValueError):
        module.public_pem(path)


def test_resource_reference_must_bind_exactly():
    table = (
        "Package name=org.happyrun.app id=7f\n"
        "    resource 0x7f010001 xml/remote_qa_network_security\n"
    )
    module.bind_reference("@7f010001", "xml/remote_qa_network_security", table)
    with pytest.raises(ValueError):
        module.bind_reference("@7f010002", "xml/remote_qa_network_security", table)
    with pytest.raises(ValueError):
        module.bind_reference("@7f010001", "xml/remote_qa_network_security", table + table)


def test_openssl_requires_chain_ip_purpose_and_no_global_store(monkeypatch, tmp_path):
    cert = tmp_path / "public.pem"
    cert.write_bytes(b"-----BEGIN CERTIFICATE-----\nYWJj\n-----END CERTIFICATE-----\n")
    commands = []
    leaf = tmp_path / "leaf.pem"
    leaf.write_bytes(cert.read_bytes().replace(b"YWJj", b"ZGVm"))

    def openssl(command):
        commands.append(command)
        if "-pubkey" in command:
            return "-----BEGIN PUBLIC KEY-----" + command[command.index("-in") + 1]
        if "-ext" in command:
            return (
                "CA:TRUE Certificate Sign"
                if str(cert) in command
                else "CA:FALSE Digital Signature TLS Web Server Authentication"
            )
        return ""

    monkeypatch.setattr(module, "run", openssl)
    assert module.verify_certificates(cert, leaf, "192.168.1.3", "openssl") == "192.168.1.3"
    command = commands[-1]
    assert all(
        flag in command
        for flag in [
            "-x509_strict",
            "-purpose",
            "sslserver",
            "-no-CApath",
            "-no-CAstore",
            "-verify_ip",
        ]
    )
    assert command[command.index("-verify_ip") + 1] == "192.168.1.3"


def qa_inputs():
    app = (
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android" '
        'package="org.happyrun.app" '
        'android:versionCode="1" android:versionName="0.1">'
        '<application android:debuggable="true" android:networkSecurityConfig="@7f010001" />'
        "</manifest>"
    )
    test = (
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android" '
        'package="org.happyrun.app.test">'
        '<instrumentation android:targetPackage="org.happyrun.app" '
        'android:name="android.test.InstrumentationTestRunner" />'
        "</manifest>"
    )
    table = (
        "Package name=org.happyrun.app id=7f\n"
        "    resource 0x7f010001 xml/remote_qa_network_security\n"
        "    resource 0x7f020001 raw/remote_qa_ca\n"
    )
    config = (
        "<network-security-config>"
        '<base-config cleartextTrafficPermitted="false">'
        "<trust-anchors>"
        '<certificates src="system" />'
        "</trust-anchors>"
        "</base-config>"
        "<debug-overrides>"
        "<trust-anchors>"
        '<certificates src="@7f020001" />'
        "</trust-anchors>"
        "</debug-overrides>"
        "</network-security-config>"
    )
    return app, test, table, config


def test_exact_qa_policy():
    assert module.qa_manifest(*qa_inputs())["app_package"] == "org.happyrun.app"


@pytest.mark.parametrize(
    "old,new",
    [
        ("false", "true"),
        ("system", "user"),
        ("@7f020001", "@7f020002"),
        ("</network-security-config>", "<domain-config /></network-security-config>"),
    ],
)
def test_qa_policy_mutations_rejected(old, new):
    app, test, table, config = qa_inputs()
    with pytest.raises(ValueError):
        module.qa_manifest(app, test, table, config.replace(old, new))


def test_build_requires_exact_clean_source(monkeypatch, tmp_path):
    import build_local_https_delivery as builder

    for values in (
        [module.SOURCE_COMMIT, module.SOURCE_TREE, " M file"],
        ["bad", module.SOURCE_TREE, ""],
        [module.SOURCE_COMMIT, "bad", ""],
    ):
        sequence = iter(values)
        monkeypatch.setattr(builder, "run", lambda _command, sequence=sequence: next(sequence))
        with pytest.raises(ValueError):
            builder.source_identity(tmp_path)


def test_manifest_host_mismatch_rejected(monkeypatch, tmp_path):
    import json

    report = {
        "schema_version": 1,
        "source": {"commit": module.SOURCE_COMMIT, "tree": module.SOURCE_TREE},
        "host": "10.0.0.1",
        "runtime_status": "not_run",
        "temporary_debug_signature": True,
        "tool_sha256": "a" * 64,
        "validator_sha256": "b" * 64,
        "adapter": None,
        "runtime_capabilities": [],
    }
    report.update({"ca_sha256": "c" * 64, "server_certificate_sha256": "d" * 64, "pairs": {}})
    (tmp_path / "delivery.json").write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(module, "verify_certificates", lambda *_args: "10.0.0.2")
    monkeypatch.setattr(module, "public_pem", lambda *_args: b"public")
    with pytest.raises(ValueError, match="host_mismatch"):
        module.verify_bundle(
            tmp_path,
            "ca",
            "leaf",
            "10.0.0.2",
            openssl="o",
            apksigner="s",
            apkanalyzer="a",
            aapt2="r",
        )


def test_build_failure_cleans_only_created_public_ca(monkeypatch, tmp_path):
    import argparse

    import build_local_https_delivery as builder

    source = tmp_path / "source"
    source.mkdir()
    ca = tmp_path / "ca.pem"
    ca.write_text("public fixture", encoding="utf-8")
    args = argparse.Namespace(
        source_root=source,
        output=tmp_path / "bundle",
        ca_cert=ca,
        server_cert=ca,
        host="10.0.0.1",
        openssl="openssl",
        gradle="gradle",
        adapter=None,
        adapter_commit=None,
    )
    monkeypatch.setattr(builder, "source_identity", lambda _: {})
    monkeypatch.setattr(builder, "verify_certificates", lambda *_: "10.0.0.1")
    commands = []

    def fake(command, **kwargs):
        commands.append(command)
        if len(commands) == 2:
            raise ValueError("build failed")

    monkeypatch.setattr(builder, "run", fake)
    with pytest.raises(ValueError):
        builder.build(args)
    assert not (source / "android/app/build/generated/remoteQa/res/raw/remote_qa_ca.pem").exists()
    assert ca.read_text(encoding="utf-8") == "public fixture"
    assert not (tmp_path / "bundle/delivery.json").exists()
    assert commands[0][-3:] == ["clean", "assembleDebug", "assembleDebugAndroidTest"]
    assert commands[1][-3:] == [
        "-PremoteQaInstrumentation",
        "assembleRemoteQa",
        "assembleRemoteQaAndroidTest",
    ]


def test_existing_generated_ca_is_never_overwritten(monkeypatch, tmp_path):
    import argparse

    import build_local_https_delivery as builder

    source = tmp_path / "source"
    ca = source / "android/app/build/generated/remoteQa/res/raw/remote_qa_ca.pem"
    ca.parent.mkdir(parents=True)
    ca.write_text("existing", encoding="utf-8")
    args = argparse.Namespace(
        source_root=source,
        output=tmp_path / "bundle",
        ca_cert=ca,
        server_cert=ca,
        host="10.0.0.1",
        openssl="openssl",
        adapter=None,
        adapter_commit=None,
    )
    monkeypatch.setattr(builder, "source_identity", lambda _: {})
    monkeypatch.setattr(builder, "verify_certificates", lambda *_: "10.0.0.1")
    with pytest.raises(ValueError, match="already_exists"):
        builder.build(args)
    assert ca.read_text(encoding="utf-8") == "existing"
    assert not args.output.exists()


def test_four_apks_same_build_and_cleanup(monkeypatch, tmp_path):
    import argparse

    import build_local_https_delivery as builder

    source = tmp_path / "source"
    source.mkdir()
    ca = tmp_path / "ca.pem"
    ca.write_text("public", encoding="utf-8")
    adapter = tmp_path / "RemoteMumuHttpsAcceptanceTest.java"
    adapter.write_text("fixture Java", encoding="utf-8")
    args = argparse.Namespace(
        source_root=source,
        output=tmp_path / "bundle",
        ca_cert=ca,
        server_cert=ca,
        host="10.0.0.1",
        openssl="openssl",
        gradle="gradle",
        adapter=adapter,
        adapter_commit="a" * 40,
        apksigner="s",
        apkanalyzer="a",
        aapt2="r",
    )
    monkeypatch.setattr(
        builder,
        "source_identity",
        lambda _: {"commit": module.SOURCE_COMMIT, "tree": module.SOURCE_TREE},
    )
    monkeypatch.setattr(builder, "verify_certificates", lambda *_: "10.0.0.1")
    calls = []

    def gradle(command, **kwargs):
        calls.append((command, kwargs))
        if len(calls) == 2:
            assert (source / builder.ADAPTER).read_text(encoding="utf-8") == "fixture Java"
            for path in builder.OUTPUTS.values():
                target = source / "android/app/build/outputs" / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"synthetic APK")

    monkeypatch.setattr(builder, "run", gradle)
    monkeypatch.setattr(builder, "inspect_pairs", lambda *_a, **_k: {"synthetic": True})
    monkeypatch.setattr(builder, "verify_bundle", lambda *_a, **_k: {})
    report = builder.build(args)
    assert set(p.name for p in args.output.iterdir()) == set(builder.OUTPUTS) | {
        "ca.pem",
        "server.pem",
        "delivery.json",
        "SHA256SUMS",
    }
    assert report["adapter"]["files"][0]["sha256"] == module.digest(adapter)
    assert report["source"]["commit"] == module.SOURCE_COMMIT
    assert report["runtime_status"] == "not_run"
    assert all(kwargs["timeout"] == 1800 for _, kwargs in calls)
    assert not (source / builder.ADAPTER).exists()
    assert not (source / "android/app/build/generated/remoteQa/res/raw/remote_qa_ca.pem").exists()


@pytest.mark.parametrize("extra", ["secret.key", "database.sqlite", "unexpected.apk"])
def test_bundle_extra_entries_rejected(tmp_path, extra):
    (tmp_path / extra).write_text("synthetic", encoding="utf-8")
    with pytest.raises(ValueError, match="unexpected_bundle_entry"):
        module.verify_bundle(
            tmp_path,
            "ca",
            "leaf",
            "10.0.0.1",
            openssl="o",
            apksigner="s",
            apkanalyzer="a",
            aapt2="r",
        )


def test_pair_signature_mismatch_rejected(monkeypatch, tmp_path):
    import zipfile

    app_xml, test_xml, _, _ = qa_inputs()
    app_xml = app_xml.replace(' android:networkSecurityConfig="@7f010001"', "")
    for name in module.FILES["ordinary"]:
        with zipfile.ZipFile(tmp_path / name, "w") as archive:
            archive.writestr("classes.dex", b"synthetic")
    monkeypatch.setattr(module, "check", lambda *_a, **_k: None)

    def command(args):
        if "manifest" in args:
            return test_xml if args[-1].endswith("-test.apk") else app_xml
        return (
            "Signer #1 certificate SHA-256 digest: "
            + ("b" if args[-1].endswith("-test.apk") else "a") * 64
        )

    monkeypatch.setattr(module, "run", command)
    with pytest.raises(ValueError, match="app_test_signature_mismatch"):
        module.inspect_pairs(tmp_path, "ca", apksigner="s", apkanalyzer="a", aapt2="r")


@pytest.mark.parametrize(
    "leaf",
    [
        "CA:TRUE Certificate Sign Digital Signature TLS Web Server Authentication",
        "CA:FALSE Digital Signature",
        "CA:FALSE TLS Web Server Authentication",
    ],
)
def test_reject_leaf_without_exact_roles(monkeypatch, tmp_path, leaf):
    ca = tmp_path / "ca.pem"
    cert = tmp_path / "leaf.pem"
    for path in (ca, cert):
        path.write_bytes(b"-----BEGIN CERTIFICATE-----\nYWJj\n-----END CERTIFICATE-----\n")
    cert.write_bytes(cert.read_bytes().replace(b"YWJj", b"ZGVm"))

    def fake_openssl(command):
        if "-pubkey" in command:
            return "-----BEGIN PUBLIC KEY-----" + command[command.index("-in") + 1]
        return "CA:TRUE Certificate Sign" if str(ca) in command else leaf

    monkeypatch.setattr(module, "run", fake_openssl)
    with pytest.raises(ValueError, match="certificate_"):
        module.verify_certificates(ca, cert, "10.0.0.1", "openssl")


@pytest.mark.parametrize(
    "patch",
    [
        {"tool_sha256": "bad"},
        {"validator_sha256": "bad"},
        {"runtime_capabilities": ["mumu-own-simulation-v1"]},
        {
            "adapter": {
                "source_commit": "a" * 40,
                "files": [{"path": "../../bad.java", "sha256": "a" * 64}],
            }
        },
    ],
)
def test_reject_false_adapter_or_tool_claim(monkeypatch, tmp_path, patch):
    import json

    report = {
        "schema_version": 1,
        "source": {"commit": module.SOURCE_COMMIT, "tree": module.SOURCE_TREE},
        "runtime_status": "not_run",
        "temporary_debug_signature": True,
        "tool_sha256": "a" * 64,
        "validator_sha256": "b" * 64,
        "adapter": None,
        "runtime_capabilities": [],
    }
    report.update(
        {
            "host": "10.0.0.1",
            "ca_sha256": "c" * 64,
            "server_certificate_sha256": "d" * 64,
            "pairs": {},
        }
    )
    report.update(patch)
    (tmp_path / "delivery.json").write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(
        module, "verify_certificates", lambda *_: pytest.fail("must reject before tools")
    )
    with pytest.raises(ValueError):
        module.verify_bundle(
            tmp_path,
            "ca",
            "leaf",
            "10.0.0.1",
            openssl="o",
            apksigner="s",
            apkanalyzer="a",
            aapt2="r",
        )


@pytest.mark.parametrize("data", [{"unexpected_private_input": "synthetic"}, [], None])
def test_unknown_top_level_fields_rejected(tmp_path, data):
    import json

    (tmp_path / "delivery.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="schema_fields"):
        module.verify_bundle(
            tmp_path,
            "ca",
            "leaf",
            "10.0.0.1",
            openssl="o",
            apksigner="s",
            apkanalyzer="a",
            aapt2="r",
        )
