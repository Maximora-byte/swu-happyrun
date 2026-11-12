# Continuous foreground Activity / real HTTPS acceptance

## Scope and current evidence

Independent second-stage four-file test delta for the 278-file continuous-session
candidate manifest `4c35bc74cf8e9b2b0d7e1f704a8a5d35e96e61971ae2414336cde426d0ad28bd`,
based on `28871b2d599a8ec8335570effb3207d2564639ab`.

The existing fifteen remote HTTPS cases, production code, workflow, and KVM gate
are unchanged. The inherited certificate fixture is byte-identical to that base
and includes the corrected CA key usage. New tests reuse the dedicated remoteQa
build and per-job certificate; no downloadable variant gets a test trust anchor.

LOCAL STATUS: Python syntax, Ruff and twelve host/parser/source-contract checks
passed. Android SDK/android.jar, adb and Gradle are unavailable in the current
workspace, so this new Java instrumentation has NOT been compiled or executed.
No new Activity, Android TLS, Home, rotation, or MuMu success is claimed.

## Fourteen isolated scenarios per API

- `two_jobs`: start through Main's actual remote-entry button, explicitly connect,
  visibly wait, observe a real heartbeat approximately ten seconds after hello,
  then ADMIN creates two successive jobs. Both must complete with different
  sessions and increasing fences. Observe two real driver starts; exactly ten
  phase-boundary renewals, no per-tick renewal traffic; explicitly disconnect.
- `disconnect_idle`, `disconnect_running`: click actual Disconnect, require the
  worker to release ownership, real drivers stopped and no later HTTP/claim.
- `back_idle`, `back_running`: real Back key, old Activity stops, return through
  Main's entry. The new page must not restore a token or reconnect.
- `home_idle`, `home_running`: fixed `input keyevent 3` through instrumentation's
  UiAutomation, require actual loss of foreground/focus, then return the same
  Activity using Android's reorder-to-front intent. No lifecycle method is called.
  Missing/broken launcher or failure to leave foreground is a failure, not a skip.
- `rotate_idle`, `rotate_running`: request the opposite real screen orientation;
  require a different Activity instance from an ActivityMonitor and old worker
  shutdown. The recreated Activity must remain disconnected with an empty token.
- `auth_latch`: actual 401, visible session-ended state, no claim.
- `attention_latch`: real unsupported-profile attention; no driver start, no next
  claim, visible administrator-attention message.
- `transport_latch`: real fourth-renew delayed-response fault must fire; driver
  starts once then stops, session closes, server remains running/unconfirmed.
- `storage_latch`: a real private filesystem file occupies the journal directory;
  initialization fails, UI storage warning is visible, Connect stays disabled,
  and no agent HTTP is sent. It does not claim every later disk-failure mode.
- `rapid_toggle`: rapid duplicate Connect and Disconnect, wait for that worker's
  genuine release, explicitly connect again on the same Activity/executor, then
  ADMIN creates a job. It must really complete once without a stale interrupt.

Every scenario creates an additional ADMIN job after the UI's STOPPED marker.
It must remain queued while the test watches for no further authenticated agent
requests, including GET. No emergency cleanup may count as success. Platform
exit status, exactly `OK (1 test)` and one exact controlled PASS marker are all
required. First-phase fault injection remains in test wrappers around the real
server, not in production endpoints.

## Integration commands (future authorized AVD run)

Copy only the four manifest-listed files onto the candidate. Use the already
reviewed remoteQa preparation/build/install flow and its disposable-emulator
safety guard. Its generated CA resource remains
`android/app/build/generated/remoteQa/res/raw/remote_qa_ca.pem`.

The test APK must be built for remoteQa with `-PremoteQaInstrumentation`; the new
class is in the existing `src/remoteQaAndroidTest/java` source-set. Once the app
and matching test APK are installed, and the existing fixture's private
certificate directory has been prepared:

```sh
HAPPYRUN_DISPOSABLE_EMULATOR=1 ANDROID_SERIAL=emulator-5554 \
  python scripts/check_foreground_activity_https.py \
  --private-dir "$RUNNER_TEMP/remote-private" \
  --output qa/android-foreground
```

The host invokes only
`org.happyrun.app.remoteqa.RemoteForegroundActivityAcceptanceTest#testScenario`,
one test invocation for each of the fourteen cases. It requires synthetic
scenario/origin/agent/device/token arguments and runs real UI-owned
RemoteForegroundSession, HttpsAgentClient, RemoteJournal and RemoteFakeDriver.
Reflection is read-only observation of actual session/driver ownership and start
counts. No fake AgentClient, manual onStart/onStop, or Activity.recreate substitute
is used. Request counters and exact server state/fence assertions are independent
of the UI's controlled result markers.

Suggested future artifact whitelist: only `qa/android-foreground/report.json`.
Do not upload instrumentation stdout/stderr, command lines, private fixture
files, databases, journals, keys, credentials, or token-widget screenshots.
There are deliberately no screenshots in this delta. Even failure assertions for
the token field use booleans, so JUnit cannot print its actual value. App files and
shared preferences are inspected for the synthetic token before success.

Pure host checks, which do not start an emulator:

```sh
pytest -q -p no:cacheprovider tests/delivery/test_foreground_activity_contract.py
ruff check scripts/check_foreground_activity_https.py tests/delivery/test_foreground_activity_contract.py
```

Publication, workflow integration and the next exact KVM grant remain outside
this test delta. Actual official API31/API35 runs must pass before claiming the
second-stage Android lifecycle gates. Official AVD evidence does not establish
MuMu compatibility or real-school execution.
