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


## Revision after ordinary Windows rejection

Codex tested `7aeddd4` on the original ordinary account with Python 3.11.16 and
Oracle JDK 25.0.4.1: 31 synthetic tests passed, but real compilation failed.
The old reader-thread warning disappeared; the preserved failure was
`javac / invalid_utf8 / stderr`, 214 bytes. The independently observed JVM
properties were `native.encoding=GBK`, `stderr.encoding=GBK`,
`file.encoding=UTF-8`, and locale zh/CN. The bytes remain private. This is
reported source evidence, not a guessed decoding fallback or successful
navigation acceptance. See [Codex's exact report](https://github.com/Maximora-byte/swu-happyrun/issues/59#issuecomment-6264083583).

The revision sets only these two JVM **launch** options on all four commands,
before their main class (or classpath options):

    java -Dstdout.encoding=UTF-8 -Dstderr.encoding=UTF-8 com.sun.tools.javac.Main ...
    java -Dstdout.encoding=UTF-8 -Dstderr.encoding=UTF-8 -cp ... <check-main>

These configure output at its source. Captured bytes still undergo strict
UTF-8 decoding and the same exit, deadline, exact-output, and stderr checks.
An option's presence is not proof of its effect: malformed bytes still reject.
No file.encoding, native.encoding, locale, environment variable, system
codepage, javac source/target/source-encoding option, or budget is changed.

Official basis:

- [JDK 19 release notes](https://www.oracle.com/java/technologies/javase/19-relnote-issues.html)
  introduce stdout.encoding/stderr.encoding and the launch-time UTF-8 override.
- [Java 25 System properties](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/System.html#getProperties())
  specify UTF-8 as the supported override. file.encoding is a separate setting;
  changing native.encoding on the command line has no effect.
- [jdk.compiler invocation restrictions](https://docs.oracle.com/en/java/javase/25/docs/api/jdk.compiler/module-summary.html)
  explain why -J is not supported through legacy Main/API invocation. We invoke
  java with com.sun.tools.javac.Main, so the JVM options precede that class.
  A native javac launch would use -J, but this patch does not switch launchers.

JDK 17 predates these standard stream-property guarantees. This revision does
not claim that setting the property forces all JDK 17 implementations to use
UTF-8, and does not impose a project-wide JDK upgrade. Strict byte validation
remains the authority; an older JVM emitting another encoding fails closed.

Regression coverage adds a missing-launch-options RED for all four commands,
non-ASCII synthetic compiler diagnostics, and rejection of non-ASCII runtime
output that violates the success protocol. Real installed-JVM probes exercise
both non-ASCII stdout and stderr through the actual runner, checking bytes
rather than just property strings. Only these two additional probes explicitly
skip for a detected JDK older than 19, where this standard guarantee does not
exist; unknown versions fail and the original real navigation test never
skips for this reason. Those probes use synthetic Java source
with Unicode escapes and do not sample private device or host output.

The controlled Linux/JDK21 localized compiler experiment selects zh/CN only
for its test child, observes actual non-ASCII javac diagnostics, and checks
strict UTF-8 bytes and all unchanged navigation assertions. This experiment
is not a production locale override, and does not replace ordinary Windows
JDK25 acceptance. Codex must retest the new exact repair HEAD before accepting
#59; do not reuse either the old rejection or Hosted Windows passes as that
result.
