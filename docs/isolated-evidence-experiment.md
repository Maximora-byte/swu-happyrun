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

The read-only original receipt loader, its lifecycle rechecks and generic Windows
PID/creation-time/image facts are now implemented below. They do not provide a
MuMu ownership/exit adapter. What still requires original-machine evidence is
the MuMu-specific relation from stable instance identity to attributable execution
processes, the original host/device/journal mapping, and verified launch/shutdown
grammar. Those evidence-backed adapters still require implementation and review;
a generic OS process record does not prove MuMu ownership.
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

## Read-only original identity prerequisites

The prerequisite implementation adds no executable MuMu adapter. `--execute`
continues to return `not_ready`, with no launch/install/input/shutdown. These are
separate inspection commands, not an execution approval:

```console
python scripts/mumu_evidence_experiment.py --preview
python scripts/mumu_evidence_experiment.py --execute
python scripts/mumu_evidence_experiment.py --process-facts
```

The first two still start zero subprocesses. The last explicitly starts only a
fixed isolated Python read-only helper on Windows and prints fixed status/counts,
never paths, PIDs, creation times or raw OS errors. Non-Windows returns unknown
(exit 3); complete process facts return exit 0, partial/unknown exit 3. This is
not an instance shutdown check or MuMu ownership verdict. No process is stopped
except cleanup of the helper that this query itself started.

### Original receipt contract and provenance

There was no persisted instance-to-original-journal registry in the existing
product. The new loader therefore does not pretend one already exists. It reads
only `mumu-experiment-registration.json` next to the ORIGINAL persisted host-id
file resolved by `drivers.identity._namespace_path()` (including the previously
configured `SWU_HAPPYRUN_HOST_ID_FILE`, if any). It never calls `load_host_id`,
which creates missing identities. A missing receipt, host file, initialized
journal, or existing one-byte device lock is not-ready, not an invitation to
bootstrap, migrate, clear a marker, copy a journal, or rotate an identity.

The strict schema is a local private evidence receipt, not a new wire contract:

- `schema`: integer 1; `stable_instance`: canonical original vendor UUID;
  `instance_index`: canonical decimal string; `host_id` and `device_id`:
  canonical UUIDs.
- `host_file`, `manager_file`, `journal_file`: exactly `path` (canonical absolute
  original local path) and `identity` (two integers: Python stat device/inode).
- `journal_directory_identity` and `lock_identity`: original stat identity pairs.
  The lock path is derived by the existing journal device-ID SHA256 naming rule,
  never supplied by the receipt. `evidence_root` is the private output directory,
  not an alternative journal or lock namespace.

The receipt is capped at 8 KiB, rejects duplicate/unknown keys, wrong types,
noncanonical UUID/index/path, symlinks/reparse points and changed file/ancestor
identities. Device ID is recomputed using the ACTUAL existing manager contract:
UUID5 of the original persisted host namespace, `mumu`, and
`normcase(resolved original manager path):instance_index`. Vendor UUID is a
separate stable-instance claim; it must not replace this derivation.

A reviewed original-machine adapter must independently pin the receipt's SHA256
and stat identity before calling the loader. Computing a hash of an arbitrary new
receipt does NOT authenticate its history. This PR has no receipt writer, no
reviewed production receipt, no anchor-generation command, and no CLI journal,
device-ID or receipt overrides. Only synthetic tests create synthetic receipts.
The private library interface is:

```python
from swu_happyrun.drivers.mumu.original_registration import (
    load_original_registration,
    locked_original,
)

registration = load_original_registration(
    receipt_sha256=independently_reviewed_digest,
    receipt_identity=independently_reviewed_stat_identity,
)
with locked_original(registration) as original_journal:
    # Inspection only: shared original lock held, reservation checked, no writes.
    pass
```

These anchors must come from the original private review, not from untrusted
caller JSON. Inspection never opens SQLite (even SQLite read-only mode can create WAL shared
memory). It checks a bounded original header, rejects WAL/recovery sidecars, and
uses the existing lock only; database query/write methods are disabled;
regular agent defaults are unchanged. When the internal lifecycle receives this
validated registration type, it opens only the existing journal, keeps the same
original lock through cleanup and revalidates under lock and immediately before
launch. Windows ancestor/file handles deny delete-sharing; every path identity
is checked again. This is not a security boundary against a hostile administrator
or same-user process. Missing/changed files, lock contention, corrupt/uncertain
reservation all keep launch at zero. Neither inspection nor experiment releases
or deletes an unresolved marker. The preview does not fabricate a registration.

### Windows process facts and remaining original-machine evidence

`query_process_facts(deadline)` uses actual standard-library ctypes Toolhelp
snapshot APIs, query-limited process handles, process creation FILETIME, full
image path and a read-only file identity query. It returns private typed facts.
The native image lookup requires a fixed local NTFS volume and rejects remote
drives, unsupported filesystems and reparse paths. At most 64 ancestor/file
components are guarded without write/delete sharing through the file query.
The fixed helper has 512-row, 32,768-character per-path, 65,536-character aggregate
path and 512-KiB IPC caps (the shared capture retains its 1-MiB/stream cap). Total
budget is the lesser of the supplied absolute deadline and five seconds, with
0.5 seconds reserved INSIDE that deadline for helper cleanup. OS scheduling is
not hard realtime: overrun or unconfirmed cleanup is unknown, not hidden.

Permission denial, failed reads and partial enumeration are retained as unknown
or partial facts. PID reuse is distinguishable by `(PID, creation FILETIME)`;
missing PID is NEVER automatically exit evidence. Parent PID is an unverified
snapshot hint, not ownership or reliable ancestry, and the snapshot is not
atomic. Legacy Windows volume/file-index identity describes the file opened at
the image path, not a loaded-image attestation or universal ReFS identity. Never
infer MuMu ownership from process names, or turn these facts into a successful
`processes` shutdown signal without separately reviewed attribution evidence.

Still needed privately on the ORIGINAL machine before an executable adapter:

1. Independently established historical host file/namespace, manager path/index,
   vendor UUID mapping, original journal directory/file and initialized lock
   identities; reviewed receipt digest/file identity. If absent, remain not-ready
   and separately review how provenance can be established, never synthesize it.
2. Actual MuMu 6.8.4 manager version/hash/help and verified targeted launch and
   shutdown syntax; exact stopped-instance state schema and all four identities.
3. Evidence tying the target vendor UUID/index to the VM execution PID plus
   creation time and attributable descendants, including ambiguity/shared-service
   handling. Do not launch merely to collect this missing evidence.
4. Fresh approved serial/boot/API35 binding, selfProbe artifact/certificate and
   permissions, privately preregistered raw target/tolerance, and independent
   Windows review of native file/process behavior and ACL enforcement.

All identifiers, paths, raw receipts, command output and process facts stay local
and private. Public reports contain only fixed reason/status/counts and safe
artifact hashes. No account, school, system permission or other instance changes;
continuous replay remains closed, and manual restart of the isolated instance
remains outside and prohibited by this experiment's workflow.
