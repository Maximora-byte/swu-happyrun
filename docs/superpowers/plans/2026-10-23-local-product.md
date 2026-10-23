# Local HappyRun product delivery

> **For agentic workers:** Use superpowers:executing-plans. The human authorized local implementation and testing on 2026-10-23 and selected finishing the local product before Budao login. Continue without intermediate approval gates.

**Goal:** Deliver an installable local workstation with one-command startup, a usable Chinese simulation workflow, persistent jobs, cancellation and recovery, plus an Android application checked in the dedicated MuMu QA instance.

**Architecture:** Reuse protocol v1, the existing SQLite server, AgentRunner and FakeDriver. A separate loopback-only desktop factory adds a local browser session and a narrowly scoped synthetic workspace; the normal server and ADMIN/AGENT authentication stay intact. No desktop operation can register physical capabilities or invoke native MuMu writes.

**Tech Stack:** Existing locked Python 3.11+ dependencies; Python 3.13 for this Windows delivery; FastAPI, HTTPX, Java/Android API35, MuMu 6.8.4.0.

**Spec:** Existing 2026-10-18 design, control-plane-v1 and 2026-10-20 virtual-run plan. New human direction supersedes Dot-only implementation ownership for this local branch. The user has no logged-in Budao session; school-record acceptance is deferred explicitly.

## Global constraints

- Preserve exact protocol models, persistence-before-effects, leases, cancellation acknowledgment and uncertainty.
- Local simulation is named explicitly. Unknown native enrollment, position acknowledgment and stop semantics remain blocked.
- Use a dedicated workspace with synthetic profiles. Never adopt or clear existing MuMu journals or reservations.
- Bind desktop to 127.0.0.1 only. Random per-launch credentials remain in process memory. Browser session uses an HttpOnly, SameSite=Strict cookie and a one-use bootstrap nonce; no ADMIN token in URLs, storage, assets or logs.
- Desktop mutations require the exact loopback Host and Origin. Existing server API still requires bearer authentication.
- No Root, TLS, system protection, production or DNS changes. Private screenshots, artifacts and databases remain outside Git.

## Review focus

1. Cross-origin requests and DNS rebinding must not create a session or mutate jobs.
2. Refreshing or restarting must preserve jobs without silently restarting uncertain work.
3. Duplicate create requests must replay one job; changed requests with the same key conflict.
4. A desktop request cannot select a physical device/profile, supply a route URL or claim a valid school record.
5. Worker failure and shutdown must be visible; cancellation cannot be reported final before acknowledgment.

## Task 1: Persistent synthetic workspace and desktop factory

**Files:** New `src/swu_happyrun/desktop/{workspace,app,worker}.py`, `tests/desktop/test_workspace.py`, `tests/desktop/test_app.py`.

**Interfaces:** `Workspace.open(root: Path) -> Workspace`; `.job_spec(now) -> JobSpec`; `create_desktop_app(workspace, *, port: int)` returns the existing FastAPI application extended only at `/desktop/` and `/api/v1/desktop/*`.

- [ ] Write and run failing tests for restart identity preservation, corrupt state rejection, one-use bootstrap, origin/host rejection, cookie attributes, simulation-only creation, idempotency and inaccessible bearer APIs.
- [ ] Implement the workspace and factory, calling the original store and models.
- [ ] Implement one cooperative background fake worker using the original ControlClient/AgentRunner/RunJournal; do not auto-resume attention states.
- [ ] Run desktop and contract tests, plus actual loopback HTTP completion/cancel/restart coverage.

## Task 2: One-command UI and launcher

**Files:** New packaged desktop HTML/CSS/JS and `desktop/__main__.py`; modify CLI, add Windows launcher and installation documentation.

**Interfaces:** `swu-happyrun desktop [--data-dir PATH] [--port PORT] [--no-browser]`; default port 8765; bind host fixed to 127.0.0.1. UI can create one synthetic job, view progress/history, cancel, and explicitly request stop-only recovery.

- [ ] Add failing CLI dispatch/invalid-port tests.
- [ ] Implement the launcher; open the bootstrap URL only after successful listening. Keep nonce out of terminal output and access logs.
- [ ] Browser-test real desktop flow, refresh, duplicate clicks, cancellation and phone-sized layout; inspect screenshots.

## Task 3: Freeze, install and real MuMu local acceptance

**Files:** Delivery script, artifact README and `docs/qa/2026-10-23-local-product.md`.

- [ ] Build wheel and ordinary Android app/test pair from the frozen source; record source/tree, hashes and tool versions.
- [ ] Install wheel in a fresh environment and exercise the installed desktop outside source.
- [ ] In existing HappyRun QA MuMu instance 1, verify exact APK/signatures and run local simulation, interruption/restart and controlled stop; save private evidence.
- [ ] Run required schema/lint/build/install checks and the complete Python suite with bounded execution. Preserve failures and platform skips separately.
- [ ] Obtain one fresh whole-branch review, fix important findings, publish a focused draft integration PR and provide the usable artifacts with exact limitations.

## Progress ledger

- Baseline: `6a0dac84bf66125c7e2bd506bb0d8c988b1dcc34`; clean isolated managed worktree, own `codex/tonight-delivery-20261023` branch.
- Ruling: Existing Python 3.11 native crash remains open; use 3.13 for this delivery, without calling that a fix.
- Ruling: Local product scope follows the user's explicit reply; Budao login/school rules/record acceptance are deferred, native virtual input is still a separate unaccepted path.
- Preparation: First baseline command referenced nonexistent `tests/core`, collected no tests; corrected to actual contracts/server/integration directories.
