"""Schema 2 pins and package contents are checked against real clean Git input."""

import base64
import csv
import hashlib
import importlib
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))


builder = importlib.import_module("build_local_https_delivery")
legacy = importlib.import_module("check_local_https_delivery")
runner = importlib.import_module("check_mumu_https")
v2 = importlib.import_module("local_delivery_v2")


def test_schema2_module_exists():
    module = importlib.import_module("local_delivery_v2")
    assert module.FILES["selfProbe"] == ("selfProbe.apk", "selfProbe-test.apk")


def git(source, *args):
    return subprocess.check_output(["git", "-C", str(source), *args], encoding="utf-8").strip()


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "product checkout"
    root.mkdir()
    (root / "src/swu_happyrun").mkdir(parents=True)
    (root / "src/swu_happyrun/__init__.py").write_bytes(b'__version__ = "0.1.0"\n')
    (root / "src/swu_happyrun/route.json").write_bytes(b"{}\n")
    adapter = root / legacy.ADAPTER_PATH
    adapter.parent.mkdir(parents=True)
    adapter.write_bytes(b"// synthetic adapter, no device execution\n")
    (root / ".gitignore").write_text("build/\n__pycache__/\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[project]\nname="swu-happyrun"\nversion="0.1.0"\nrequires-python=">=3.11"\n'
        '[project.scripts]\nswu-happyrun="swu_happyrun.cli:main"\n',
        encoding="utf-8",
    )
    git(root, "init", "--quiet")
    git(root, "add", ".")
    git(
        root,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "synthetic clean product",
    )
    return root, git(root, "rev-parse", "HEAD"), git(root, "rev-parse", "HEAD^{tree}")


def write_wheel(path, root, *, changed=None, extra=None, metadata_change=None):
    contents = {
        name: b"tampered" if name == changed else data
        for name, data in v2.package_files(root).items()
    }
    prefix = "swu_happyrun-0.1.0.dist-info/"
    contents[prefix + "METADATA"] = b"Name: swu-happyrun\nVersion: 0.1.0\nRequires-Python: >=3.11\n"
    contents[prefix + "WHEEL"] = b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    contents[prefix + "entry_points.txt"] = (
        b"[console_scripts]\nswu-happyrun = swu_happyrun.cli:main\n"
    )
    if metadata_change:
        name, data = metadata_change
        contents[prefix + name] = data
    if extra:
        contents[extra] = b"unwanted"
    rows = []
    for name, data in contents.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode("ascii").rstrip("=")
        rows.append((name, "sha256=" + digest, str(len(data))))
    rows.append((prefix + "RECORD", "", ""))
    output = io.StringIO()
    csv.writer(output).writerows(rows)
    contents[prefix + "RECORD"] = output.getvalue().encode("utf-8")
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in contents.items():
            archive.writestr(name, data)


def test_clean_git_pins_are_required(source):
    root, head, tree = source
    assert v2.source_identity(root, head, tree) == {"commit": head, "tree": tree}
    for pins in ((None, None), (head, None), ("0" * 40, tree), (head, "0" * 40)):
        with pytest.raises(ValueError):
            v2.source_identity(root, *pins)
    (root / "src/swu_happyrun/__init__.py").write_bytes(b"changed")
    with pytest.raises(ValueError, match="clean_exact"):
        v2.source_identity(root, head, tree)


def test_untracked_source_rejected(source):
    root, head, tree = source
    (root / "src/new.py").write_bytes(b"untracked")
    with pytest.raises(ValueError, match="clean_exact"):
        v2.source_identity(root, head, tree)


@pytest.mark.parametrize("extra", ["../escape", "/absolute", "other/package.py", "evil\\file.py"])
def test_wheel_rejects_unknown_members(source, tmp_path, extra):
    wheel = tmp_path / "swu_happyrun-0.1.0-py3-none-any.whl"
    write_wheel(wheel, source[0], extra=extra)
    with pytest.raises(ValueError):
        v2.inspect_wheel(wheel, source[0])


def test_wheel_exact_module_and_resource_bytes(source, tmp_path):
    wheel = tmp_path / "swu_happyrun-0.1.0-py3-none-any.whl"
    write_wheel(wheel, source[0])
    assert len(v2.inspect_wheel(wheel, source[0])["package_files"]) == 2
    write_wheel(wheel, source[0], changed="swu_happyrun/route.json")
    with pytest.raises(ValueError, match="wheel_source_bytes"):
        v2.inspect_wheel(wheel, source[0])


def test_copy_never_overwrites(source, tmp_path):
    target = tmp_path / "retained"
    target.write_bytes(b"original")
    with pytest.raises(FileExistsError):
        v2.copy_exclusive(source[0] / ".gitignore", target)
    assert target.read_bytes() == b"original"


@pytest.fixture
def sdk(monkeypatch, source, tmp_path):
    """SDK/build process fake only. The real builder, parser and all verifiers run."""
    root, head, tree = source
    ca, leaf = tmp_path / "ca.pem", tmp_path / "leaf.pem"
    ca.write_bytes(b"-----BEGIN CERTIFICATE-----\nYWJj\n-----END CERTIFICATE-----\n")
    leaf.write_bytes(b"-----BEGIN CERTIFICATE-----\nZGVm\n-----END CERTIFICATE-----\n")
    monkeypatch.setattr(legacy, "verify_certificates", lambda ca, leaf, host, tool: host)
    actual_run = legacy.run
    calls = []
    states = {"signature": "a" * 64, "bad_variant": None, "bad_permission": None}
    table = (
        "Package name=org.happyrun.app id=7f\n"
        "    resource 0x7f010001 xml/remote_qa_network_security\n"
        "    resource 0x7f020001 raw/remote_qa_ca\n"
    )
    config = (
        '<network-security-config><base-config cleartextTrafficPermitted="false">'
        '<trust-anchors><certificates src="system" /></trust-anchors></base-config>'
        '<debug-overrides><trust-anchors><certificates src="@7f020001" />'
        "</trust-anchors></debug-overrides></network-security-config>"
    )
    test_xml = (
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android" '
        'package="org.happyrun.app.test"><instrumentation '
        'android:targetPackage="org.happyrun.app" '
        'android:name="android.test.InstrumentationTestRunner" /></manifest>'
    )

    def app_xml(variant):
        metadata = ""
        if variant == "selfProbe":
            metadata = (
                '<meta-data android:name="xposedmodule" android:value="true" />'
                '<meta-data android:name="xposeddescription" android:value="own probe" />'
                '<meta-data android:name="xposedminversion" android:value="82" />'
                '<meta-data android:name="xposedscope" '
                'android:resource="@array/happyrun_self_probe_scope" />'
            )
        trust = ' android:networkSecurityConfig="@7f010001"' if variant == "remoteQa" else ""
        permission = '<uses-permission android:name="android.permission.INTERNET" />'
        if states["bad_permission"] == variant:
            permission += (
                '<uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" />'
            )
        return (
            '<manifest xmlns:android="http://schemas.android.com/apk/res/android" '
            'package="org.happyrun.app" android:versionCode="1" android:versionName="0.1">'
            + permission
            + '<application android:debuggable="true" android:usesCleartextTraffic="false"'
            + trust
            + ">"
            + metadata
            + "</application></manifest>"
        )

    def run(command, **kwargs):
        calls.append(command)
        if command[0] == "git":
            return actual_run(command, **kwargs)
        if command[0] == "gradle":
            if "assembleSelfProbeAndroidTest" in command:
                assert "-PprobeInstrumentation" in command
            for name, relative in v2.OUTPUTS.items():
                path = root / "android/app/build/outputs" / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(path, "w") as archive:
                    archive.writestr("classes.dex", b"synthetic")
                    if name == "remoteQa.apk":
                        archive.writestr("res/raw/remote_qa_ca.pem", ca.read_bytes())
                    if name == "selfProbe.apk":
                        archive.writestr("assets/xposed_init", v2.ENTRY + "\n")
            return "BUILD SUCCESSFUL\n"
        if command[0] == sys.executable:
            out = Path(command[command.index("--outdir") + 1])
            write_wheel(out / "swu_happyrun-0.1.0-py3-none-any.whl", root)
            return "built\n"
        path = Path(command[-1])
        variant = path.name.split(".")[0].removesuffix("-test")
        if command[0] == "signer":
            cert = "b" * 64 if states["bad_variant"] == variant else states["signature"]
            return "Signer #1 certificate SHA-256 digest: " + cert + "\n"
        if command[0] == "aapt2":
            return (
                (
                    "Package name=org.happyrun.app id=7f\n"
                    "    resource 0x7f010002 array/happyrun_self_probe_scope\n"
                    '      () (array) size=1\n        ["org.happyrun.app"]\n'
                )
                if variant == "selfProbe"
                else table
            )
        if command[1:3] == ["manifest", "print"]:
            return test_xml if path.name.endswith("-test.apk") else app_xml(variant)
        if command[1] == "resources":
            return config
        if command[1] == "dex":
            return "C d 1 org.happyrun.app.MainActivity\n" + (
                "C d 1 " + v2.ENTRY + "\n" if variant == "selfProbe" else ""
            )
        raise AssertionError(command)

    monkeypatch.setattr(legacy, "run", run)
    args = SimpleNamespace(
        source_root=root,
        output=tmp_path / "new bundle",
        ca_cert=ca,
        server_cert=leaf,
        host="10.0.0.1",
        openssl="openssl",
        apksigner="signer",
        apkanalyzer="analyzer",
        aapt2="aapt2",
        gradle="gradle",
        adapter=None,
        adapter_commit=None,
        private_build_evidence=None,
        gradle_stderr_encoding="utf-8",
        expected_source_commit=head,
        expected_source_tree=tree,
    )
    return args, calls, states


def test_real_three_interfaces_schema2_fake_sdk_only(sdk):
    args, calls, _ = sdk
    report = builder.build(args)
    assert report["schema_version"] == 2
    assert set(report["pairs"]) == {"ordinary", "selfProbe", "remoteQa"}
    args.bundle = args.output
    assert runner.verify_public_bundle(args) == report
    assert len(list(args.output.iterdir())) == 11
    for field, invalid in (("expected_source_commit", None), ("expected_source_tree", "0" * 40)):
        old = getattr(args, field)
        setattr(args, field, invalid)
        with pytest.raises(ValueError):
            runner.verify_public_bundle(args)
        setattr(args, field, old)
    assert any("clean" in c for c in calls)
    assert not (
        args.source_root / "android/app/build/generated/remoteQa/res/raw/remote_qa_ca.pem"
    ).exists()


@pytest.mark.parametrize("variant", ["ordinary", "remoteQa"])
def test_location_permissions_not_allowed_in_nonoptional(sdk, variant):
    args, _, states = sdk
    states["bad_permission"] = variant
    with pytest.raises(AssertionError):
        builder.build(args)
    assert not (args.output / "delivery.json").exists()
    assert not (args.output / "SHA256SUMS").exists()


def test_cross_variant_signature_cannot_mix(sdk):
    args, _, states = sdk
    states["bad_variant"] = "selfProbe"
    with pytest.raises(ValueError, match="build_group_signature"):
        builder.build(args)


def test_manifest_unknown_fields_and_adapter_changes_rejected(sdk):
    args, _, _ = sdk
    builder.build(args)
    args.bundle = args.output
    path = args.output / "delivery.json"
    original = json.loads(path.read_text(encoding="utf-8"))
    for change in ({"unknown": "private"}, {"adapter": None}, {"runtime_status": "passed"}):
        path.write_text(json.dumps(original | change), encoding="utf-8")
        with pytest.raises(ValueError):
            runner.verify_public_bundle(args)
    path.write_text(json.dumps(original), encoding="utf-8")


@pytest.mark.parametrize(
    "missing", ["source_root", "expected_source_commit", "expected_source_tree"]
)
def test_schema2_requires_all_three_actual_source_inputs(sdk, missing):
    args, _, _ = sdk
    builder.build(args)
    args.bundle = args.output
    setattr(args, missing, None)
    with pytest.raises(ValueError):
        runner.verify_public_bundle(args)


def test_lexical_parent_escape_rejected(sdk):
    args, _, _ = sdk
    args.output = args.source_root.parent / "outside" / ".." / args.source_root.name / "new"
    with pytest.raises(ValueError, match="outside_source"):
        builder.build(args)


def test_schema2_external_adapter_rejected(sdk):
    args, _, _ = sdk
    args.adapter = args.source_root / legacy.ADAPTER_PATH
    args.adapter_commit = args.expected_source_commit
    with pytest.raises(ValueError, match="in_source_adapter"):
        builder.build(args)


def test_existing_bundle_retained(sdk):
    args, _, _ = sdk
    args.output.mkdir()
    (args.output / "retain").write_bytes(b"preserved")
    with pytest.raises(ValueError, match="new_output"):
        builder.build(args)
    assert (args.output / "retain").read_bytes() == b"preserved"


@pytest.mark.parametrize("corruption", ["apk", "wheel", "sum", "extra"])
def test_post_build_corruption_rejected(sdk, corruption):
    args, _, _ = sdk
    builder.build(args)
    args.bundle = args.output
    if corruption == "apk":
        with zipfile.ZipFile(args.output / "ordinary.apk", "a") as archive:
            archive.writestr("res/raw/remote_qa_ca.pem", args.ca_cert.read_bytes())
    elif corruption == "wheel":
        write_wheel(
            next(args.output.glob("*.whl")), args.source_root, changed="swu_happyrun/__init__.py"
        )
    elif corruption == "sum":
        (args.output / "SHA256SUMS").write_text("incorrect\n", encoding="utf-8")
    else:
        (args.output / "private.key").write_bytes(b"synthetic forbidden extra")
    with pytest.raises(ValueError):
        runner.verify_public_bundle(args)


def test_failed_build_has_no_complete_manifest(sdk, monkeypatch):
    args, _, _ = sdk
    previous = legacy.run

    def fail_wheel(command, **kwargs):
        if command[0] == sys.executable:
            raise subprocess.CalledProcessError(1, "synthetic build")
        return previous(command, **kwargs)

    monkeypatch.setattr(legacy, "run", fail_wheel)
    with pytest.raises(subprocess.CalledProcessError):
        builder.build(args)
    assert not (args.output / "delivery.json").exists()
    assert not (args.output / "SHA256SUMS").exists()
    assert not (
        args.source_root / "android/app/build/generated/remoteQa/res/raw/remote_qa_ca.pem"
    ).exists()


@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
def test_hidden_tracked_modification_rejected(source, flag):
    root, head, tree = source
    git(root, "update-index", flag, "src/swu_happyrun/__init__.py")
    (root / "src/swu_happyrun/__init__.py").write_bytes(b"hidden modified product")
    assert git(root, "status", "--porcelain") == ""
    with pytest.raises(ValueError):
        v2.source_identity(root, head, tree)


def test_ignored_extra_python_source_rejected(source):
    root, head, tree = source
    (root / ".git/info/exclude").write_text("src/swu_happyrun/extra.py\n", encoding="utf-8")
    (root / "src/swu_happyrun/extra.py").write_bytes(b"hidden extra product")
    assert git(root, "status", "--porcelain") == ""
    with pytest.raises(ValueError):
        v2.source_identity(root, head, tree)


@pytest.mark.parametrize(
    "name,data",
    [
        (
            "METADATA",
            b"Name: swu-happyrun\nVersion: 0.1.0\nRequires-Python: >=3.11\n"
            b"Requires-Dist: malicious-extra\n",
        ),
        ("METADATA", b"Name: swu-happyrun\nVersion: 9.9.9\nRequires-Python: >=3.11\n"),
        ("entry_points.txt", b"[console_scripts]\nswu-happyrun = other.module:main\n"),
        ("WHEEL", b"Wheel-Version: 1.0\nRoot-Is-Purelib: false\nTag: py3-none-any\n"),
    ],
)
def test_changed_wheel_metadata_rejected(source, tmp_path, name, data):
    wheel = tmp_path / "swu_happyrun-0.1.0-py3-none-any.whl"
    write_wheel(wheel, source[0], metadata_change=(name, data))
    with pytest.raises(ValueError):
        v2.inspect_wheel(wheel, source[0])


def test_source_symlink_ancestor_rejected(source, tmp_path, symlink_or_skip):
    linked = tmp_path / "linked"
    symlink_or_skip(linked, source[0], target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        v2.source_identity(linked, *source[1:])


def test_wheel_record_hash_rejected(source, tmp_path):
    wheel = tmp_path / "swu_happyrun-0.1.0-py3-none-any.whl"
    write_wheel(wheel, source[0])
    with zipfile.ZipFile(wheel) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    key = "swu_happyrun-0.1.0.dist-info/RECORD"
    contents[key] = contents[key].replace(b"sha256=", b"sha512=", 1)
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, data in contents.items():
            archive.writestr(name, data)
    with pytest.raises(ValueError, match="record_digest"):
        v2.inspect_wheel(wheel, source[0])


def test_wheel_duplicate_member_rejected(source, tmp_path):
    wheel = tmp_path / "swu_happyrun-0.1.0-py3-none-any.whl"
    write_wheel(wheel, source[0])
    with pytest.warns(UserWarning, match="Duplicate name"):
        with zipfile.ZipFile(wheel, "a") as archive:
            archive.writestr("swu_happyrun/__init__.py", b"duplicate")
    with pytest.raises(ValueError):
        v2.inspect_wheel(wheel, source[0])
