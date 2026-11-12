#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
: "${HAPPYRUN_REMOTE_PRIVATE_DIR:?temporary TLS fixture directory required}"
python "$root/scripts/check_remote_https_android.py" run --private-dir "$HAPPYRUN_REMOTE_PRIVATE_DIR" --output "$root/qa/android-remote"
python "$root/scripts/check_foreground_activity_https.py" --private-dir "$HAPPYRUN_REMOTE_PRIVATE_DIR" --output "$root/qa/android-foreground"

python "$root/scripts/check_android_durable_recovery.py" --private-dir "$HAPPYRUN_REMOTE_PRIVATE_DIR" --output "$root/qa/android-recovery"
python "$root/scripts/check_android_live_fence.py" --private-dir "$HAPPYRUN_REMOTE_PRIVATE_DIR" --output "$root/qa/android-live-fence"
