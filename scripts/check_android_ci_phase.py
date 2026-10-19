"""Read-only runtime authorization and same-run APK provenance; no ACL operations."""

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

REPOSITORY = "Maximora-byte/swu-happyrun"
BRANCH = "refs/heads/dot/android-foreground-agent"
# Final same-round matrix: three reviewed jobs, API31/35, exact transition.
BEFORE = "005bb79058d434d9897a266868a1fbd5bae566b4"


def authorized(env, event):
    return (
        env.get("GITHUB_ACTIONS") == "true"
        and env.get("RUNNER_ENVIRONMENT") == "github-hosted"
        and env.get("RUNNER_OS") == "Linux"
        and env.get("GITHUB_REPOSITORY") == REPOSITORY
        and env.get("GITHUB_EVENT_NAME") == "push"
        and env.get("GITHUB_REF") == BRANCH
        and event.get("repository", {}).get("full_name") == REPOSITORY
        and event.get("ref") == BRANCH
        and event.get("before") == BEFORE
        and isinstance(event.get("after"), str)
        and len(event["after"]) == 40
        and all(c in "0123456789abcdef" for c in event["after"])
        and event["after"] == env.get("GITHUB_SHA")
        and env.get("HAPPYRUN_ANDROID_API") in {"31", "35"}
        and env.get("GITHUB_JOB") in {"android-apk", "android-self-probe", "remote-https"}
    )


def context(env, root, variant):
    if subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=normal"], cwd=root, text=True
    ).strip():
        raise ValueError("dirty_checkout_sources")
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=root, text=True).strip()
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if commit != env["GITHUB_SHA"]:
        raise ValueError("checkout_commit_mismatch")
    return {
        "repository": env["GITHUB_REPOSITORY"],
        "commit": commit,
        "tree": tree,
        "run_id": env["GITHUB_RUN_ID"],
        "run_attempt": env["GITHUB_RUN_ATTEMPT"],
        "variant": variant,
        "job": env["GITHUB_JOB"],
        "api": env["HAPPYRUN_ANDROID_API"],
    }


def apk_files(root):
    output = root / "android/app/build/outputs/apk"
    files = sorted(output.rglob("*.apk"))
    if not files:
        raise ValueError("missing_apks")
    result = {}
    for path in files:
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("unsafe_apk_path")
        result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def required_apks(variant, files):
    names = {
        "debug": ["debug/app-debug.apk", "androidTest/debug/app-debug-androidTest.apk"],
        "selfProbe": [
            "debug/app-debug.apk",
            "androidTest/debug/app-debug-androidTest.apk",
            "selfProbe/app-selfProbe.apk",
            "androidTest/selfProbe/app-selfProbe-androidTest.apk",
        ],
        "remoteQa": [
            "debug/app-debug.apk",
            "selfProbe/app-selfProbe.apk",
            "release/app-release-unsigned.apk",
            "remoteQa/app-remoteQa.apk",
            "androidTest/remoteQa/app-remoteQa-androidTest.apk",
        ],
    }
    if variant not in names or any(
        "android/app/build/outputs/apk/" + name not in files for name in names[variant]
    ):
        raise ValueError("missing_variant_apk_role")


def verify(manifest, expected, files):
    if manifest.get("context") != expected:
        raise ValueError("provenance_context_mismatch")
    if not files or manifest.get("apks") != files:
        raise ValueError("apk_set_or_hash_mismatch")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["gate", "seal", "verify", "report"])
    parser.add_argument("--variant", required=True)
    parser.add_argument("--manifest", type=Path, default=Path("qa/android/build-provenance.json"))
    args = parser.parse_args()
    root = Path.cwd()
    if args.action == "report":
        authorization = os.environ.get("HAPPYRUN_RUNTIME_AUTHORIZED", "")
        approved = authorization == "true"
        outcome = os.environ.get("HAPPYRUN_RUNTIME_OUTCOME", "")
        status = (
            "passed" if approved and outcome == "success" else "failed" if approved else "not_run"
        )
        if authorization not in {"true", "false"}:
            status = "unknown"
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        (args.manifest.parent / "runtime-status.json").write_text(
            json.dumps(
                {
                    "authorized": approved if authorization in {"true", "false"} else None,
                    "runtime_status": status,
                }
            )
            + "\n"
        )
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as stream:
            stream.write(
                "Android runtime result: "
                + status
                + (" — 未执行设备验收" if not approved else "")
                + "\n"
            )
        if status == "unknown":
            raise SystemExit("Runtime authorization was not evaluated")
        if approved and outcome != "success":
            raise SystemExit("Authorized Android runtime did not pass")
        return
    if args.action == "gate":
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        approved = authorized(os.environ, event)
        status = {"authorized": approved, "runtime_status": "pending" if approved else "not_run"}
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        (args.manifest.parent / "runtime-status.json").write_text(
            json.dumps(status) + "\n", encoding="utf-8"
        )
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
            stream.write(f"authorized={str(approved).lower()}\n")
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as stream:
            stream.write(
                "Android runtime: "
                + ("authorized; result pending" if approved else "SKIPPED — 未执行设备验收")
                + "\n"
            )
        return
    expected = context(os.environ, root, args.variant)
    files = apk_files(root)
    required_apks(args.variant, files)
    if args.action == "seal":
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps({"context": expected, "apks": files}, indent=2) + "\n")
    else:
        verify(json.loads(args.manifest.read_text(encoding="utf-8")), expected, files)


if __name__ == "__main__":
    main()
