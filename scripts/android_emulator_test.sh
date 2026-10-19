#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
api="${HAPPYRUN_ANDROID_API:-35}"
# API31 default is stable/channel-0 and uses the standard SDK license.
# This app has no Google Services dependency; API35 keeps its reviewed image.
case "$api" in
  31) image_tag=default ;;
  35) image_tag=google_apis ;;
  *) echo 'Only reviewed API 31/35 images supported' >&2; exit 2 ;;
esac
avd="happyrun-ci-api$api"
# Both Android tools use one disposable, explicit AVD directory.
export ANDROID_USER_HOME="${RUNNER_TEMP:-${TMPDIR:-/tmp}}/happyrun-android-api$api"
export ANDROID_EMULATOR_HOME="$ANDROID_USER_HOME"
export ANDROID_AVD_HOME="$ANDROID_USER_HOME/avd"
mkdir -p "$ANDROID_AVD_HOME"
system_image="system-images;android-$api;$image_tag;x86_64"
sdk="${ANDROID_HOME:?ANDROID_HOME must point to the official SDK}"
export PATH="$sdk/platform-tools:$sdk/emulator:$sdk/cmdline-tools/latest/bin:$PATH"
# Never auto-accept licenses or change KVM/system security permissions.
acceleration=on
if [[ ! -r /dev/kvm || ! -w /dev/kvm ]]; then
  acceleration=off
  echo 'KVM not available; using bounded official emulator software acceleration mode.'
fi
sdkmanager "$system_image" </dev/null || {
  echo 'Official SDK installation failed; a missing/new license must be reviewed, not auto-accepted.' >&2
  exit 1
}
test -d "$sdk/system-images/android-$api/$image_tag/x86_64" || {
  echo 'Required official system image missing; inspect SDK/license output.' >&2; exit 1;
}
printf 'no
' | avdmanager create avd --force -n "$avd" -k "$system_image" --path "$ANDROID_AVD_HOME/$avd.avd"
test -f "$ANDROID_AVD_HOME/$avd.ini" || { echo "AVD metadata missing after creation" >&2; exit 1; }
emulator -list-avds | grep -Fx "$avd" >/dev/null || { echo "Created AVD not visible to emulator" >&2; exit 1; }
mkdir -p "$root/qa/android"
emulator -avd "$avd" -port 5554 -accel "$acceleration" -no-window -no-audio -no-boot-anim -no-snapshot -gpu swiftshader_indirect >"$root/qa/android/emulator.log" 2>&1 &
pid=$!
trap 'adb -s emulator-5554 emu kill >/dev/null 2>&1 || true; kill "$pid" 2>/dev/null || true' EXIT
export ANDROID_SERIAL=emulator-5554
check_emulator_alive() {
  if ! kill -0 "$pid" 2>/dev/null; then
    echo 'Emulator exited before readiness' >&2
    tail -n 80 "$root/qa/android/emulator.log" >&2
    exit 1
  fi
}
wait_until=$((SECONDS + 600))
while [[ "$(timeout 5 adb -s "$ANDROID_SERIAL" get-state 2>/dev/null || true)" != device ]]; do
  check_emulator_alive
  if (( SECONDS >= wait_until )); then
    echo 'Timed out waiting for emulator ADB readiness' >&2
    tail -n 80 "$root/qa/android/emulator.log" >&2
    exit 1
  fi
  sleep 2
done
wait_until=$((SECONDS + 600))
while [[ "$(timeout 5 adb -s "$ANDROID_SERIAL" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r\n' || true)" != 1 ]]; do
  check_emulator_alive
  if (( SECONDS >= wait_until )); then
    echo 'Timed out waiting for Android boot completion' >&2
    tail -n 80 "$root/qa/android/emulator.log" >&2
    exit 1
  fi
  sleep 2
done
check_emulator_alive
adb install -r "${HAPPYRUN_ANDROID_APK:-$root/android/app/build/outputs/apk/debug/app-debug.apk}"
HAPPYRUN_DISPOSABLE_EMULATOR=1 python "$root/scripts/check_android_launch.py" "$root/qa/android"
adb install -r "${HAPPYRUN_ANDROID_TEST_APK:-$root/android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk}"
HAPPYRUN_DISPOSABLE_EMULATOR=1 bash "${HAPPYRUN_ANDROID_ACCEPTANCE_SCRIPT:-$root/scripts/android_acceptance.sh}"
adb exec-out screencap -p > "$root/qa/android/launched.png"
