"""Bounded argument-list subprocess calls with safe diagnostic errors."""

import os
import subprocess
from pathlib import Path


class ProbeError(RuntimeError):
    """A safe reason code; never includes raw command output or device identifiers."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def run_readonly(path: Path, *args: str, timeout: float = 5) -> str:
    try:
        result = subprocess.run(
            [str(path), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired:
        raise ProbeError("command_timeout") from None
    except FileNotFoundError:
        raise ProbeError("executable_missing") from None
    except OSError:
        raise ProbeError("command_unavailable") from None
    if result.returncode != 0:
        raise ProbeError("command_failed")
    return result.stdout
