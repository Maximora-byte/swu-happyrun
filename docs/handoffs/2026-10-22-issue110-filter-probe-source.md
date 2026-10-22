# Issue 110: disabled, no-target DbgEng probe source

## Scope and status

This is a software-only implementation of the direction approved in [6343958061](https://github.com/Maximora-byte/swu-happyrun/issues/110#issuecomment-6343958061), following the completed old-sample classification in [6343848989](https://github.com/Maximora-byte/swu-happyrun/issues/110#issuecomment-6343848989). It is not a runnable native candidate or a repair of the historical Python 3.11 access violation.

The baseline is `36a35d0e6563e825482cb392243499705bdce8e0`, tree `0c681634fa2d78bc0d7878202ba8a99eab0b54a0`. Existing generators, acceptance predicates, pins, Session, and workflows are unchanged. No private sample is read or uploaded. No installation, Windows API execution, debugger invocation, target, exception, device operation, or CI activation is part of this software check.

The executable entry remains unconditionally blocked. There is no command-line, environment, or build-flag execution bypass. The Windows adapter is integration source, not evidence that its external engine-factory precondition is authenticated. A caller-supplied pointer is not a trust proof.

## Fixed experiment, not an old-session replay

The intended command is the public synthetic ASCII literal `$$>a<C:\SWU_ISSUE110_SYNTHETIC\terminal.cdb`, containing two isolated path separators. The code does not check, create, open, or execute that filename; the synthetic name is not a claim that the file has been verified absent on another computer.

A future reviewed integration would create one new engine on one thread, verify no target, enumerate bounded event filters to find the unique access-violation exception code, and register the fixed quoted `sxd -c2` command. It then reads the second-chance getter A, requests `sx`, and reads getter B, with no-target checks between meaningful operations and after them. It never invokes the registered command or falls back to a target, exception, setter, server, or extension.

`GetExceptionFilterSecondCommand` is distinct from the first-chance event-filter getter. Exact `S_OK`, a bounded returned size including the terminating NUL, no embedded NUL, and supported ASCII are required. Truncation, unknown state, duplicate/missing AV filters, target changes, and output association failures remain blocked or inconclusive. There is no sizing retry or alternate experimental pass.

Getter equality/stability are limited new-experiment observations. A/B changes are explicitly blocked after retaining both observations; stable A=B values differing from the intended input remain discrepancy evidence, not success. The native `sx` format in this API topology is not validated, so `display_comparison` remains `format_unknown`; no guessed positive parser is supplied. The native client output mask/completeness has not been validated; bounded nonempty phase-associated output is not proof that the native display was complete. Even complete A/B results do not establish the old session's registered contents or historical AV root cause, and never make the product `passed` or `execution_ready`.

## Official ABI reference and build boundary

The native source uses the official Windows SDK headers and named interfaces, not hardcoded vtable slots, handwritten COM structures, or a ctypes substitute. The reference inspected for source review is Microsoft's [DbgEng.h at 71033001b4479c6566546b68d32276e70a8d68b9](https://github.com/microsoft/win32metadata/blob/71033001b4479c6566546b68d32276e70a8d68b9/generation/WinSDK/RecompiledIdlHeaders/um/DbgEng.h), associated with SDK 10.0.26100.6584. Its SHA256 is `a9037bf9a096700082ec5d4d96a98d1d98dee6c8ed71b3eac8de64c1fd9a0f4f`. It is not vendored or installed by this change, and is not claimed to be the same build as runtime 10.0.26100.8249.

Cloud checks use g++ for portable logic and the disabled entry only. There is no Windows compiler/SDK here; compilation of the `_WIN32` branch, linking with the actual SDK, native callback behavior, and compatibility with the intended engine remain unverified. A Linux build that excludes that branch is not a Windows build result.

Official semantics:
- [Second-chance command getter](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/dbgeng/nf-dbgeng-idebugcontrol-getexceptionfiltersecondcommand)
- [Exception-filter parameters](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/dbgeng/nf-dbgeng-idebugcontrol-getexceptionfilterparameters)
- [Filter enumeration](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/dbgeng/nf-dbgeng-idebugcontrol-getnumbereventfilters)
- [Event filters](https://learn.microsoft.com/en-us/windows-hardware/drivers/debugger/event-filters)
- [sx command](https://learn.microsoft.com/en-us/windows-hardware/drivers/debuggercmds/sx--sxd--sxe--sxi--sxn--sxr--sx---set-exceptions-)

## Required work before any real execution

The following are deliberately not replaced by a permissive enable switch:
1. Build and inspect an exact native binary using an approved Windows SDK/toolchain; bind its source and binary identities.
2. Implement and review exact existing Microsoft-engine identity/signature validation and restricted loading. No bare factory pointer or DLL pathname establishes this.
3. Implement and verify parent supervision and ownership cleanup for potentially blocking native calls. The planned shared preflight 300 seconds, signature `min(30, remaining)`, child 15 seconds, and cleanup up to 5 seconds are not implemented timing guarantees in this source slice.
4. Establish a bounded private evidence/output contract and any native display-format evidence needed for conclusions. Internal getter/output buffers must not be dumped publicly.
5. Obtain an accurate new single-run authorization. The earlier local CDB observation and old sample-read permissions do not authorize this new topology.

Owned release calls and reference-count observations must not be conflated with proof that the engine or module has been destroyed. An unresponsive native call cannot be bounded merely by checking a clock on the same blocked thread. Failure or missing evidence never authorizes an automatic second attempt.
