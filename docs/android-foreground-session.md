# Native foreground continuous simulation session (phase 2)

This independent delta extends the frozen single-claim native fake runner. It is not yet wired into the Activity or validated on Android/real HTTPS. It does not add permissions, credentials, endpoints, background services, school upload, or physical execution.

## Integration

Create `RemoteForegroundSession(client, journal, clock, agentId, deviceId, runSeconds)` only after explicit user connection, on one caller-owned worker. `run()` is blocking and single-use. Poll `status()` and `currentJob()` for rendering. The caller closes the journal after the worker exits. Use Android elapsedRealtime for monotonic time and microsecond-or-coarser UTC timestamps. The existing A HTTPS client owns an in-memory token and bounds requests to 5 seconds.

Call `requestStop()` on explicit disconnect or leaving the foreground page. It stops the synchronous fake driver first, closes the client exactly once, then interrupts the owning worker. This cancels waiting and requests without starting replacement work. Owner-thread publication and cleanup are synchronized to avoid interrupting a reused executor thread. Stop-before-worker-attachment remains latched. Closure is irreversible: a new explicit connection needs a new client/session.

Immediate disconnect can prevent a final event from reaching the server. `disconnected_unconfirmed` means local execution has stopped; the last JobView may still say running, and the server must reconcile lease expiry. Never render it as cancelled, completed, or a confirmed attention event. Start intent stays durable. Storage failure overrides disconnect with `storage_failed_not_persisted`. No automatic recovery or replay follows.

## Scheduling and bounds

After a successful hello, claim once. An empty queue waits 1, 2, 4, then at most 8 seconds between claims. A fresh fake capability observation and hello precede each subsequent claim; heartbeat reuses its observation and occurs every 10 seconds when the worker can make a request. Request latency can delay heartbeat; this is not an independent real-time scheduler. Only confirmed completed/cancelled jobs allow another claim. Attention, unsupported profile, failed lease/auth/network/ambiguous claim, or unhealthy storage ends the session.

Motion still ticks locally about every 100 ms. Normal renewal is scheduled at `min(5 seconds, (actual remaining lease - 5.1 seconds)/2)` after a grant/renewal. Preflight/start/finalization retain explicit renewals. Every effect checks monotonic lease and execution-window deadlines; requests/start are refused if their conservative 5.1-second lease budget is absent. Expiry is calculated from request-start timestamps so round-trip latency is deducted, and an expired old lease cannot be revived by a late response.

With a functioning connection, cancellation becomes visible on the next renewal, nominally within 5 seconds plus request latency (5-second client budget). Network failure does not authorize more ticks; the synchronous fake driver has no autonomous movement during a blocked call. This is not a hard real-time guarantee for filesystem or platform DNS operations, and is not a physical-device watchdog implementation.

Device fences now strictly increase across distinct jobs. Same-binding retransmission remains permitted, but equal-fence different-job responses and replayed journal records fail closed. The server normally increments fences transactionally; this protects malformed responses/rollback as well.

## Evidence and remaining gates

JUnit uses injected stateful clients, fake clocks, actual private filesystem journals, and real worker threads for blocked hello/claim, idle sleep, and executor reuse. It performs no network, device, root, or school action. First-phase journal corruption/start-intent/recovery tests remain included. Actual Android scheduling, HTTPS teardown, Activity lifecycle integration, and multi-job server acceptance require separate integration evidence. First-phase frozen harness inputs remain unchanged.
