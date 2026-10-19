"""Explicit one-run hosted-CI KVM ACL grant, bound to one reviewed branch transition."""

import json
import os
import stat
import subprocess
from pathlib import Path


def main() -> int:
    expected = {
        "HAPPYRUN_KVM_APPROVED_THIS_RUN": "true",
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": "Maximora-byte/swu-happyrun",
        "RUNNER_ENVIRONMENT": "github-hosted",
        "RUNNER_OS": "Linux",
    }
    for key, value in expected.items():
        if os.environ.get(key) != value:
            raise SystemExit(f"KVM grant refused: missing exact {key} gate")
    if (
        os.environ.get("HAPPYRUN_ANDROID_API") != "31"
        or os.environ.get("GITHUB_JOB") != "android-apk"
    ):
        raise SystemExit("KVM grant refused: only ordinary API31 diagnostic job")
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    repository = "Maximora-byte/swu-happyrun"
    branch = "dot/android-foreground-agent"
    event_name = os.environ.get("GITHUB_EVENT_NAME")
    push = (
        event_name == "push"
        and event.get("ref") == "refs/heads/" + branch
        and os.environ.get("GITHUB_REF") == "refs/heads/" + branch
        and event.get("after") == os.environ.get("GITHUB_SHA")
    )
    if (
        event.get("before") != "b3642f7215135fb90230b13ff1bdcfb5930ae227"
        or event.get("repository", {}).get("full_name") != repository
        or not isinstance(event.get("after"), str)
        or len(event["after"]) != 40
        or any(c not in "0123456789abcdef" for c in event["after"])
        or not push
    ):
        raise SystemExit("KVM grant refused: not the single reviewed branch transition")
    device = Path("/dev/kvm")
    if not device.exists() or not stat.S_ISCHR(device.stat().st_mode):
        raise SystemExit("KVM blocked: /dev/kvm character device absent")
    uid = os.getuid()
    if uid == 0:
        raise SystemExit("KVM grant refused: expected unprivileged hosted test account")
    # Named current-account ACL only. No global mode/group/udev changes.
    subprocess.run(
        ["sudo", "-n", "setfacl", "-n", "-m", f"u:{uid}:rw", str(device)], check=True, timeout=30
    )
    subprocess.run(["getfacl", "-n", str(device)], check=True, timeout=30)
    if not os.access(device, os.R_OK | os.W_OK):
        raise SystemExit("KVM blocked: current account lacks effective read/write access")
    emulator = Path(os.environ["ANDROID_HOME"]) / "emulator/emulator"
    subprocess.run([str(emulator), "-accel-check"], check=True, timeout=30)
    print(f"KVM verified for current hosted test uid={uid}; this reviewed transition only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
