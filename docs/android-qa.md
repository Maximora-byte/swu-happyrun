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
