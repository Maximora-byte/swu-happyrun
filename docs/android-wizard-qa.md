# Independent novice-wizard QA

This delta does not alter or relabel the initial eleven native APK tests.

Run `org.happyrun.app.WizardAcceptanceTest` with the existing platform instrumentation runner on each ordinary/no-framework optional-module APK variant. The variant flag is read reflectively through the installed target Context class loader, never an inlined test-APK BuildConfig constant. All app view IDs likewise resolve by name from target resources; platform android.R.id.message stays platform-owned. Four tests cover conservative inactive/unknown receipts and variant labels; opening the explicit Root confirmation, duplicate entry, then cancelling; returning from instructions and refreshing without authorizing Root; and presentation-only active/pending fixtures that still cannot unlock real execution or open a second request.

The positive Root confirmation button is never pressed. No test installs a framework, enables a module, invokes `su`, or accepts a manager permission. The active receipt and pending state in the fourth test are explicitly reflection-injected UI fixtures, not ART hook or Root evidence. Dialog cancellation is checked against unchanged `not_checked`/not-pending UI state and the source's only positive-confirmation launch path; it is not a device-level process audit.

The separate JUnit `RootDiagnosticIndependentTest` injects only in-memory Process objects into the package-private runner. Three tests check one fixed-command invocation and timeout cleanup, exact successful uid=0 interpretation versus rejection/malformed identities, and pre-cancellation with zero factory calls. The public process-discovery/execution overload is never used. Runtime's existing fake-process tests and UI's WizardPresentation tests remain additional coverage.

Instrumentation invocation: `adb -s "$ANDROID_SERIAL" shell am instrument -w -r -e class org.happyrun.app.WizardAcceptanceTest org.happyrun.app.test/android.test.InstrumentationTestRunner`. Require exact `OK (4 tests)` and reject instrumentation failure markers; a shell exit code alone is insufficient. Run only on the explicit disposable CI emulator using the packaging workflow's guardrails. Native initial-suite report stays separate.

Real framework activation, a live Root manager decision, custom Android image compatibility, and real execution remain unverified by these tests. Source handoff is not a device pass; record the immutable HEAD and each actual CI result.
