"""Structural state edges. Stores must additionally check lease and recovery context."""

from enum import StrEnum


class JobState(StrEnum):
    QUEUED = "queued"
    LEASED = "leased"
    PREFLIGHT = "preflight"
    READY = "ready"
    RUNNING = "running"
    FINISHING = "finishing"
    VERIFYING = "verifying"
    CANCELLING = "cancelling"
    NEEDS_ATTENTION = "needs_attention"
    COMPLETED = "completed"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


_EDGES = {
    "queued": {"leased", "failed", "cancelled"},
    "leased": {"preflight", "verifying", "queued", "needs_attention", "cancelling", "failed"},
    "preflight": {"ready", "queued", "needs_attention", "cancelling", "failed"},
    "ready": {"running", "queued", "needs_attention", "cancelling", "failed"},
    "running": {"finishing", "needs_attention", "cancelling", "failed"},
    "finishing": {"verifying", "needs_attention", "cancelling", "failed"},
    "verifying": {"completed", "succeeded", "needs_attention", "cancelling", "failed"},
    "cancelling": {"cancelled", "needs_attention"},
    "needs_attention": {"leased", "cancelling"},
}


def transition_allowed(current: JobState, target: JobState, mode: str) -> bool:
    """Return a necessary, not sufficient, condition for a store transition.

    Device occupancy, stop acknowledgments, evidence, desired_state and recovery
    actions need persisted context and remain mandatory server/agent checks.
    In particular, leased -> verifying requires an approved verify_only recovery
    lease; it does not authorize a fresh job to skip execution.
    """
    if mode not in {"simulation", "device"}:
        return False
    if target == JobState.SUCCEEDED and mode != "device":
        return False
    if target == JobState.COMPLETED and mode != "simulation":
        return False
    return target in _EDGES.get(current, set())
