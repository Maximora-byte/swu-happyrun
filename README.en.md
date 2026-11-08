# SWU HappyRun

[简体中文](README.md) | English

Adaptation project for Southwest University's Budao Lepao, planning a Windows/MuMu execution agent, server scheduling, and root-free vivo compatibility validation.

Latest responsibilities (2026-10-18): **Dot leads all major development; local Codex handles real-world testing and integration acceptance.** The current implementation entry point is [the overnight sprint](docs/handoffs/2026-10-18-dot-lead-sprint.md); this assignment supersedes the older owner columns in the original plans below.

**The current branch inherits the C0 shared protocol library and L0 read-only diagnostics, and fixes recovery state-transition edges, pending review and merge. The server and execution agent are not yet implemented; full compatibility with any Budao Lepao version has not been verified.**

## Local development and probing

```powershell
uv sync --all-extras --frozen
uv run --no-sync python -m pytest -q
uv run --no-sync python scripts/export_schema.py --check
uv run --no-sync python -m swu_happyrun.drivers.mumu.discovery --json --index 0
```

Diagnostic exit code 2 means an environment condition needs attention, such as an instance that is not running or a disconnected device. This command only reads information. See the [compatibility record](docs/compatibility.md) for detailed behavior and local evidence. The unified CLI is scheduled for L2.

## Development entry points

- [Design assessment and revisions](docs/design-review.md)
- [Overall development plan for both ends](docs/superpowers/plans/2026-10-18-development.md)
- [Server implementation plan: cloud Dot](docs/superpowers/plans/2026-10-18-server.md)
- [Execution-side implementation plan: local Codex](docs/superpowers/plans/2026-10-18-agent.md)
- [Control-plane interface contract v1](docs/contracts/control-plane-v1.md)
- [Full design specification](docs/superpowers/specs/2026-10-18-swu-happyrun-design.md)
- [Current collaboration status](docs/status.md)
- [Dot handoff](docs/handoffs/dot-server.md)
- [GitHub development tasks](https://github.com/Maximora-byte/swu-happyrun/issues)

## Responsibilities

| Work | Owner | Primary directories |
| --- | --- | --- |
| Shared contracts, core logic, CLI, and implementation tests | Dot develops; local Codex independently verifies | `contracts/`, `src/swu_happyrun/core/`, `tests/contracts/` |
| Windows/MuMu, ADB, and execution agent | Dot develops; local Codex tests on devices | `src/swu_happyrun/agent/`, `src/swu_happyrun/drivers/`, `tests/agent/` |
| Service API, database, leases, scheduling, and container configuration | ChatGPT Dot in the Matrix group | `src/swu_happyrun/server/`, `tests/server/`, `deploy/` |

These source directories are planned ownership boundaries and are not yet implemented. Both parties use independent branches and PRs; GitHub Issues track task status, while Matrix is used for notifications and clarification. Successful message delivery, Dot's acceptance of a task, code submission, passing tests, and device acceptance are recorded separately.

Eleven development/handoff tasks have been created. In this round, only the Dot handoff package was prepared, as selected by the user. No Matrix kickoff message has been sent, and cloud development has not started.

## Compatibility and data

The known user environment is a root-free vivo X200 Pro and a MuMu 6.8.4.0 / Android 15 instance on Windows. Campus, current school rules, Lepao version, and actual routes must be collected during initial onboarding.

The first server version schedules online device agents; device-free API-only execution is a separate research track. Emulator route completion, upload prompts, and the final valid record require different acceptance evidence. This repository does not provide fabricated school IDs, check-in points, or “100% success” promises.

Account sessions, device screenshots, raw routes, and databases belong in Git-ignored local directories. See [third-party sources](THIRD_PARTY_NOTICES.md) for reference projects and reuse boundaries.

---

This is an English translation of the Chinese README, preserving its stated project snapshot. Consult [current collaboration status](docs/status.md) for newer development evidence. Linked documents may still be in Chinese; this README does not imply that runtime interfaces or all project documentation have been localized.
