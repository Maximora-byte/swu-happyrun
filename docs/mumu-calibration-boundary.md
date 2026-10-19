# R2 offline calibration and stopping boundary

This candidate adds only local evidence validation and an explicit synthetic test
seam. `MuMuLocation()` and `MuMuSensors()` remain closed. There is no gateway,
port, subprocess, socket, physical transport registration, or new capability name.
`for_synthetic_testing` is deliberately not reachable from CLI/device factories.
Synthetic transport injection is a test seam, not a physical execution permission.

## Evidence and behavior

`CalibrationRecord` binds R1 `MumuBinding.digest`, host/engine/app versions,
channel, explicit input/readback CRS, observation/expiry instants, per-point
requested/observed `GeoPoint` values and an explicit meter error threshold.
There is no default success tolerance. WGS84 normalization and distance are the
existing core implementations; no MuMu12 compensation is applied. Validity and
nested coordinate values are checked again on each write. The injected binding
check must call the R1 binding's `assert_current` with a fresh observation. The
R1 structural validation alone cannot authenticate live boot/mapping: a trusted
caller must supply independently observed current device identity. Default
read-only sampling does not produce an authenticated binding and keeps all
capabilities empty. The execution guard retains responsibility for device ownership, current fence,
cancellation and action budget. Neither binding nor calibration grants a lease.

Every synthetic write invokes the guard; location success requires readback.
Any guard, transport or readback error halts that instance, so replacing a guard
cannot replay cancelled backlog. Sensor writes accept one synthetic sample at a
time, with a finite explicit monotonic deadline. There is no catch-up scheduler.
Stop does not require an active lease. An exact `True` from
`stop_and_confirm_empty` is required; missing acknowledgment, truthy strings,
exceptions and timeouts raise `stop_unconfirmed`. Stopping or joining a local
thread is never acknowledgment. Stop can retry confirmation, is idempotent once
confirmed, and does not reenable writes. Transport calls are synchronous; the
synthetic seam is not a timeout-enforced physical transport implementation.

Coordinate ranges catch out-of-range axis inversions. Both axes may still be
numerically valid when swapped; only a known target and independent readback can
detect that case. No numeric validator can infer arbitrary mislabeled CRS/axes.

## Separate future controlled probe (Codex; not implemented or executed here)

1. Start with the default read-only R1 sample and verify the exact instance,
   ADB serial, display/task, boot identity, package/version and fresh digest.
2. Obtain local help/configuration evidence for the installed host/engine's
   actual location/sensor channel and queue-clear/readback semantics. Do not
   guess a port/command or substitute Android12 compensation. Missing evidence
   blocks real channel activation.
3. Separately arrange an explicitly authorized own-probe test, outside normal
   read-only collection. Record explicit input/readback CRS, controlled target,
   finite meter threshold, test time/expiry and the exact binding/version tuple.
4. Only in that separately implemented and reviewed physical probe: recheck the
   guard before one bounded write, independently read the own-probe location,
   compare errors against the declared threshold, then confirm queue clearance.
   Preserve private raw observations locally; publish only redacted evidence.
5. A separately authorized short sensor probe must prove queue clearance after
   cancel/timeout/lease loss. If it cannot, retain `stop_unconfirmed` and block
   another run. It must not invoke finish/upload as a way to stop.

Actual `location_read`, `location_write` and `sensor_probe` are all unverified in
this delivery. Offline synthetic tests prove software rejection/stop behavior
only. No real step count, Budao acceptance or school record is verified. Real
Windows/MuMu help, controlled transport/readback, device queue-clear evidence,
current app samples and end-to-end acceptance remain required.

## Issue 53: authority after validation callbacks

Synthetic location writes retain the calibration revalidation after the initial
execution guard, then recheck the current binding and calibration after that
observation. Immediately before transport
write, they recheck execution authority, then use a pure clock read to reject
calibration expiry during that guard, and recheck the halted flag. Calibration or binding
callbacks can consume the remaining lease or request stop; neither a still-valid
calibration nor a successful earlier guard permits a later write. Sensors apply the
same final authority recheck after the action-deadline clock read, followed by
a pure deadline read and halted check so a slow guard cannot overrun that budget. No renewal,
lease extension, capability change, or physical-channel activation is introduced.

Deterministic regressions use the actual `AgentRunner._effect_guard`: a 30-second
lease expires at synthetic t=31 while the location calibration remains valid for
five minutes, and the transport receives zero writes. Other cases cover remaining
budget, cancellation, stop during calibration/binding/clock/final guard callbacks,
and changed boot/display/app identity. A failed write keeps the channel halted;
replacing the guard cannot replay it, and cleanup still requires queue-clear ack.

`MuMuDriver` wires its binding observation separately into each channel and passes
the runner authority guard directly; it no longer nests binding I/O inside the
channel authority callback. The fake route retains its original combined guard.
The authority guard must synchronously validate current authority without further
external observations; final time reads must be pure clock observations. These
checks do not support arbitrary callbacks mutating state after their own check.
This is a synchronous, cooperative callback boundary, not hardware-level atomicity
between a check and a device effect. A future physical transport still needs its own
bounded-call and queue-clear evidence. MuMu现场及真实乐跑记录仍待验收。
