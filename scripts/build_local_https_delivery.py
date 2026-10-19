"""Build four locally signed test APKs from a clean pinned product checkout."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

from check_local_https_delivery import (
    SOURCE_COMMIT,
    SOURCE_TREE,
    digest,
    inspect_pairs,
    run,
    verify_bundle,
    verify_certificates,
)

ADAPTER = (
    "android/app/src/remoteQaAndroidTest/java/org/happyrun/app/remoteqa/"
    "RemoteMumuHttpsAcceptanceTest.java"
)
OUTPUTS = {
    "ordinary.apk": "apk/debug/app-debug.apk",
    "ordinary-test.apk": "apk/androidTest/debug/app-debug-androidTest.apk",
    "remoteQa.apk": "apk/remoteQa/app-remoteQa.apk",
    "remoteQa-test.apk": "apk/androidTest/remoteQa/app-remoteQa-androidTest.apk",
}


def source_identity(source):
    head = run(["git", "-C", str(source), "rev-parse", "HEAD"]).strip()
    tree = run(["git", "-C", str(source), "rev-parse", "HEAD^{tree}"]).strip()
    dirty = run(["git", "-C", str(source), "status", "--porcelain", "--untracked-files=all"])
    if head != SOURCE_COMMIT or tree != SOURCE_TREE or dirty.strip():
        raise ValueError("clean_exact_9534_checkout_required")
    return {"commit": head, "tree": tree}


def build(args):
    source, output = Path(args.source_root).resolve(), Path(args.output).resolve()
    identity = source_identity(source)
    if output.exists() or output == source or source in output.parents:
        raise ValueError("new_output_directory_outside_source_required")
    host = verify_certificates(args.ca_cert, args.server_cert, args.host, args.openssl)
    ca = source / "android/app/build/generated/remoteQa/res/raw/remote_qa_ca.pem"
    adapter = source / ADAPTER
    overlay = None
    if args.adapter:
        incoming = Path(args.adapter)
        if (
            incoming.name != "RemoteMumuHttpsAcceptanceTest.java"
            or incoming.is_symlink()
            or not incoming.is_file()
            or adapter.exists()
        ):
            raise ValueError("single_new_adapter_file_required")
        if not re.fullmatch("[0-9a-f]{40}", args.adapter_commit or ""):
            raise ValueError("adapter_source_commit_required")
        overlay = {
            "source_commit": args.adapter_commit,
            "files": [{"path": ADAPTER, "sha256": digest(incoming)}],
        }
    elif args.adapter_commit:
        raise ValueError("adapter_file_required")
    if ca.exists():
        raise ValueError("generated_ca_already_exists")
    output.mkdir(parents=True, exist_ok=False)
    created_ca = created_adapter = False
    try:
        # Clean removes stale variant APKs, preventing success from reusing old output.
        command = [args.gradle, "--no-daemon", "-p", str(source / "android")]
        run(command + ["clean", "assembleDebug", "assembleDebugAndroidTest"], timeout=1800)
        ca.parent.mkdir(parents=True, exist_ok=True)
        with ca.open("xb") as stream:
            stream.write(Path(args.ca_cert).read_bytes())
        created_ca = True
        if overlay:
            adapter.parent.mkdir(parents=True, exist_ok=True)
            with adapter.open("xb") as stream:
                stream.write(Path(args.adapter).read_bytes())
            created_adapter = True
        run(
            command
            + ["-PremoteQaInstrumentation", "assembleRemoteQa", "assembleRemoteQaAndroidTest"],
            timeout=1800,
        )
        for name, relative in OUTPUTS.items():
            original = source / "android/app/build/outputs" / relative
            if not original.is_file() or original.is_symlink():
                raise ValueError("expected_fresh_apk_missing")
            shutil.copyfile(original, output / name)
        shutil.copyfile(args.ca_cert, output / "ca.pem")
        shutil.copyfile(args.server_cert, output / "server.pem")
        if created_adapter:
            adapter.unlink()
            created_adapter = False
        source_identity(source)
        report = {
            "schema_version": 1,
            "source": identity,
            "tool_sha256": digest(__file__),
            "validator_sha256": digest(Path(__file__).with_name("check_local_https_delivery.py")),
            "host": host,
            "ca_sha256": digest(args.ca_cert),
            "server_certificate_sha256": digest(args.server_cert),
            "adapter": overlay,
            "runtime_capabilities": ["mumu-own-simulation-v1"] if overlay else [],
            "runtime_status": "not_run",
            "temporary_debug_signature": True,
            "pairs": inspect_pairs(
                output,
                args.ca_cert,
                apksigner=args.apksigner,
                apkanalyzer=args.apkanalyzer,
                aapt2=args.aapt2,
            ),
        }
        (output / "delivery.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        verify_bundle(
            output,
            args.ca_cert,
            args.server_cert,
            host,
            openssl=args.openssl,
            apksigner=args.apksigner,
            apkanalyzer=args.apkanalyzer,
            aapt2=args.aapt2,
        )
        (output / "SHA256SUMS").write_text(
            "".join(f"{digest(p)}  {p.name}\n" for p in sorted(output.iterdir()) if p.is_file()),
            encoding="utf-8",
        )
    finally:
        if created_ca:
            ca.unlink()
        if created_adapter:
            adapter.unlink()
    source_identity(source)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "source-root",
        "output",
        "ca-cert",
        "server-cert",
        "host",
        "gradle",
        "openssl",
        "apksigner",
        "apkanalyzer",
        "aapt2",
    ):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--adapter")
    parser.add_argument("--adapter-commit")
    args = parser.parse_args()
    try:
        build(args)
    except (ValueError, OSError, subprocess.SubprocessError):
        parser.exit(2, "Build rejected or failed; partial output is not a verified delivery.\n")
    print("Four APKs verified. Device execution: not_run.")


if __name__ == "__main__":
    main()
