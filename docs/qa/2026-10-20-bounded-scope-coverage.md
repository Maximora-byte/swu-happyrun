# Bounded v2 discovery coverage

This additive software slice starts from PR107 `7763ece6bb5edde47961454a106be783d492f6cf`.
It closes the scanner's 450-entry limitation for explicitly selected v2 scopes,
not historical-source review or production admission. No original-machine state
is initialized and no device execution is enabled by these APIs or examples.

## Fixed policy and actual traversal

Existing `DiscoveryScope`, v1 ledger bytes, depth 4 and global 450-entry refusal
remain unchanged. Independently reviewed Python tooling may explicitly construct
`BoundedDiscoveryScope` with the same effective roots, journal arguments, working
directories and configuration sources. There is no CLI/environment budget,
exclusion list, resume cursor or trust override.

V2 has a fixed 450-entry page, at most 64 pages (28,800 total entries), depth 8,
and at most 32 roots, with one global entry budget across roots. Reaching the
total bound is conservatively incomplete, even if the last entry might be the
last real one. A larger or deeper scope still stops unknown and requires a
separately reviewed software policy, not local policy editing. Ledger bytes
remain bounded by 2 MiB; oversize evidence also fails closed.

The scanner retains its open directory iterator across page boundaries and an
internal pending subtree list. It captures each pending directory's chain,
identity and modification/change times before descending, verifies them before
reading, and rechecks all observed directories at completion. Cross-root final
revalidation catches an earlier root changing during a later root's scan.
Redirects, special files, inaccessible paths, depth exhaustion or incomplete
traversal produce unknown, never a silently excluded success. An interrupted
directory and discovered pending subtrees are retained in the private exclusions
list so an operator can see the unfinished coverage; any exclusion still blocks
a reviewed ledger. Missing roots
retain a checked-parent observation and are checked again, not manufactured.
These observations detect ordinary filesystem changes; they do not establish an
atomic filesystem snapshot or resist an administrator/hostile same-user writer.
The independent legacy-writer exclusion requirement therefore remains essential.

## Ledger and original-lock consumption

`build_review_scope` emits strict `enrollment-review-scope-v2` only for the explicit
v2 scope. It binds the literal scan policy, complete inventory and every traversed
directory's `python_stat` identity. `load_review_scope` rejects policy edits,
unknown keys, impossible counts, incomplete inventory and malformed identities,
even with a recomputed hash. It reconstructs the explicit v2 scope; it cannot
interpret a v1 truncated report as v2. Hashes are consistency checks, not trust.

The existing independently pinned plan digest binds the entire ledger. For path
compatibility, either ledger schema occupies the already fixed private
`reviews/<plan hash>/reviewed-scope-v1.json` slot. That filename does not select
policy: strict validated content does. Existing `ReviewedScope` callers and plan
formats are unchanged. Initializer and pin issuer/loader reload that pinned
ledger and perform an actual full v2 rewalk under their original protections and
locks. No scan cursor or earlier inspection object is accepted as fresh evidence.

Phase comparison subtracts only existing exact-identity, transaction-owned
additions, including created directories, through the existing ownership check.
It does not exempt arbitrary names or staging suffixes. Directory timestamps are
checked within each live scan, not frozen across legitimate transaction writes;
directory identities remain part of ledger comparison. Journal SQL/reservation
checks remain under the original locks and are not replaced with inventory hashes.

## Human source review remains independent

All five default unchecked categories stay unknown until independently reviewed:
historical launch arguments; historical configuration sources; custom roots and
other disks; other accounts; legacy writers. Follow the concrete private-source
checklist in the [fixed entry handoff](2026-10-20-fixed-enrollment-entry.md).
`declared_complete=True` alone, an empty scanned tree, and a successful v2 traversal
are not historical evidence. No new public repository artifact or source reference
format replaces the original operator's review. Raw paths, identities, history and
configuration evidence remain private. All results remain non-authorizing and
production `require_native_enrollment` stays closed.

## Verification boundary

Synthetic tests must include traversal beyond 450 entries, v1 unchanged, pending
and already-scanned directory change, total/depth truncation, redirects/special
files, policy/ledger tampering, nested directory replacement, and fixed initializer
plus independent pin issuance/readback using actual v2 reinspection. Linux results
are not Windows/NTFS acceptance. Product 45-second budgets, existing assertions and
lock order remain unchanged; original-machine acceptance is a separate gate.

## Original Windows CI result and portability correction

The first published tree `67ee12113debc53a1b77a4bd7bebe66593b1ba0d`
(remote HEAD `2e264fd5bcb9dd3253de0a11ece67b36781b5e2c`) is not Windows
accepted. Both original checks attempts ended in failure:
[push](https://github.com/Maximora-byte/swu-happyrun/actions/runs/39451749778)
and [pull request](https://github.com/Maximora-byte/swu-happyrun/actions/runs/39451805912).
The PR event checked synthetic merge `7b18ae0ee921bab745e04eca079085eb8a4711dc`.
No original attempt was rerun or cancelled during diagnosis.

- Push Windows 3.11 main: 17 failed, 2812 passed, 66 skipped, 1 warning,
  6 subtests passed (1370.69 seconds).
- Push Windows 3.13 main: 16 failed, 2813 passed, 66 skipped, 6 warnings,
  6 subtests passed (1408.32 seconds).
- PR Windows 3.11 main: 16 failed, 2813 passed, 66 skipped, 1 warning,
  6 subtests passed (1650.77 seconds).
- PR Windows 3.13 main: 17 failed, 2812 passed, 66 skipped, 6 warnings,
  6 subtests passed (1378.31 seconds).
- Each event's Windows 3.13 pin shards passed all 42 cases. Windows 3.11
  boundary shards passed 23 cases each, but remaining shards suffered fatal
  access violations during diagnostic dumps; these are not passing suites.
- All four Linux jobs passed 2920 tests with 17 conditional skips and 6 subtests.
  Console, Android/optional build/static and container jobs passed. Conditional
  Android runtime steps were skipped, not device acceptance.

The new scanner incorrectly compared `DirEntry.stat(follow_symlinks=False)`
identity/time metadata against fresh `Path.lstat()` observations. Python documents
that Windows `DirEntry.stat()` returns zero `st_ino`, `st_dev` and `st_nlink`, and
caches its result; fresh `os.stat()` is required for those identity attributes.
See [Python 3.13 DirEntry.stat documentation](https://docs.python.org/3.13/library/os.html#os.DirEntry.stat).
Thus valid nested directories were rejected as changed. This is a product
portability defect, separate from the diagnostic crashes. The corrective scanner
must use fresh no-follow path metadata consistently, without removing discovery,
pending-subtree, descent, page or completion comparisons.

Timestamp checks observe only changes visible through the filesystem metadata
API. Windows `st_ctime` can represent creation time, and timestamp visibility or
resolution can delay or conceal a mutation. These checks are not an atomic
snapshot or a substitute for independently excluding concurrent legacy writers.
A page-boundary unit test must make its simulated metadata change visible
explicitly rather than assume that creating a file immediately updates directory
timestamps on every platform; its early-stop assertions must remain intact.
