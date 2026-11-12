# One Android durable-completion recovery scenario

Test-only delta for the native recovery manifest
`a83af3f1663da197a962bd34a3718a0ace238b4b150650ec2a2520478c265718`.
The ordinary fifteen remote cases and fourteen foreground-Activity cases are not
modified. In particular, their unknown/incomplete crash recovery continues to
require attention. This adds one separate positive scenario with two real Android
process stages.

## Required evidence

1. Prepare stage uses real HttpsAgentClient, RemoteAgentRunner, RemoteJournal and
   RemoteFakeDriver. The bundled route actually finishes once. Before the real
   verifying event is applied, the fixture holds that request. Instrumentation
   independently checks real driver startCount=1, finished=true, stopped=true and
   journal.finished=true. It emits a fixed nonsecret READY marker.
2. Host requires both that marker and the actual server request barrier, then
   performs real `am force-stop org.happyrun.app`. The preparation test must not
   have returned a successful JUnit result. No `pm clear` occurs between stages.
3. Wait for actual lease expiry and needs_attention/lease_expired. ADMIN issues
   verify_only with the correct current revision. No server clock is forged.
4. A new instrumentation process opens the same app-private journal. Its real
   completed request is held after the real verifying transition. Host posts a
   completion with the previous fence: real server must return 409 and leave its
   revision/state unchanged. Release the legitimate request.
5. The server must be completed, retain the original session and have a higher
   fence. Recovery's only committed events are verifying and completed. The new
   real driver must have zero starts, zero distance, finished=false and stopped=true.
   No journal bytes are manufactured, modified or truncated by the tests.

The fixed barrier is bounded and does not fabricate successful API replies.
Only requests at deliberate interruption/fence-probe boundaries are held.
Tokens and lease commands remain in private test-process memory. No raw output,
command line, screenshot, database, journal, certificate private key or token may
be uploaded. Even assertion messages contain only nonsecret fixed text.

## Integration

Use the existing reviewed remoteQa build, test APK, disposable-emulator guard,
per-job certificate preparation and installed Python server environment. Copy
only this delta's manifest-listed files; production code and workflow remain
owned separately. The test class is already under the remoteQa test source-set.

With matching APKs installed and the existing private CA directory available:

```sh
HAPPYRUN_DISPOSABLE_EMULATOR=1 ANDROID_SERIAL=emulator-5554 \
  python scripts/check_android_durable_recovery.py \
  --private-dir "$RUNNER_TEMP/remote-private" --output qa/android-recovery
```

The host targets
`org.happyrun.app.remoteqa.RemoteDurableRecoveryAcceptanceTest#testStage`, once
with stage=prepare and once with stage=recover. Preparation is deliberately
interrupted; recovery must return exactly `OK (1 test)` and one exact PASS marker.
Suggested artifact whitelist is only `qa/android-recovery/report.json`.
Report it as one scenario, not two successful JUnit tests; keep 15 + 14 + 1 counts
separate in summaries.

## Verification boundary

Four local Python barrier/source-contract checks and Ruff pass. New Android Java
has not been compiled or executed in this workspace: no SDK/android.jar, Gradle
or adb is present. The companion JVM test did exercise the real TLS/API and
cross-process journal behavior, including a negative missing-finished case, but
that does not establish Android ART/process behavior. Actual API31/API35 execution
is required before this scenario is called passed. MuMu remains unverified.

The companion JVM host also recorded intermittent ADMIN read timeouts when
running two separate Uvicorn fixtures sequentially in one Python process.
These failures are retained and are under diagnosis; an isolated-host pass must
not be taken as proof that the timeout's cause has been resolved. HTTP request
budgets remain unchanged. This test-source delta does not certify that issue.
