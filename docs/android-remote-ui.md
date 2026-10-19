# Foreground persistent remote simulation UI candidate

Based on Android source from PR33 `091f2428139176370390daa40b0570fcc9fa612a` in the verified platform candidate. This delta requires the separately owned `remote.protocol` / `remote.transport` and `remote.runtime` / `remote.journal` / `remote.simulation` modules. It does not add a second protocol.

## Interaction and boundaries

The existing local wizard/simulation remains available. Its new bottom button opens a private, non-exported `RemoteAgentActivity`. Opening it makes no network requests. Users enter a trusted HTTPS origin, the server-bound agent UUID, registered device UUID and an AGENT token. IDs are not invented. There are no ADMIN controls or automatic job creation.

The explicit connect button starts one foreground session through RemoteForegroundSession. It owns hello, heartbeat, bounded empty-queue waiting and sequential simulation claims. A confirmed completed/cancelled task keeps the same memory-only client connected for the next task. Attention or an uncertain result ends the session; it is never automatically reconnected. The runner owns profile revision checks; an unknown profile is refused. Only the bundled synthetic fake driver is used. No real school execution, uploads, Root changes, physical driver or background service is provided.

The UI polls read-only session status every 500 ms only while foreground/busy, and redraws status only when it changes. It does not issue heartbeat or claim calls itself. Waiting, claiming/preparing, running synthetic simulation, administrator attention and unconfirmed disconnect have distinct labels.

Only the origin and two UUIDs are saved in private preferences. The token field disables state saving and autofill and is cleared immediately after constructing the memory-only client. The window uses FLAG_SECURE. Credentials remain in the client only until the session disconnects and close drops references; Java immutable strings cannot promise physical memory zeroization. Tokens are never written to a Bundle, preferences, journal, UI errors or logs.

Leaving the page, rotation, or explicit stop latches a local stop. A worker attaching after that stop receives the same latch. No new claim is automatically started and reconnect never resumes motion. Disconnect requests immediate local stop and closes the client; server acknowledgment may therefore be unavailable and the UI explicitly reports unconfirmed. The caller closes the private journal after the session run returns. `shutdown()` allows that cleanup; it does not schedule new work. HTTP call deadlines come from the client and execution/lease bounds from the runner; blocking OS operations are not described as hard real-time.

The UI differentiates local stop, last confirmed server state, unconfirmed attention and unavailable/unconfirmed durable journal writes. Journal failures disable new tasks in this Activity; cross-session protection remains the journal/runtime's responsibility. The namespace is SHA-256 of origin and identity, below app-private files, with no user-provided path component. No clear-data/retry shortcut exists.

## Verification

- Deterministic lifecycle gate tests: foreground and explicit start, duplicate start, leave-before-attach, repeated stop, storage-failure latch. RED compilation before implementation, then 13 JUnit tests passed on Linux JRE21 (`-source 17 -target 17`).
- Five Python source/XML boundary checks passed. These are not Android runtime tests.
- Presentation tests additionally reject unconfirmed claim/attention, stale running views and unconfirmed storage, and require a confirmed view for terminal server status. New presentation cases distinguish online waiting from actual running and do not turn stale running views into acknowledged disconnects. Wire timestamps are explicitly truncated to the protocol microsecond precision.
- Three instrumentation tests supplied for disconnected start/token state, rejecting HTTP and clearing a token on leaving. They use only invalid endpoints and synthetic field text; they have not run on ART in this workspace.
- SDK build/lint, real HTTPS on Android, rotation/process-death instrumentation and emulator acceptance remain integration work. Neither these tests nor UI status establish a real device or accepted school record.

## Second-stage inputs

This UI delta is isolated from the first-stage frozen UI manifest `38741ce3167d8f84c51002e3aa931dc940b2f67dc012061428fcaa743aae9a6b`. It requires the B foreground-session manifest `961f7addee87e5d3bbb55d29918c4ee8702bf2cdc15d1c2d438955940960ffb4`. First-stage publish inputs were not modified. No new permissions, service, background scheduler, trust override or protocol fields are introduced.
