"""Bounded process capture and a read-only text wrapper with fixed errors.

This is host process control, never physical-device stop confirmation. A child
may leave descendants holding pipes; unconfirmed cleanup must not report success.
"""

import os
import subprocess
import threading
import time
from dataclasses import dataclass, field, replace
from math import isfinite
from pathlib import Path

MAX_OUTPUT_BYTES = 1024 * 1024  # Per stream; local capture policy, not a vendor limit.
CLEANUP_TIMEOUT_SECONDS = 0.5
_CAPTURE_LOCK = threading.Lock()
_PENDING_CAPTURE = None


@dataclass(frozen=True)
class CaptureSnapshot:
    """Private binary evidence, not a public diagnostic or device receipt.

    Never serialize this object into public JSON. Raw fields are intentionally
    absent from repr; callers must persist them only in a verified private sink.
    """

    stdout: bytes = field(repr=False)
    stderr: bytes = field(repr=False)
    returncode: int | None
    primary_code: str
    final_code: str
    cleanup_code: str
    started_monotonic: float
    finished_monotonic: float
    output_complete: bool
    truncated: bool
    process_started: bool


@dataclass
class CaptureEvidence:
    """Optional per-call collector; no observer callbacks run during cleanup."""

    snapshot: CaptureSnapshot | None = field(default=None, repr=False)


@dataclass(repr=False)
class _CaptureState:
    data: dict[str, bytearray] = field(
        default_factory=lambda: {"stdout": bytearray(), "stderr": bytearray()}
    )
    reasons: list[str] = field(default_factory=list)
    process: subprocess.Popen[bytes] | None = None
    reason: str = "ok"
    cleanup_code: str = "not_started"


_SAFE_CODES = frozenset(
    {
        "ok",
        "command_capture_busy",
        "command_cleanup_unconfirmed",
        "command_budget_invalid",
        "command_cancelled",
        "command_timeout",
        "command_output_limit",
        "command_reader_failed",
        "executable_missing",
        "command_unavailable",
        "command_failed",
        "command_encoding_invalid",
        "command_guard_failed",
        "command_interrupted",
        "command_capture_failed",
    }
)


def _safe_code(code: str) -> str:
    return code if code in _SAFE_CODES else "command_capture_failed"


class ProbeError(RuntimeError):
    """Safe reason codes only; never raw output, arguments or device identifiers."""

    def __init__(self, code: str, *, primary_code: str | None = None):
        self.code = code
        self.primary_code = primary_code
        super().__init__(code)


def _read_pipe(
    pipe, target: bytearray, failed: threading.Event, reasons: list[str], done: threading.Event
) -> None:
    try:
        while True:
            block = pipe.read1(8192)
            if not block:
                break
            available = MAX_OUTPUT_BYTES - len(target)
            target.extend(block[:available])
            if len(block) > available:
                reasons.append("command_output_limit")
                failed.set()
                break
    except Exception:
        reasons.append("command_reader_failed")
        failed.set()
    finally:
        try:
            pipe.close()
        except Exception:
            reasons.append("command_reader_failed")
            failed.set()
        done.set()


def run_readonly(
    path: Path,
    *args: str,
    timeout: float = 5,
    evidence: CaptureEvidence | None = None,
    cleanup_deadline_monotonic: float | None = None,
) -> str:
    """Return strict UTF-8 stdout with the original text-mode newline contract."""
    kwargs = {}
    if evidence is not None:
        kwargs["evidence"] = evidence
    if cleanup_deadline_monotonic is not None:
        kwargs["cleanup_deadline_monotonic"] = cleanup_deadline_monotonic
    stdout, _stderr, returncode = _run_bounded_bytes(path, *args, timeout=timeout, **kwargs)
    if returncode != 0:
        raise ProbeError("command_failed")
    try:
        text = stdout.decode("utf-8", errors="strict")
        return text.replace("\r\n", "\n").replace("\r", "\n")
    except UnicodeDecodeError:
        if evidence is not None and evidence.snapshot is not None:
            evidence.snapshot = replace(
                evidence.snapshot,
                primary_code="command_encoding_invalid",
                final_code="command_encoding_invalid",
            )
        raise ProbeError("command_encoding_invalid") from None


def _run_bounded_bytes(
    path: Path,
    *args: str,
    timeout: float = 5,
    before_spawn=None,
    cancel_event=None,
    evidence: CaptureEvidence | None = None,
    cleanup_deadline_monotonic: float | None = None,
) -> tuple[bytes, bytes, int]:
    """Capture under the existing shared gate and optionally retain private bytes.

    Snapshot publication is a fixed assignment after cleanup, never a callback.
    Unresolved readers may append later; the immutable bounded snapshot remains
    explicitly incomplete and shared pending ownership is never cleared here.
    """
    started = time.monotonic()
    state = _CaptureState()
    final_code = "ok"
    try:
        result = _run_locked_bytes(
            path,
            *args,
            timeout=timeout,
            before_spawn=before_spawn,
            cancel_event=cancel_event,
            state=state,
            cleanup_deadline_monotonic=cleanup_deadline_monotonic,
        )
        if result[2] != 0:
            state.reason = final_code = "command_failed"
        return result
    except BaseException as exc:
        if isinstance(exc, ProbeError):
            final_code = _safe_code(exc.code)
            if state.reason == "ok":
                state.reason = _safe_code(exc.primary_code or exc.code)
        else:
            final_code = (
                "command_interrupted"
                if not isinstance(exc, Exception)
                else "command_capture_failed"
            )
            if state.reason == "ok":
                state.reason = final_code
            elif state.reason == "command_guard_failed":
                final_code = state.reason
        raise
    finally:
        if evidence is not None:
            reasons = tuple(state.reasons)
            primary = state.reason
            if primary == "ok" and reasons:
                primary = reasons[0]
            evidence.snapshot = CaptureSnapshot(
                stdout=bytes(state.data["stdout"]),
                stderr=bytes(state.data["stderr"]),
                returncode=getattr(state.process, "returncode", None),
                primary_code=_safe_code(primary),
                final_code=final_code,
                cleanup_code=state.cleanup_code,
                started_monotonic=started,
                finished_monotonic=time.monotonic(),
                output_complete=(
                    state.cleanup_code == "confirmed"
                    and primary in {"ok", "command_failed"}
                    and not reasons
                ),
                truncated="command_output_limit" in reasons,
                process_started=state.process is not None,
            )


def _run_locked_bytes(
    path: Path,
    *args: str,
    timeout: float = 5,
    before_spawn=None,
    cancel_event=None,
    state: _CaptureState,
    cleanup_deadline_monotonic: float | None = None,
) -> tuple[bytes, bytes, int]:
    """Internal process capture; bytes never establish device application or stop.

    One shared capture, including read-only and controlled-native consumers.
    The trusted pre-spawn guard runs under this lock and the original deadline.
    """
    global _PENDING_CAPTURE
    if not _CAPTURE_LOCK.acquire(blocking=False):
        raise ProbeError("command_capture_busy")
    try:
        if _PENDING_CAPTURE is not None:
            process, threads, primary = _PENDING_CAPTURE
            try:
                finished = process.poll() is not None and all(
                    done.is_set() and not thread.is_alive() for thread, _pipe, done in threads
                )
            except OSError:
                finished = False
            if not finished:
                state.cleanup_code = "unconfirmed"
                raise ProbeError("command_cleanup_unconfirmed", primary_code=primary)
            _PENDING_CAPTURE = None
        return _capture(
            path,
            *args,
            timeout=timeout,
            before_spawn=before_spawn,
            cancel_event=cancel_event,
            state=state,
            cleanup_deadline_monotonic=cleanup_deadline_monotonic,
        )
    finally:
        _CAPTURE_LOCK.release()


def _capture(
    path: Path,
    *args: str,
    timeout: float,
    before_spawn=None,
    cancel_event=None,
    state: _CaptureState,
    cleanup_deadline_monotonic: float | None = None,
) -> tuple[bytes, bytes, int]:
    """Capture both pipes under one deadline and a separate cleanup budget.

    Raw bytes return only after both readers and the direct child finish.
    On failure raw output is available only through the opt-in private collector.
    OS process creation and scheduling are not hard real-time guarantees.
    Never retries a command.
    """
    global _PENDING_CAPTURE
    if type(timeout) not in (int, float):
        raise ProbeError("command_budget_invalid")
    try:
        valid_timeout = isfinite(timeout) and timeout > 0
    except OverflowError:
        valid_timeout = False
    if not valid_timeout:
        raise ProbeError("command_budget_invalid")
    if cleanup_deadline_monotonic is not None:
        try:
            valid_cleanup = type(cleanup_deadline_monotonic) in (int, float) and isfinite(
                cleanup_deadline_monotonic
            )
        except OverflowError:
            valid_cleanup = False
        if not valid_cleanup:
            raise ProbeError("command_budget_invalid")
    deadline = time.monotonic() + timeout
    data = state.data
    failed, reasons = threading.Event(), state.reasons
    threads = []
    process = None
    cleanup_confirmed = True
    # Guard exceptions (including Cancelled/LeaseLost RuntimeError subclasses)
    # must propagate unchanged; they are not process/reader failures. The outer
    # shared-capture finally still releases its lock when this callback raises.
    if before_spawn is not None:
        try:
            before_spawn()
        except BaseException:
            state.reason = "command_guard_failed"
            raise
    if cancel_event is not None and cancel_event.is_set():
        raise ProbeError("command_cancelled")
    if time.monotonic() >= deadline:
        raise ProbeError("command_timeout")
    try:
        process = subprocess.Popen(
            [str(path), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=False,
            shell=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        state.process = process
        state.cleanup_code = "unconfirmed"
        for name in data:
            pipe, done = getattr(process, name), threading.Event()
            thread = threading.Thread(
                target=_read_pipe,
                args=(pipe, data[name], failed, reasons, done),
                daemon=True,
                name="happyrun-readonly-capture",
            )
            # Publish ownership before attempting start: an OS thread can exist
            # before ident/is_alive become observable. Only its own completion
            # signal proves that it cannot later begin reading this pipe.
            threads.append((thread, pipe, done))
            try:
                thread.start()
            except BaseException:
                state.reason = "command_reader_failed"
                raise
        while True:
            if cancel_event is not None and cancel_event.is_set():
                state.reason = "command_cancelled"
                break
            if failed.is_set():
                state.reason = reasons[0]
                break
            # EOF after the exact deadline is still expired, not successful.
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                state.reason = "command_timeout"
                break
            if process.poll() is not None and all(
                done.is_set() and not thread.is_alive() for thread, _pipe, done in threads
            ):
                break
            failed.wait(min(0.01, remaining))
    except ProbeError:
        raise
    except FileNotFoundError:
        state.reason = "executable_missing"
    except OSError:
        state.reason = "command_unavailable"
    except RuntimeError:
        state.reason = "command_reader_failed"
    except BaseException:
        if state.reason == "ok":
            state.reason = "command_interrupted"
        raise
    finally:
        if process is not None:
            # Publish pending ownership before cleanup, including interruptions.
            _PENDING_CAPTURE = (process, tuple(threads), state.reason)
            cleanup_deadline = time.monotonic() + CLEANUP_TIMEOUT_SECONDS
            if cleanup_deadline_monotonic is not None:
                cleanup_deadline = min(cleanup_deadline, cleanup_deadline_monotonic)
            try:
                if process.poll() is None:
                    process.kill()  # Direct child only, never a device/queue stop.
                process.wait(timeout=max(0, cleanup_deadline - time.monotonic()))
            except (OSError, subprocess.TimeoutExpired):
                cleanup_confirmed = False
            for thread, _pipe, done in threads:
                # join() rejects a thread still bootstrapping. Wait for reader
                # completion first, spending only the original cleanup budget.
                if done.wait(timeout=max(0, cleanup_deadline - time.monotonic())):
                    thread.join(timeout=max(0, cleanup_deadline - time.monotonic()))
                if not done.is_set() or thread.is_alive():
                    cleanup_confirmed = False
            for pipe in (process.stdout, process.stderr):
                if not any(pipe is owned for _thread, owned, _done in threads):
                    try:
                        pipe.close()
                    except OSError:
                        cleanup_confirmed = False
            if cleanup_confirmed:
                _PENDING_CAPTURE = None
                state.cleanup_code = "confirmed"
            # Do not close a pipe from this thread: a blocked reader may own its
            # BufferedReader lock. Reader threads close their own pipe on EOF.
    if state.reason == "ok" and reasons:
        state.reason = reasons[0]
    if not cleanup_confirmed:
        raise ProbeError("command_cleanup_unconfirmed", primary_code=state.reason) from None
    if state.reason != "ok":
        raise ProbeError(state.reason) from None
    return bytes(data["stdout"]), bytes(data["stderr"]), process.returncode
