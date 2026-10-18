# SWU HappyRun agent instructions

Read `docs/status.md`, the design, the control-plane contract, and your assigned implementation plan before editing.

## Ownership and collaboration

- Local Codex owns shared contract changes, `core/`, `agent/`, `drivers/`, the CLI, Windows verification, and integration review.
- Cloud ChatGPT Dot owns `server/`, `tests/server/`, and `deploy/`. Work on `dot/server-*` branches and open a PR. Local work uses `codex/*` branches.
- Do not commit to another worker's branch. Coordinate changes to `pyproject.toml`, dependency locks, shared models, or CI in the associated issue before editing them.
- A server PR can be reviewed and tested with fake devices. It must not claim MuMu, vivo, or accepted running-record verification.
- GitHub is the source of truth for code and task status. Matrix notifications carry issue/PR URLs and commit SHAs, never credentials or raw device data.
- Do not substitute OpenClaw or Hermes for the user-requested ChatGPT Dot without the user's direction.

## Implementation requirements

- Python 3.11+, package `swu_happyrun`, CLI `swu-happyrun`, API prefix `/api/v1`, protocol major version `1`.
- Use the exact models and state transitions in `docs/contracts/control-plane-v1.md`; incompatible changes require a contract PR first.
- Persist intent before device side effects. Never automatically start a second run after an ambiguous start/upload or a lease loss.
- `needs_attention` is resumable, not a terminal state. A remote cancellation becomes final only after a stop acknowledgment when a device may be active.
- Never convert an unknown device capability into a successful check. No guessed campus coordinates, school IDs, app selectors, or API signatures.
- Keep runtime dependencies optional by component; the server must run without Windows/MuMu dependencies.
- Never weaken TLS, device security, or system protections to make a check pass. Do not change Root settings as part of installation.
- Account data, tokens, raw screenshots, routes, and databases stay outside version control. Redact test fixtures before committing them.

## Verification and PRs

- Add tests for contracts, state changes, recovery, ownership, timeouts, and meaningful edge cases. Record the command, exit result, platform, and tested commit.
- Run the component's checks and the shared contract suite. Use a fake clock for lease/schedule tests and a fake driver for protocol tests.
- Live device checks must identify MuMu/Android/app versions and distinguish device observations from server-side record acceptance.
- Hosted CI errors or inability to run CI are external blocks, not passing checks. Provide local results separately.
- PR descriptions state the behavior, scope, evidence, and unverified paths. Merge only after reviewing the immutable head, relevant tests, and contract compatibility.
- Production hosting, DNS, and existing server changes are outside the initial repository setup. Deliver deployment files first.
