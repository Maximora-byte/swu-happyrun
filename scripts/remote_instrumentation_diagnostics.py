"""Allowlisted summaries of private synthetic instrumentation output. No raw text escapes."""

import re

PHASES = frozenset(
    {
        "arguments",
        "client_open",
        "hello_begin",
        "hello_return",
        "journal_open",
        "worker_start",
        "worker_join_begin",
        "worker_join_return",
        "fallback_begin",
        "fallback_return",
        "assert_worker",
        "assert_job",
        "assert_outcome",
        "assert_uncertain",
        "assert_stopped_distance",
        "report",
        "resources_closed",
        "runner",
        "expired_wait",
        "expired_renew",
        "wait_durable_start",
        "process_kill_wait",
    }
)
CONTROL_CODES = frozenset(
    {
        "transport_failed",
        "request_timeout",
        "http_rejected",
        "invalid_response",
        "closed",
        "busy",
        "control_failure",
        "other",
    }
)

ERRORS = frozenset(
    {
        "AssertionFailedError",
        "AssertionError",
        "SecurityException",
        "IOException",
        "IllegalStateException",
        "RuntimeException",
        "NullPointerException",
        "ControlException",
        "InterruptedException",
        "other",
    }
)
LOCAL_STATES = frozenset(
    {
        "idle",
        "claiming",
        "running",
        "stopped",
        "completed",
        "cancelled",
        "attention_unconfirmed",
        "claim_unconfirmed",
        "execution_stopped",
        "storage_failed_not_persisted",
        "needs_attention",
    }
)
ASSERTIONS = {
    "fallback_stop": "Acceptance must not rely on emergency fallback stop",
    "worker_alive": "Worker exceeded bounded shutdown",
    "runner_exception": "Runner leaked an exception",
    "no_claim": "No real server job claimed",
    "driver_not_stopped": "Driver must be stopped before reporting",
    "uncertain_completed": "Uncertain execution claimed completion",
    "attention_status": "Timed-out client cannot confirm attention",
    "stopped_moving": "Stopped driver must not keep moving",
    "durable_start": "Real driver did not reach its durable start",
    "kill_not_observed": "Host did not perform the required process interruption",
    "redirect_status": "Redirect must be rejected without following",
    "auth_status": "Real auth rejection required",
    "unsafe_connection": "Unsafe/rejected connection unexpectedly succeeded",
    "expired_conflict": "Real expired lease conflict required",
    "expired_renewed": "Expired lease was renewed",
    "plaintext_accepted": "HTTP origin accepted",
}


def summarize(output, returncode):
    if isinstance(output, bytes):
        output = output.decode("utf-8", errors="replace")
    output = output or ""
    phases, errors, frames, snapshots, controls = [], [], [], [], []
    for line in output.splitlines():
        control = re.fullmatch(
            r"REMOTE_QA CONTROL code=([a-z_]+) status=(0|[1-5][0-9]{2}|other) "
            r"retryable=(true|false) ambiguous=(true|false) phase=([a-z_]+) "
            r"elapsed_ms=(-1|[0-9]{1,5}) elapsed_capped=(true|false)",
            line,
        )
        if (
            control
            and control[1] in CONTROL_CODES
            and control[5] in PHASES
            and -1 <= int(control[6]) <= 60000
        ):
            controls.append(
                {
                    "code": control[1],
                    "status": None if control[2] == "other" else int(control[2]),
                    "retryable": control[3] == "true",
                    "ambiguous": control[4] == "true",
                    "phase": control[5],
                    "elapsed_ms": int(control[6]),
                    "elapsed_capped": control[7] == "true",
                }
            )
        phase = line.removeprefix("REMOTE_QA PHASE ")
        if line.startswith("REMOTE_QA PHASE ") and phase in PHASES:
            phases.append(phase)
        match = re.fullmatch(r"REMOTE_QA ERROR kind=([A-Za-z]+) phase=([a-z_]+)", line)
        if match and match[1] in ERRORS and match[2] in PHASES:
            errors.append({"kind": match[1], "phase": match[2]})
        match = re.fullmatch(
            r"\s*at org\.happyrun\.app\.remoteqa\.RemoteHttpsAcceptanceTest\."
            r"(testScenario|exercise|report|phase|diagnosticError)"
            r"\(RemoteHttpsAcceptanceTest\.java:([0-9]{1,6})\)",
            line,
        )
        if match:
            frames.append({"method": match[1], "line": int(match[2])})
        match = re.fullmatch(
            r"REMOTE_QA SNAPSHOT starts=([012]) stopped=(true|false) "
            r"worker_alive=(true|false) runner_error=(true|false) local=([a-z_]+)",
            line,
        )
        if match and match[5] in LOCAL_STATES:
            snapshots.append(
                {
                    "starts": int(match[1]),
                    "stopped": match[2] == "true",
                    "worker_alive": match[3] == "true",
                    "runner_error": match[4] == "true",
                    "local": match[5],
                }
            )
    return {
        "returncode": returncode,
        "junit_ok_one": len(re.findall(r"OK \(1 test\)", output)),
        "platform_failure": bool(re.search(r"FAILURES|INSTRUMENTATION_(?:FAILED|ABORTED)", output)),
        "exception_indicator": "Exception" in output,
        "assertion_codes": [code for code, label in ASSERTIONS.items() if label in output],
        "phases": phases[-32:],
        "errors": errors[:4],
        "frames": frames[:8],
        "snapshots": snapshots[-4:],
        "controls": controls[:4],
    }
