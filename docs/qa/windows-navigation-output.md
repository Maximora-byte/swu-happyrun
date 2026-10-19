# Windows native-navigation output capture (#59)

## Evidence and scope

The reported Windows Python 3.11.16 warning is in the outer pytest
`subprocess.run([sys.executable, scripts/check_native_navigation.py],
text=True, encoding="utf-8", capture_output=True, timeout=60)` reader thread.
The script previously let these child commands inherit that stdout/stderr:

1. `java com.sun.tools.javac.Main -encoding UTF-8 -source 17 -target 17 ...`
2. `java -cp ... LegacyDeadlineRepro`
3. `java -cp ... org.happyrun.app.NativeViewDeadlineCheck`
4. `java -cp ... NavigationAdapterCheck`

The old traceback does not identify which of these commands or which stream
emitted byte 0xbe. It does not establish GBK or any other source encoding.
A synthetic child emitting all expected stdout markers and invalid stderr can
exit zero through the old script. On Windows, losing that stderr in a reader
thread could leave all old success assertions satisfied. This is a real
coverage gap, independent of identifying the original machine's emitter.

## Policy

Both boundaries now capture bytes. Each Java command is checked before the
next command starts. No decoding runs inside subprocess reader threads.
Return codes and timeouts reject; successful commands require strict UTF-8
on both streams and exact expected stdout (CRLF normalized). These fixed
success strings are ASCII. There is no guessed locale/codepage fallback,
replacement, ignore mode, global encoding change, or compiler flag change.

Compiler stdout must be empty. Valid UTF-8 compiler stderr is reported only as
`compiler_diagnostics` plus byte count, because javac can issue normal warnings
on newer JDKs. A zero compilation exit is still insufficient: all three
executables must produce their exact success output. Runtime stderr is
unexpected and rejects. Invalid bytes reject even if every PASS marker exists.
Safe JSON identifies the command stage, stream for decoding failures, error
category, byte counts, and nonzero exit code. It never includes raw text,
command arguments, paths, environment values, or exception messages.

The existing outer 60-second timeout stays unchanged; command timeouts share
one 60-second script deadline. Tests use a shorter injected timeout solely to
exercise rejection. UI/deadline assertions and budgets are unchanged.

## Ordinary Windows reproduction and acceptance

On the exact repair HEAD, using the ordinary account and Python 3.11.16:

    python -m pytest tests/delivery/test_android_native_navigation.py tests/delivery/test_navigation_output_capture.py -q -W error::pytest.PytestUnhandledThreadExceptionWarning
    python -m pytest tests/delivery -q
    python -m pytest -q

The synthetic suite replaces only Java launch commands with real Python child
processes. No installed Java or private host output is needed for its failure
matrix. It exercises each of the four stages with malformed stdout/stderr,
nonzero exit, timeout, unexpected success output, runtime diagnostics, and
launch failure; also valid compiler diagnostics and Windows line endings.
The original navigation test still executes the actual installed JVM.

If the actual JVM emits non-UTF-8 diagnostics, the new test must fail with a
safe classification, not silently pass. Do not change the system codepage or
publish raw output to make this test green. Linux synthetic passes do not
establish that the reported Windows warning is eliminated on that machine.

Only when explicitly collecting private bytes locally, run:

    python scripts/check_native_navigation.py --private-output-dir <new-private-directory>

Choose a new directory outside the repository under a private user-controlled
parent. The directory must not already exist. POSIX mode is 0700; on Windows
it inherits the parent's ACL, so use a private parent. On failure only, raw
stdout/stderr are written to fixed per-stage `.bin` files without overwriting.
There is no upload or default raw-output collection. Timeout evidence can be
partial. Existing-directory/write failures remain failures and never replace
the original failure with success. Do not attach these files to GitHub.
Share only the safe JSON stage/stream/category and the tested commit/version.
