# Issue 110 Disabled Probe Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement testable trusted-loading, one-shot host supervision and private-result contracts without enabling or executing the native probe.

**Architecture:** An independent standard-library Python parent prepares a pinned private bundle and supervises one C++ host. The existing portable experiment remains the experiment authority; a new loader supplies its factory only through a verified module owner. Results cross a bounded private capsule, never through public stdout forwarding.

**Tech Stack:** Python 3.11+, standard library; C++17; official Windows SDK/DbgEng declarations; existing pytest/Ruff and portable g++ tests. No new runtime dependency, installation, user-computer action or native engine execution.

**Spec:** `docs/superpowers/specs/2026-10-23-issue110-probe-integration-design.md`, approved commit `1b7ce7250d037878225d388c010f9338c92c22d6`, tree `5707206ba1a2340accd2aa5585d1fa758e091f7a`, spec SHA256 `96030fa683ee9c15dc6308ae6552750267e94d08ef5df3c82684e699b61ad61b`. Read the approved bytes, not the later unapproved draft. The strict deadline tests below elaborate that contract; they do not replace its text.

## Global Constraints

- C++ main and new Python main remain unconditionally blocked. No argument, environment variable or build switch enables them; no CI/workflow changes or real native runs.
- Keep `issue110_win32.Session`, original tool pins, fixed experiment commands, no-target gates, A/B stability rejection and the five workflows unchanged.
- Public `passed=false`, `execution_ready=false`, `display_comparison=format_unknown` always; software completion is not AV remediation or native acceptance.
- Shared `D = monotonic_start + 300s`; one installed-location three-file V6 signature deadline `S = min(D, stage_start+30s)`; require a full 15-second host window; `H = min(D, now+15s)` starts before process creation. All cleanup shares one `C = now+5s`.
- Acceptance requires `now < H` for host observation and `now < D` for final projection. Equal/late success retains observed facts but cannot become complete. Cleanup/saving never restarts work or resets these deadlines.
- `issue110-filter-probe-1` is the sole new experiment child. Existing/uncertain reservation means stop: no retry, alternate name, adoption, overwrite, deletion, ACL repair or automatic retention action.
- Use official JOB_LIST at creation, restricted HANDLE_LIST, suspended absolute EXE, one resume, fresh unnamed kill-on-close Job, active-process-limit=1; unsupported means blocked without fallback.
- Capsule parsing rejects above 256 KiB; stdout/stderr detection thresholds are 64 KiB each. `disk_hard_cap=false`; monitored budgets are not OS hard-wall guarantees.
- Trust pinned Microsoft code and current Windows, not a complete dynamic-DLL sandbox. No claim that post-load enumeration prevents DllMain or observes transient modules.
- New EXE build identity, exact dependency evidence and Windows API behavior remain unverified until actual later review. Do not invent a positive manifest, reuse the old EXE hash, or weaken unknown branches to make tests green.
- Commit checkpoints are local implementation steps after execution-method approval. Push, publication and runtime authorization are separate; this plan itself changes no code.

## Review Focus

1. A signed source changes or a staged copy aliases another file: reject before child creation, keep read-only pins throughout (Task 3, `test_source_identity_changes_before_copy`).
2. A process-creation call fails ambiguously, or resume loses its reply: no second invocation; preserve null host/engine facts and owned handles (Task 4, `test_ambiguous_create_and_resume_never_retry`).
3. A valid capsule arrives exactly at a deadline after exit 0: retain facts but reject completeness, never grant more time (Tasks 1/4, `test_valid_capsule_at_deadline_is_not_complete`).
4. Cleanup throws during an original cancellation or write failure: preserve the primary error, do not claim all handles closed (Tasks 3/4, `test_primary_cancel_survives_cleanup_exception`).
5. A correct-looking child document contains duplicate keys, boolean integers or raw private canaries: reject structural ambiguity and rebuild the public allowlist (Task 1, `test_duplicate_bool_and_private_canary`).

## Files and interfaces

All new Python files live in `scripts/diagnostics/`; matching tests in `tests/delivery/`. Keep responsibilities small:

- `issue110_filter_contract.py`: immutable dataclasses, request/capsule validation, public projection, no native calls.
- `issue110_filter_pe.py`: bounded PE metadata parsing and evidence-based dependency admission, no DLL loading.
- `issue110_filter_bundle.py`: reviewed-build binding, exact source/stage pins, reservation and one V6 phase.
- `issue110_filter_supervisor.py`: fakeable monotonic state machine and a blocked `main()`.
- `issue110_filter_host_win32.py`: official Win32 file-pin/job/process/handle-list backend, no DbgEng COM.
- `issue110_filter_loader.hpp` and `.cpp`: verified module ownership and official native loader binding, not a public entry.
- `issue110_filter_capsule.hpp`: bounded portable C++ private-capsule encoder.
- Modify `issue110_filter_command_probe.cpp` only for the verified-loader factory boundary and internal serialization; keep `main()` closed and core experiment bytes unchanged.
- Modify `issue110_local_acl.py` only for an explicit new child role; update exact helper hashes in `issue110_debugger_config_local.py` and `issue110_prepare_private_root.py` if required, with no behavior changes there.
- New handoff: `docs/handoffs/2026-10-23-issue110-filter-integration.md` with actual tested identities and remaining blocks. Do not create an accepted build manifest before a new real build.

Use existing diagnostic import/test conventions. Python types shared across tasks are defined in Task 1, not duplicated. Native-specific structures stay behind `HostAPI`/`BundleAPI` or the C++ loader seam; tests never instantiate the Windows backend on Linux.

### Task 1: Freeze the private protocol and conservative public projection

**Files:** Create `scripts/diagnostics/issue110_filter_contract.py`, `scripts/diagnostics/issue110_filter_capsule.hpp`, `tests/delivery/test_issue110_filter_contract.py`, `tests/delivery/issue110_filter_capsule_test.cpp`.

**Interfaces:** Define the C++ `CapsuleInput`, bounded `ByteSink` (`append(const char*, size_t) -> bool`) and `EncodeResult` (`complete`, `bytes_written`, fixed `error` enum) in the new capsule header. Define frozen `ReviewedBuild` (manifest digest, EXE digest, source digests, x64/toolchain/header/protocol evidence), `FileIdentity` (volume plus file ID), `CapsuleContext` (nonce, child PID), `ChildReceipt`, and `HostObservation`. `HostObservation` separates create/resume intent and result, host/engine attempted, natural pre-cleanup exit, signature/host cleanup, result validity, deadline rejection and completeness. Define `parse_capsule(data: bytes, context: CapsuleContext) -> ChildReceipt`, `public_projection(observation: HostObservation) -> dict`, and C++ `encode_capsule(const CapsuleInput&, ByteSink&) -> EncodeResult`.

- [ ] Write failing protocol tests. Fix framing to `SWU110FP1\n`, eight lowercase hex length digits plus `\n`, exact UTF-8 JSON body, then `\nSWU110END\n`; total including framing must be <=262144 bytes. Use independently written Python/C++ golden fixtures, not one encoder as the other's oracle. Assert getter hex lengths <=4096 decoded bytes each and sx <=65536; invalid getters cannot serialize untouched sentinel tails.
- [ ] Add named tests `test_duplicate_bool_and_private_canary` and `test_valid_capsule_at_deadline_is_not_complete`: duplicate/unknown/missing keys, NaN, booleans in integer fields, wrong nonce/PID, malformed hex/UTF-8, trailing bytes, incomplete footer and lengths 262143/262144/262145. Assert no raw/path/nonce/PID/HRESULT-trace canary appears in public JSON; all three fixed public acceptance fields remain conservative.
- [ ] Run `python -B -m pytest -q tests/delivery/test_issue110_filter_contract.py`; record missing-module/behavior RED. The Python test compiles/runs the portable C++ harness with `g++ -std=c++17 -Wall -Wextra -Werror -pedantic` and never links DbgEng.
- [ ] Implement only those types, strict parser/encoder and projection. Use exact JSON types and explicit field sets; distinguish missing unknowns from false. No dynamic paths or target/script strings in request. Record only bounded confirmed bytes, not full scratch arrays.
- [ ] Re-run the same command to GREEN; record platform/compiler and count. Locally commit the four files as `feat: define private filter probe result contract`.

### Task 2: Admit only independently evidenced PE dependencies

**Files:** Create `scripts/diagnostics/issue110_filter_pe.py`, `tests/delivery/test_issue110_filter_pe.py`.

**Interfaces:** `inspect_pe(data: bytes) -> PeFacts`; `admit_dependencies(facts: tuple[PeFacts, ...], evidence: DependencyEvidence) -> DependencyDecision`. Define these immutable types here: facts include x64, import/delay-import names, manifest/resource and redirection requirements; evidence contains exact reviewed file identities and observed system/API-set/KnownDLL mapping. Empty/unverified evidence cannot return admitted.

- [ ] Write RED fixtures for out-of-bounds/overlapping RVA tables, unterminated names, PE32 instead of x64 PE32+, delay imports, embedded/adjacent manifest and `.local` requirements; assert `admitted is False` for every unknown mapping and path-like DLL name. Fixture bytes are synthetic and contain no machine data.
- [ ] Run `python -B -m pytest -q tests/delivery/test_issue110_filter_pe.py` and preserve RED.
- [ ] Implement bounded parsing with standard-library `struct`, explicit bounds and no loader calls. Do not infer “system” from a basename or API-set prefix alone. Admission consumes separate exact evidence; positive tests use clearly labeled synthetic evidence, not a production allowlist.
- [ ] Re-run to GREEN; locally commit as `feat: reject unproven filter host dependency graphs`. Record that no real dependency closure has yet been accepted.

### Task 3: Prepare a one-shot pinned bundle without changing legacy callers

**Files:** Create `scripts/diagnostics/issue110_filter_bundle.py`, `tests/delivery/test_issue110_filter_bundle.py`; modify `issue110_local_acl.py`, its existing tests, and only necessary old helper-pin literals.

**Interfaces:** `prepare_bundle(reviewed_build: ReviewedBuild, private_root: str, deadline: float, api: BundleAPI) -> PinnedBundle`. `PinnedBundle` is a context-managed owner of root/child/file handles and immutable stage identities, not freely constructible user authorization. `BundleAPI` exposes monotonic time, strict ACL role validation, exclusive reservation/writes/copies, read-shared-only file pin/hash, fixed installed V6 verification, identity/revalidation and close. No process-host creation method is present.

- [ ] Add RED tests proving default old child/ACL behavior unchanged; new explicit `filter_probe` role chooses only `issue110-filter-probe-1` and retains prepared-top-level/NTFS/reparse/DACL checks. Reject an existing child and uncertain create without retry. Assert attempt record is written/flushed before V6 and all writes are exclusive.
- [ ] Add `test_source_identity_changes_before_copy` and `test_primary_cancel_survives_cleanup_exception`; assert changed source/stage identity/hash/version, unknown build manifest or dependencies never returns a bundle. Assert one V6 call shares min(30, remaining), cdb is verified but never copied/launched, stage contains only EXE/dbgeng/dbghelp. Assert source/stage pins deny WRITE/DELETE sharing and remain live to owner close.
- [ ] Run `python -B -m pytest -q tests/delivery/test_issue110_filter_bundle.py tests/delivery/test_issue110_debugger_config_local.py tests/delivery/test_issue110_prepare_private_root.py`; save expected RED without modifying unrelated tests.
- [ ] Implement role selection without mutating global `CHILD`; consume Tasks 1/2 contracts. Use source-V6 plus locked same-byte stage binding, not a second signature stage or an assertion that the old verifier inspected stage. Preserve primary cancellation and unknown close facts; no root provisioning, cleanup deletion or installation.
- [ ] Run the same tests to GREEN; validate exact old helper-pin updates and no other legacy changes; locally commit as `feat: prepare isolated pinned filter host bundles`.

### Task 4: Supervise one host with explicit uncertainty and deadlines

**Files:** Create `scripts/diagnostics/issue110_filter_supervisor.py`, `tests/delivery/test_issue110_filter_supervisor.py`.

**Interfaces:** `observe_once(bundle: PinnedBundle, deadline: float, api: HostAPI) -> HostObservation`. Define `HostAPI` methods for `now`, fresh Job/attribute preparation, exclusive transport handles, `create_suspended`, image identity, `resume_once`, wait/poll/read-length, bounded result read, terminate-owned and close. Use opaque handles returned by the API; never take arbitrary PID for control. `main() -> int` returns blocked without invoking an API.

- [ ] Write RED call-log tests: insufficient full 15 seconds =>no create; JOB_LIST/HANDLE_LIST preflight failure =>no create; CreateProcess-only failure =>attempt recorded, no fallback; wrong image =>zero resume. Assert one fixed EXE, one fresh Job and exactly request-read/result-write/stdout-write/stderr-write inherited handles, no stdin.
- [ ] Add `test_ambiguous_create_and_resume_never_retry`, `test_valid_capsule_at_deadline_is_not_complete`, and `test_primary_cancel_survives_cleanup_exception`. Fake clocks cover just-before/equal/after H/D; cleanup calls all receive the same C, including partial-create failure. Assert exit0, capsule validity and cleanup are separate; forced kill code cannot populate natural exit; no receipt after resume means engine attempted null. File overshoot stops work without claiming a disk hard cap.
- [ ] Run `python -B -m pytest -q tests/delivery/test_issue110_filter_supervisor.py` to RED.
- [ ] Implement the state machine against the fakeable API. Persist intent before creation, sample natural exit before termination, parse only signaled complete results, and rebuild public summary. Blocked main has no flag/env bypass; ordinary close errors preserve an earlier primary error, cancellation remains cancellation.
- [ ] Run to GREEN and add blocked-main subprocess tests with hostile flags/environment. Locally commit as `feat: supervise a single closed filter host attempt`.

### Task 5: Bind the native APIs without enabling an entry

**Files:** Create `scripts/diagnostics/issue110_filter_host_win32.py`, `scripts/diagnostics/issue110_filter_loader.hpp`, `scripts/diagnostics/issue110_filter_loader.cpp`, `tests/delivery/test_issue110_filter_native_bindings.py`, `tests/delivery/issue110_filter_loader_test.cpp`; modify `issue110_filter_command_probe.cpp` and its source-contract tests.

**Interfaces:** `WindowsHostAPI`/`WindowsBundleAPI` implement the previous narrow seams with official declarations and pointer-sized structures. C++ `load_verified_engine(const StageEvidence&, LoaderAPI&) -> LoadAttempt` owns a move-only `VerifiedEngineModule`; only that owner can supply DebugCreate to `make_verified_source_adapter(VerifiedEngineModule&)`. `LoaderAPI` is a non-entry test seam for identity/search/load/enumeration, not a user-supplied arbitrary factory. `StageEvidence` binds current EXE and exact fixed DLL identities from the private request.

- [ ] Write RED portable loader tests: missing/unknown evidence, stage alias/hash change, initial unexpected module, unsupported restricted-search API, wrong actual loaded identity and wrong thread all reject. Assert limited flags, no PATH/Kits fallback, no FreeLibrary after engine interfaces may exist, and post-load mismatch retains the fact that code may already have run. Preserve existing no-target/getter/A-B/callback regressions.
- [ ] Write RED Win32-binding fake tests for exact JOB_LIST/HANDLE_LIST sizes, noninheritable Job/pin handles, active-process-limit=1, absolute application name, CREATE_SUSPENDED, identity before resume, full original return handles on partial failure, and one cleanup deadline. These are binding tests, not claims of Windows success.
- [ ] Run `python -B -m pytest -q tests/delivery/test_issue110_filter_native_bindings.py tests/delivery/test_issue110_filter_command_probe.py tests/delivery/test_issue110_filter_probe_source.py` to RED.
- [ ] Implement official Win32 bindings; no handwritten COM vtables. Keep native loader separate from the adapter so existing adapter source tests still forbid direct loading/target APIs; replace the unverified factory-pointer seam without weakening blocked-main tests. Default entries never construct native APIs. Implement same-handle file hashing and loaded-image observations, preserving explicit dynamic-module sandbox limits.
- [ ] Re-run to GREEN using portable fakes. Any unavailable real SDK compilation is reported as unverified, not simulated ABI acceptance. Locally commit as `feat: bind closed filter host loading and ownership APIs`.

### Task 6: Join the closed pipeline and produce an honest verification handoff

**Files:** Modify the new supervisor/contract/loader files only as needed for internal composition; create `tests/delivery/test_issue110_filter_integration.py` and `docs/handoffs/2026-10-23-issue110-filter-integration.md`.

**Interfaces:** An internal `run_closed_pipeline(reviewed_build, private_root, api) -> HostObservation` is reachable only by software tests/explicit internal callers, never either main. It composes Tasks 1–5 without a second reservation, signature phase, process or budget. No accepted build manifest or real-run command is shipped in this slice.

- [ ] Write RED end-to-end fake tests for the entire successful-observation trace and every inter-component failure. “Successful” still asserts `passed is False`, `execution_ready is False`, and `display_comparison == 'format_unknown'`. Assert private canaries never leave public projection and unknown signature cleanup remains unknown even when host cleanup is true.
- [ ] Run `python -B -m pytest -q tests/delivery/test_issue110_filter_integration.py` to RED; implement only missing composition and C++ capsule plumbing, then run to GREEN.
- [ ] Run `python -B -m pytest -q tests/delivery/test_issue110_filter*.py tests/delivery/test_issue110_capture.py tests/delivery/test_issue110_setup_verify.py tests/delivery/test_issue110_debugger_config.py tests/delivery/test_issue110_debugger_config_local.py tests/delivery/test_issue110_prepare_private_root.py tests/contracts`. Use the existing isolated pytest/Ruff interpreter, record its exact path, commands/counts and collection failures. Do not install missing dependencies without authorization or borrow historical suite results.
- [ ] Run Ruff on changed Python files, portable C++ strict builds, `git diff --check`, and baseline hash comparison for core experiment, `issue110_win32.py`, original pins and all five workflows. Review any intended helper hash-only differences separately. Both mains must remain blocked under hostile arguments/environment.
- [ ] Write the handoff with exact source/commit/tree identities, observed tests and remaining facts: new Windows compile/build manifest, precise dependencies/system mapping, JOB_LIST/platform behavior, actual loader/cleanup verification and future one-run permission. Include dynamic-DLL, filesystem blocking and file-size detection limitations. Locally commit as `test: verify closed filter host integration boundaries`.

## Self-review and execution handoff

Spec coverage: §1–2 global constraints and Tasks 4–6; §3 Tasks 1/3/5; §4 Tasks 2/5; §5 Task 3; §6 Tasks 4/5; §7 Tasks 1/6; §8 all RED/GREEN gates. Each of five Review Focus items maps to named tests above. Shared Python contract types are owned by Task 1; PE-only types by Task 2; API seams by their consuming Task 3/4; C++ loader types by Task 5. No task changes the already-approved spec.

The three implementation areas remain in one plan because they share one attempt, one trust chain and one result protocol; each task can be rejected independently without granting runtime permission. Recommend subagent-driven execution: fresh implementation/review per task, then whole-branch review, because a trust or cleanup mistake crosses the private-data/native-process boundary. Parent will present this plan and ask for review/execution-method choice before any implementation. No publication, native loading or actual-machine work follows from plan approval alone.
