# Standalone Android / vivo read-only diagnostics

This module works without MuMu. It does not implement a running adapter or prove
vivo compatibility. Run it only on the authorized local host with the exact
selected, already-authorized device. No device was accessed during development.

```powershell
python -m swu_happyrun.drivers.android_diagnostics --adb "C:\platform-tools\adb.exe" --serial "YOUR_SELECTED_SERIAL" --package "YOUR_CONFIRMED_PACKAGE" --json
```

No package name is guessed. Omit `--package` to omit app inspection. Without
`--serial`, only `adb devices` runs; even one connected device requires explicit
selection. Raw serials and the device list are not returned. The caller keeps the
selected serial privately to correlate the report. Android and MuMu identities
are never automatically merged.

The metadata report includes model, ABI list, Android release/API level, and
requested app versionName/versionCode. Each field is `observed` or `unknown` with
a reason. Empty/invalid/vendor-specific output is not successful evidence.
Connection failures distinguish no device, multiple devices, serial required,
selected device absent, unauthorized, offline, host permission denied, unsupported
transport state, invalid output, missing executable and command timeout. Each ADB
command has a five-second host timeout. No permission is granted automatically.

`--samples` additionally lists diagnostic services with `dumpsys -l` and reads
`dumpsys location` / `dumpsys sensorservice` only when listed. It reports only
recognizable diagnostic-header presence. All raw service text is discarded;
coordinates, accounts, active clients, and sensor values are never printed or
written. Permission denial, missing services, timeout, empty response and unknown
OEM formats remain `unknown` with distinct reasons. `unsupported` here means the
requested diagnostic service is unavailable, not that the physical hardware is
incapable. This deliberately minimal service diagnostic is not a live position
or sensor sample: `live_read` always remains `unknown`. Fresh, timestamped values
and the app's use/acceptance of them require a separately verified device adapter.

Top-level `ok` / exit 0 means the requested metadata and diagnostic headers were
observed. `partial` / exit 2 means a requested item was unknown. `blocked` / exit 2
means no device metadata queries were permitted/completed. Omitted package/sample
checks do not fail the report. Even `ok` always has `capabilities=[]`,
`device_verified=false`, `record_verified=false` and execution unsupported by this
candidate. It is not a school record or a server capability-probe payload.

Commands never pair/connect/install/start apps, write settings or position/sensor
data, grant permissions, request Root, or upload. As documented by Android, an
ADB invocation can implicitly start the host ADB server; “read-only” describes
the device queries, not an assertion of zero host-process side effects.

## Integration

Use `swu_happyrun.drivers.android_diagnostics.collect_report(adb=Path(...),
serial=..., package=..., samples=False)` from an explicit Android doctor backend.
Do not require MuMu discovery for that backend. This change intentionally does
not modify the central CLI, existing AdbClient capability model, protocol schema,
dependencies or CI. The standalone module entry point is immediately usable.

## Sources and evidence boundaries

- [Android ADB documentation](https://developer.android.com/tools/adb): explicit
  target selection, authorization, device state, and implicit host-server startup.
- [Android dumpsys documentation](https://developer.android.com/tools/dumpsys):
  per-service read-only diagnostic commands and service listing.
- [AOSP LocationManagerService](https://android.googlesource.com/platform/frameworks/base/+/103d94325d602d73f6ff2a12554c484c29899cdc/services/core/java/com/android/server/location/LocationManagerService.java):
  `Location Manager State:` diagnostic header.
- [AOSP SensorService](https://android.googlesource.com/platform/frameworks/native/+/2eaec5a833f69b3c460386e38aa6affe5e4b1772/services/sensorservice/SensorService.cpp):
  `Sensor List:` header and permission-denial behavior.

Sources checked 2026-10-18. AOSP format recognition is not evidence that any
particular vivo/Android release returns the same format. Tests use synthetic
transcripts only. Windows, real vivo, MuMu, app sessions and school acceptance
remain not tested.
