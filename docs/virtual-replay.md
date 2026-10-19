# Local MuMu virtual route playback

This is an explicitly local tool, independent of remote JobSpec and school rules.
It never logs into Budao, starts/finishes a school run, uploads a record, or claims
school acceptance. `record_verified` is always false. Only an isolated instance
without personal data is eligible for the opt-in device path.

## Delivery and evidence limits

The route/controller implementation is tested with synthetic adapters. The real
entry point imports `MuMuNative684` and `OwnProbe`, never FakeDriver or a
`for_synthetic_testing` adapter. Install the matching N1/N2/N3 candidate together;
missing native modules produce `replay_native_adapter_unavailable`.

At this delivery, vendor write acknowledgment and queue/stop semantics still
lack accepted MuMu 6.8.4.0 evidence. The N1 native implementation runs the exact
bounded command but returns `write_ack_unconfirmed` even for exit zero, and
permanently refuses further writes. Stop remains `stop_unconfirmed`. Therefore
this delivery is **not yet a demonstrated usable trajectory on MuMu**. Synthetic
controller tests, actual own-probe readings, native command delivery, and school
records remain separate claims. Do not replace those errors with success or
pass a `verified=true` switch. A single-point uncertain command must not be
retried automatically; use the independent own-probe readback entry to inspect
it, then obtain the missing vendor/process/queue evidence locally.

## Preview: no processes and no journal writes

Use an existing local OSM RouteProfile JSON. Do not rescrape or enter an invented
campus boundary. A route needs its actual `route_id`, content `revision`, explicit
`input_crs`, points and source reference. The revision is recomputed with the
existing profile canonicalization. Unknown fields, duplicate keys, oversized
files, a mismatched revision, zero-length routes, non-finite inputs and ambiguous
antimeridian segments are rejected. WGS84/GCJ02/BD09 normalization remains the
existing offline calculation; this is not a device-calibration claim.

```powershell
python -m swu_happyrun.cli mumu replay --instance 0 `
  --route C:\Private\routes\chosen-route.json --speed-mps 2 --duration-seconds 30
```

The numbers are explicit example trial parameters, not SWU requirements. Preview
reports `processes_started: 0`, distance and bounded duration. It does not import
the native/probe adapters, launch ADB/MuMu, create a journal, or verify a device.
The source route stays local and source_ref is never fetched.

`--duration-seconds` caps active route playback. A short trial uses a prefix;
it never jumps to the route endpoint or reports that the entire route was
traversed. Paused time is excluded. There are no loops, jitter or queued missed
points. A late tick samples at most one current position; at the hard cutoff it
only stops and emits no overdue position. Normal school RouteExecution
construction still checks every SchoolProfile rule as before.

## First controlled point: no calibration prerequisite

Before trajectory playback, Codex may use the separate one-point experiment
entry to collect the actual vendor coordinate semantics. It is not the replay
success path and does not infer CRS. The input file contains only the explicit
raw `latitude` and `longitude` vendor numbers chosen locally; the encoder performs
no WGS84/GCJ02 compensation. Do not put real points into repository fixtures.

```powershell
python -m swu_happyrun.cli mumu probe-point --instance 0 --point C:\Private\target.json
```

Without `--execute-virtual-probe`, this is zero-process preview. Only after Codex
has reviewed the isolated instance's execution conditions and the currently
unknown vendor stop/queue semantics, the one-shot entry is:

```powershell
python -m swu_happyrun.cli mumu probe-point --instance 0 `
  --point C:\Private\target.json --duration-ms 1000 `
  --execute-virtual-probe --isolated-no-personal-data `
  --manager '<verified manager path>' --adb '<verified adb path>' `
  --serial '<reviewed serial>' --binding C:\Private\current-binding.json `
  --device-id '<same registered device UUID>' --journal C:\Private\agent.sqlite `
  --private-output C:\Private\new-point-evidence.json
```

This takes the same device lock and persists intent/reservation before the one
command. Only the exact `write_ack_unconfirmed` result together with native
`CommandDelivery.command_completed` evidence permits one independent own-probe
readback. Timeout, missing receipt or process/pipe cleanup uncertainty does not
permit observation. The writer remains permanently closed; there is no retry.
`command_status`, `observation_status` and `stop_status` are separate output fields.
Raw input and readback go only to the explicitly requested, exclusively created
private output file, with `coordinate_semantics: raw_vendor_unverified`.

Every executed experiment retains an unresolved reservation, even if readback
matches. It does not create calibration, prove stop, or enable replay. A second
point is refused until actual stop/queue and observation cleanup evidence can
resolve the previous operation. With the current unknown native stop semantics,
that is a concrete Codex acceptance blocker; do not delete the reservation,
switch device IDs, or use another journal to force the second experiment.

## Explicit execution inputs

Install the reviewed wheel with its agent extra in an ordinary-user environment.
No administrator, Root, TLS changes or permission grants are performed by this
script. SelfProbe app/test APKs must be the same reviewed source/signature pair;
the user grants precise location permission themselves when required.

Supply all of:

- Exact manager and ADB executable paths and selected instance/serial.
- `--device-id`: the same registered device UUID used by agents for this instance.
- `--journal`: the same private agent journal directory used by every local
  producer for this device. Different IDs/directories do not prove different
  physical instances and would defeat shared exclusion; never use them to bypass
  an unresolved session. Shared process exclusion reuses RunJournal.device_lock.
- `--binding`: a fresh local-review observation accepted by resolve_binding,
  with host 6.8.4.0, actual engine/app versions, boot identity, instance/ADB mapping
  and exactly one matching display/task. For OwnProbe the package must be
  `org.happyrun.app`, not Budao. The file is rechecked and the actual device boot
  ID is read before each adapter operation. Refresh through actual local review
  when it expires; never update only its timestamp.
- `--calibration`: local JSON serialization of the existing CalibrationRecord
  and CalibrationSample fields, not a new wire contract. It must have channel
  `location`, input CRS `WGS84`, exact original binding.digest, matching
  host/engine/app versions, explicit aware observed_at/expires_at and a declared
  finite error budget in meters. `samples` contains at least two distinct,
  asymmetric controlled `target`/`observed` GeoPoints and each `observed_crs`.
  Targets are the actual controlled N1 single-point inputs, observations come
  from the accepted N2 private readbacks. The serializer must use the original
  observation digest (not OwnProbe's stable identity_digest). Keep raw targets
  and observations private; do not commit or attach them to an issue.

Minimal evidence collection is N1's locally reviewed single-point command,
then `scripts/check_mumu_virtual_channel.py --channel location
--observe-own-channel --isolated-no-personal-data --adb <PATH>
--binding <LOCAL> --private-output <NEW-LOCAL-FILE>`, for each of two targets.
This gathers samples only; it does not prove vendor acknowledgment or stop
semantics. Validate the supplied CalibrationRecord against that original binding
before use. N2's gravity samples do not enable gyro or steps. The `values` order
for location readback is latitude, longitude; Android elapsedRealtime is never
subtracted from the host monotonic clock.

```powershell
.\scripts\start_mumu_virtual_replay.ps1 -Instance 0 `
  -Route C:\Private\routes\chosen-route.json -SpeedMps 2 -DurationSeconds 30 `
  -ExecuteVirtualReplay -IsolatedNoPersonalData `
  -Manager 'C:\Program Files\Netease\MuMu\nx_main\MuMuManager.exe' `
  -Adb 'C:\Private\verified-tools\adb.exe' -Serial '<locally reviewed serial>' `
  -Binding C:\Private\current-binding.json -Calibration C:\Private\location-calibration.json `
  -DeviceId '<same registered device UUID>' -Journal C:\Private\agent.sqlite
```

Executable paths are examples; use paths actually verified on this host. The
PowerShell wrapper builds an argument array and invokes Python without a shell
command string. Its default without ExecuteVirtualReplay remains preview.

## Controls and output

After a confirmed initial write/readback, type `pause`, `resume`, `stop` or
`progress`, followed by Enter. EOF is a stop request. Ctrl+C/SIGTERM requests
controlled stop. `--no-interactive` (PowerShell `-NoInteractive`) runs until the
explicit time budget; signals still stop it. A pause invalidates the generation
before stopping the writer. It only reports paused after native stop confirms.
Resume is an explicit in-process action and creates a new generation/writer only
after confirmed pause. Cancel/lease loss cannot be downgraded to pause.

The owner thread alone handles journal, route and adapter calls. The input
thread only queues controls and sets a fast halt latch; old callbacks cannot
write after pause/cancel. A request during I/O waits only for the adapters' bounded
operations. Native write budgets are at most five seconds and additionally
clamped by the remaining route budget. N2 observation/cleanup has its own finite
budget, so shutdown feedback can take longer than one sample interval. A failed
or unconfirmed cleanup is visible, never reported as stopped.

Output contains progress and fixed error codes, never continuous coordinates,
serial, nonce, private paths, raw command output or school records. `distance_m`
and `elapsed_seconds` describe the sampled route clock; `last_confirmed_distance_m`
is the latest position with native acknowledgment and matching own-probe
readback. `route_finished` is true only when that confirmed point is the endpoint.
A cutoff reason does not imply the last emitted point reached the cutoff.
`stop_confirmed` is independent of readback success; a stationary reading or a
closed listener alone cannot confirm the vendor queue and all producers stopped.

## Durable intent and crash recovery

Before the first write, the tool persists a per-device unresolved marker and
RunJournal start intent. It holds the existing device lock while it owns the
session. Every final native write gate checks generation, cancellation,
authorization, current calibration and durable intent again. Write/readback
errors are never retried automatically. A marker remains after process loss,
failed stop or close-without-stop; a new start is refused even after OS locks are
released. The shared RunJournal gate also blocks an unchanged AgentRunner from
claiming or starting a remote job for that same device. Corrupt, unknown-owner,
duplicate-key and symlink reservation files fail closed. The opaque recovery
permit is bound to the held journal/device/session and can only stop, never write. Do not delete the marker/journal or use a different device ID to retry.

Recovery does not need the old route or calibration. It may only inspect the
existing unresolved state and attempt stop; it never calls write_location/start
or automatically replays a route:

```powershell
.\scripts\start_mumu_virtual_replay.ps1 -Instance 0 -RecoverStop `
  -ExecuteVirtualReplay -IsolatedNoPersonalData `
  -Manager '<verified manager path>' -Adb '<verified adb path>' -Serial '<reviewed serial>' `
  -Binding C:\Private\current-binding.json -DeviceId '<same registered device UUID>' `
  -Journal C:\Private\agent.sqlite
```

Before each observation, `probe_pending` is persisted. Only the complete sample
call, including listener/private-file cleanup, clears it. A timeout or cleanup
failure therefore survives process restart; native stop alone cannot release
that reservation. N2 currently has no independently verified cleanup recovery
API, so these cases require local inspection and remain unconfirmed.

A fresh native instance's empty in-memory process set is not recovery evidence.
With the current unknown queue/stop semantics this remains stop_unconfirmed and
the durable reservation is retained. Only a later genuinely confirmed stop can
release it for a separately requested new session. A normal quit before adapters
exist does not invent an uncertain device action or overwrite another owner's
marker. A quit after possible side effects always prints the stop result.

## Independent acceptance still required

Codex owns Windows/PowerShell ordinary-user installation, exact N1 ACK/queue
semantics, APK signature/source pairing, actual two-target calibration, and then
single-point/30-second prefix trials, pause/resume/stop, interruption, stale
binding/boot rejection and duplicate-launch refusal. No such actions run in
cloud tests. Record final immutable candidate SHA, command, platform, exit code
and unverified stages separately. School login/rules/screens and this run's valid
record remain separate B-level prerequisites.
