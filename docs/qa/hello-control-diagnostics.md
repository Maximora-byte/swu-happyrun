# Hello ControlException diagnostic refinement

## Recorded failure

Base HEAD: `8f9f3351ee2d297f58c55b8b1c1dcf31ff33ff17`.
The actual API 35 report (artifact SHA-256 `845b0ddcbb07ef2a7154aaa59a323c1bcfc44172b56620272bb5c8417e5ecea3`) failed the first completed case at `hello_begin` with ControlException, no JUnit success, and instrumentation exit code zero. Fixture shutdown completed normally. Three preceding UI tests and the other fourteen HTTP cases passed. Foreground and recovery suites did not run.

The existing summary retained the exception class but discarded its already-sanitized control code, HTTP status, retryable and ambiguous fields. It cannot establish timeout, transport rejection, HTTP rejection or invalid response as the cause. It also cannot establish that this failure shares a cause with earlier independent JVM normal/oversize failures.

## Test-only evidence fields

Only ControlException supplies the new CONTROL marker. Its code is accepted from seven explicit constants: transport_failed, request_timeout, http_rejected, invalid_response, closed, busy, control_failure. Any unknown code becomes other; generic exception messages are never emitted. HTTP status accepts zero or 100 through 599; other values become other in Java and null in the host summary. Retryable and ambiguous are booleans. Phase must belong to the existing fixed phase allowlist.

Elapsed time uses a monotonic clock from entry to the current diagnostic phase. It includes status-emission and scheduling overhead and is not pure network time. It is capped at 60,000 milliseconds with an explicit capped boolean. A worker error not associated with the current phase uses -1 for unavailable timing. The host rejects arbitrary codes, phases, malformed booleans, out-of-range status and elapsed numbers. Production exception causes remain discarded and no new production diagnostic fields are introduced.

The fixture separately observes hello requests at the ASGI boundary. It reports a capped count (maximum 1,000 with capped flag), at most eight observations, HTTP status or null, a final-body-generated boolean, and an ASGI-send-completed boolean. Generation is recorded before passing the final body to send; completion is recorded only after that await returns. Its monotonic elapsed time ends at send completion, or at snapshot time while incomplete, with the same 60,000-millisecond cap. No header, body, path, address, token, identifier or arbitrary exception is serialized. No await occurs while holding the observation lock.

An ASGI send return does not prove the client received or accepted the response. Zero observations means no hello reached this fixture's ASGI wrapper before the snapshot; it does not distinguish DNS, connect, TLS or other earlier causes. Capturing these fields does not relax the original success predicate or infer success from diagnostics.

## Scope and verification

Changes are restricted to the acceptance fixture, host summary, Android instrumentation and their diagnostic tests/documentation. Production transport, TLS verification, HTTP connection policy, five-second request budget, instrumentation timeout, lifecycle calls and business assertions are unchanged. Failed fixture teardown still contaminates the runner and marks remaining cases not_run with an overall failure.

Validation includes fixed-code positive/negative parsing, actual extracted Java diagnostic methods preserving primary failures, real ControlException sanitization, actual ASGI wrapper status/send ordering and send failure, a real loopback TLS hello with observation, and the existing TLS fixture suite. Initial missing-control-field regression was RED before implementation. Complete Android compilation and ART execution have not been performed locally. The recorded hello failure and earlier connection-lifecycle failures remain unresolved pending an authorized real run with these fields.
