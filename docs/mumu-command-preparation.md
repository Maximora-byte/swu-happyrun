# MuMu 6.8.4.0/API35 command preparation

This is a pure argument encoder, **not a physical transport**. It has no
subprocess, executable selection, device access, CLI registration, or capabilities.
It neither writes samples nor implements readback or stop.

## Source and scope

The only command syntax comes from the locally observed vendor help recorded in
[issue 7](https://github.com/Maximora-byte/swu-happyrun/issues/7#issuecomment-6263450120)
and the [PR61 capability plan](https://github.com/Maximora-byte/swu-happyrun/pull/61).
No other MuMu version's mapping, port, compensation or semantics is inherited.
PR61 remains a separate offline plan; this change does not merge it.

`drivers/mumu/commands_684.py` provides `MuMu684Commands`, constructed with exact
host version `6.8.4.0`, integer Android API `35`, and one explicit decimal instance
index. The 128-character index limit is a local validation ceiling, not a claimed
vendor limit. Unknown versions, `all`, Unicode digits and shell fragments fail.

- `location(longitude=..., latitude=...)` returns a tuple beginning with
  `control --vmindex INDEX tool location`, then longitude and latitude flags in
  the documented order. Documented inclusive ranges are [-180,180] and [-90,90].
- `gyro(x=..., y=..., z=...)` returns the analogous gyro command with flags
  `--gyro_x`, `--gyro_y`, `--gyro_z`. Values are finite built-in numbers, encoded
  as fixed decimal strings. No gyro magnitude limit or unit conversion is guessed.
- `require_physical_transport(channel)` always rejects location and gyro with
  `physical_transport_unverified`; unknown channels reject with `channel_invalid`.
  No caller-supplied boolean or evidence object can unlock it. `capabilities` is
  always empty.

The encoded numbers are raw vendor arguments. No CRS is assigned, no WGS84/GCJ02
conversion occurs, and gyro is not a step-count interface. Successful encoding
does not show that the vendor accepts a value or that it affects a device.
Returned arguments contain private instance/sample data: do not publish or log
them. The object repr omits the instance. A future executor must use an argument
list with `shell=False`, not join these values into a shell command.

## Existing boundaries remain authoritative

R1 `MumuBinding` and fresh `assert_current` checks remain the identity boundary;
this encoder is not fresh device evidence. R2 `CalibrationRecord`, `MuMuLocation`
and `MuMuSensors` keep their existing guard/readback/stop behavior. No duplicate
state machine, calibration model, new protocol field or real-driver registration
is introduced. The additional R2 tests verify that a fake transport's write or
read timeout after a side effect prevents resending; cleanup remains possible
after lease loss, requires exact confirmation and never re-enables writes.
They do not enforce a wall-clock timeout on a blocking vendor process.

## Still required before any physical dispatch

Current evidence lacks location CRS, gyro units/axis meaning/timing, independent
correlated readback, and documented per-channel stop/queue-clear semantics.
Each remains unknown. There is no guessed zero-value reset or stop command.
Actual support needs reviewed semantics and a bounded executor, independent
observation, existing intent/guard/binding integration and independent Windows
acceptance. Killing a process or joining a thread cannot confirm device stop.

This change does not operate MuMu, a third-party app or school services, and does
not establish a real location, sensor, running record or school acceptance result.
The current PR46 baseline's own-app HTTPS acceptance is separate evidence.

## Read-only subprocess capture (independent follow-up)

The existing `drivers.command.run_readonly` used by MuMuManager information and
ADB diagnostics now bounds each binary output stream to 1 MiB, preserving the
five-second default call timeout. Both pipes are drained concurrently; successful
return requires direct-child exit and reader EOF inside one monotonic deadline.
Strict UTF-8 is required for returned stdout; malformed stdout is not silently
replaced. Stderr is bounded bytes and discarded, preserving compatibility with
local-codepage diagnostics when exit status and stdout are valid. Exceeding the output cap, invalid timeout, failed readers, launch errors,
nonzero exit and timeout produce fixed `ProbeError` codes without raw output.
The output cap is local policy, not a MuMu limit. There are no automatic retries.

Cleanup has a separate, shared 0.5-second budget for waiting on the direct child
and joining both readers. Only the direct child is killed. Descendants can remain
alive or hold inherited pipes; in that case the function reports
`command_cleanup_unconfirmed`, with its original safe reason in `primary_code`.
A process-local nonblocking lock allows only one capture at a time; concurrent
calls fail with `command_capture_busy`. After unconfirmed cleanup, no new child
may start until the old direct child has exited AND every reader has finished.
The pending object retains the original safe reason; there is no override/reset.
Thus repeated diagnostics cannot accumulate child processes or reader threads.
Readers own their pipe close operation and may remain as daemon threads until EOF;
this avoids blocking the caller on a pipe lock held by an inherited-pipe reader.
The bounds apply to captured bytes and explicit waits, not an absolute real-time
promise about OS process creation, kill, scheduling or arbitrary descendants.
Nothing here confirms device stop or queue empty, and the physical gate is unchanged.

Tests execute isolated Python children for stdout/stderr flood, dual streams,
UTF-8, literal argument passing, timeout, nonzero exit and inherited pipes; the
known test descendant exits naturally. Parser fixture stubs use binary completed
child pipes; they do not replace the actual-process acceptance cases. Windows
behavior still requires exact-source CI and local independent acceptance.
