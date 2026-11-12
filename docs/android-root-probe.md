# Explicit, read-only Root diagnostic (separate follow-up)

This source delta is independent of the frozen first APK and optional selfProbe
source-set snapshot. No actual `su` command has been executed during development.
Tests inject Java fake Process objects; they do not demonstrate real authorization.

## User flow and consent

The UI must offer an explicit “只读 Root 授权检查” button and a confirmation explaining:

- It runs only fixed `su -c id` to inspect the returned UID; it does not change files,
  system settings, accounts, app state, locations or sensors.
- A Root manager may show its own allow/deny prompt. The user decides there; the APK
  cannot choose, store or promise to revoke that choice. Some managers offer a
  persistent grant. This app does not select that option or remember the decision.
- Waiting is bounded to 30 seconds, with a visible cancel button. A timeout or
  cancellation terminates this child process best-effort, but cannot necessarily
  dismiss a separate manager prompt or undo an already granted authorization.
- Denial/cancellation does not prevent local simulation. No result enables actual
  running-app control or indicates an accepted school record.

`RootDiagnostic.run(BooleanSupplier cancelled)` is blocking and must run on a
background executor after confirmation, never from Activity creation, periodic
refresh, an automatic retry or a UI-thread callback. Only one check should be
pending. Keep it alive across onStop caused by the Root-manager prompt. Explicit
cancel, timeout, or Activity destruction cancels the current check; never restart
it automatically on Activity recreation. UI should suppress stale results.

## Bounds and outcomes

Read-only lookup checks executable `su` in absolute PATH directories and a short
set of conventional Android paths. `su_not_found` means not found in those searched
paths, not proof that the device has no Root. A discovered file grants no capability.
The subprocess receives a fixed argument vector: resolved-su-path, `-c`, `id`.
No user-controlled command fragments or extra shell commands are accepted.

The monitor uses a monotonic 30-second deadline, cancellation checks at most every
20ms between reads, merged stdout/stderr capped at 4096 bytes, and no wait-for-EOF
that could hang on an inherited open pipe. It only reads bytes reported available.
All paths close streams and request process destruction, forcibly if still alive.
As with Java Process APIs generally, kernel-level spawn/destroy/stream operations
cannot provide a hard realtime guarantee; the explicit deadline bounds the polling
and authorization wait. No extra reader thread can survive the operation.

Only exit code zero with a single syntactically valid leading `uid=0` result marks
`uid_zero_observed`. That is a local observation for this invocation, not security
attestation: a compromised su binary or process can forge output. Raw `id` output
is neither returned, logged nor persisted. `nonzero_exit` means authorization was
not obtained or the command failed; it must not assert a specific user's denial.

Statuses: uid_zero_observed, su_not_found, launch_failed, nonzero_exit,
non_root_uid, invalid_response, output_limit, timeout, cancelled, interrupted,
io_error. RootReport exposes only status and uidZeroObserved.

## Self-probe three-state compatibility delta

This directory also contains replacements for SelfProbe and ProbeReport, without
editing the prior frozen source. ProbeReport adds status while retaining active:
normal null response -> inactive; malformed response or reflective/runtime failure
-> unknown; matching live response and positive bridge/API version -> active.
The integer remains an Xposed bridge/API version, never a LSPosed release version.

## Validation still required

Fake-process tests cover exact UID recognition, nonzero exit, invalid/multiline
response, output cap, timeout, cancellation before/after start, interruption,
cleanup and no retry. They do not test a real Root manager, real su/SELinux access,
OS-specific process cleanup or Android lifecycle behavior. Those require explicit
user-device acceptance; no device authorization has been performed by development.
