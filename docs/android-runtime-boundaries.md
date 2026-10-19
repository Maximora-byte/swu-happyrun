# Native local runtime: scope and evidence

The APK local runtime requires no host Python/server process. Its built-in 8-second,
20-metre square is a synthetic diagnostic example, expressed in local metres, with
no campus coordinates or school rules. Completing it proves only local simulation
progress. It does not inject device locations/sensors, control another app, upload
runs, or prove an accepted school record.

`LocalRuntime.get(Context)` is process-wide. SQLite in private app storage saves
`ready/start_intent` before initializing synthetic motion. A single scheduler uses
Android elapsed realtime; concurrent start requests while running return the same
ID. Stop saves `cancelled` for this local simulation. Completed/cancelled states
remain persisted. Reopening a process converts prior ready/running to
`needs_attention/restart_uncertain`; no automatic resume or replay occurs. A recovered task blocks new starts until the user explicitly stops that local
simulation. Only then can another simulation click create a new UUID. Old rows
remain available with `getTask(id)`. This is a local-only DTO, not a server JobView, grant, or stop-ack.

Keep the app foreground during the example. There is no foreground-service or
background-execution permission. Android can kill the process; recovery remains
uncertain. Activity recreation must not call runtime.close(): that method is for
process-level shutdown, not view lifecycle events. No INTERNET, location, sensor
injection, accessibility or Root permissions are requested.

Diagnostics enumerate OS and accelerometer availability only. They do not imply
live sensor quality. Public `su` path existence is an unverified Root hint; absence
is inconclusive. No `su` is run. LSPosed version, activation, module scope and write
capabilities are unknown. `ExecutionAdapter.Unsupported` is an extension boundary
for Android/MuMu/Root/LSPosed; its start always fails with adapter_not_verified.
There is no hook implementation in this deliverable.

## Official capability references (checked 2026-10-19)

- Android [LocationManager](https://developer.android.com/reference/android/location/LocationManager):
  test providers require allowed mock-location app-op; injected locations are marked
  mock. Location read permission is not injection authorization.
- [Developer options](https://developer.android.com/studio/debug/dev-options): the
  user chooses a mock-location app. This APK does not change that setting.
- AOSP [SensorManager source](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/main/core/java/android/hardware/SensorManager.java):
  sensor data injection is hidden/system testing API, requires service/HAL test mode,
  and is explicitly not a third-party app API.
- [Foreground service launch](https://developer.android.com/develop/background-work/services/fgs/launch):
  background launch and service-type permissions constrain modern Android services.
- The current [LSPosed official site](https://lsposed.org/) points to the public
  `lsposed.zip` distribution and its changelog. The older GitHub v1.9.2 README's
  Android 8.1–14 range must not be applied to every current official build. Exact
  Android 15/16, emulator-image, framework build and module-scope compatibility
  still requires version-specific evidence; this APK does not claim it.
- MuMu's [Mac developer documentation](https://www.mumuplayer.com/help/mac/developer-support-function.html)
  describes host command tools; it is not a guest APK API and is not evidence for
  MuMu 15 Windows behavior. The Windows developer page could not be retrieved in
  this review, so its exact feature/version support remains unverified.

Actual target app package/version, permitted integration, selectors, record readout,
and sensor/location transport remain missing adaptation evidence. No guessed
values or security bypasses are supplied.

## Storage failure visibility

If a tick write and its follow-up attention write both fail, motion is stopped in
memory and storage health is latched. `health()` reports
`storage_write_failed_not_persisted`. `currentTask()` projects needs_attention with
`persisted=false`; this explicitly does not claim SQLite was updated. The original
persisted intent stays in the database. Start/stop writes also latch failures and
throw instead of returning success. New operations remain blocked for this process;
repair storage and restart to recheck the durable state. History/getTask apply the same explicitly unpersisted projection only to the
affected task ID; prior completed tasks remain unchanged. If the first intent
insert failed, no new snapshot exists, so the UI must always display health
independently of whether currentTask is null.

The only target-package query is `com.lptiyu.tanke`, identified by the publisher's
[official application-store listing](https://a.app.qq.com/o/simple.jsp?pkgname=com.lptiyu.tanke).
Diagnostics report the installed PackageInfo version, never the store's version as
a device observation. A matching package or version does not verify an adapter.
