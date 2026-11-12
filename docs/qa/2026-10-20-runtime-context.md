# Fixed runtime storage context and uncertainty retention

This slice builds on Draft #108, base tree
`67ee12113debc53a1b77a4bd7bebe66593b1ba0d`, with its interface registered in
[Issue #100](https://github.com/Maximora-byte/swu-happyrun/issues/100#issuecomment-6295021487).
It is **not** native execution, original-machine acceptance or a production
shutdown implementation. No formal user state is initialized by this change.

## Concrete resolver boundary

`enrollment_runtime.resolve_fixed_runtime(ReviewPinAnchors)` is a context manager.
It loads the original fixed scope, retains the existing protected-path guards,
account lock and original device OS lock, then opens the existing original SQL
journal without initialization, schema creation or migration. WAL mode and
sidecar artifacts are rejected before the SQL connection is opened.

The returned `RuntimeContext` is an opaque, process-local registry member bound
to that exact live session and connection. Direct construction, reconstruction,
copying, serialization, a lookalike object, or an expired reference cannot recreate
it. This is accidental substitution/lifetime protection, **not a sandbox against
Python code that can modify module internals**. Independent fixed runner/product
review remains necessary; a dataclass, a hash or a caller callback cannot establish
that trust.

`inspect()` revalidates the original independent pin, frozen material, full scope,
account/device locks and path protections before and after reading current SQL.
The journal identity stays fixed, but its mutable bytes are not permanently
hash-pinned. Each SQL observation uses a read transaction, validates the exact
expected two-table schema, runs a bounded integrity check, and validates at most
4096 rows per table. Unexpected schema, malformed rows, sidecars or excessive
rows fail closed. All retained start intents count as unresolved, even with a
confirmed result or upload; a stop-ack row is only an intent, not exit evidence.
No intent, reservation, row or historical evidence is removed or repaired.

The context exposes no raw journal, native factory, callback installer or start
method. `require_execution()` still calls the unchanged unconditional native
admission denial. All observations report `execution_allowed=false`. Missing
independent runtime trust and positive configuration-to-PID/creation-time
ownership remain separate blockers. No observation status can open native
startup, installation, device input, sampling or cleanup.

An invalid observation irreversibly seals its producer state. Revalidating after
the original expiry/revocation is undone cannot reopen the same context. Before
startup, invalidation performs no retention write. If authority expires while
waiting to acquire an original lock, it is rechecked before opening SQL.

## Separate original-scope operation

`OriginalScopeCleanup` is deliberately **uncertainty-retention authority only**,
not native stop, process kill, queue-clearance or reservation-release authority.
There is no production start issuer that binds it. Tests seed an already-started
private state, without changing native admission, to exercise the real logic.

The private binding requires the same live context, exact original lock token,
SQL connection, registered replay reservation object, session, generation and
already-persisted start intent. It does not create that intent or reservation.
Its only permitted transition is active to uncertain (or retaining uncertain),
with the same owner/session/generation and unchanged `probe_pending`. Serialized
marker bytes remain bounded by the existing 4096-byte parser limit. Stopped
markers, foreign objects, missing start intent and changed identity are rejected.

`retain_uncertain()` first irreversibly seals the producer, then uses a single
two-second checkpoint budget capped by the already-established original absolute
deadline (never more than the existing 45-second outer scope). A future trusted
start issuer must supply that original deadline, not renew it on invalidation;
the deadline itself is not proof of ownership. Python/OS/SQLite/filesystem calls
can block past a checkpoint, so this is not a hard wall-clock guarantee. Late
completion, including descriptor close, remains unconfirmed. It checks original account/device descriptor
identity, path/ancestor identity, original storage protections, marker identity
and exact reservation/SQL ownership. These checks are independent of the expired
or revoked new-execution approval. The original locks remain held throughout.
No new-execution guard is called from this cleanup path.

The writer opens the exact original marker with no-follow/nonblocking flags,
binds its descriptor and path identity, and revalidates before every bounded
write, truncation, flush and readback. It never publishes a staging filename or
replaces/unlinks a reservation. A partial write, interruption, flush failure,
identity change or overrun reports `retention_unconfirmed`. The original object
remains present; torn/invalid bytes continue to block admission under the existing
strict parser. It is not automatically repaired or retried. Windows crash/power
loss and native filesystem behavior remain unaccepted.

The result of a repeated call is the historical first-attempt result, not a new
ownership validation or a renewed deadline. Context exit performs pending
retention before closing SQL and releasing OS lock handles; durable occupancy is
never cleared on exit. Every context and cleanup reference expires before those
resources are released. An active, uncertain or malformed marker blocks any
later original-device admission.

## Synthetic evidence and remaining work

The focused tests use the real transaction/pin loader, OS locking, existing SQL
and marker persistence against disposable synthetic files; only native Windows
protection is replaced by existing test fixtures. Coverage includes forged and
expired objects, mutable SQL, expiry/revocation/pin loss, invalidation during lock
acquisition, unresolved incoming markers, exact scope drift, exception unwinding,
probe-pending preservation, unchanged marker identity, partial writes, boundary
interruptions, no retries and no native execution capability.

Exact test commands, counts, platform and final commit/tree belong in the delivery
receipt. Linux synthetic results are not Windows/NTFS acceptance. The known
Windows baseline pin-test crash remains unresolved by this slice. Real device
startup, installation, input, target shutdown, PID ownership, independently
observed target exit and final school records have not been exercised or accepted.
