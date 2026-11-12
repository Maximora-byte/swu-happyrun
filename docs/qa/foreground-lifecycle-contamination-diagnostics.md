# Foreground HTTPS lifecycle diagnostics

This test-only delta follows the e490 API 35 failure. It does not establish an Android product fix.

## Preserved evidence

The HTTPS artifact SHA-256 is `cb754983f65492a121adf70bf66e94d1ff647d3cf32a21934badac3590a04195`.
The disconnect-running instrumentation passed, including STOPPED and PASS markers, but the fixture failed its unchanged 10-second shutdown join: one connection, zero tasks, a live event loop and scheduler. Back idle/running later timed out at the host's await-stopped phase; Home idle/running reported platform failure. Their precise Java blocking/failure stages were unavailable. The existing runner continued after the live fixture thread, so independence of these later failures was not established. API 31 passed on the same source.

## Bounded local mechanism experiment

A real trusted loopback TLS client read a complete HTTP 200 response and retained its idle TLS socket without consuming shutdown traffic. The fixture failed after approximately 10.4 seconds with the same one-connection/zero-task shape. After recording that failure, closing only the experiment's own client socket allowed all new fixture threads to exit naturally within two seconds. A separate control closed its own client before fixture teardown and completed normally in approximately 2.65 seconds. No force-exit, transport abort, increased budget, or successful-result substitution was used. Temporary certificates and credentials were discarded.

This demonstrates a possible idle TLS shutdown mechanism. It does not identify the Android connection owner or establish the cause of the Back/Home failures. Python asyncio documents a default SSL shutdown timeout of 30 seconds; Uvicorn waits for connections before lifespan shutdown. No production or fixture shutdown configuration is changed here.

## Diagnostic changes

- A fixture shutdown failure now terminates this foreground runner. Remaining cases are explicitly `not_run` with `fixture_contaminated`; the suite exits nonzero. Ordinary body failures with successful teardown continue to collect independent cases.
- Each remaining connection contributes only fixed `last_route_role`, transport-closing boolean and SSL-state enum. The role describes the latest parsed route, not authenticated identity or socket ownership. Shared GET-job routes remain unknown. No path, ID, address, header or token is serialized.
- Instrumentation emits fixed stages around Back input, Home automation/shell/EOF/closure, observed leave, worker release, reopening, credential checks and cleanup. Original lifecycle actions, assertions and budgets remain intact.
- Primary exceptions are classified and emitted before UI cleanup. A cleanup exception is separately classified and cannot replace a primary exception. Diagnostic emission failure also cannot replace it. Exception messages and arbitrary instrumentation text are excluded.

## Verification boundary

Deterministic host regressions exercise fail-fast versus clean-teardown continuation, fixed-enum privacy and error separation. An extracted Java control-flow harness executes the actual diagnostic methods and catch/finally logic with controlled failures. Existing host contracts and real loopback TLS checks are retained. These do not compile the complete Android instrumentation class or execute ART. A new authorized Android run is required to locate the actual Back/Home failure stage; current root cause remains unresolved.

Platform calls such as runOnMainSync, startActivitySync and shell reads can block internally. Existing outer budgets are not a hard wall-clock guarantee; this delta adds observation rather than pretending to bound those calls.
