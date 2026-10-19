# Native Android acceptance

This suite exercises the delivered native Activity and real local simulation engine, clock and SQLite. It creates only synthetic local data, does not run a real device driver, and cannot establish MuMu compatibility or accepted school records. The existing web console twelve-group suite remains separate and unchanged.

## Execution

Build the app and test APK with `gradle -p android :app:assembleDebug :app:assembleDebugAndroidTest`. On an explicitly selected disposable, booted Android API35 emulator, install both APKs without `-g`. Set `HAPPYRUN_DISPOSABLE_EMULATOR=1` to acknowledge this disposable fixture. Set `ANDROID_SERIAL` to its exact serial and run `bash scripts/android_acceptance.sh qa/android`.

The script clears only this synthetic emulator app's data. Never run it against a user's installation. Platform `android.test.InstrumentationTestRunner` is used; no AndroidX or UIAutomator dependency is added. Accessibility actions are issued by the test instrumentation to operate native controls. These test privileges are not shipping-APK capabilities.

The script checks instrumentation's success text and exact test counts as well as explicit failure markers, because `am instrument` can return shell success after a test failure. Use this script, not automatic discovery of all methods: process-recovery methods have an intentional host-orchestrated ordering.

## Assertions (eleven tests)

- Chinese native start control, diagnostics refresh, and disabled real execution.
- Fine/coarse location permission denied in a clean install; diagnostics remains usable and real execution stays disabled. No blanket permission grants. This does not claim a permission request dialog was exercised if the manifest requests none.
- User starts through native confirmation. Real engine advances the synthetic route to its endpoint, records `completed` rather than a real record, repeated start returns the same active task, and Activity recreation preserves the completed task.
- User confirms cancellation; the real engine persists `cancelled`, progress stops and no restart occurs.
- Separate process creates and actually finishes a simulation.
- After host `am force-stop`, another instrumentation invocation confirms the same completed task and endpoint remain in private SQLite.
- Separate process persists a real running intent.
- After host `am force-stop`, another invocation observes the same ID as `needs_attention/restart_uncertain`, then waits longer than a full simulation and confirms it did not replay or advance. Repeated start remains blocked on the same uncertain task; explicit cancellation permits a new ID while retaining the prior cancelled history.

Three additional storage cases each run in a separately cleared disposable process. They install a real SQLite `BEFORE INSERT` trigger using `RAISE(FAIL, ...)`, and remove it in `finally` cleanup:

- First ready-intent write fails in an empty database: there is no task row, global health is failed, subsequent mutation is refused, and the Activity explains “未保存” with both mutation buttons disabled.
- After a real completed simulation, a new ready-intent write fails: the old completed row remains persisted and unchanged, while global health and UI expose the new failure.
- A running tick and its fallback attention write both fail: direct SQL still reads `running`, but current/get/history project the affected ID as unpersisted attention. Start and stop cannot report success. Removing the fault does not silently resume motion or clear the latch.

These assertions distinguish durable rows from explicitly unpersisted UI projections. The storage tests do not reset a production singleton or add fault-injection hooks to production.

Activity recreation is explicitly not process-death evidence. No runtime `close()` call or mocked response substitutes for process recovery. Root/LSPosed installation, enablement, hooks, security changes and third-party app execution are outside this suite. Optional diagnostic indicators cannot enable real execution.

## Evidence and limitations

`qa/android` contains two synthetic screenshots, per-stage instrumentation text and report.json. Only publish reports/screenshots permitted by the workflow; never upload app databases or user data. CI must retain the tested commit, APK hash, package/version, SDK and emulator image. SDK installation may use already accepted runner licenses only; new license prompts must block rather than be blindly accepted.

At source handoff these tests have not run on Android: this executor lacks javac, Android SDK, adb and emulator. Shell syntax checking is not an Android pass. Actual results must come from the immutable candidate's CI. MuMu remains unverified until the actual delivered APK is installed and used without instrumentation on the specified MuMu version, with user-authorized permissions. Real app/device and final school-record evidence remain separate gates.

## MuMu Task 5: explicit display/task observation (not yet device accepted)

`DisplayObservationTest#testObserveOwnActivity` is an opt-in, API29+ entry for an
explicitly isolated test instance. It checks the installed signing certificate,
exact own package/Activity and one independently selected existing app task before
launching only that Activity within that task, preserving its display. It then checks the
actual Activity task/display, focused window and visible resource IDs in-process.
It does not use screen coordinates, UIAutomator/XML, shell input, Root, database
reset or simulation controls. A UUID binds each host invocation to its response;
missing, partial, late, wrong-display, wrong-task or mismatched-signature results
fail closed. `observed` is a first-frame observation, never a simulation completion.
`writes=0` means no test-issued input, simulation or control actions; instrumentation
itself may restart the target process and the app may perform normal lifecycle
persistence. It is therefore **not suitable for the user's existing installation**.

The pure-Java gate has host regression cases for wrong display/task/signature/app,
stale observation/timestamp, dump exit139, multiple tasks, no window/controls and
timeout. Six matching instrumentation fault cases are selectable individually.
These are synthetic policy checks, not evidence that MuMu executed them. The
existing disposable-AVD launch probe now rejects a nonzero dump even if its stdout
claims a file was written. No old XML is used by the new MuMu entry.

### Existing user data: observation only

1. Record the intended MuMu instance index/serial and MuMu/Android/app versions.
   Use `adb -s SERIAL shell pm path org.happyrun.app`, `dumpsys package
   org.happyrun.app`, `dumpsys activity activities` and `dumpsys window` as read-only
   observations. Keep raw output private; it may include other apps.
2. Verify the candidate's `SHA256SUMS`, APK package/version and certificate against
   the paired build manifest. Compare the installed APK certificate locally using
   the actual path returned by `pm path` and `apksigner verify --print-certs`.
   Never assume debug certificates from different CI runs match.
3. If signature differs, preserve the installed app/data and stop the upgrade path.
   Use a separate new test instance. Do not uninstall, `pm clear`, change Root,
   remove protection or run any reset fixtures to make an install succeed.
4. On the existing installation, Codex/user can visually inspect the selected
   window. If multiple tasks/displays cannot be disambiguated or dump exits139,
   report `blocked` and retain minimal local diagnostic evidence. Do not select
   the first task, assume display0 or click another app. Do not run instrumentation
   on the existing installation merely to obtain an observation.

### Isolated test instance: copyable checklist

Create/select a separate MuMu instance explicitly confirmed to contain no personal
data; do not clone a user's data into it. Record its identity. Install the ordinary
app and matching test APK from the **same build and signing identity**, without
`-g`; never substitute `remoteQa`. The package task handles the downloadable paired
artifacts and metadata. If those artifacts are missing, keep this step blocked.
Open only HappyRun manually in that instance, inspect the current task/display
from the device's actual `dumpsys` output, and require exactly one matching task.
Do not copy the example placeholders as IDs:

```sh
python scripts/check_mumu_observation.py --serial SERIAL --display OBSERVED_DISPLAY \
  --task OBSERVED_TASK --signature-sha256 VERIFIED_LOWERCASE_CERT_SHA256 \
  --isolated-no-personal-data --output observation.json
```

The host command has a 30-second bound. A timeout remains failed, even if a later
window appears; the device runner may still be alive. Do not start another action
until Codex has inspected that isolated instance. The script does not kill/reset
anything automatically. Never treat ADB exit0 alone as success; this script requires
one exact successful instrumentation test and one complete matching status bundle.

After a successful observation, independently exercise native controls in the
verified own window: complete the built-in 8-second/20-metre synthetic simulation;
explicitly stop a second simulation; restart after completion and confirm the same
completed ID persists; interrupt an active simulation and confirm the same ID
recovers to `needs_attention` without resumed motion. Record IDs/state and action
counts privately. These are manual Codex device acceptance steps, not performed by
the observation command. Existing automated storage/process fixtures may clear
synthetic data and remain limited to their disposable official AVD workflow:
`scripts/android_acceptance.sh` is **not a MuMu script**.

MuMu6.8.4.0/API35, instrumentation compilation/execution, same-build installed
signature validation, multi-display window observation and the four simulation
flows remain pending until the exact delivered candidate is tested on that device.
None establish third-party-app or school-record acceptance.

The paired-build checker publishes `qa/android/delivery-debug.json` (or
`delivery-optional.json` for the separately labelled optional build), with the
corresponding `.signatures.txt` and `.SHA256SUMS`. Select both APKs from the same
pair. Availability/verification depends on the exact candidate's CI; this source
change does not assert those artifacts have already been built.

### Explicit CI execution on the disposable official AVD

After installing the paired APKs and before any native fault/reset cases, run:

```sh
HAPPYRUN_DISPOSABLE_EMULATOR=1 ANDROID_SERIAL=SELECTED_OFFICIAL_AVD_SERIAL \
  python scripts/check_android_display_ci.py --delivery qa/android/delivery-debug.json \
  --output qa/android/display-debug
```

For the optional variant select its matching `delivery-optional.json` and separate
`display-optional` output. The helper starts only the own Activity once, reads the
actual display sections and all own task identities from successful `dumpsys`,
requires one resumed MainActivity/task/display, then runs the bound observation and
six individually selected negative methods. `report.json` requires seven actual
instrumentation passes; failure/timeout preserves its phase and partial count.
It does not use the first task, hardcode display0, clear data, click or change any
security setting. Task IDs use the public persistent `taskId`, not the deprecated
running-only `id` that may become -1 during instrumentation restart.

The observation checks the visible wizard resources `app_scroll`, `framework_probe`
and `wizard_refresh`, including `getGlobalVisibleRect` viewport intersection. The
simulation controls are farther down the long page and are not misreported as
first-frame visible; the observation does not scroll to them. API31/API35 exact-head
CI still must actually execute these checks; host fixtures and old dumpsys-format
compatibility tests are not execution evidence.

### Recent-task restoration scope

Instrumentation can leave the selected own task in recents without a live Activity.
The isolated observation entry validates the exact persistent MainActivity component,
then uses that same AppTask's public `moveToFront()` restoration path. Before restoring,
it requires the independently observed display to equal the system-reported default
display. Non-default or unavailable default displays fail as
`restore_display_unsupported` before restoration. No display is reassigned, no new
task is requested, and no task/data reset is performed. This is a current support
limit, not evidence of general multi-display or MuMu compatibility. The restored
Activity must still satisfy the original task/display/signature/window/viewport and
fresh-observation checks; a restoration return alone cannot pass acceptance.
