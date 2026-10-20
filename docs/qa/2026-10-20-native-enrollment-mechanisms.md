# Opt-in Windows enrollment mechanism QA

## Status and authorization

This is a **test entry, not a Windows acceptance result or execution permission**.
Implementation started at PR #105 `8622e25f91490f039b7adceedd7c1d4fad3fbc5c`
and resumed after its fixture prerequisite
`725e5d610fa96da2b409f55dba6296fd0ab63ba0`. The prerequisite fixed synthetic
binary-mode/fixture issues; it does not prove these native cases pass.

Only portable safety tests and default-skipped collection were run on Linux.
Windows/NTFS/ACL behavior, process exclusion and durability remain **not run**
until an authorized operator executes this exact test entry and reviews its
per-case reports. The current working tree can contain concurrent implementation;
the report records HEAD, HEAD tree, dirty status and an aggregate hash of the
actual product Python files. HEAD, tree and product-source hash are checked again
before a case can pass. A dirty tree is not represented as an immutable commit
acceptance.

Delivering this code, approving the design, or running ordinary pytest **does not
authorize Windows ACL/state-writing QA**. Obtain explicit operator authorization
for creating new private test directories and synthetic enrollment state under
the chosen disposable QA directory first. This code does not authorize changes to
existing ACLs, production account state, native device operations, security
settings, or execution-capability issuance.

## Commands

Portable checks, including subprocess verification that native collection skips:

```sh
python -m pytest tests/native_enrollment -q
python -m ruff check tests/native_enrollment
python -m ruff format --check tests/native_enrollment
```

After separate authorization, in an ordinary Windows checkout with the project's
Python dependencies installed:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/native_enrollment/test_native_mechanisms.py `
  --run-native-enrollment `
  --authorize-native-enrollment-writes `
  --native-enrollment-qa-root C:\qa `
  -v -s
```

`C:\qa` is an example, not a default. Select an **already existing** disposable
directory on a fixed local NTFS volume. A short path is recommended; long-path
support is not enabled or changed by the tests. The directory must not be the
drive root, a redirected/reparse path, the formal product-state directory, a
descendant of that state, or an ancestor containing that state. Existing parent
ACLs are never modified. Unsupported ACLs, NTFS, path lengths or permissions fail
the case; there is no repair, privilege elevation, or fallback fake guard.

Before provisioning, the helper rejects reparse chains, obtains filesystem-backed
canonical paths for the selected root and the nearest existing formal-state
ancestor, reconstructs any missing formal suffix, and compares canonical ancestry
and relevant existing directory identities. A Windows 8.3 spelling is not
accepted as evidence that a directory lies outside formal state. These exclusion
checks read only ancestor metadata; they do not create missing formal directories
or scan formal enrollment files.

All three options are required. Without opt-in, without explicit write
authorization, without a selected QA directory, or on non-Windows, the 12 native
cases skip **before any QA root is created**. Flags are an operator entry gate,
not a substitute for any authorization required by the environment.

## Isolation and real mechanisms

Each case creates a new, exclusive `eq-<random>` private child beneath the
selected directory. No existing test case is reused. The fixture consists only
of synthetic UUIDs, non-executable manager bytes, `.nemu` XML, and a synthetic
empty or historical SQLite database. The fixture's `6.8.4.0` plan version is a
synthetic input, not an observed MuMu installation/version.

New directories and files use the real `windows_private` APIs. The actual local
NTFS checks, protected-directory/ancestor handles, owner/DACL checks,
`enrollment_reviewer.prepare_control_layout`, reviewer approval publication,
private storage, and `initialize_candidate` remain in force. No
`_protected_paths`, `verified_directory`, NTFS checker, or storage readback guard
is replaced with a fake.

Only test helper subprocesses bind the reviewer, transaction and admission
modules' imported root resolvers to the new fixture root. The production
`enrollment.resolve_control_root` remains unchanged. Helpers also bind the
inspector namespace source and set their own `LOCALAPPDATA`/`XDG_CONFIG_HOME` to
the new synthetic namespace, removing a host-file override. This prevents the
inspector's additional default-root discovery from visiting formal user state.
The pytest parent's environment is not modified. There is **no product CLI or
environment bypass**, bootstrap, real host-ID creation, or formal enrollment.

Native I/O observation subclasses the captured real `_NativeIO`: constructor,
ACL/path checks, handle management and readback are inherited unchanged.
`create`, `write`, `fsync`, `flush` and `move` wrappers call captured real methods.
Only an explicitly selected before-fault omits its intended operation. An
after-fault is raised only **after the real operation returns**. Native failures
are not relabelled as successful injection.

## Per-case evidence and pass criteria

1. **Native stage/publish positive.** The reviewer creates the real fixture
   authority. With its original account lock held, private storage stages and
   publishes a binary payload containing LF, CRLF, NUL, Ctrl-Z and `0xff`.
   Real create/write/fsync/FlushFileBuffers/MoveFileExW boundaries must return,
   the stage must disappear, and final bytes must match exactly.

2. **Account-lock coordinator contention.** One spawned process calls the actual
   `initialize_candidate` and pauses just after the real account lock succeeds.
   A second process calls `initialize_candidate` against the same reviewer
   anchors. The loser must attempt and fail that account lock, return incomplete,
   and show zero journal-byte opens, zero SQLite connects, zero native storage
   mutations, zero audited filesystem mutations and zero process-launch attempts.
   Bounded before/after state snapshots must match while the winner remains
   paused. The account lock is inspected through metadata only while its byte is
   locked, then checked for its original byte after release. The winner resumes
   its same coordinator attempt and must finish `candidate_unpinned`, with
   `execution_allowed == false`. This is **not** labelled acceptance from a
   low-level lock-only test.

3. **Original-device contention.** A separate process holds the actual
   `RunJournal.lock_existing` lock on synthetic existing history. The contender
   calls the actual coordinator and must finish incomplete with zero SQLite
   connects, zero device/process-launch attempts, no candidate, and unchanged
   original DB/lock identity, size and byte hash after release. The report names
   the observed rejection boundary: original-device lock rejection, or earlier
   failure reading the already locked byte. Windows can enforce that earlier
   byte-read boundary. The test does not invent a later lock attempt.
   Admission/intent prefixes may exist because they precede original-device
   locking; their actual presence is recorded. Arbitrary earlier failure is not
   accepted as proof of device exclusion.

4. **Existing-history coordinator positive.** The actual coordinator must
   complete `candidate_unpinned` after one SQLite open under its original locks.
   Both original fixture artifacts must retain identical identity and bytes.
   It does not establish historical provenance or issue a review pin.

5. **Eight native-delegating faults.** Before/after each of write, fsync,
   FlushFileBuffers and MoveFileExW is injected once in a new case. The
   private-storage result must be incomplete/uncertain at that exact phase.
   The report distinguishes attempted, delegated, returned and injected calls.
   Before-move and prepublication faults retain the stage. After a successful
   move followed by the injected exception, the destination must remain with
   exact bytes and the stage must be absent. That destination remains an
   **uncertain result**, never a successful/retryable publication.

The storage fault cases exercise the real primitive under real reviewer
authority/account locking. They are not full-coordinator fault-injection
acceptance and do not simulate power loss. The two contention cases and existing
positive separately exercise the real coordinator.

## Reports, bounds and failure handling

The runner prints each retained case directory. A bounded private
`reports/result.json` records the checkout evidence, synthetic fixture scope,
per-process counters, actual boundary, expected/actual state observations and
case outcome. It is outside all scanned state roots, as is the storage test's
`evidence` directory. On failure, pytest reports the failed assertion; worker
setup errors additionally record the precise setup phase and sanitized exception
type. If setup fails before a private report directory exists, no report is
manufactured in an unverified location. If native report publication itself
fails, pytest reports that failure and retains any partial report artifacts.

Reports are capped at 128 KiB; native traces at 1,024 events; state snapshots at
256 entries, 16 MiB per file and 32 MiB aggregate. The inventory is capped during
enumeration, before sorting or descending. Symlink/reparse and non-regular file
observations are rejected; regular bytes are hashed in bounded chunks with
pre-open, owned-fd and post-read identity/metadata checks. Product scan/read
budgets remain unchanged.
Spawned processes use 90-second IPC/release deadlines, bounded joins, then
termination/kill of **only the harness's owned process** if required. Successful
worker reports also require observed zero exit status; receipt of IPC alone is
not considered successful completion. No worker launches MuMu, ADB or any other
external process. Python's process-launch audit paths are blocked during tested
operations and counted if attempted.

Native case snapshots and original DB/lock byte observations run in supervised
read-only helper processes, not as potentially blocking parent file opens.
Their parent IPC wait is bounded just like other helper operations. This is not
a hard real-time operating-system guarantee. These tests assume nobody modifies
the controlled disposable fixtures concurrently, except the tested processes.
Windows lacks Python's `O_NOFOLLOW`/`O_NONBLOCK` protection on these opens;
pre/post identity checks and rejection are not a claim of immunity to hostile
reparse or special-file substitution during an open race.

The zero journal-byte-open evidence counts Python byte-open calls for the exact
journal path, not metadata-only Win32 handles held by `_protected_paths`.
Filesystem audit counters plus captured-native mutation counters and snapshots
cover these implementation paths; they are not a universal kernel syscall trace.

There is **no automatic repair, resume, repeat of a failed operation, ACL
modification, rollback, deletion, or artifact cleanup**, including successful
cases. Inspect retained evidence before deciding separately whether to delete a
disposable case. A new invocation always chooses a new case directory.

## Linux implementation verification

The post-review focused run reported **45 passed, 12 skipped**
on Linux/Python 3.12.14. It covered the explicit-option gate, real default-skipped
pytest collection, non-Windows refusal even with all flags, pure before/after
delegation semantics, native-error preservation, bounded owned-child cleanup,
synthetic in-memory SQLite fixture contents and audit-report serialization.
It also checks that the helper never replaces the native/private guards,
canonical/identity root isolation including simulated 8.3 aliases and absent
formal roots, pre-enumeration caps, special-file/reparse rejection, bounded reads
and identity mismatch rejection, metadata-only locked-byte observations, and
supervised read-only evidence helpers. The synthetic SQLite connection is
explicitly closed. Ruff checks and format checks passed for all six Python files.

The combined regression command also passed on Linux/Python 3.12.14:

```sh
python -m pytest tests/native_enrollment \
  tests/agent/test_enrollment_transaction.py \
  tests/agent/test_enrollment_admission.py \
  tests/agent/test_journal_preopen.py \
  tests/agent/test_enrollment_reviewer.py -q
```

Post-review result: **158 passed, 13 skipped in 58.89 seconds**. The earlier
pre-review run was 140 passed, 13 skipped in 60.08 seconds. The skips are the 12
new opt-in cases and the existing native Windows NTFS probe. This is a focused
regression run, not the full project suite.

These are test-harness/synthetic results only. They do not establish Windows
private ACL ownership, NTFS behavior, real exclusion, power-loss durability,
MuMu/ADB behavior, real-device execution, or school/server acceptance. The
production admission boundary remains closed.
