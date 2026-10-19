# Foreground remote simulation UI candidate

Based on Android source from PR33 `091f2428139176370390daa40b0570fcc9fa612a` in the verified platform candidate. This delta requires the separately owned `remote.protocol` / `remote.transport` and `remote.runtime` / `remote.journal` / `remote.simulation` modules. It does not add a second protocol.

## Interaction and boundaries

The existing local wizard/simulation remains available. Its new bottom button opens a private, non-exported `RemoteAgentActivity`. Opening it makes no network requests. Users enter a trusted HTTPS origin, the server-bound agent UUID, registered device UUID and an AGENT token. IDs are not invented. There are no ADMIN controls or automatic job creation.

The explicit connect button runs one hello and one simulation claim through the existing v1 client/runner. The runner owns profile revision checks; an unknown profile is refused. Only the bundled synthetic fake driver is used. No real school execution, uploads, Root changes, physical driver or background service is provided.

Only the origin and two UUIDs are saved in private preferences. The token field disables state saving and autofill and is cleared immediately after constructing the memory-only client. The window uses FLAG_SECURE. Credentials remain in the client only until finite stop/attention reporting ends and close drops references; Java immutable strings cannot promise physical memory zeroization. Tokens are never written to a Bundle, preferences, journal, UI errors or logs.

Leaving the page, rotation, or explicit stop latches a local stop. A worker attaching after that stop receives the same latch. No new claim is automatically started and reconnect never resumes motion. The existing worker may finish bounded stop/attention reporting before its client and private journal close. `shutdown()` allows that cleanup; it does not schedule new work. HTTP call deadlines come from the client and execution/lease bounds from the runner; blocking OS operations are not described as hard real-time.

The UI differentiates local stop, last confirmed server state, unconfirmed attention and unavailable/unconfirmed durable journal writes. Journal failures disable new tasks in this Activity; cross-session protection remains the journal/runtime's responsibility. The namespace is SHA-256 of origin and identity, below app-private files, with no user-provided path component. No clear-data/retry shortcut exists.

## Verification

- Deterministic lifecycle gate tests: foreground and explicit start, duplicate start, leave-before-attach, repeated stop, storage-failure latch. RED compilation before implementation, then 9 JUnit tests passed on Linux JRE21 (`-source 17 -target 17`).
- Four Python source/XML boundary checks passed. These are not Android runtime tests.
- Presentation tests additionally reject unconfirmed claim/attention, stale running views and unconfirmed storage, and require a confirmed view for terminal server status. Wire timestamps are explicitly truncated to the protocol microsecond precision.
- Three instrumentation tests supplied for disconnected start/token state, rejecting HTTP and clearing a token on leaving. They use only invalid endpoints and synthetic field text; they have not run on ART in this workspace.
- SDK build/lint, real HTTPS on Android, rotation/process-death instrumentation and emulator acceptance remain integration work. Neither these tests nor UI status establish a real device or accepted school record.
