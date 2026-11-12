# Native UI navigation regression: diagnosis and test-only revision

## Exact observed failure

PR40 head `8aef593dd89ca47d63a702ee1cf6952382169bbd`, selfProbe API31 job
117901246029, artifact12164599188. Artifact SHA256:
`794713040877a6097346b31b269900730696da9f22ae5af9c0736662c33f4892`.
All four AndroidAcceptanceTest cases failed before their first UI action:
three could not find start_simulation and one could not find refresh_checks.
SelfProbeInactiveTest had passed. The failing phase was native-debug, before
installation of the optional variant. The test finds resource names, not compiled
cross-variant numeric resource IDs.

The actual app-debug.apk resource table contains app_scroll (0x7f010001),
refresh_checks (0x7f010005), and start_simulation (0x7f010011), independently
checked with aapt2. The launch XML/screenshot show the real 320x640 MainActivity,
with the optional-framework wizard occupying the first viewport. The simulation
and environment buttons are below it. app_scroll is present and scrollable.
There is no failure-time UI tree, scroll position, or target geometry in that
artifact. A launch-time image cannot establish the failure-time Activity state.
The evidence does not establish missing resources, ANR, a product database fault,
or the precise reason why the accessibility search failed.

## Two test-helper issues

1. waitEnabled nominally allows 5000ms, but calls waitId(id,1000), which throws
   immediately on its own timeout. The outer budget is never used in that case.
   LegacyDeadlineRepro extracts that original method unchanged into controlled
   clock/lookup ports and reproduces failure at1000ms, before an otherwise-valid
   target could appear at1500ms.
2. The old waitId repeatedly sends scroll actions every50ms and changes direction
   whenever performAction returns false. It does not observe actual scroll
   completion or distinguish a rejected action from a real content boundary.
   This is fragile navigation, but has NOT been proven to cause this CI failure.
   AOSP Android12 ScrollView uses smoothScrollTo for accessibility scrolling:
   https://github.com/aosp-mirror/platform_frameworks_base/blob/android12-release/core/java/android/widget/ScrollView.java

## Minimal test-only change

AndroidAcceptanceTest's four test methods and semantic assertions remain.
NativeViewDeadline gives each wait one original budget, including observation,
with no nested1000ms assertion or timeout increase. Platform calls can themselves
block, so this is a shared request budget, not a hard wall-clock guarantee.

The adapter resolves the installed Activity's target resource by name, locates
its actual View, and requests its rectangle on screen with the standard immediate
View request. This only changes viewport position. It does not performClick,
invoke a listener, call business logic, grant permissions, or alter visibility.
ActivityMonitor tracks the actual new MainActivity after recreation; a destroyed
old reference is not reused. Missing/hidden/detached/unfocused targets fail.

After revealing, lookup STILL requires the active accessibility window and node
to belong to org.happyrun.app, a visible nonempty node rectangle intersecting the
active window, and the original enabled state. Clicks STILL use real
AccessibilityNodeInfo.ACTION_CLICK and must succeed. A new failure line records
only local resource/geometry/focus/window-package/scroll/reveal metadata. No UI
text, remote page dump, credentials or full app database is logged.

## Actual local verification

Run `python scripts/check_native_navigation.py` from the delta root.
- Legacy original-method controlled RED:5000ms advertised, failure at1000ms.
- Five compiled real NativeViewDeadline checks: delayed appearance/enabling,
  missing/disabled exhaustion, expected-disabled success, late response rejection.
- Eight compiled extracted-adapter checks: reveal before accessibility observation,
  recreated-current Activity, wrong window package, wrong node package, hidden,
  unfocused, detached, and wholly off-viewport node rejection.
- Python Ruff and compile check pass.

These are controlled JVM ports and source-extracted method tests. No Android SDK
or emulator was available locally. They do NOT establish Android compilation,
ART behavior, or that the specific8aef failure is resolved. The next actual AVD run
must still pass all four native UI cases; if it fails, retain NATIVE_NAV_FAIL and
its precise target geometry. Do not waive failures or infer success from this
source revision. The original four-failure evidence remains retained separately.

Unrelated JVM HTTPS intermittent_unresolved remains a separate open finding.

`tests/delivery/test_android_native_navigation.py` wires the same exact-source
checks into the existing pytest suite. It requires the Java compiler module
(JDK17+); absence of the java executable is an explicit skip, never a pass.
If Java exists but compilation or any check fails, pytest fails. Hosted jobs with
JDK17 run all13 controlled checks plus the legacy RED reproduction. No workflow
or Gradle changes are part of this test-only delta.
