# Issue 110 bounded native capture contract

**Goal:** Capture bounded, process-local terminal AV metadata without altering the original tests or treating diagnostic success as a repair.

**Architecture:** An isolated exact-branch push workflow checks out the fixed subject separately from its supervisor. Two independent Windows jobs verify installed CDB and their harness before one exact 12-node group each. Only allowlisted JSON leaves the runner.

**Tech Stack:** CPython 3.11.16 standard library, installed Microsoft CDB, Windows Job Objects, GitHub Actions.

**Spec:** https://github.com/Maximora-byte/swu-happyrun/issues/110#issuecomment-6306172759

**Independent per-job gate clarification:** https://github.com/Maximora-byte/swu-happyrun/issues/110#issuecomment-6306308281

## Fixed boundaries

- Subject 6a0dac84bf66125c7e2bd506bb0d8c988b1dcc34 / tree 09b5064a5e30495f7ced68b84fe453bd5d0413ce. Exact group arrays from issue 110, never regenerated.
- Each group once, 1800 seconds including capture, independent job ceiling 40 minutes, setup/preflight/smoke at most 5 minutes, aggregate at most 5 minutes. No automatic retries or workflow reruns.
- Installed verified x64 CDB only; no installation, network symbols, dump, WER/AeDebug/registry changes, devices or original-machine execution.
- Preserve 60-second reporter, product deadlines and true native exit. Terminal second-chance AV is not proof of earliest fault or root cause.
- No publication or actual diagnostic run until independent review and final scope check.

## Tasks

- [x] Add failing manifest, parser, command, environment, budget and workflow tests.
- [x] Implement fixed supervisor and Win32 process containment with retained child handle.
- [x] Implement bounded synthetic Windows verification: exits 0/7, reporter plus AV, timeout/descendant cleanup, environment canary.
- [x] Add exact-branch-only workflow and operator notes, with explicit prerequisites and no raw artifacts.
- [x] Run focused Linux-compatible controller tests and Ruff. These are not Windows native validation or a product-suite result.
- [ ] Independent final review and scope check before publication.
- [ ] Each Windows job must pass its own focused controller tests and all native synthetic smoke checks before its original group. No automatic repair or retry if either gate fails.

The only execution trigger is the initial reviewed push of diagnostics/issue110-native-capture. Verify every existing workflow excludes that branch. Publishing remains unauthorized until independent review and final scope check. Do not dispatch a second push or rerun this batch.

## Operator boundaries and evidence

- The workflow contains two parallel jobs, not two sequential attempts. Each has a 40-minute ceiling including at most 300 seconds of setup/preflight/smoke, one original group with a 1800-second supervisor deadline including capture, and finalization. The aggregate job has a five-minute ceiling. The nominal wall-clock ceiling is 45 minutes after both runners start, excluding GitHub scheduling queues. A failed prerequisite stops only that job's original group.
- Both jobs check out the unchanged subject separately from this harness. The manifest byte hash is 1b34864118722925ceeccf46a79cebf0325e8ccc0cf848f750144524ed9e023f. Fixed original order and reporter options are not configurable. A per-job exclusive consumption marker is written before launch, even if launch subsequently fails.
- Required debugger files are the already installed Windows Kits/10/Debuggers/x64 cdb.exe, dbgeng.dll and dbghelp.dll. All must be AMD64 PE files and pass Microsoft's Authenticode verification with a Microsoft Corporation signer. No installer, execution-policy override, elevation, debug privilege, network symbol source, dump or global crash configuration is used. Missing binaries, policy/API denial, invalid signature, unsupported command syntax or incomplete synthetic capture are blockers, not reasons for fallback or repetition.
- The pinned setup-uv installs CPython 3.11.16. Frozen extras are exported from the pinned lock and installed into its disposable direct base interpreter; the project is installed editable without dependency resolution so distribution metadata remains present. The native gate requires sys.prefix == sys.base_prefix and exact Python PID agreement. This is deliberately not the original venv-launcher topology and is not proof of a matching original interpreter distribution/build. The report records executable/DLL hashes and build metadata. Any finding retains this confound.
- CDB launches suspended and is assigned to an unnamed kill-on-close Job Object before resume. At the initial debugger stop the supervisor retains a handle to the exact target PID before sending g. All AV continuation is gn, never gh. Natural child status is sampled before cleanup and never replaced with CDB's exit or an injected timeout termination code. Unverified cleanup fails the harness even if the test returned zero. Only owned processes are terminated.
- Native smoke is mandatory: ordinary exits 0/7, exact Python PID plus stdout/stderr and secret-canary exclusion, the unchanged 60-second faulthandler reporter followed by a genuine null-read AV, and timeout cleanup of an owned descendant. Focused malformed-output and fake-API negative tests also run on Windows before smoke. These all share the same 300-second setup deadline; syntax or prerequisite failure consumes no original group.
- The capture script selects terminal second-chance AV and bounds capture to ten seconds within the group deadline. It emits exception metadata, knL and lm into local transient output. Only strict, unique, PID-matched numeric fields and module-relative frames enter JSON. There are no locals, parameters, symbol names, raw stack memory or source paths in the artifact. Without matched private symbols, module plus offset is the limit of attribution.
- No earliest first-chance context is captured. The terminal AV could be a secondary failure while faulthandler is reporting an earlier fault. It does not establish the original fault or root cause. The debugger still changes scheduling despite -hd; a no-crash run is only a debugger-attached observation, never a repair or a green retry target.
- The debuggee and CDB receive only a Windows environment allowlist and disposable profile/temp paths, not GitHub credentials, inherited symbol paths or arbitrary parent variables. Raw debugger/test output, setup logs and local JUnit remain on the disposable runner and are never uploaded. GitHub artifacts are not a private dump vault: only sanitized group JSON is uploaded, with one-day retention and repository-reader visibility. No dump is created.
- Existing Android, MuMu, checks and container workflows exclude this branch on push. Do not open a PR merely to execute the diagnostic, since existing PR triggers have different scope. Do not delete/recreate the branch or rerun jobs to obtain another original invocation. Stop after the two scoped observations or their prerequisite failures and review evidence first.

## Reference

The terminal script uses the documented no-command-echo $$>a< form: https://learn.microsoft.com/en-us/windows-hardware/drivers/debuggercmds/-----------------------a---run-script-file-. Actual installed-CDB syntax and native behavior must still pass the runner smoke gate.

## Local validation record

31 focused controller tests passed on Linux, both with the normal repository configuration and the isolated configuration used by the Windows gate. Ruff check and format passed. Independent review also exercised eight fake-API lifecycle cases; 2,000 deterministic malformed parser mutations returned without exceptions. The original product source, tests, lockfile and existing workflows are unchanged. This is not evidence that the Windows native gate or either original group has run.
