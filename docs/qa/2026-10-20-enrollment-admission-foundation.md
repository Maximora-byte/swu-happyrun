# Enrollment admission foundation (Issue #100, second batch increment 1)

Base: `87c507b0629c3330fd6cb8aee512b8c1418c89d1`.
Shared-file registration: [Issue #100 comment 6289033254](https://github.com/Maximora-byte/swu-happyrun/issues/100#issuecomment-6289033254).

## What this increment provides

- Strict readers for separately supplied runner pins, fixed control-root authority,
  immutable approved-plan bytes, current epoch/revocation/expiry, and target identity.
- Host namespace and legacy device-ID derivation, paired static config UUID/name/index
  consistency, fixed registration receipt location, and single-record account capacity.
- Native Windows local-NTFS/private-ACL checks and held no-delete-sharing directory/file
  handles. Existing account admission lock is acquired before the original device OS lock,
  which is acquired before opening an existing SQLite database in `mode=rw`.
- The new journal helper never creates the lock/database/schema and rejects active,
  uncertain or malformed existing reservations. It keeps the original OS lock live until
  SQLite closes. Live approval is rechecked before exposed database access or reservation
  mutation. Expiry/revocation blocks new mutations; there is no cleanup bypass.
- Existing mutable journal contents are identity-bound, not frozen-hash-bound. Normal
  journal writes do not invalidate immutable approved configuration facts.

## Deliberate limits: not transaction completion

This is a pre-write foundation, not an enrollment initializer or a usable execution
permit. There is no review-tool CLI, pin issuer, approved-plan writer, first-use state
publication, transaction stage journal, recovery coordinator, ready-receipt publisher,
process ownership check, installation, device start/stop, sensor write or trajectory replay.
`ApprovedPlan.execution_allowed` is always false. Existing native entry gates are unchanged
and remain closed. Passing fixture tests does not authorize real-device use.

Runner anchors must come from a separately reviewed immutable runner; the Python dataclass
constructor is not a trusted issuer. The reviewed-scope digest is envelope binding only:
this increment does not independently build or validate a complete discovery ledger.
Manager bytes/version are pinned input facts, not a new runtime version probe. Existing
receipt bytes are pinned, not interpreted as a complete ready-state proof.

New-enrollment plans require absent journal/receipt targets. Revalidation deliberately
rejects a newly published target or changed admission record, even if a future initializer
created it. The next increment needs explicit phase-owned artifact verification and
no-overwrite transaction transitions; it must not weaken absence checks or silently reuse
this pre-write snapshot. Cleanup authority after a started run must be separate, bounded
and attributable; this increment starts no run and grants no such authority.

## Validation and interpretation

All Linux tests use synthetic private temporary files. Native protection contexts are
substituted only in integration fixtures; real platform entry fails closed on Linux.
The native local-NTFS probe is skipped outside Windows. This is not evidence of Windows
ACL/reparse/race behavior or original-machine acceptance.

Commands:

```sh
PYTHONPATH=src pytest -q tests/agent/test_enrollment_authority.py tests/agent/test_enrollment_admission.py tests/agent/test_journal_preopen.py
ruff check src tests
ruff format --check src tests
```

Covered failures include missing/replaced objects, malformed/revoked/expired authority,
wrong identity domain, target substitution, mutable-journal changes, conflicting admission
records, held-account/held-device contention, approval loss after device acquisition before
SQLite open, and expiry/revocation after SQLite open before mutation. Tests also verify
first-use cannot open SQLite and loaded plan cannot open native execution gates.

Exact final test counts and commit/tree are recorded in the PR/Issue #100 handoff. No real
user state or device was touched and no merge or user acceptance is implied.
