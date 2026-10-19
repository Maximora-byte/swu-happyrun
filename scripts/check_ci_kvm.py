"""Explicit one-run hosted-CI KVM ACL grant, bound to one reviewed push transition."""

import json
import os
import stat
import subprocess
from pathlib import Path


def main() -> int:
    expected = {
        "HAPPYRUN_KVM_APPROVED_THIS_RUN": "true",
        "GITHUB_ACTIONS": "true",
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_REF": "refs/heads/dot/android-app",
        "GITHUB_REPOSITORY": "Maximora-byte/swu-happyrun",
        "RUNNER_ENVIRONMENT": "github-hosted",
        "RUNNER_OS": "Linux",
    }
    for key, value in expected.items():
        if os.environ.get(key) != value:
            raise SystemExit(f"KVM grant refused: missing exact {key} gate")
    if os.environ.get("HAPPYRUN_ANDROID_API") not in {"31", "35"}:
        raise SystemExit("KVM grant refused: only this API31/35 acceptance matrix")
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    if (
        event.get("before") != "629f2e9b86d7a72502f528abd1c1edf999d6a842"
        or event.get("ref") != expected["GITHUB_REF"]
        or event.get("repository", {}).get("full_name") != expected["GITHUB_REPOSITORY"]
        or event.get("after") != os.environ.get("GITHUB_SHA")
        or not event.get("after")
    ):
        raise SystemExit("KVM grant refused: not the single reviewed push transition")
    device = Path("/dev/kvm")
    if not device.exists() or not stat.S_ISCHR(device.stat().st_mode):
        raise SystemExit("KVM blocked: /dev/kvm character device absent")
    uid = os.getuid()
    if uid == 0:
        raise SystemExit("KVM grant refused: expected unprivileged hosted test account")
    # Named current-account ACL only; -n preserves any existing mask.
    # No global mode/group/udev changes. Insufficient effective rights fail closed.
    subprocess.run(
        ["sudo", "-n", "setfacl", "-n", "-m", f"u:{uid}:rw", str(device)], check=True, timeout=30
    )
    subprocess.run(["getfacl", "-n", str(device)], check=True, timeout=30)
    if not os.access(device, os.R_OK | os.W_OK):
        raise SystemExit("KVM blocked: current account lacks effective read/write access")
    emulator = Path(os.environ["ANDROID_HOME"]) / "emulator/emulator"
    subprocess.run([str(emulator), "-accel-check"], check=True, timeout=30)
    print(f"KVM verified for current hosted test uid={uid}; this reviewed push only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
