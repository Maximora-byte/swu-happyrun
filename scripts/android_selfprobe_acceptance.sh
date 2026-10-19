#!/usr/bin/env bash
# Only a disposable official AVD. No framework install, root, or external app scope.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
[[ "${HAPPYRUN_DISPOSABLE_EMULATOR:-}" == 1 ]]
[[ "${ANDROID_SERIAL:-}" =~ ^emulator-[0-9]+$ ]]
[[ "$(adb shell getprop ro.kernel.qemu | tr -d '\r')" == 1 ]]
mkdir -p "$root/qa/android"
run_inactive() {
  local variant="$1"
  adb shell am instrument -w -r -e class org.happyrun.app.SelfProbeInactiveTest \
    -e expectedProbeVariant "$variant" \
    org.happyrun.app.test/android.test.InstrumentationTestRunner | tee "$root/qa/android/selfprobe-$variant.txt"
  ! grep -Eq 'FAILURES!!!|INSTRUMENTATION_FAILED|INSTRUMENTATION_ABORTED|shortMsg=|INSTRUMENTATION_STATUS_CODE: -[123]' "$root/qa/android/selfprobe-$variant.txt"
  grep -Eq 'OK \(1 test\)' "$root/qa/android/selfprobe-$variant.txt"
}
run_wizard() {
  local variant="$1"
  adb shell am instrument -w -r -e class org.happyrun.app.WizardAcceptanceTest \
    org.happyrun.app.test/android.test.InstrumentationTestRunner | tee "$root/qa/android/wizard-$variant.txt"
  ! grep -Eq 'FAILURES!!!|INSTRUMENTATION_FAILED|INSTRUMENTATION_ABORTED|shortMsg=|INSTRUMENTATION_STATUS_CODE: -[123]' "$root/qa/android/wizard-$variant.txt"
  grep -Eq 'OK \(4 tests\)' "$root/qa/android/wizard-$variant.txt"
}
run_inactive debug
bash "$root/scripts/android_acceptance.sh" "$root/qa/android/native-debug"
run_wizard debug
adb shell am force-stop org.happyrun.app
# Same-job debug certificate, same application ID: replacement, not co-installation.
adb install -r "$root/android/app/build/outputs/apk/selfProbe/app-selfProbe.apk"
adb install -r "$root/android/app/build/outputs/apk/androidTest/selfProbe/app-selfProbe-androidTest.apk"
HAPPYRUN_ANDROID_LAUNCH_PROFILE=wizard python "$root/scripts/check_android_launch.py" "$root/qa/android/optional-launch"
run_inactive optional
bash "$root/scripts/android_acceptance.sh" "$root/qa/android/native-optional"
run_wizard optional
printf '%s\n' '{"no_framework_tests":2,"result":"passed","art_activation_verified":false}' > "$root/qa/android/selfprobe-report.json"
printf '%s\n' '{"wizard_tests_per_variant":4,"variants":2,"result":"passed","root_command_executed":false}' > "$root/qa/android/wizard-report.json"
