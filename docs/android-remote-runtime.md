# Native remote synthetic runner (B+C)

This candidate adds a foreground, explicitly invoked fake AGENT core. It is not a
physical Android driver, school-record uploader, or replacement server protocol.
It depends on the separately reviewed `remote.protocol` DTOs and
`remote.transport.AgentClient` implementation. Original offline `simulation_local`
classes and their database are untouched.

## Integration API

Construct `RemoteJournal(Path)` in the app's private files directory, namespaced
by canonical server origin + agent UUID + device UUID. Hold it for one worker's
entire lifetime; close only when that worker has exited. A FileLock refuses a
second process/session using that directory. Do not substitute a new directory
when a journal is corrupt or unresolved. Files are never uploaded.

Construct `RemoteAgentRunner(client, journal, new RemoteFakeDriver(), clock,
agentId, deviceId, runSeconds)` with a finite budget in (0,30]. Clock must use
Android `SystemClock.elapsedRealtimeNanos()` including suspend, UTC `Instant.now`,
and interruptible sleep. Prepare a genuinely new fake observation, call
`setHeartbeatObservation(observation)` then perform `client.hello(observation)`.
Call blocking `runOnce()` on a worker, never the UI thread. It claims once, never
retries an ambiguous claim/start, and heartbeats with the same observation after
10 seconds while active. No constructor starts network activity.

`requestStop()` sets an atomic flag and immediately stops only in-memory synthetic
motion. A stopped instance cannot be reused. `runOnce` is single use. Background
and exit should request stop; a bounded existing request may finish, then at most
GET job + attention reporting is attempted. Do not close the journal concurrently.
The transport owns request timeout/cancellation; ordinary OS file I/O is not a
hard real-time promise.

`currentJob()` / the return value is the last confirmed server snapshot, not proof
that execution continues. Always display `localStatus()` beside it:
`idle` means an actual 204; `claim_unconfirmed`, `execution_stopped`,
`attention_unconfirmed` and `storage_failed_not_persisted` must not appear as idle
or successful completion. Local stop does not grant ADMIN cancellation authority.
The UI must retain the storage error visibly and require reconciliation instead
of discarding/replacing the journal. No token enters this journal API.

## State, durability and recovery

The wire states and fields come solely from existing v1 models. A transition
response must match the requested state, expected revision + 1, exact job/spec,
agent/session and fence before it authorizes subsequent work. Accepted `running`
precedes durable start intent, which precedes guarded fake start. Uncertain
running response never starts. Current monotonic lease expiry cannot be revived
by a late renewal. Every tick checks cancellation, remaining lease/action budget,
job window and user stop; elapsed route time is clamped to the execution budget.

Journal records contain only operation, job UUID, session UUID, fence, revision,
local spec fingerprint, intent/result marker or ack UUID. Each bounded append
includes a SHA256 integrity checksum and forces the file before returning.
Checksums detect corruption; they are not authentication against the same user.
Partial/truncated data fails closed. Write failure latches unavailable and prevents
new work. The filesystem's persistence guarantees still require Android/real
power-loss validation; JVM reopen tests are not such evidence. A private directory
must not be writable by other apps. The 4 MB cap rejects rather than silently
pruning historical intent. There is no destructive repair/reset command.

Cancel is stopped before acknowledgement; fresh server view handles concurrent
revision changes. Stop-ack ID is durable for the exact job/session/fence/revision.
This runner does not automatically retry an ambiguous stop-ack; the server GET
and later explicit recovery are the conservative path. `verify_only` never
reconstructs motion and currently reports verification_pending, matching the
conservative Python runner. `stop_only` stops and acknowledges. Both preserve
original session and historical phase. `retry_preflight` cannot bypass an existing
start intent. No path uploads records or reports `succeeded`.

## Exact synthetic profile

Only the bundled WGS84 school/route IDs and revisions are accepted. Canonical
asset bytes are checked with SHA256 before start. The JSON/canonical bytes were
produced with current Python models and canonical_profile_json; Python regression
tests check revision, validity and explicit synthetic provenance. General imports,
CRS conversion and arbitrary canonical numeric serialization are unsupported.
The actual route is (0.2,0.2) to (0.20001,0.20001), about 1.57 m at 2 m/s. These are
synthetic coordinates, never a campus claim or device write. `completed` requires
actual endpoint motion, stopped fake and durable finished marker. Short budgets
produce simulation_incomplete; unknown revisions produce unsupported_simulation_profile.

## Evidence boundaries

Local tests use real filesystem durability/reopen/lock/corruption and an injected
revision-aware control client. They do not establish Android TLS, server HTTP,
AVD/MuMu execution or school acceptance. Production endpoint, token and UUID are
user configured; token remains memory-only. No real credential or root command
was used by these tests. Remote HTTPS/AVD acceptance is a separate required gate.
