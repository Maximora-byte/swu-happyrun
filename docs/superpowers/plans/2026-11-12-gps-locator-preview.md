# GPS Locator Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an offline route export and read-only compatibility inspection, without enabling device execution.
**Architecture:** Standalone optional adapter consumed by two CLI subcommands. No core protocol or runtime dependency changes.
**Tech Stack:** Python 3.11+, existing Pydantic/ADB bounded command runner.
**Spec:** ../specs/2026-11-12-gps-locator-preview.md

## Global Constraints
Preserve MuMu defaults. No location-write, permissions, install, account or school actions. Source revision and CRS must be checked. Status is app-reported only.

## Review Focus
- Malformed, duplicate, oversized status: fail closed with no raw output.
- Serial all/list/shell injection: reject before command.
- Non-finite speed, stale revision, degenerate coordinates: no export.
- Existing output: never overwrite private data.
- App readiness flags must never turn into location or record acceptance.

### Task 1: Adapter and CLI
Files: src/swu_happyrun/drivers/gps_locator.py, src/swu_happyrun/cli.py; tests/drivers/test_gps_locator.py.
Interfaces: export_route(route: RouteProfile, speed_mps: float) -> dict; inspect(adb: Path, serial: str) -> dict.
- [x] Write failing validation, export, status and CLI tests; verify failure.
- [x] Implement offline adapter and only the two explicit CLI subcommands.
- [ ] Run targeted tests, contracts, lint, then full pytest; record limitations.
- [x] Add Chinese tutorial, license/source notices, and independent review fixes.
- [ ] Commit and publish a Draft PR; verify remote exact HEAD/CI separately.
