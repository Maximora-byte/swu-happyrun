# MuMu 6.8.4.0 / Android 15 API 35: channel probe design

This first small delivery is a **data-only version plan and offline trace validator**.
It has no physical transport, CLI registration, command executor, device calls,
readback implementation, stop implementation or execution capability. Both channels
remain `unsupported`, capabilities remain empty, and the validator performs zero
writes. A consistent synthetic trace is not device evidence or school acceptance.

## Observed facts and missing inputs

Source: [Codex's actual help observation](https://github.com/Maximora-byte/swu-happyrun/issues/7#issuecomment-6263450120),
[accepted QA report PR60](https://github.com/Maximora-byte/swu-happyrun/pull/60),
and the task 2 section of the [current delivery plan](https://github.com/Maximora-byte/swu-happyrun/blob/79f180bbc20c1edaa4fb0df2301602f5bc9d1f40/docs/superpowers/plans/2026-10-19-post-e490-device-delivery.md).
The help spelling is recorded as evidence, never assembled into executable argv:

```
MuMuManager.exe control --vmindex INDEX tool location --longitude LONGITUDE --latitude LATITUDE
MuMuManager.exe control --vmindex INDEX tool gyro --gyro_x X --gyro_y Y --gyro_z Z
```

Location help gives longitude [-180,180] and latitude [-90,90]. It does not
establish CRS, readback, stopping or queue clearing. Gyro is described as gravity
sensing; units, axes, timing, persistence, readback and stop remain unknown. It is
not a step-count channel. No Android 12 compensation, route, school point,
readback command, stop command or default zero-value reset may be guessed.
The catalog exposes unavailable operations as null, never a success stub.

### Codex's next minimum collection (read-only; no physical write authorized)

1. Preserve the existing QA instance and data. Reuse the already approved local
   version/help-reading workflow to inspect the installed vendor's own help or
   documentation. Record whether that source explicitly defines readback, units,
   CRS, cancellation, queued work and post-stop semantics for **each** channel.
   This document intentionally supplies no guessed CLI help switches or commands.
2. If no documented readback/stop operation exists, report `not_found` plus the
   reviewed source/version privately; do not experiment with location/gyro values,
   reset commands, process termination or network ports to discover a stop.
3. Independently inspect whether an already installed, authorized own probe can
   observe location or the relevant sensor, using its existing read-only entry.
   If not, record the missing observer. New observer installation/permissions or
   active stimulus belong to a separate reviewed task. Passive samples alone do
   not prove injected-value correlation or queue clearing.
4. Keep the actual instance, ADB, boot, app version, package, display/task and
   observations in existing private R1 `MumuBinding` evidence. Reuse
   `assert_current` with a trusted fresh observation; do not create another binding
   format or publish raw identity/stable digests. Location calibration remains the
   existing R2 `CalibrationRecord` / `CalibrationSample` with explicit CRS,
   target/readback and error threshold. Do not fabricate a calibration now.
5. Return the exact reviewed vendor source/version, each missing semantic and
   redacted finding. No raw stdout, screenshots, coordinates, identifiers or
   account data belong in a PR. A trusted local review is still needed to connect
   public summaries to private evidence; these JSON schemas cannot authenticate it.

## Later transport design, gated on evidence and separate write authorization

The subsequent PR must implement an actual bounded executor and independent
readback, and demonstrate its Windows behavior. This PR does not claim a hard
wall-clock guarantee. Proposed maximums in `ProbeBudget` are local review ceilings:
5,000 ms per call, 30,000 ms per channel attempt, 65,536 output bytes per call.
A smaller finite budget may be chosen; these are not measured vendor requirements.
One write attempt, no retry, no catch-up queue and no automatically resumed write.
Reserve independent cleanup budget: a write's expired lease or deadline must not
suppress stop attempts. Cleanup tries every potentially active channel even if
one fails; each needs its own acknowledgment and no-later-write observation.

Before dispatch, the implementation must persist intent and recheck existing R1
binding, R2 calibration and execution guard. Late binding/boot/version changes,
lease expiry, cancellation or exhausted budget prevent dispatch. Recheck at the
actual effect boundary, as required by the accepted #56 fix. This document adds
no authorization model and does not replace existing R1/R2 regression coverage.

Use exact reviewed argument lists, shell=false, bounded streaming capture and a
monotonic deadline. Reaching either a call deadline or an output cap fails closed;
stop capturing arbitrary output and retain only fixed error classifications. A
future worker/process may need local containment, but killing/joining that worker
is never a device stop acknowledgment. Timeout after dispatch means effect
unknown, no repeat write and no unlock/new run until independently resolved.
Readback must be independent of the command exit code and correlated with the
same binding/channel/attempt. Location requires CRS and explicit numeric error
threshold from real evidence. Gyro requires independently established units,
axes, tolerance and observation interval; scalar elapsed time is not sensor data.

Stopping must use the actual reviewed per-channel operation and independently
confirm its documented queue-empty/no-further-emission semantics. A last observed
sample remaining on screen may be a retained value rather than ongoing emission;
the protocol must distinguish them. A finite quiet window alone cannot prove an
unbounded queue is empty. Its duration and meaning need vendor/observer evidence,
not a convenient constant. Missing acknowledgment remains `stop_unconfirmed`,
with writes latched off and ownership retained under the existing lifecycle.
No stop path invokes app finish/upload. Stop can be attempted after loss of lease.

## Offline input/output schema

Python definitions are authoritative and emit JSON Schema via
`ChannelTrace.model_json_schema()` / `ProbeBudget.model_json_schema()` /
`ProbeAssessment.model_json_schema()`. They are local review artifacts, not new
control-plane wire models. Unknown keys and coercion are rejected.

Input `ChannelTrace`:
- channel: exactly `location` or `gyro`; host_version: `6.8.4.0`; android_api: 35.
- source: `synthetic` or `redacted_field_trace`, a provenance label only.
- steps: exactly binding, write, readback, stop, quiescence, in that order.
- Each step: phase; outcome (`observed`, `failed`, `timeout`, `unknown`, `not_run`);
  nonnegative integer started_ms/finished_ms on one attempt-local monotonic axis;
  output_bytes (nonnegative integer, default zero). Durations cannot be negative;
  steps cannot overlap. `observed` is a reported claim, not authenticated success.
- Preserve failed or not-run cleanup steps rather than omitting them. This trace
  shape reviews planned/recorded phase ordering; it does not schedule cleanup or
  assert that a physical queue has emptied. A rejected trace never triggers retry.

Output `ProbeAssessment`:
- channel; status always unsupported; capabilities always []; writes_performed
  always zero (the **validator's** actions, not a count of the supplied trace).
- trace_result consistent/rejected. Consistent means syntactic and timing checks
  only; it never grants capabilities even when source is redacted_field_trace.
- fixed reason: physical_transport_not_implemented, phase_unconfirmed,
  call_budget_exceeded, total_budget_exceeded or output_budget_exceeded.
- Deadlines are exclusive: equality is expired. A rejected trace retains all input
  evidence privately; the summary reports one primary rejection. Channels are
  assessed independently, so one channel's result never confirms the other.

The schemas deliberately exclude binding identity/digest, raw commands/output,
coordinates, free-text errors and app records. Existing R1/R2 evidence stays local.
There is no `supported=true` override. No new dependency, shared state model,
control-plane field, device factory or real-driver registration is introduced.

## Acceptance scope

Tests cover exact version/help facts, per-phase failure/timeout/unknown/not_run,
missing/duplicate/reordered/overlapping steps, nested mutation, finite strict
budgets, exact deadline expiry, total duration, output cap and private extra-field
rejection. Complete traces for both channels still return unsupported.
These tests validate the offline checker only. Real process bounding, identity
freshness, write timeout effects, independent readback, stopping, queue clearing,
post-stop observation and current-school record acceptance remain unimplemented
or unverified and require their separate evidence before capability activation.
