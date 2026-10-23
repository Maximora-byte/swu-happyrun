# Issue 110 closed filter integration: software-only handoff

Status, updated 2026-10-23 UTC: software-only candidate with completed scoped independent review and full Linux regression validation. The final lint/format and bounded-test-ID cleanup was independently approved without findings on tree `f45c2144c6a49cf7678ca4901cd442ca971e792b`, committed locally as `76af14bdacc5f00aa39bd5d0b012fcf7879403c5`. This is not Windows acceptance, native execution or AV remediation. Both mains remain unconditionally blocked. No real-run command, accepted build manifest, new EXE hash or production allowlist is supplied. Earlier failed attempts remain below as historical evidence, not current unresolved tool-availability claims.

## Exact source identity

Original Task 6 implementation base: `85a41cf4dbed725bc76dd81402d90db0cc7de6d6`, tree `5b575efa96f5627492dbc956c116f91cc5057845`. The original disabled native-source baseline is `72e9aec0f4c3385c566fef3f7813c078bfb70abd`; its EXE identity does not identify this source.

Whole-branch fix base: `286cf6a84f5157c99a3a059d1c8e359ae1fbb7c9`, tree `6d288872bdc9ec7d6a5917c950c3c0fc50aa3c4d`. That earlier fix wave changed only the supervisor, new Win32 bundle adapter, their regression tests and this handoff; the legacy ACL helper remained byte-identical in that wave.

Final tested implementation: `76af14bdacc5f00aa39bd5d0b012fcf7879403c5`, tree `f45c2144c6a49cf7678ca4901cd442ca971e792b`, parent `9c9d8e5e5c886d2d38da49e4edc692da0fb9202d` (tree `bb70c174a9d7c1c23fcaebc804d154993b03342c`). The later documentation-only follow-up changes this handoff, not the runtime or test files validated at that implementation tree. Its own commit/tree is supplied by the publication report rather than a self-referential identity here.

Current source SHA256 at the tested implementation, under `scripts/diagnostics/`:

| Source | SHA256 |
| --- | --- |
| issue110_filter_command_probe.cpp | f05f1a5553a77c95b9fd71a52a376114e8248df87b61e3ea208e1e01eac04f53 |
| issue110_filter_loader.hpp | 0c54a6d9cffd008209f35f9f50f6393cd829ded9b005f3dbdc6b0d6936facf5d |
| issue110_filter_loader.cpp | cf254cfaa4630a5f2f37676b87521bc4e5feae2c371c0c3e4a77c1b39056bc2a |
| issue110_filter_capsule.hpp | 805dc320e82dddcb8c2093b7bfe8ac230e54b5579d50b8d4e54b59d9aa34cde3 |
| issue110_filter_probe_core.hpp | 7731c283c3395bc6fd19c31899225a448b1405f756057f0b427ec7873e830ea0 |
| issue110_filter_supervisor.py | 909859a7f4dfdd2d6e6d0fb3835c5f48c19aefc7c4afee1d7d44583171e79d9f |
| issue110_filter_contract.py | 3301ed2e9c90bce39834d0ed853a851372fddee2a39484d5aa644f19dc13da7b |
| issue110_filter_bundle.py | e8c74a04f3b756550e94ecc50f48d815a6766a4ad8ae904b8562e1e0c2e68bfa |
| issue110_filter_host_win32.py | 5f39e7daa768648c670201fcced2d41691e2b9cc002b0c85fe74c7874abd7021 |
| issue110_filter_pe.py | e53c27eb0597abc2413487252f9351f7eb44d196408d512d3bf57d31ec2b8064 |
| issue110_local_acl.py | e48d7aa1a4b0a9c2e209b6a027c587b5a6ec353fc2e11e15aba1fb60eba4e388 |
| issue110_debugger_config_local.py | a485d947f66e6ac1db5c03bd1fcc4781d48cdf572a6835735ce7dfc9d30ecb81 |
| issue110_prepare_private_root.py | f8dbdff4ec60b0cd840dfbb8cab109f63ebe740fd7148373dbc7545ddde2f231 |

These source hashes are not a reviewed Windows build manifest.

## What is connected

- Internal `run_closed_pipeline(reviewed_build, private_root, api)` establishes D once at monotonic start +300, calls the existing bundle factory once, constructs a side-effect-free host adapter bound to that same backend, then calls the existing one-shot supervisor. No second reservation, signature phase, process, S/H/D or cleanup C is introduced. A host-constructor failure closes the already-owned bundle under its one C and preserves the primary exception.
- The new C++ internal `run_closed_host` accepts only the bounded canonical request emitted by the sole Python writer. Identity/hash/manifest equality is exact; paths, commands, targets and output routing are not request-controlled. Caller assertions do not admit a build. Windows additionally binds the supplied receipt PID to GetCurrentProcessId; this Windows check remains unexecuted.
- The existing trusted-loader capability is still the only native factory route. A fake LoaderAPI can report matching observations and an arbitrary export address but cannot mint VerifiedEngineModule or reach DebugCreate. Production build admission and actual mapped-backing association remain unknown and blocked.
- Closed-host calls retain an owning LoaderAPI shared pointer and its pins until OS process teardown, including load/factory failure. Retention deliberately survives ordinary static destruction, because owned Release calls cannot prove global engine disposal. No unload is added. No retained owner/interface can outlive those pins merely because the internal call returns.
- Review F1 correction: an existing getter-stage trace is required before projecting its returned HRESULT/length. A getter never called, or called but throwing before return, retains null/null. An actually returned invalid getter keeps its real numeric facts and no bytes; a true S_OK confirmed getter retains its bytes. The core and protocol are unchanged.
- The unchanged core result is synchronously projected into the existing capsule type. Only confirmed getter bytes, bounded sx bytes, HRESULT trace, owned-release observations and bounded lossless UTF-16LE module paths are encoded. Sink false/throw is terminal, without retry. Invalid/oversized input is not truncated into success.
- WB1: full-window admission and H construction now share the same monotonic sample. Equality permits the original 15 seconds; a just-insufficient sample stops before intent/create. No D/H extension or retry is added.
- WB2: the final result length is compared with the parsed capsule before either result-limit or independent stream-limit rejection can preserve stale receipt proof. Result growth clears validity/receipt and derived engine/comparison facts; stdout/stderr-only growth retains a length-confirmed capsule but never completeness. Rejection records the final observation time, so H equality/late facts remain blocked.
- WB3: failure of lazy legacy ACL-helper construction conservatively marks the new backend cleanup unknown. Draining the known directory handle cannot erase unreported token-close uncertainty; the original exception survives and the uncertain token close is never retried. A successful constructor does not invent uncertainty.
- Public projection is unchanged: passed=false, execution_ready=false, display_comparison=format_unknown, disk_hard_cap=false. A complete synthetic observation is not product or runtime acceptance. Unknown signature cleanup remains independent of confirmed host cleanup.

## Historical verification before the final validation cleanup

The following records the earlier whole-branch fix checkpoint at `9c9d8e5e5c886d2d38da49e4edc692da0fb9202d` and its stated bases. It is retained to preserve the original successes, failures and limited environment, and is superseded for current validation by the dated addendum below.

Linux x86_64, CPython 3.12.14 at `/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin/python`, Debian g++ 14.2.0. At that checkpoint no tools were installed and no pytest shim was used. The later explicitly approved isolated PyPI installation is recorded below.

- `PYTHONPATH=tests/delivery:scripts/diagnostics:src python -B -m unittest discover -s tests/delivery -p 'test_issue110_filter*.py' -v`: 183 passed, 0 failed, 0 skipped. Includes 21 Task 6 methods, seven added whole-branch-fix methods and portable C++ strict compilation/runs. The two changed test modules alone passed 82 methods. The exact original base passed 75 methods in those modules before adding tests.
- Earlier Task 6 evidence, not repeated as RED in this fix wave: initial missing-composition RED: 16 methods, 63 assertion failures. Additional request/capsule glue, missing module-path output, unsafe private error-fact handling and real-PID source guard each had recorded RED before their implementation. Missing pytest itself is not a behavioral RED.
- Whole-branch-fix TDD: four supervisor RED assertions and six actual-legacy-constructor/fake-DLL RED subcases preceded the fixes. A further six final-result observation-time RED subcases caught a timestamp regression in the intermediate WB2 edit before the final fix. All are covered by the final GREEN counts. Normal ACL construction and independent stdout/stderr-only overflow controls also pass.
- Actual Python writer → synthetic C++ StageEvidence/loader → C++ capsule → independent Python parser was exercised. A separate pure Engine fake exercises complete core observation, every core call exception, every target gate and changed A/B results. It does not supply a native factory.
- Five separate portable strict g++ builds passed: core, capsule, loader, integration and adapter+loader blocked main. Flags: `-std=c++17 -Wall -Wextra -Werror -pedantic`, plus `-pthread` where applicable. Both mains stayed blocked under hostile arguments/environment. No Windows branch was compiled or executed.
- Prior review nits C1/C2/P3 are covered: exact C++ total frames 262143/262144 accepted and independently parsed, 262145 rejected before any sink call; partial-write/throw sinks stop after the failing append and report confirmed bytes only; normal OFT fallback, explicit normal shared lookup/IAT and delay shared INT/IAT preserve the dependency edge and still require exact independent mapping. The PE production change is explanatory comments only.
- `git diff --check` and Python AST parsing passed. Core, Session, original tool hashes/version/commands and all five Issue 110 workflows match the original disabled baseline byte-for-byte. Earlier approved ACL-role changes and the two helper-hash-only differences were separately checked; this fix does not change those helpers/pins, the C++ sources, or the protocol.

Historical attempts that did not pass at that checkpoint:

- Required focused, related and full `python -B -m pytest` attempts all stopped before collection: No module named pytest.
- The related unittest fallback ran 183 real filter tests but failed overall: 188 entries, 5 import errors in test_issue110_capture, test_issue110_setup_verify, test_issue110_debugger_config, test_issue110_debugger_config_local and test_issue110_prepare_private_root, all for missing pytest.
- Contracts unittest discovery failed to import test_c1, test_canonical, test_models, test_schema and test_states for missing pytest. No shared-contract or project-wide pass is claimed.
- Ruff check could not run: No module named ruff. Syntax/whitespace checks are not lint success. The earlier Task 6 inspection of the other isolated interpreter also found neither tool; it was not re-inspected in this fix wave.

## Facts still required before any future activation

1. Accurate new Windows compile/link with real SDK/MSVC/DbgEng ABI, exact source/header/toolchain identities, exact resulting EXE SHA256 and externally reviewed build manifest. Historical build success does not cover this candidate.
2. Exact imports/delay imports, transitive file identities/hashes, redirection/manifest/.local/activation evidence, and independently established current Windows system/API-set/KnownDLL mappings. Actual loaded-mapping to retained-backing association remains unknown. No positive admission may be inferred from path/disk hashes.
3. Real platform support and behavior for official creation-time JOB_LIST, restricted HANDLE_LIST, suspended absolute-image creation, one resume, file access/sharing, ACL/NTFS checks, installed-location V6 verification and independent signature-process descendant cleanup.
4. Actual loader, no-target/getter/callback/owned-release behavior, host exit and cleanup evidence. No native host, CDB, DbgEng, target, PowerShell or real V6 was run here.
5. Scoped independent software-only review is now satisfied for the final tested implementation recorded above. A separately reviewed activation change and explicit future one-run permission for the accurate candidate, private location and retention terms are still required. Software review and regression success imply no deletion, retention expiry, publication or runtime permission.

The trusted Microsoft code/current Windows model is not a complete dynamic-DLL sandbox. Post-load enumeration cannot prevent or undo DllMain, constrain all trusted dynamic loads, or observe every transient module. Synchronous filesystem/API calls and scheduling may block beyond monitored deadlines; 300/30/15/5 seconds are not OS hard-wall guarantees. Result/stdout/stderr polling and bounded reads detect oversize only after growth and cannot enforce disk quotas. Missing or equal/late observations never become acceptance, and cleanup does not restart work or renew a budget.

## Final software validation addendum: 2026-10-23 UTC

After explicit approval, repository-declared development/server dependencies were installed from official PyPI into an isolated own-cloud virtual environment and aligned with `uv.lock`. The final tools were CPython 3.12.14, pytest 9.1.1, Ruff 0.17.1 and Debian g++ 14.2.0. No browser package/browser, native debugger, device tooling or user-computer software was installed or run for this validation. External pytest plugin auto-loading and bytecode writes were disabled, `PYTEST_ADDOPTS` was cleared, and the project test configuration remained active.

Initial validation of `9c9d8e5` found 65 Ruff diagnostics (57 B023, four I001, four E501) and 15 formatting failures. Its full pytest run finished with 1 failed, 3871 passed, 32 skipped and 301 subtests passed: the failure was `tests/agent/test_enrollment_test_portability.py::test_collected_case_ids_fit_windows_environment`. The oversized descriptor fixture produced a 65657-character node ID; the same failure was reproduced on baseline `49812dd` (1 failed, 4 passed in the focused reproduction). These failures are not erased or relabeled as successful runs.

The local cleanup commit `76af14bdacc5f00aa39bd5d0b012fcf7879403c5` binds loop-local fake callbacks, organizes imports, formats the diagnosed Python paths, and gives the four descriptor cases short explicit IDs without altering adversarial bytes or assertions. Formatting the ACL helper changes only its newly added constructor signature; its AST is identical. Both exact-byte helper pins were refreshed to the current hash in the table. Each stale pin assertion was observed failing separately before both passed. The node-ID reproduction changed from 1 failed / 4 passed to 5 passed. No gate, native permission, production executable body or default-closed outcome was changed by this cleanup.

Verified results on exact tree `f45c2144c6a49cf7678ca4901cd442ca971e792b`:

- `ruff check --no-cache .`: exit 0, no diagnostics. `ruff format --check --no-cache .`: exit 0, all 371 Python files already formatted.
- Affected filter, legacy debugger/private-root and shared-contract pytest suite: 572 passed, 295 subtests passed, exit 0.
- Full project `python -m pytest -q -o faulthandler_timeout=60 --durations=20` (report/cache destinations omitted here): 3872 passed, 32 skipped, 301 subtests passed in 516.96 seconds, exit 0. The run completed at 06:58 UTC; its recorded staged tree matches the committed tree exactly. The node-ID guard passed against the full collection.
- One inherited FastAPI/Starlette warning concerns deprecated httpx TestClient use; no dependency replacement or suppression was added. The 32 skips comprise three Windows-native tests, 17 PowerShell-dependent tests and 12 explicitly opt-in native-enrollment tests. Skips are not native acceptance.
- AST comparison, `git diff --check`, both pin regressions and node-ID RED/GREEN checks passed. Scoped independent review of the exact final tree approved the cleanup without findings. Neither reviewed source nor tests changed between that review, the successful full run and the local implementation commit.

The documentation-only follow-up updates this handoff and its hashes. It does not rerun the expensive full suite or claim a full run on the documentation-modified repository tree; runtime/test bytes remain identical to the fully tested implementation tree. Current source hashes and that documentation-only delta are checked separately. All future Windows, build-admission and activation requirements above remain open; no native host, CDB, DbgEng, live target/device, browser, real V6 or user-computer action was performed.
