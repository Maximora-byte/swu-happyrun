# Isolated evidence experiment: staged implementation, not device-ready

This incremental slice starts from product `59b1d5a76e58d2d1e6dfd557d21e9faa8f284f63`
and implements the approved [design](https://github.com/Maximora-byte/swu-happyrun/issues/86#issuecomment-6282572811)
with its [mandatory corrections](https://github.com/Maximora-byte/swu-happyrun/issues/86#issuecomment-6282624740).
Shared changes were registered [before editing](https://github.com/Maximora-byte/swu-happyrun/issues/86#issuecomment-6282668908).

## What runs now

From the checkout, with Python 3.11 or later:

```sh
python scripts/mumu_evidence_experiment.py --preview
python scripts/mumu_evidence_experiment.py --execute
```

Preview exits 0; `--execute` intentionally exits 3 with `device_adapter_unverified`.
Both start **zero** processes and perform zero launch, installation, permission,
location, sensor or shutdown actions. They do not read a private point or create
a journal. No executable Windows/MuMu experiment adapter is installed. The older
`probe-point` entrypoint is **not** a substitute for this gate. Do not use it to
work around the missing prelaunch registration/closure verification.

Implemented software pieces:

- Optional `CaptureEvidence` on the existing shared capture path and native
  constructor. Immutable snapshots retain bounded binary streams on success,
  nonzero exit, timeout, limit, reader and cleanup failure, and interruption.
  Default callers still receive their existing strict text/errors. The process
  lock and unresolved-reader guard remain shared, with no reset or bypass.
- `PrivateEvidenceStore` performs exclusive bounded writes and flush/fsync;
  interrupted intent files stay present and forbid another attempt. It verifies
  private storage, not physical instance identity or authority. Windows uses
  typed native APIs to verify actual owner and protected current-user-only DACL;
  ancestor handles and reparse checks protect the path, and file ACL is checked
  before private bytes are written. The explicit setup API
  `windows_private.provision_private_directory(absolute_path)` creates only a new
  directory with protected inheritable DACL, never changes an existing ACL.
  This API is not invoked by preview. Native Windows execution is not yet tested.
  Windows file fsync is implemented; POSIX directory-fsync equivalence is not claimed.
- Internal `run_experiment` holds the original `RunJournal.device_lock` from
  before stopped-state preflight through final cleanup. It reserves before launch,
  durably claims launch/location/shutdown once, and retains unresolved exclusion.
  Installation/preparation, capture, save and cancellation paths reach producer
  sealing and bounded drain. Unreliable storage, identity or cleanup forbids a
  shutdown command and reports the specific decision.
- `capture_native_point` composes the existing native write without relaxing its
  success gate. A probe is allowed only after exact `write_ack_unconfirmed`,
  `last_delivery.command_completed`, complete nontruncated capture, confirmed
  cleanup and successful private persistence. The trusted adapter must use the
  existing `OwnProbe` at 1000 ms/128 maximum samples. The private typed result
  preserves nonce/binding/boot/device-window/sample-time/accuracy correlation.
  `observe_declared_point` invokes exactly one window and compares every sample
  numerically with the frozen raw target and supplied tolerance. It does not
  convert or infer vendor CRS, create calibration, prove causality, or acknowledge
  injection. No samples remains `no_samples`, not a match. Public output includes
  only fixed observation status and sample count; target, tolerance and errors
  remain private.
- The shutdown observer samples four signals sequentially on fixed 0/5/.../30 s
  offsets. The same absolute 45 s deadline begins before sealing/draining and
  includes identity checks, intent persistence, shutdown, capture cleanup, reads,
  waits and evidence persistence. Each read receives min(1 s, remaining), and
  shutdown min(5 s, remaining). The capture helper accepts the same absolute
  cleanup deadline; a 1 s read plus its cleanup is not a 1 s wall-time guarantee.
  Storage/OS scheduling cannot be forcibly interrupted: overruns are unknown and
  actual monotonic times remain visible. Missing reads, observed identity/restart
  changes and any change in the other three instances are retained, never erased
  by later stopped samples. At least the last three complete rounds must agree.

`sampled_shutdown_consistent` means only that the sampled evidence agrees over
that observation window. It does **not** mean native stop ACK, queue clearance,
causal uniqueness of a location match, no brief inter-sample restart, or safety
to restart. Native `stop_unconfirmed` and replay-disabled status always remain.

## Trusted adapter boundary and remaining work

The internal adapter seam is for reviewed code, not a user-configurable plugin or
an API accepting claimed-success booleans. Tests inject synthetic adapters; those
results are not device evidence. Before installing a real adapter it must:

1. Read the original fixed local registration, bind stable instance UUID/index
   to the original device ID and journal, and reject missing/ambiguous/changed
   mappings before launch. Boot ID is only a per-run association, not the
   cross-boot exclusion key. Changing output directory, device ID or journal is
   not recovery. The kernel cannot prevent unrelated manual MuMu operations;
   retain the isolated instance and **do not restart it** after this experiment.
2. Implement independently reviewed, bounded fixed-argv launch, approved same-source
   installation and target shutdown from original-machine evidence. Do not grant
   permissions automatically. Bind manager existence and valid process/Android
   states, exact ADB serial status, current boot, and the attributable execution
   processes plus descendants using PID **and creation time**. A window title or
   bare PID is not identity; a missing manager entry is unknown, not stopped.
3. Pass the shared capture guard for all reads/writes. Missing executables,
   denied queries, timeouts and parse failures are unknown, not ADB-unavailable
   or process-exited evidence. Unattributable shared services stay unknown.
4. Use the implemented `observe_declared_point` helper with the predeclared
   private target/tolerance and an existing guarded `OwnProbe`. Its typed result
   retains nonce/binding/boot/device-clock correlation, accuracy and numeric errors.
   No clock subtraction across host/Android domains, matching retry, second point
   or CRS inference is allowed.
5. Independently review the exact implementation and validate Windows privacy,
   crash recovery and all negative cases before any separately approved runtime.

Remaining implementation is not all an external evidence blocker: generic
Windows PID/creation-time/image/exit querying, strict fixed registration loading,
and concrete lifecycle wiring can be implemented and tested with synthetic inputs.
Those components are not installed yet. What requires original-machine evidence
is the actual MuMu-specific relation from stable instance identity to attributable
execution processes, the original host/device/journal mapping, and verified launch
and shutdown grammar. A generic OS process record does not prove MuMu ownership.
The earlier staged omission of numeric point/tolerance correlation was an
implementation omission, not something requiring real-device execution.

Read-only original-machine preflight should retain privately: exact manager
version/hash and read-only help grammar; the four stopped-instance records;
stable registration mapping and original journal path; the observed schema fields
needed for manager/ADB identity; and Windows process-query access/attribution
evidence (including executable identity, PID, creation time and descendants).
Do not start an instance merely to fill a missing process sample. If the necessary
stopped-state attribution cannot be established without launch, stop at not-ready
and review that dependency before runtime. Do not upload raw identifiers, paths,
stdout/stderr, coordinates or screenshots publicly. Public handoff uses only fixed
status/reason codes, counts and safe artifact hashes.

Hard kill/power loss cannot run `finally`. Recovery retains the original marker
and intent files and permits investigation only, not restart, input, repeated
shutdown, marker deletion, reset/clear or global kill. Normal agent/server and
wire models are unchanged. The historical #57 HTTP failure remains unresolved by
this slice. No continuous replay capability is created.

## Software verification

```sh
python -m pytest tests/agent/test_command_evidence.py tests/agent/test_private_evidence.py tests/agent/test_windows_private.py tests/agent/test_evidence_experiment.py tests/agent/test_experiment_shutdown.py tests/agent/test_evidence_entry.py tests/contracts
python -m pytest
```

These are fake clocks, synthetic host children, local temporary storage and
protocol tests, not MuMu/API35/installation or school-record acceptance. The PR
records exact results, failures and immutable source identity separately.
