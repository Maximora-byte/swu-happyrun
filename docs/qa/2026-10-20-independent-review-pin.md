# Independent ReviewPin software slice

## Scope and status

This slice depends on PR #105. It is software for independent review and
read-only pin inspection, not permission to provision formal user state or run a
device. Production execution and continuous replay remain closed. All public
results have `execution_allowed=false`.

The separate reviewer API `enrollment_pin_reviewer.issue_review_pin` publishes
one fixed `control-v1/reviews/<plan_sha>/review-pin-v1.json` through exclusive
staging and no-overwrite publication. The initializer never invokes this issuer.
The read-only `enrollment_review_pin.load_review_pin` does not import the issuer,
write files, open SQLite, repair partial state, or infer authority from filenames.

A canonical reviewer label records provenance; it does not authenticate a human.
`ReviewPinAnchors`, frozen dataclasses, callbacks and hashes are not capabilities.
A separately reviewed immutable external runner must independently bind the
approval anchors and final pin hash, file identity and parent identity. This
slice does not build such a runner or grant it device execution permission.

## Binding and live checks

The strict record binds the original authority epoch, approved plan, reviewed
scope, candidate and transaction, product commit/tree, reviewer timestamp and
exact approval expiry. It preserves the frozen identities and hashes of the
original inputs, seven stage records, provenance, receipt and candidate. The full candidate/pin evidence snapshot is collected under account and
original-device locks. Held lock bytes
are read through their owner descriptors, not conflicting second handles.

The mutable journal is bound by path, file identity and parent identity, not its
current byte hash, size or mtime. Its original staging hash remains historical
evidence, not a permanent prohibition on later legitimate journal updates.

Publication revalidates current authority, expiry, protected paths, ACLs, frozen
evidence and scope at each mutation boundary. Scope subtraction is restricted to
exact owned live staging or the externally pinned final artifact. It does not
whitelist arbitrary matching filenames. Foreign files, changed frozen inputs,
changed identity, expiry or revocation prevent further publication. Partial or
uncertain artifacts are retained; no overwrite, adoption, deletion or retry is
provided. Checks are boundary-based, not hard real-time preemption.

## Synthetic lifecycle coverage

The additional `test_evidence_approval_expiry.py` suite exercises the test-only
lifecycle harness. Approval loss latches producer closure; later restoration
does not reopen producers. Post-start shutdown judgment remains independent of
new producer approval, retains the original lock through journal close and uses
one 45-second total synthetic budget including persistence/close. Missing command
issuance stays `shutdown_not_attempted`; uncertain issued shutdown remains
`shutdown_unknown`. Reservations and missing stop acknowledgements are retained.

This proves synthetic state-machine behavior, not production cleanup-capability
wiring, an authenticated approval issuer, actual process shutdown, in-flight
adapter preemption or native device acceptance. Production runtime gates remain
closed and still require separate implementation/acceptance where applicable.

## Native mechanism entry

See `2026-10-20-native-enrollment-mechanisms.md` for the separately gated Windows
QA entry and its retained private reports. Ordinary tests skip the native cases.
Delivery of that entry is not authorization to run ACL/state-writing QA; the
operator must separately authorize an isolated disposable root. No native
Windows or original-machine acceptance result is claimed by Linux test output.

## Verification accounting

PR descriptions and exact-HEAD receipts carry the final test counts and CI
results. Earlier focused results belong only to their stated source snapshot.
Native cases skipped on Linux are not passes. A completed CI job is not user
acceptance, and a successful pin inspection is not execution readiness.
