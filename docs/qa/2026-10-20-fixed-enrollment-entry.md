# Fixed enrollment handoff entry

This small slice follows the accepted `94dcbfc` candidate. It connects existing
review/transaction APIs; it does **not** implement native execution, a trusted
runtime resolver, positive PID attribution, or production cleanup authority.
Those remain separate blockers. A successful software test, candidate creation,
or pin inspection is not original-machine acceptance or permission to run MuMu.

## What is executable now

The installed package provides:

- `enrollment_runner.diagnose_fixed_candidate(RunnerAnchors)`: load the original
  pinned plan and scope, then inspect retained transaction evidence. No SQLite
  connection, initializer, repair or pin issuer is invoked.
- `enrollment_runner.initialize_fixed_candidate(RunnerAnchors)`: one explicitly
  authorized candidate initialization through the existing protected-path,
  account-lock, original-device-lock and existing-SQL checks. It does not create
  approval, grant execution, clear reservations, or fabricate historical receipts.
- `enrollment_pin_reviewer.issue_fixed_pin(RunnerAnchors)`: a **reviewer-only
  entry**, imported directly by the physically separate external reviewer
  script, never by another production package module. It only publishes a pin for an
  already complete candidate, through the original exclusive issuer. It does not
  initialize an unstarted candidate or overwrite/adopt a previous pin.
- `enrollment_runner.inspect_fixed_pin(ReviewPinAnchors)`: load the exact original
  scope and inspect the independently pinned final artifact under existing locks.
  It does not open SQLite or issue/renew a pin.

The initializer and inspector receive no scope/path argument. They read only the
fixed `reviews/<plan hash>/reviewed-scope-v1.json`, bounded by 2 MiB, with its
expected digest taken from the independently pinned plan. A no-redirect bounded
read checks the observed identity; it does not turn that observation into a new
trust anchor. Plan and parent identity are checked again. Initialization and pin
operations repeat their checks under their original locks; read-only diagnosis
remains an unlocked observation, not a current runtime admission. Expiry/revocation
between these checks still fails closed.

All four return `execution_allowed=false`. `RunnerAnchors`, `ReviewPinAnchors`,
ordinary registrations, JSON, hashes and dataclasses still cannot pass
`require_native_enrollment`. No CLI option or environment variable selects an
anchor, approval file, latest revision, reviewer module, or production bypass.

## Original-machine operator sequence (not authorization to execute it)

The current formal account is **not initialized**. Do not run write steps until
the independent original-machine operator has separately approved that exact
operation and the scope blockers below are resolved.

1. Independently review the exact product commit/tree, installed distribution and
   interpreter. Record the installed package files and the external runner code,
   hashes, file identities and protected parent identities in private evidence.
   Do not run against an editable source checkout or automatically install latest.
   The package cannot authenticate its own code or establish reviewer independence.
2. Collect the original host/manager/config identities and historical source
   ledger below. Use `inspect_enrollment` for actual read-only observations.
   Keep unknowns and original truncated reports. `build_review_scope` is only a
   serializer/validator; it cannot certify a person's scope declaration.
3. The independent reviewer, not the initializer, explicitly provisions the
   control layout with `enrollment_reviewer.prepare_control_layout(transaction_id)`
   only after separate write authorization. Independently inspect the returned
   layout and parent identities. Construct and review the original V2 plan and
   full scope, then call `publish_initial_approval(layout, raw_plan, reviewed_scope)`.
   This is a separate operation, not invoked by either example script. Any
   incomplete result or uncertain publication retains its evidence; do not retry,
   clean, replace, or manufacture a historical receipt.
4. Independently verify the published authority, epoch/revocations, plan bytes,
   scope digest, control-root and plan-parent identities and original lock
   identity. Copy `examples/enrollment/fixed_candidate_runner.py` to a private
   protected **external** location. Embed the reviewed `RunnerAnchors` as literal
   Python values. Do not read them from JSON, environment, CLI, current-directory
   files or a newly discovered authority. Re-review/fix this external code and
   installed package; changing constants is a new review, not an automatic update.
5. First use a fixed copy with `OPERATION = "diagnose"`. Run the independently
   fixed interpreter with `-I <private external script>`, without arguments.
   `unstarted` is diagnostic only and exits 2; it is not a success or permission.
   If separately authorized, a **separately reviewed copy** fixed to `"initialize"`
   performs one initializer attempt. `candidate_unpinned` exits 0 but means only
   that the candidate artifacts exist, not execution readiness.
6. The reviewer independently inspects that candidate and uses its separate
   protected copy of `examples/enrollment/independent_pin_reviewer.py`, with the
   same reviewed literal `RunnerAnchors`, for one separately authorized pin
   publication. Both templates reject all arguments. The distributed templates
   have unset anchors and always refuse. Neither emits raw paths or identities.
7. Inspect the final pin's actual bytes/hash, file identity and parent identity
   independently. Construct `ReviewPinAnchors` using those exact observations,
   not a file found by newest timestamp or the issuer's return value alone.
   Fix a separate external runner copy to `"inspect_pin"` with those literals.
   A successful read-only inspection exits 0 but still cannot run a device.

Frozen authority, plan, scope, source configuration, stage records, provenance,
receipt, candidate and pin bytes are distinct from the mutable journal. Later
legitimate intent/result updates do not require changing a journal byte hash.
Runtime SQL/reservation validation must stay under the original locks; this
entry does not replace it with read-only file inspection or release an unresolved
reservation. Missing independent trust or positive process attribution leaves
production execution closed.

## Concrete historical-source ledger and the 450-entry blocker

Keep the ledger in private evidence, not Git or public comments. For **each** of
the following categories record: the exact source examined; the retrieval method
and date; original file identity/hash where a file exists; original text or
private evidence reference; the effective host/journal/root paths; whether a
relative path was resolved against its actual historical working directory;
the operator who checked it; and every inaccessible/unknown source.

1. **Historical launch arguments:** inspect retained terminal/PowerShell history,
   launch scripts, shortcut targets plus “Start in”, Task Scheduler actions plus
   working directory, and service command lines where applicable. Explicitly
   enumerate every observed `--journal` path, including nonstandard suffixes.
   A missing selected old journal is unknown, not a new namespace.
2. **Historical configuration sources:** inspect the actual configuration files,
   wrappers and documented environment sources used by those launches. Preserve
   host override and effective namespace evidence. Merely listing an existing
   config file does not prove its contents or effective paths were checked.
3. **Custom roots and other disks:** follow every path referenced by (1)/(2),
   including previous working directories and moved installations. Record which
   volumes and roots were checked and which are unavailable. Do not infer that
   the current default directory was the only historical one.
4. **Other accounts:** identify the account contexts that could have run the
   program. Obtain independently authorized evidence for each relevant context,
   or leave it unchecked. The current account's empty directory proves nothing
   about another account; this checklist authorizes no cross-account access.
5. **Legacy writers:** inspect retained versions, entry scripts, service/task
   definitions and their configured state paths. Inventory old reservations and
   journals; absence of a new receipt does not erase old state. Do not launch a
   legacy writer just to discover its path.

Feed the effective paths into the existing `DiscoveryScope.roots`,
`journal_arguments`, `working_directories`, and `configuration_sources`. Preserve
the relation from each path to its concrete source. Resolve duplicates only from
positive identity evidence; do not silently collapse aliases or redirecting
paths. Review the fresh actual inspection, not an edited copy of its JSON.

The v1 `DiscoveryScope` retains its **global 450-entry budget**, depth 4 and
32-root limit. The original ten-root report exhausted that budget and left five
source categories unchecked. Keep that original report; it is not made complete
retroactively. The additive [bounded v2 coverage](2026-10-20-bounded-scope-coverage.md)
provides an explicit fixed-policy full rewalk beyond 450 entries. It does not
prove any of the five historical source categories or authorize initialization.
Separate old truncated scans cannot be concatenated into either ledger version.

## Evidence and remaining work

Tests exercise the real existing transaction and issuer against synthetic local
storage, with native protection replaced only in test fixtures. Invalid anchors,
missing/tampered/oversized scope, and approval loss produce no initialization
mutation. Read-only paths do not open SQLite, emit new pins, or change bytes.
Standalone unset scripts and installed isolated-interpreter refusal are separate
checks from successful synthetic function integration. Exact commands/platform,
HEAD/tree and CI belong in the PR receipt, not an inferred Windows result.

This entry does not establish historical source completeness, internal typed
runtime resolver, per-action approval/SQL validation, bounded original-scope
cleanup after producer shutdown, positive PID association, active sampling, or
real device execution. None of these may be inferred from an exit code of 0 here.
