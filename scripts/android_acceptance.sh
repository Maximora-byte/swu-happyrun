#!/usr/bin/env bash
# Execute only against a disposable CI emulator with synthetic local simulation data.
set -euo pipefail
: "${ANDROID_SERIAL:?Set ANDROID_SERIAL to the explicitly selected disposable emulator}"
[[ "$ANDROID_SERIAL" =~ ^emulator-[0-9]+$ ]] || { echo 'Refusing non-emulator serial' >&2; exit 1; }
[[ "${HAPPYRUN_DISPOSABLE_EMULATOR:-}" == 1 ]] || { echo 'Set HAPPYRUN_DISPOSABLE_EMULATOR=1 only for a disposable QA emulator' >&2; exit 1; }
OUTPUT_DIR="${1:-qa/android}"
mkdir -p "$OUTPUT_DIR"
PACKAGE=org.happyrun.app
RUNNER=org.happyrun.app.test/android.test.InstrumentationTestRunner
run_case() {
  local label="$1" class="$2" expected="$3" log="$OUTPUT_DIR/$1.txt"
  adb -s "$ANDROID_SERIAL" shell am instrument -w -r -e class "$class" "$RUNNER" | tee "$log"
  if grep -Eq 'FAILURES!!!|INSTRUMENTATION_FAILED|INSTRUMENTATION_ABORTED|shortMsg=|INSTRUMENTATION_STATUS_CODE: -[123]' "$log"; then
    echo "ANDROID_QA_FAIL $label" >&2; exit 1
  fi
  grep -Eq "OK \(${expected} tests?\)" "$log" || { echo "Missing exact successful test count for $label" >&2; exit 1; }
  echo "ANDROID_QA_PASS $label $expected"
}
adb -s "$ANDROID_SERIAL" wait-for-device
[[ "$(adb -s "$ANDROID_SERIAL" shell getprop ro.kernel.qemu | tr -d '\r')" == 1 ]] || { echo 'Selected target is not an Android emulator' >&2; exit 1; }
# No grant-all flag, permission elevation, Root, module install, or personal data.
adb -s "$ANDROID_SERIAL" shell pm clear "$PACKAGE" | grep -qx 'Success'
run_case native_ui org.happyrun.app.AndroidAcceptanceTest 4
run_case prepare_completed org.happyrun.app.ProcessRecoveryTest\#testPrepareCompletedTask 1
adb -s "$ANDROID_SERIAL" shell am force-stop "$PACKAGE"
run_case completed_persistence org.happyrun.app.ProcessRecoveryTest\#testCompletedTaskSurvivesProcessRestart 1
run_case prepare_interruption org.happyrun.app.ProcessRecoveryTest\#testPrepareRunningIntent 1
adb -s "$ANDROID_SERIAL" shell am force-stop "$PACKAGE"
run_case recover_without_replay org.happyrun.app.ProcessRecoveryTest\#testRecoverWithoutReplay 1
adb -s "$ANDROID_SERIAL" pull "/sdcard/Android/data/$PACKAGE/files/qa/." "$OUTPUT_DIR/"
for method in FirstIntentFailureIsVisibleWithoutTask NewIntentFailurePreservesPreviousCompletion TickAndAttentionWriteFailureNeverClaimsSavedOrStopped; do
  adb -s "$ANDROID_SERIAL" shell am force-stop "$PACKAGE"
  adb -s "$ANDROID_SERIAL" shell pm clear "$PACKAGE" | grep -qx 'Success'
  run_case "storage_$method" "org.happyrun.app.StorageFailureTest#test$method" 1
done
for method in EmptyUiStaysIdle TerminalUiStaysIdle ActiveProgressBackgroundReturnAndStop StorageLatchRemainsVisibleAndIdle; do
  adb -s "$ANDROID_SERIAL" shell am force-stop "$PACKAGE"
  adb -s "$ANDROID_SERIAL" shell pm clear "$PACKAGE" | grep -qx 'Success'
  run_case "polling_$method" "org.happyrun.app.PollingAcceptanceTest#test$method" 1
done
printf '%s\n' '{"suite":"android-native","tests":15,"result":"passed","simulation_only":true,"mumu_verified":false,"record_verified":false}' > "$OUTPUT_DIR/report.json"
echo 'ANDROID_QA_RESULT 15 passed / 0 failed'
