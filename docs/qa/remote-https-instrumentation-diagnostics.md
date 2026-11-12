# Original HTTPS acceptance: private instrumentation diagnostics

## Actual a449 failure

The API 35 artifact has SHA-256 `fd231527a19d7a9bfd9872f62bb157c34ae6827e110110ea6be68cb6780895e6` (job 117973599458, run 39226390278). Its report contains 14 successful original HTTPS cases and one `lost_event` failure at check_remote_https_android.py line 100. The three UI tests run before this loop and passed. Later foreground and recovery groups were not executed.

Line 100 rejects any nonzero instrumentation exit, missing `OK (1 test)`, or output containing `FAILURES`, `INSTRUMENTATION_FAILED`, or `Exception`. The artifact retained none of the distinguishing instrumentation output. Therefore it cannot determine which of these conditions occurred, which Java assertion failed, or whether the Android process aborted. This failure was not reported as FixtureLifecycleError. No current evidence proves a production defect or an environmental explanation.

The lost-event fixture commits the finishing event, then withholds its response for seven seconds. The actual client retains its five-second budget. The Java test joins the real worker for 15 seconds, rejects use of its existing seven-second emergency stop, checks worker exit/no exception/claimed job/stopped driver, rejects completion, requires one start and `attention_unconfirmed`, then verifies distance remains unchanged after 200 milliseconds. These assertions and budgets are unchanged. Successful prior runs do not establish why this run failed; no blind rerun was performed for this diagnostic delta.

## New evidence

The original 15-case runner now records the same fixture startup/body/shutdown separation already used by the foreground runner. Instrumentation summaries contain only exit code, exact JUnit count, failure/exception booleans, fixed assertion codes, fixed Java phase/error categories, bounded known-test-method line numbers, and bounded driver/worker/local-state snapshots. Arbitrary stdout, stderr, messages, paths, tokens and stack frames are never copied to the report. Timeout partial output passes through the same allowlist.

Java emits stages around hello, journal open, real worker start/join, fallback, assertion groups, final reporting and normal resource closure. The snapshot distinguishes worker-alive, captured runner error, driver stop/start count and enumerated local status. An exception is classified and rethrown unchanged; failure to emit diagnostics cannot replace the primary exception. The existing success predicate is unchanged, so diagnostic markers cannot make an otherwise failing test pass.

If fixture shutdown fails, subsequent original cases are explicitly `not_run` with `fixture_contaminated`, and the whole runner fails. A body failure with clean teardown continues collecting independent cases. No resource is force-closed to manufacture success, and no timeout, lifecycle action, or production code changes.

## Local verification and limits

Fourteen local regression tests cover private-text exclusion, enum/count bounds, actual host rejection/pass/timeout paths, strict predicate preservation, case-loop fail-fast/continuation, and extracted Java diagnostic methods preserving the original exception even when status emission fails. The initial three diagnostics tests failed before the new parser existed, then passed after implementation. Ruff checks use the candidate's project configuration.

The Java extraction test compiles and executes the actual diagnostic methods and test wrapper with controlled ports. It does not compile the complete Android test against the Android SDK or execute ART. Full Android compilation and real API 31/35 execution remain required. This delta increases evidence and isolation; the a449 lost-event root cause remains unresolved.
