"""Six APKs and a wheel bound to an explicitly pinned clean local product checkout.

Artifact schema only. This module never starts an emulator, server or device.
"""

from __future__ import annotations

import base64
import configparser
import csv
import hashlib
import io
import json
import os
import re
import shutil
import stat
import sys
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

import check_local_https_delivery as legacy
from check_selfprobe_apks import ENTRY, verify_classes, verify_manifest, verify_resource_table
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

FILES = {**legacy.FILES, "selfProbe": ("selfProbe.apk", "selfProbe-test.apk")}
OUTPUTS = {
    "ordinary.apk": "apk/debug/app-debug.apk",
    "ordinary-test.apk": "apk/androidTest/debug/app-debug-androidTest.apk",
    "selfProbe.apk": "apk/selfProbe/app-selfProbe.apk",
    "selfProbe-test.apk": "apk/androidTest/selfProbe/app-selfProbe-androidTest.apk",
    "remoteQa.apk": "apk/remoteQa/app-remoteQa.apk",
    "remoteQa-test.apk": "apk/androidTest/remoteQa/app-remoteQa-androidTest.apk",
}
FIELDS = {
    "schema_version",
    "source",
    "tool_sha256",
    "validator_sha256",
    "helper_sha256",
    "host",
    "ca_sha256",
    "server_certificate_sha256",
    "adapter",
    "runtime_capabilities",
    "runtime_status",
    "temporary_debug_signature",
    "pairs",
    "wheel",
}


def safe_path(value, *, directory=False, must_exist=True):
    # Normalize lexical .. first, then reject every symlink ancestor. Do not resolve through links.
    path = Path(os.path.abspath(value))
    for part in (*reversed(path.parents), path):
        if part.is_symlink():
            raise ValueError("symlink_path_rejected")
    if must_exist and (not path.is_dir() if directory else not path.is_file()):
        raise ValueError("regular_path_required")
    return path


def copy_exclusive(source, target):
    source, target = safe_path(source), safe_path(target, must_exist=False)
    src_fd = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        dst_fd = os.open(
            target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600
        )
        with (
            os.fdopen(dst_fd, "wb") as destination,
            os.fdopen(src_fd, "rb", closefd=False) as original,
        ):
            shutil.copyfileobj(original, destination)
    finally:
        os.close(src_fd)


def source_identity(source, expected_commit, expected_tree):
    if not all(
        isinstance(p, str) and re.fullmatch(r"[0-9a-f]{40}", p)
        for p in (expected_commit, expected_tree)
    ):
        raise ValueError("explicit_source_commit_and_tree_required")
    source = safe_path(source, directory=True)
    head = legacy.run(["git", "-C", str(source), "rev-parse", "HEAD"]).strip()
    tree = legacy.run(["git", "-C", str(source), "rev-parse", "HEAD^{tree}"]).strip()
    dirty = legacy.run(["git", "-C", str(source), "status", "--porcelain", "--untracked-files=all"])
    if head != expected_commit or tree != expected_tree or dirty.strip():
        raise ValueError("clean_exact_source_checkout_required")
    # Index flags can hide changes from status. Compare every tracked file to HEAD blobs.
    entries = legacy.run(["git", "-C", str(source), "ls-tree", "-r", "-z", "HEAD"])
    tracked = set()
    for entry in entries.split("\0"):
        if not entry:
            continue
        metadata, name = entry.split("\t", 1)
        mode, kind, blob = metadata.split(" ")
        if mode not in {"100644", "100755"} or kind != "blob":
            raise ValueError("unsupported_source_tree_entry")
        if name.startswith("/") or ".." in PurePosixPath(name).parts or "\\" in name:
            raise ValueError("invalid_source_tree_path")
        data = safe_path(source / name).read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()
        if actual != blob:
            raise ValueError("source_git_blob_mismatch")
        tracked.add(name)
    if not tracked:
        raise ValueError("empty_source_tree")
    for directory in ("src", "android/app/src", "scripts", "tests", "contracts"):
        root = source / directory
        if not root.exists():
            continue
        safe_path(root, directory=True)
        for path in root.rglob("*"):
            if path.is_symlink():
                raise ValueError("source_tree_symlink")
            if path.is_file() and not ("__pycache__" in path.parts and path.suffix == ".pyc"):
                if path.relative_to(source).as_posix() not in tracked:
                    raise ValueError("untracked_source_file")
    return {"commit": head, "tree": tree}


def package_files(source):
    root = safe_path(Path(source) / "src/swu_happyrun", directory=True)
    result = {}
    for p in sorted(root.rglob("*")):
        if p.is_symlink():
            raise ValueError("source_package_symlink")
        if p.is_file() and not ("__pycache__" in p.parts and p.suffix == ".pyc"):
            safe_path(p)
            result["swu_happyrun/" + p.relative_to(root).as_posix()] = p.read_bytes()
    if not result or not any(name.endswith(".py") for name in result):
        raise ValueError("source_python_modules_missing")
    return result


def verify_wheel_metadata(contents, project, prefix):
    metadata = BytesParser().parsebytes(contents[prefix + "METADATA"])
    for field, expected in (
        ("Name", project["name"]),
        ("Version", project["version"]),
        ("Requires-Python", project["requires-python"]),
    ):
        if metadata.get_all(field, []) != [expected]:
            raise ValueError("wheel_project_identity_mismatch")
    extras = project.get("optional-dependencies", {})
    actual_extras = metadata.get_all("Provides-Extra", [])
    if len(actual_extras) != len(set(actual_extras)) or set(actual_extras) != set(extras):
        raise ValueError("wheel_extras_mismatch")
    expected_requirements = [Requirement(dep) for dep in project.get("dependencies", [])]
    for extra, requirements in extras.items():
        for dep in requirements:
            base, separator, marker = dep.partition(";")
            combined = f"({marker}) and extra == '{extra}'" if separator else f"extra == '{extra}'"
            expected_requirements.append(Requirement(base + "; " + combined))
    actual_requirements = [Requirement(dep) for dep in metadata.get_all("Requires-Dist", [])]
    if len(actual_requirements) != len(set(actual_requirements)) or set(actual_requirements) != set(
        expected_requirements
    ):
        raise ValueError("wheel_dependencies_mismatch")
    wheel = BytesParser().parsebytes(contents[prefix + "WHEEL"])
    if set(wheel.keys()) - {"Wheel-Version", "Generator", "Root-Is-Purelib", "Tag"}:
        raise ValueError("unexpected_wheel_header")
    for key, value in (
        ("Wheel-Version", "1.0"),
        ("Root-Is-Purelib", "true"),
        ("Tag", "py3-none-any"),
    ):
        if wheel.get_all(key, []) != [value]:
            raise ValueError("wheel_platform_mismatch")
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read_string(contents[prefix + "entry_points.txt"].decode("utf-8"))
    expected_points = {"console_scripts": project.get("scripts", {})}
    if {section: dict(parser[section]) for section in parser.sections()} != expected_points:
        raise ValueError("wheel_entrypoints_mismatch")
    records = list(csv.reader(io.StringIO(contents[prefix + "RECORD"].decode("utf-8"))))
    if any(len(row) != 3 for row in records) or len(records) != len(contents):
        raise ValueError("wheel_record_shape")
    if len({row[0] for row in records}) != len(records) or {row[0] for row in records} != set(
        contents
    ):
        raise ValueError("wheel_record_members")
    for name, digest, size in records:
        if name == prefix + "RECORD":
            if digest or size:
                raise ValueError("wheel_record_self_hash")
            continue
        expected = "sha256=" + base64.urlsafe_b64encode(
            hashlib.sha256(contents[name]).digest()
        ).decode("ascii").rstrip("=")
        if digest != expected or size != str(len(contents[name])):
            raise ValueError("wheel_record_digest")


def inspect_wheel(path, source):
    path = safe_path(path)
    project = tomllib.loads(safe_path(Path(source) / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    normalized_name = canonicalize_name(project["name"]).replace("-", "_")
    expected_name = normalized_name + "-" + project["version"]
    if path.name != expected_name + "-py3-none-any.whl":
        raise ValueError("unexpected_wheel_filename")
    prefix = expected_name + ".dist-info/"
    expected = package_files(source)
    required_metadata = {
        prefix + name for name in ("METADATA", "WHEEL", "entry_points.txt", "RECORD")
    }
    contents = {}
    with zipfile.ZipFile(path) as archive:
        if len(archive.infolist()) != len(expected) + len(required_metadata):
            raise ValueError("wheel_file_count_mismatch")
        for entry in archive.infolist():
            name = entry.filename
            if (
                name in contents
                or name not in expected.keys() | required_metadata
                or entry.is_dir()
                or stat.S_ISLNK(entry.external_attr >> 16)
            ):
                raise ValueError("unsafe_wheel_entry")
            if entry.file_size > 8 * 1024 * 1024:
                raise ValueError("oversize_wheel_entry")
            contents[name] = archive.read(entry)
    packaged = {k: v for k, v in contents.items() if k.startswith("swu_happyrun/")}
    if packaged != expected:
        raise ValueError("wheel_source_bytes_mismatch")
    if not required_metadata <= contents.keys():
        raise ValueError("wheel_metadata_missing")
    verify_wheel_metadata(contents, project, prefix)
    return {
        "filename": path.name,
        "sha256": legacy.digest(path),
        "package_files": {k: hashlib.sha256(v).hexdigest() for k, v in sorted(expected.items())},
    }


def inspect_pairs(bundle, ca, *, apksigner, apkanalyzer, aapt2):
    pairs = legacy.inspect_pairs(
        bundle, ca, apksigner=apksigner, apkanalyzer=apkanalyzer, aapt2=aapt2, file_groups=FILES
    )
    versions = set()
    for variant, names in FILES.items():
        app = safe_path(Path(bundle) / names[0])
        optional = variant == "selfProbe"
        scope_id = (
            verify_resource_table(legacy.run([aapt2, "dump", "resources", str(app)]))
            if optional
            else None
        )
        verify_manifest(
            legacy.run([apkanalyzer, "manifest", "print", str(app)]), optional, scope_id
        )
        verify_classes(
            legacy.run([apkanalyzer, "dex", "packages", "--defined-only", str(app)]), optional
        )
        with zipfile.ZipFile(app) as archive:
            if optional:
                if archive.read("assets/xposed_init").decode("utf-8").strip() != ENTRY:
                    raise ValueError("invalid_self_scope_entry")
            elif "assets/xposed_init" in archive.namelist():
                raise ValueError("unexpected_module_entry")
        versions.add((pairs[variant]["version_code"], pairs[variant]["version_name"]))
    if len(versions) != 1:
        raise ValueError("build_group_version_mismatch")
    return pairs


def checksums(bundle):
    return "".join(
        f"{legacy.digest(p)}  {p.name}\n"
        for p in sorted(bundle.iterdir())
        if p.name != "SHA256SUMS"
    )


def verify_bundle(
    bundle_dir,
    ca_cert,
    server_cert,
    host,
    *,
    source_root,
    expected_source_commit,
    expected_source_tree,
    openssl,
    apksigner,
    apkanalyzer,
    aapt2,
):
    if source_root is None:
        raise ValueError("source_checkout_required_for_schema2")
    identity = source_identity(source_root, expected_source_commit, expected_source_tree)
    bundle = safe_path(bundle_dir, directory=True)
    report = json.loads(safe_path(bundle / "delivery.json").read_text(encoding="utf-8"))
    if not isinstance(report, dict) or set(report) != FIELDS or report["schema_version"] != 2:
        raise ValueError("delivery_schema_fields_mismatch")
    if report["source"] != identity:
        raise ValueError("unrecognized_product_source")
    wheel = report["wheel"]
    if not isinstance(wheel, dict) or set(wheel) != {"filename", "sha256", "package_files"}:
        raise ValueError("invalid_wheel_provenance")
    name = wheel["filename"]
    if not isinstance(name, str) or not re.fullmatch(
        r"swu_happyrun-[A-Za-z0-9_.]+-py3-none-any\.whl", name
    ):
        raise ValueError("invalid_wheel_filename")
    allowed = set(OUTPUTS) | {"ca.pem", "server.pem", "delivery.json", "SHA256SUMS", name}
    if {p.name for p in bundle.iterdir()} != allowed:
        raise ValueError("bundle_file_set_mismatch")
    for p in bundle.iterdir():
        safe_path(p)
    if report["runtime_status"] != "not_run" or report["temporary_debug_signature"] is not True:
        raise ValueError("unexpected_runtime_or_signing_claim")
    for field in ("tool_sha256", "validator_sha256", "helper_sha256"):
        if not isinstance(report[field], str) or not re.fullmatch(r"[0-9a-f]{64}", report[field]):
            raise ValueError("invalid_tool_provenance")
    adapter = safe_path(Path(source_root) / legacy.ADAPTER_PATH)
    if report["adapter"] != {
        "source_commit": identity["commit"],
        "files": [{"path": legacy.ADAPTER_PATH, "sha256": legacy.digest(adapter)}],
    }:
        raise ValueError("same_source_adapter_required")
    if report["runtime_capabilities"] != ["mumu-own-simulation-v1"]:
        raise ValueError("adapter_capability_mismatch")
    host = legacy.verify_certificates(ca_cert, server_cert, host, openssl)
    if (
        legacy.public_pem(bundle / "ca.pem") != legacy.public_pem(ca_cert)
        or legacy.public_pem(bundle / "server.pem") != legacy.public_pem(server_cert)
        or report["host"] != host
        or report["ca_sha256"] != legacy.digest(ca_cert)
        or report["server_certificate_sha256"] != legacy.digest(server_cert)
    ):
        raise ValueError("certificate_or_host_mismatch")
    if wheel != inspect_wheel(bundle / name, source_root):
        raise ValueError("wheel_metadata_mismatch")
    if report["pairs"] != inspect_pairs(
        bundle, ca_cert, apksigner=apksigner, apkanalyzer=apkanalyzer, aapt2=aapt2
    ):
        raise ValueError("artifact_metadata_mismatch")
    if (bundle / "SHA256SUMS").read_text(encoding="utf-8") != checksums(bundle):
        raise ValueError("bundle_checksums_mismatch")
    source_identity(source_root, expected_source_commit, expected_source_tree)
    return report


def build(args):
    source = safe_path(args.source_root, directory=True)
    identity = source_identity(source, args.expected_source_commit, args.expected_source_tree)
    output = safe_path(args.output, must_exist=False)
    if output.exists() or output == source or source in output.parents:
        raise ValueError("new_output_directory_outside_source_required")
    if args.adapter or args.adapter_commit:
        raise ValueError("schema2_requires_in_source_adapter")
    adapter = safe_path(source / legacy.ADAPTER_PATH)
    host = legacy.verify_certificates(args.ca_cert, args.server_cert, args.host, args.openssl)
    ca = safe_path(
        source / "android/app/build/generated/remoteQa/res/raw/remote_qa_ca.pem", must_exist=False
    )
    if ca.exists():
        raise ValueError("generated_ca_already_exists")
    evidence = args.private_build_evidence
    if evidence is not None:
        evidence = safe_path(evidence, must_exist=False)
        if (
            evidence == source
            or source in evidence.parents
            or evidence == output
            or output in evidence.parents
        ):
            raise ValueError("private_evidence_must_be_outside_source_and_bundle")
        evidence = legacy.private_directory(evidence)
    if args.gradle_stderr_encoding not in ("utf-8", "gbk"):
        raise ValueError("invalid_gradle_stderr_encoding")
    output.mkdir(parents=True, exist_ok=False)
    created_ca = False
    try:
        command = [args.gradle, "--no-daemon", "-p", str(source / "android")]
        for label, tasks in (
            ("ordinary", ["clean", "assembleDebug", "assembleDebugAndroidTest"]),
            (
                "selfProbe",
                ["-PprobeInstrumentation", "assembleSelfProbe", "assembleSelfProbeAndroidTest"],
            ),
        ):
            legacy.run(
                command + tasks,
                timeout=1800,
                stderr_encoding=args.gradle_stderr_encoding,
                private_evidence=evidence / label if evidence else None,
            )
        ca = safe_path(ca, must_exist=False)
        ca.parent.mkdir(parents=True, exist_ok=True)
        with ca.open("xb") as stream:
            stream.write(safe_path(args.ca_cert).read_bytes())
        created_ca = True
        legacy.run(
            command
            + ["-PremoteQaInstrumentation", "assembleRemoteQa", "assembleRemoteQaAndroidTest"],
            timeout=1800,
            stderr_encoding=args.gradle_stderr_encoding,
            private_evidence=evidence / "remoteQa" if evidence else None,
        )
        for name, relative in OUTPUTS.items():
            copy_exclusive(source / "android/app/build/outputs" / relative, output / name)
        for original, name in ((args.ca_cert, "ca.pem"), (args.server_cert, "server.pem")):
            copy_exclusive(original, output / name)
        # The wheel backend is the pinned product checkout's pyproject build-system.
        legacy.run(
            [sys.executable, "-m", "build", "--wheel", "--outdir", str(output), str(source)],
            timeout=1800,
            private_evidence=evidence / "wheel" if evidence else None,
        )
        wheels = list(output.glob("*.whl"))
        if len(wheels) != 1:
            raise ValueError("exactly_one_fresh_wheel_required")
        source_identity(source, args.expected_source_commit, args.expected_source_tree)
        report = {
            "schema_version": 2,
            "source": identity,
            "tool_sha256": legacy.digest(Path(__file__).with_name("build_local_https_delivery.py")),
            "validator_sha256": legacy.digest(
                Path(__file__).with_name("check_local_https_delivery.py")
            ),
            "helper_sha256": legacy.digest(__file__),
            "host": host,
            "ca_sha256": legacy.digest(args.ca_cert),
            "server_certificate_sha256": legacy.digest(args.server_cert),
            "adapter": {
                "source_commit": identity["commit"],
                "files": [{"path": legacy.ADAPTER_PATH, "sha256": legacy.digest(adapter)}],
            },
            "runtime_capabilities": ["mumu-own-simulation-v1"],
            "runtime_status": "not_run",
            "temporary_debug_signature": True,
            "pairs": inspect_pairs(
                output,
                args.ca_cert,
                apksigner=args.apksigner,
                apkanalyzer=args.apkanalyzer,
                aapt2=args.aapt2,
            ),
            "wheel": inspect_wheel(wheels[0], source),
        }
        with (output / "delivery.json").open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(report, indent=2) + "\n")
        with (output / "SHA256SUMS").open("x", encoding="utf-8") as stream:
            stream.write(checksums(output))
        verify_bundle(
            output,
            args.ca_cert,
            args.server_cert,
            host,
            source_root=source,
            expected_source_commit=args.expected_source_commit,
            expected_source_tree=args.expected_source_tree,
            openssl=args.openssl,
            apksigner=args.apksigner,
            apkanalyzer=args.apkanalyzer,
            aapt2=args.aapt2,
        )
    except BaseException:
        # A failed inspection must not leave a manifest that looks complete.
        for name in ("delivery.json", "SHA256SUMS"):
            target = output / name
            if target.is_file() and not target.is_symlink():
                target.unlink()
        raise
    finally:
        if created_ca:
            ca.unlink()
    source_identity(source, args.expected_source_commit, args.expected_source_tree)
    return report
