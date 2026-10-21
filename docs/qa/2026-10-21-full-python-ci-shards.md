# Finite full Python CI coverage

Contract registered before editing in [#100](https://github.com/Maximora-byte/swu-happyrun/issues/100#issuecomment-6306133895).
Source baseline: `6a0dac84bf66125c7e2bd506bb0d8c988b1dcc34`, tree
`09b5064a5e30495f7ced68b84fe453bd5d0413ce`.

## Scope and budgets

- Each Windows/Python 3.11 and 3.13 job collects the actual entire `tests` tree
  using its own interpreter and frozen dependencies. It preserves collection
  order, selects `nodes[index::6]`, and runs one of six independent shards.
  `fail-fast: false`, maximum four concurrent shard jobs, 30-minute job limit,
  and 1,500-second pytest child limit bound cost. There are no automatic retries.
- Linux still runs the whole Python suite once per interpreter, not a subset.
  Its original 15-minute job limit remains, with a 750-second child limit to
  leave time for packaging and evidence. Windows lint/schema/build/install
  checks remain in the existing platform matrix.
- The direct child still uses `python -m pytest tests -vv
  -o faulthandler_timeout=60 --durations=20`. Neither product deadlines,
  assertions, dependencies, system permissions nor native QA gates change.
  Plugin arguments apply only to that child; nested pytest tests do not inherit
  plugin activation through environment variables.
- On child timeout the runner kills and waits for its direct pytest child only.
  This is not process-tree cancellation. The isolated hosted job's finite limit
  and runner cleanup remain responsible for any orphaned test descendants.

## Evidence and completeness gate

Before the first test, each shard stores its full ordered collection and selected
nodes, exact source HEAD/tree, frozen lock hash, OS, full Python/pytest versions,
run ID and attempt. Duplicate/empty collections, hidden selectors, changed
collection order, collection errors and dirty/wrong-SHA checkouts refuse execution.
No universal platform-independent node count is assumed.

Flushed JSONL records distinguish node start, setup/call/teardown reports,
pytest 9 built-in subtest reports, and node completion. A normal session receipt
and direct process return code are also required. A child exiting zero without
completing pytest is not success. Setup skips, xfails and non-strict xpasses are
reported separately from passed assertions. Subtest outcomes have their own four
`subtest_*` counters, never inflating or hiding within the parent node totals;
strict xpasses, any failed phase,
and failed subtests fail. Ordinary duplicate phases remain invalid.

The always-running five-minute aggregate downloads only this SHA/run attempt's
artifacts. Required identity fields are typed, the full Python version must match
its minor, and SHA/tree/lock hash must match the aggregate’s own clean checkout,
not only other receipts. It requires both prerequisite matrix job groups to succeed, every
expected OS/Python/shard exactly once, matching source/interpreter/ordered full
collection within each OS/Python, the deterministic selection in every shard,
and the full union exactly once. Every selected node must have its complete
ordered lifecycle. Missing artifacts, missing phases, unknown/duplicate nodes,
crashes, timeouts, cancellation and nonzero exits cannot become a green gate.
Raw fixture contents are not added to manifest/event receipts. JUnit and normal
CI logs remain diagnostic evidence; artifacts expire after seven days.

## Load evidence and limits

The baseline Linux/Python 3.12 collection contains 2,988 distinct nodes. Its six
partitions each contain 498 nodes: runtime 6, pin 7, and other 485. This is a
partition arithmetic check, not a Windows/Python 3.11 or 3.13 manifest.

Baseline [#109 PR CI](https://github.com/Maximora-byte/swu-happyrun/actions/runs/39464897709)
Windows main jobs collected 2,946 non-pin nodes but stopped near 30 minutes after
about 590 terminal outcomes. Successful separate pin groups of 23 and 19 took
1,076.92 and 1,030.29 seconds. Spreading the complete suite avoids concentrating
all runtime nodes in one already-long job, without a filename allowlist.
Actual target-platform load and receipts still require running this exact new
candidate. A budget overrun is a failure to investigate, not permission to drop
nodes or extend product deadlines.

This change repairs CI coverage accounting and scheduling only. It does not
identify or fix the interpreter access violations in [#110](https://github.com/Maximora-byte/swu-happyrun/issues/110),
replace original failure evidence, authorize native devices, or authorize a merge.
