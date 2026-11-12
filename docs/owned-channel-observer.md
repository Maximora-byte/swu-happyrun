# Own-APK channel observer (review candidate)

Baseline: 9534f51efe3a557e6b4bda5605426e4004a34783. See #7 and #41;
PR61 remains the separate offline MuMu 6.8.4/API35 design.

This incremental observer is contained in the instrumentation APK. It registers
Android GPS location or TYPE_GRAVITY listeners against org.happyrun.app only.
It never writes a location or sensor value, invokes MuMu, requests permissions,
changes a provider, enables a framework, or contacts another application/server.
It grants no driver capability and creates no control-plane evidence or stop ack.
The existing optional selfProbe target declares coarse/fine location permissions;
ordinary debug/release permissions are unchanged. No Root/LSPosed setup is needed
or performed by this reader. remoteQa does not inherit the permission overlay.

## Callable surface and privacy

AndroidObservation.start(ownTarget, channel, durationMillis) must run on the main
thread. Only location/gravity and 1–5000 ms are accepted. Location requires an
already granted precise permission; refusal, approximate-only permission, absent
GPS provider or absent gravity sensor remain permission_required/unsupported.
It never accepts an Android permission prompt. A local user may choose permission
in Android settings on their isolated QA instance after reviewing the artifact.

The session retains up to 128 fresh finite samples in memory only. Each has the
channel, elapsedRealtime timestamp, copied numeric values and reported accuracy.
Location values are latitude/longitude and accuracy in metres; gravity values are
Android TYPE_GRAVITY values and sensor accuracy status. These Android semantics
DO NOT establish MuMu input CRS, vendor gyro units/axes or correlation with an
injected value. Coordinates never appear in instrumentation status/log output.
The immutable per-sample snapshot API is intended for subsequent locally reviewed
correlation against existing R1 binding/R2 calibration evidence, not a replacement
identity/calibration model. There is no persisted trace/export in this increment.

References: [Android Location](https://developer.android.com/reference/android/location/Location),
[LocationManager](https://developer.android.com/reference/android/location/LocationManager),
[SensorEvent](https://developer.android.com/reference/android/hardware/SensorEvent).

## Observation stop is not injection stop

stopObserving() closes the callback gate before attempting every registered
listener removal; one failure does not suppress the others. Delayed callbacks,
old/future/non-increasing timestamps, non-finite values and samples at/after the
deadline are rejected. Sample and duration bounds are independent. Snapshots are
copies, and a closed session cannot restart or register another cleanup action.
Cleanup failure remains observation_cleanup_unconfirmed, never success.

A main-thread timer attempts unregister at the deadline. Android main-thread
scheduling is not a hard wall-clock guarantee; the callback buffer independently
rejects late arrivals. The instrumentation wait and main-thread invocation also
need the existing outer host timeout. Closing a reader or observing silence does
not stop MuMu injection, clear its queue, restore prior state, or authorize a new
run. No stop/queue operation is invented here.

## Field entry (not run by this delivery)

After local artifact/signature review, matched optional selfProbe app/test
installation and the user's explicit permission choice, run only the
org.happyrun.app.observation.AndroidObservationTest class through the existing
approved instrumentation workflow, adding ownedObservationChannel=location or
gravity. Each explicit invocation observes for 1000 ms and then unregisters.
The test reports counts, samples_observed/no_samples, injection_status=unsupported
and injection_stop=unconfirmed. No samples fails the test; a nonzero count only
proves fresh callbacks, not an injected-value match or stop acceptance.

Without the explicit argument the test reports not_run_opt_in_required and
registers no listener; a generic green suite does not imply physical observation.
No installer/device command or automated permission grant is included here.

## Evidence and remaining gates

Real JVM tests cover fresh/stale/future/repeated/non-finite callbacks, independent
channels, sample cap, exact deadline, defensive copies, close/late-callback race,
idempotent close, all-cleanups-after-failure and registration after close. These
are deterministic callback/lifecycle tests, not Android API tests.

The cloud executor has Java but no Android SDK/runtime. Android adapter compilation,
permission behavior, callback availability and listener cleanup on MuMu remain
unverified. Existing checks.yml builds both debug and selfProbe instrumentation
APKs, so normal hosted build/static CI can verify API compilation without a new
KVM/runtime grant. No workflow change or emulator run is requested.

Before a physical write/readback/stop trial: independently establish vendor stop
and queue semantics per channel, location input CRS, gyro units/axes/timing, and
current private R1 binding/R2 calibration/authorization. TYPE_GRAVITY availability
alone does not prove it corresponds to vendor gyro. Unknown remains unsupported.
No school/third-party app execution or school record verification is included.

## N2 private readback bridge (software candidate, device acceptance pending)

`OwnProbe(adb, binding, binding_check=..., authorization_check=...)` consumes the
existing `MumuBinding`; `sample("location" | "gravity", duration_ms=1..5000)` returns
at most 128 immutable `OwnSample` objects. Location values are `(latitude,
longitude)` and accuracy is meters. Gravity values are Android `TYPE_GRAVITY`
`(x,y,z)` in m/s² and accuracy remains Android's integer sensor status. Vendor
MuMu `gyro --angle` takes angles according to the
[MuMu command reference](https://mumu.163.com/help/20240726/35047_1170006.html).
These channels and units are different; gravity never enables gyro or steps.

The actual bridge invokes only
`org.happyrun.app.observation.AndroidObservationTest#testPrivateReadbackWhenRequested`
in the paired `org.happyrun.app.test` instrumentation package. The method requires
the `selfProbe` build type, reads the boot ID itself, collects real own-package
callbacks, and writes a CREATE_NEW/nofollow file under the own app's private files
directory. Ordinary and remoteQa builds do not enter this private sampling path;
no manifest permission is added. Precise location permission must already be
chosen by the user; no grant command is issued. No cached/last-known location API
is used. Device timestamps must fall within the new device-side window and be
strictly increasing. Host monotonic time is never subtracted from Android time.

The host fetches that single nonce-named result with `adb exec-out run-as` and
strictly checks the nonce, binding digest, boot, channel, window, sample shape,
accuracy and the 64 KiB private-JSON budget. Capture reuses the exact #87
`65d44ae8747affd10fc7928e664cb9002cf0b120` implementation (1 MiB per stream,
strict UTF-8, shared pending-process/reader gate); the returned private JSON is
then independently capped at 64 KiB. Re-encoding normalized UTF-8 does not change
JSON numeric values. Raw output and argv are never printed. Instrumentation has
an explicit duration-plus-10-second host startup/completion budget; private fetch
and deletion each have five seconds, and each capture has its separate 0.5-second
cleanup budget. This is bounded own-app instrumentation, including listener
registration and a private temporary file, not a purely side-effect-free query.
It does not authorize using the readonly helper for arbitrary device writes. The
private remote file is removed even when decoding fails. Failed removal or an
uncertain instrumentation exit returns `private_cleanup_unconfirmed`, never
samples, and that probe instance cannot start another observation. An adb timeout
cannot prove the Android process ended; a late private result may remain and
requires local inspection/recovery before a new probe instance is used. The
latch is per object only; it is not a persisted cross-CLI recovery lock. The
raised error preserves the original fixed `primary_code` alongside the cleanup
failure, and the CLI exposes only those fixed reason codes. Listener
cleanup is not an injection stop or queue-empty acknowledgment.

Use the same-source, same-signature selfProbe app/test pair verified by the existing
`check_selfprobe_apks.py`; installation and Android permission selection remain
Codex/user operations. This change does not generate, replace or mix APKs or CA
material. Android SDK compilation is still a required normal-CI check on the
published exact head, separate from the JVM/Python tests.

PowerShell, after installing the verified package pair and preparing a fresh local
binding observation for the own package:

```powershell
python scripts/check_mumu_virtual_channel.py --channel location
python scripts/check_mumu_virtual_channel.py --adb $Adb --binding $PrivateBinding --channel location --duration-ms 1000 --observe-own-channel --isolated-no-personal-data --private-output $NewPrivateEvidence
```

The first command is a zero-process preview. The second is a bounded read only,
checks binding freshness and the actual selected device boot before/after the
observation, and prints only fixed status/channel/count/calibration/stop fields.
`--private-output` is optional, exclusively creates a new local file, and must
stay local. It contains sample values and local correlation metadata, so never
attach it to an issue, public report, or distribution. Restrict its containing
folder to the current Windows user; POSIX creation requests mode 0600. The
binding input is opened as a regular file, rejects links/reparse points in the
file and parent chain, and reads only limit-plus-one bytes. Output rejects linked
parent directories and exclusively creates a new regular file. These checks do
not create or broaden a Windows ACL; that private-directory setup remains the
operator's responsibility.

After N1's write/stop/queue prerequisites are independently accepted, Codex can
invoke this reader after each of two asymmetric controlled virtual targets.
Declare the target-to-readback error and latency budget in that local experiment.
Those observations establish only the tested point mappings and elapsed windows;
they do not prove all CRS transformations, no vendor queue, effective trajectory
stop, step counts, or any accepted school record. Missing callbacks, permissions,
cleanup or channel evidence remain failures/unknown, and capabilities stay empty.
