# SWU HappyRun

[简体中文](README.md) | English

Adaptation project for Southwest University's Budao Lepao, planning a Windows/MuMu execution agent, server scheduling, and root-free vivo compatibility validation.

**Current development and acceptance entry point: [collaboration status](docs/status.md).** It records merged work, product candidates, independent acceptance, and remaining blockers by date and exact commit. Before adopting a candidate, verify its actual HEAD and corresponding acceptance report.

Current responsibilities: **Dot leads all major development; local Codex handles real-world testing and integration acceptance.** The [2026-10-18 sprint handoff](docs/handoffs/2026-10-18-dot-lead-sprint.md) is retained as historical context; this assignment supersedes the older owner columns in the original plans.

- **Implemented on main:** C0/C1 shared contracts, core models and state logic, plus L0 read-only MuMu/ADB diagnostics and their tests. C0/L0 and C1 have been merged into main.
- **Product candidates awaiting integration:** Server, execution agent, unified CLI, web, and Android product implementations have candidates and scoped acceptance records, but have not been merged into main. Passing software tests and candidate builds does not mean the complete product has been delivered.
- **Device and school acceptance remain incomplete:** Installation, read-only observations, and synthetic workflows each have limited evidence scopes. They do not establish successful real MuMu execution, root-free vivo compatibility, or final school-accepted records. Full compatibility with any Budao Lepao version has not been verified.

## Local development and probing

```powershell
uv sync --all-extras --frozen
uv run --no-sync python -m pytest -q
uv run --no-sync python scripts/export_schema.py --check
uv run --no-sync python -m swu_happyrun.drivers.mumu.discovery --json --index 0
```

Diagnostic exit code 2 means an environment condition needs attention, such as an instance that is not running or a disconnected device. This command only reads information. See the [compatibility record](docs/compatibility.md) for detailed behavior and local evidence. main has no unified CLI entry point yet; see [collaboration status](docs/status.md) for L2 candidate progress and acceptance scope.

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
| Service API, database, leases, scheduling, and container configuration | Dot develops; local Codex independently verifies | `src/swu_happyrun/server/`, `tests/server/`, `deploy/` |

These are component ownership boundaries, not a claim that every directory is already on main. main includes `contracts/`, `core/`, `drivers/`, and their tests; `agent/`, `server/`, `tests/server/`, and `deploy/` belong to product candidates awaiting integration. Both parties use independent branches and PRs, with progress recorded in GitHub Issues/PRs and [collaboration status](docs/status.md). Message delivery, code submission, software testing, device acceptance, and school-record acceptance are recorded separately. Early handoff packages or notification status do not determine whether development has started.

## Compatibility and data

The known user environment is a root-free vivo X200 Pro and a MuMu 6.8.4.0 / Android 15 instance on Windows. The status page records some map inputs and installation and pre-login observations of Budao Lepao 4.3.1(231). Official school rules, the user's actual app pages/records, and real adaptation acceptance still have gaps; see [collaboration status](docs/status.md).

The server design delegates task execution to online device agents, with the related product implementation still in candidates; device-free API-only execution is a separate research track. Emulator route completion, upload prompts, and the final valid record require different acceptance evidence. This repository does not provide fabricated school IDs, check-in points, or “100% success” promises.

Account sessions, device screenshots, raw routes, and databases belong in Git-ignored local directories. See [third-party sources](THIRD_PARTY_NOTICES.md) for reference projects and reuse boundaries.

---

This English README follows the Chinese README's implementation and acceptance boundaries. Consult [current collaboration status](docs/status.md) for dated development evidence and verify the relevant candidate HEAD before use. Linked documents may still be in Chinese; this README does not imply that runtime interfaces or all project documentation have been localized.
