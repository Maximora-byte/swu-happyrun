# Foreground HTTPS failure evidence, head234

## Exact evidence and limits

Head234d280c23f5275371a5092bfdc7a4b7ea302f65, run39213656611,
API35 job117932440516. Artifact SHA256:
4e52654bb627e37af4c2daa97194a0bd109e90679baf991a0454b481126410dd.
The original remote15 cases passed; foreground back_idle and rapid_toggle have
only `error_type: RuntimeError`. The other12 foreground cases passed. Later
recovery suites were not reached. Raw instrumentation output was deliberately
not uploaded, because the command/UI contains synthetic credentials.

The current host's assertion failures normally produce AssertionError, and
subprocess timeouts produce TimeoutExpired. Explicit RuntimeError sites include
the disposable-emulator guard and TLS fixture startup/shutdown. The fixture's
finally block can replace a body failure with `TLS fixture did not stop`, leaving
the old report unable to identify either the body phase or the shutdown cause.
This is a confirmed evidence-loss mechanism, NOT proof that these two particular
failures were teardown failures or that the product UI passed. No failure-time
server stack exists in the original artifact. No ANR, lifecycle race, SQLite lock,
or relationship to the earlier JVM intermittent case is established.

## Narrow diagnostic revision

The host retains fixed phases for guard, server startup, device preparation,
instrumentation startup/observation, STOPPED, sentinel creation, instrument finish,
and strict stopped-state validation. Body outcome/type and cleanup phase are
recorded separately. The original lifecycle, worker-stop, no-new-HTTP, sentinel,
credential-storage, driver-start and exact JUnit/marker checks are unchanged.

The TLS fixture records independent startup and shutdown codes. A body error is
preserved as the explicit cause of shutdown failure, with its safe type and
original fixture phase. If a body passes but shutdown fails, the case still fails.
No timeout, join budget, TLS setting or server stop condition was changed. No
thread is forcibly terminated or treated as successfully stopped.

On shutdown failure, diagnostics include server thread alive/connection/task
counts plus only allowlisted source basename/function/line tuples. There are no
absolute paths, source text, locals, arguments, request headers, exception messages,
certificate contents, database rows or UI text. Instrumentation evidence retains
only exact controlled markers, a JUnit-count summary, platform-failure boolean and
matches against a fixed assertion-label allowlist. Raw stdout/stderr stays private
and is never serialized. Unknown exception classes become other_exception.

## Deterministic tests and next evidence

The regression suite demonstrates the old body-plus-finally masking behavior,
then exercises the actual revised fixture function under controlled server/thread
ports: body+shutdown failure, successful body+failed shutdown, startup failure,
startup+shutdown failure, body failure+successful shutdown, and normal close.
It also injects a sentinel credential into arbitrary output/error strings and
checks that the safe report excludes it. Stack evidence excludes unlisted frames,
absolute paths and locals. These are deterministic host tests, not Android results.

Actual original TLS fixture tests are also run against the revised fixture over
loopback using temporary synthetic certificates. The original API/Android budgets
remain unchanged. A next authorized AVD run should provide the new phase and
separate body/shutdown evidence if failure recurs. Until then the head234 failures
remain unresolved. Do not call this diagnostic addition a product/lifecycle fix
or infer success from the12 neighboring passes.

Final local result:27 passed (9 new deterministic diagnostic regressions,
12 unchanged foreground contract checks,6 unchanged real local TLS checks).
The existing two test files and Java Activity source were copied unchanged only
for this isolated local verification; they are not part of the4-file delta.
Ruff check/format use the exact candidate pyproject.toml (line length100).
Android/AVD has not been rerun for this delta. The two head234 failures remain open.
