#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
api="${HAPPYRUN_ANDROID_API:-35}"
case "$api" in 31|35) ;; *) echo 'Only reviewed API 31/35 images supported' >&2; exit 2 ;; esac
avd="happyrun-ci-api$api"
system_image="system-images;android-$api;google_apis;x86_64"
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
test -d "$sdk/system-images/android-$api/google_apis/x86_64" || {
  echo 'Required official system image missing; inspect SDK/license output.' >&2; exit 1;
}
printf 'no
' | avdmanager create avd --force -n "$avd" -k "$system_image"
mkdir -p "$root/qa/android"
emulator -avd "$avd" -port 5554 -accel "$acceleration" -no-window -no-audio -no-boot-anim -no-snapshot -gpu swiftshader_indirect >"$root/qa/android/emulator.log" 2>&1 &
pid=$!
trap 'adb -s emulator-5554 emu kill >/dev/null 2>&1 || true; kill "$pid" 2>/dev/null || true' EXIT
export ANDROID_SERIAL=emulator-5554
timeout 600 adb wait-for-device
for i in $(seq 1 300); do
  [[ "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '
')" == 1 ]] && break
  sleep 2
done
[[ "$(adb shell getprop sys.boot_completed | tr -d '
')" == 1 ]]
adb install -r "$root/android/app/build/outputs/apk/debug/app-debug.apk"
adb shell am start -W -n org.happyrun.app/.MainActivity | tee "$root/qa/android/launch.txt"
grep -q 'Status: ok' "$root/qa/android/launch.txt"
adb install -r "$root/android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk"
HAPPYRUN_DISPOSABLE_EMULATOR=1 bash "$root/scripts/android_acceptance.sh"
adb exec-out screencap -p > "$root/qa/android/launched.png"
