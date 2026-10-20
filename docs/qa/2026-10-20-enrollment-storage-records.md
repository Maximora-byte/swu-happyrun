# Reviewed candidate enrollment transaction (second-batch increment 2)

Depends on the pinned admission/pre-open lock foundation at
`07e96bd8568aa1ceb6d5b5c4748066e014c87efa` (PR #104). This increment provides candidate-only software interfaces. It does not grant
permission to initialize an actual instance or complete runtime/pin acceptance.

## Exclusive native storage

`enrollment_storage.private_storage(parent, parent_identity=..., validate_current=...)`
holds verified private parent/ancestor guards on Windows local NTFS. It provides
`stage(destination_name, payload, transaction_id=...)` and `publish(staged)`.
Staging names are deterministic, private CREATE_NEW objects. Every write/flush/
publication validates current authority through the caller's live callback.
The caller must already hold account admission and any required original-device
lock; a callback itself is not independently trusted approval.

Publication uses same-directory MoveFileExW without REPLACE_EXISTING or COPY_ALLOWED.
The source handle is closed before publication, and exact identity/hash are checked
before and after. A source-name substitution in the close-to-move window can leave
a different object at the destination; readback rejects it and the transaction stays
incomplete. Storage failures poison the session and leave artifacts in place;
there is no overwrite, adoption, deletion, implicit directory creation, automatic
recovery or retry. An uncertain outcome remains incomplete. Synthetic fault tests
cannot establish hardware power-loss durability or original-machine NTFS acceptance.

## Pure immutable record format

`TransactionLayout` derives fixed role and stage-file names. Construction is only
syntactic validation, not path approval. The separate reviewer provisions and binds
all parent directories, including `control-v1/transactions/<transaction_id>`, before
an initializer can use them. The V2 plan also binds the evidence root and receipt
inputs; this layout alone does not invent or authorize those facts.

`encode_record` / `decode_record` use strict canonical JSON and complete, explicitly
python_stat-domain file/parent identities. Each record binds plan/transaction,
sequence, previous-record SHA256 and one actually observed artifact. Role order is
admission, intent, original device lock, journal, provenance, receipt, candidate.
No observation may be prefilled as already verified before the artifact exists.

`diagnose_transaction` performs no I/O. The caller supplies actual observations and
ordered record bytes obtained under the required locks/path protections. Missing,
extra, reordered, malformed or conflicting records/artifacts return incomplete.
A full consistent chain returns candidate_unpinned, never ready. After full candidate
completion, the mutable journal's identity/parent/path still match but its initial
content hash is not permanent; partial transactions still require the recorded
initial contents. This does not inspect SQL integrity or clear unresolved intents,
start records or reservations. Those checks are required separately before runtime.

A self-consistent chain is not independent trust. The future ReviewPin must bind the
candidate and frozen record material; no module here issues one, repairs stages or
promotes a candidate to execution. A crash after an effect but before its record
remains incomplete. A receipt without candidate-completion evidence is not complete.

## Review ledger

The independent scope-ledger module serializes and validates the inspector's actual
bounded observations, retaining declared sources, roots, counts, exclusions/errors,
historical declarations, unchecked categories, identities and original observation
time. Its output is private, non-authorizing material for later reviewer provisioning.
It cannot turn the original 450-entry/incomplete snapshot into reviewed first use.
Fresh observation comparison ignores only observation time; it does not invent file
content facts that the underlying inspector never collected. Frozen host/manager/XML
bindings and explicit original-machine review remain separate requirements.

## Independent reviewer versus initializer

`enrollment_reviewer.prepare_control_layout(transaction_id)` exclusively creates the
fixed private control layout and original admission lock, but no authority, plan,
journal or receipt. Existing or partial roots are refused, never repaired. This is
an explicit original-reviewer operation, not part of inspect/dry-run/initializer.
Actual execution needs the operator's specific authorization for these private ACL
and state writes; it was exercised here only through synthetic temporary fixtures.

After layout creation, the independent reviewer captures the complete scope ledger
and prepares strict approved-plan-v2 bytes. `publish_initial_approval(layout, raw_plan,
reviewed_scope)` verifies target/root coverage and fresh scope, holds the account
lock, then publishes the scope and plan before initial authority. It never replaces
an existing authority, edits approved files, writes ReviewPin or generates a runner.
Returned anchors require separate independent inspection and fixed embedding in a
reviewed runner. A caller name, self-computed digest, dataclass or design approval
receipt cannot substitute for that trust handoff.

The V2 plan binds transaction ID, exact product commit/tree, evidence root and all
existing directory identities, original device-lock target, and static target facts.
`enrollment_transaction_plan` separately parses, loads anchored control bytes and
validates frozen inputs. No product version or source commit is auto-attested by a
JSON field; those values must be independently checked in the reviewed handoff.

`initialize_candidate(anchors, reviewed_scope)` is a one-attempt internal API. It
holds path guards, account admission lock, then the original device byte lock before
any SQLite connection. Read-only ancestor guard metadata may be inspected before an
admission conflict is rejected; losing attempts must perform no journal bytes open,
mkdir, SQLite connect or native-device action. Existing history without an old
receipt is recorded as current adoption, preserving original DB/lock bytes and IDs.
New empty SQLite is prepared only under the original device lock, not by calling an
ordinary RunJournal constructor before locking. No synthetic start or stop ACK is
inserted and no reservation is cleared.

The initializer publishes immutable admission/intent/stage artifacts, provenance,
then the fixed schema1 receipt, followed by candidate completion metadata. Every
mutation rechecks authority, expiry, frozen inputs, current ACLs and phase-adjusted
scope/control inventory. Exact owned artifacts are allowed by actual identity; new
unreviewed history, foreign admission records, orphan transactions or unexplained
count changes remain incomplete. A selected journal parent must itself be an exact
reviewed root; being under an arbitrary approved-looking path is insufficient.

Scope snapshots precede reviewer plan/authority publication. Phase comparison adds
only the exact pinned review directory/files and transaction-owned artifacts to
that original ledger; it does not silently bless a new snapshot or suppress errors.
Live exclusive staging metadata comes from its actual owned descriptor rather than
opening a second handle to a Windows share-zero file. Locked byte content is likewise
not reread through an independently opened handle while the OS byte lock is held.

`diagnose_candidate` only reads bounded existing evidence. Completed repeats do not
rewrite state; partial evidence is never resumed/repaired. A first CREATE_NEW failure
before any object exists cannot leave a durable failure marker without another write;
later diagnosis correctly sees unstarted rather than inventing persisted evidence.
All retained partial/uncertain artifacts stay in place, and a receipt alone is never
completion. A consistent result is candidate_unpinned with execution_allowed=false.

## Still absent / acceptance boundaries

Independent candidate ReviewPin issuance/loading and a ready/execution capability
remain separate future work. No approval revocation/update workflow, automatic
recovery, installed arbitrary-path enrollment CLI, real process attribution or device
runtime is provided. Existing production gates remain closed. No formal user state,
MuMu/ADB/native device commands, sensor input, reservation clearing or cleanup
permission was exercised. Windows mechanism and original-machine acceptance remain
separate from Linux/synthetic tests and hosted CI. Existing 45-second cleanup rules
are not bypassed or expanded; this slice never starts a device/run.

Final immutable commit/tree, command results and skipped-platform counts are recorded
in the PR handoff. Earlier tests while sibling files changed are not final-tree proof.
