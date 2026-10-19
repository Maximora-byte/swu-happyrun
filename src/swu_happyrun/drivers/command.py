"""Bounded read-only child capture with safe, fixed diagnostic errors.

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


def _read_pipe(pipe, target: bytearray, failed: threading.Event, reasons: list[str]) -> None:
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


def run_readonly(path: Path, *args: str, timeout: float = 5) -> str:
    """One in-flight capture; refuse new children while prior cleanup is unknown."""
    global _PENDING_CAPTURE
    if not _CAPTURE_LOCK.acquire(blocking=False):
        raise ProbeError("command_capture_busy")
    try:
        if _PENDING_CAPTURE is not None:
            process, threads, primary = _PENDING_CAPTURE
            try:
                finished = process.poll() is not None and all(not t.is_alive() for t in threads)
            except OSError:
                finished = False
            if not finished:
                raise ProbeError("command_cleanup_unconfirmed", primary_code=primary)
            _PENDING_CAPTURE = None
        return _capture(path, *args, timeout=timeout)
    finally:
        _CAPTURE_LOCK.release()


def _capture(path: Path, *args: str, timeout: float) -> str:
    """Capture both pipes under one deadline and a separate cleanup budget.

    Successful UTF-8 stdout is returned only after both readers and the direct
    child finish. On failure no partial/raw output escapes. OS process creation
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
    owned_pipes = []
    process = None
    reason = "ok"
    cleanup_confirmed = True
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
            thread = threading.Thread(
                target=_read_pipe,
                args=(getattr(process, name), data[name], failed, reasons),
                daemon=True,
                name="happyrun-readonly-capture",
            )
            thread.start()
            threads.append(thread)
            owned_pipes.append(getattr(process, name))
        while True:
            if failed.is_set():
                reason = reasons[0]
                break
            # EOF after the exact deadline is still expired, not successful.
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                reason = "command_timeout"
                break
            if process.poll() is not None and all(not t.is_alive() for t in threads):
                break
            failed.wait(min(0.01, remaining))
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
            for thread in threads:
                thread.join(timeout=max(0, cleanup_deadline - time.monotonic()))
            if any(t.is_alive() for t in threads):
                cleanup_confirmed = False
            for pipe in (process.stdout, process.stderr):
                if pipe not in owned_pipes:
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
    if process.returncode != 0:
        raise ProbeError("command_failed")
    try:
        text = data["stdout"].decode("utf-8", errors="strict")
        # Preserve the previous subprocess text=True universal-newline contract.
        return text.replace("\r\n", "\n").replace("\r", "\n")
    except UnicodeDecodeError:
        raise ProbeError("command_encoding_invalid") from None
