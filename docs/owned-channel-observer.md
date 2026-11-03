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
