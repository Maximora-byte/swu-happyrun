"""Bounded process capture and a read-only text wrapper with fixed errors.

This is host process control, never physical-device stop confirmation. A child
may leave descendants holding pipes; unconfirmed cleanup must not report success.
"""

import os
import subprocess
import threading
import time
from math import isfinite
from pathlib import Path

MAX_OUTPUT_BYTES = 1024 * 1024  # Per stream; local capture policy, not a vendor limit.
CLEANUP_TIMEOUT_SECONDS = 0.5
_CAPTURE_LOCK = threading.Lock()
_PENDING_CAPTURE = None


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


def run_readonly(path: Path, *args: str, timeout: float = 5) -> str:
    """Return strict UTF-8 stdout with the original text-mode newline contract."""
    stdout, _stderr, returncode = _run_bounded_bytes(path, *args, timeout=timeout)
    if returncode != 0:
        raise ProbeError("command_failed")
    try:
        text = stdout.decode("utf-8", errors="strict")
        return text.replace("\r\n", "\n").replace("\r", "\n")
    except UnicodeDecodeError:
        raise ProbeError("command_encoding_invalid") from None


def _run_bounded_bytes(
    path: Path, *args: str, timeout: float = 5, before_spawn=None, cancel_event=None
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
                raise ProbeError("command_cleanup_unconfirmed", primary_code=primary)
            _PENDING_CAPTURE = None
        return _capture(
            path, *args, timeout=timeout, before_spawn=before_spawn, cancel_event=cancel_event
        )
    finally:
        _CAPTURE_LOCK.release()


def _capture(
    path: Path, *args: str, timeout: float, before_spawn=None, cancel_event=None
) -> tuple[bytes, bytes, int]:
    """Capture both pipes under one deadline and a separate cleanup budget.

    Raw bytes return only after both readers and the direct child finish.
    On capture failure no partial/raw output escapes. OS process creation
    and scheduling are not hard real-time guarantees. Never retries a command.
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
    deadline = time.monotonic() + timeout
    data = {"stdout": bytearray(), "stderr": bytearray()}
    failed, reasons = threading.Event(), []
    threads = []
    process = None
    reason = "ok"
    cleanup_confirmed = True
    # Guard exceptions (including Cancelled/LeaseLost RuntimeError subclasses)
    # must propagate unchanged; they are not process/reader failures. The outer
    # shared-capture finally still releases its lock when this callback raises.
    if before_spawn is not None:
        before_spawn()
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
                reason = "command_reader_failed"
                raise
        while True:
            if cancel_event is not None and cancel_event.is_set():
                reason = "command_cancelled"
                break
            if failed.is_set():
                reason = reasons[0]
                break
            # EOF after the exact deadline is still expired, not successful.
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                reason = "command_timeout"
                break
            if process.poll() is not None and all(
                done.is_set() and not thread.is_alive() for thread, _pipe, done in threads
            ):
                break
            failed.wait(min(0.01, remaining))
    except ProbeError:
        raise
    except FileNotFoundError:
        reason = "executable_missing"
    except OSError:
        reason = "command_unavailable"
    except RuntimeError:
        reason = "command_reader_failed"
    finally:
        if process is not None:
            # Publish pending ownership before cleanup, including interruptions.
            _PENDING_CAPTURE = (process, tuple(threads), reason)
            cleanup_deadline = time.monotonic() + CLEANUP_TIMEOUT_SECONDS
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
            # Do not close a pipe from this thread: a blocked reader may own its
            # BufferedReader lock. Reader threads close their own pipe on EOF.
    if reason == "ok" and reasons:
        reason = reasons[0]
    if not cleanup_confirmed:
        raise ProbeError("command_cleanup_unconfirmed", primary_code=reason) from None
    if reason != "ok":
        raise ProbeError(reason) from None
    return bytes(data["stdout"]), bytes(data["stderr"]), process.returncode
