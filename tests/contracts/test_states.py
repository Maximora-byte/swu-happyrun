import pytest

from swu_happyrun.core.states import JobState, transition_allowed


def test_simulation_cannot_succeed():
    assert not transition_allowed(JobState.VERIFYING, JobState.SUCCEEDED, "simulation")
    assert transition_allowed(JobState.VERIFYING, JobState.COMPLETED, "simulation")
    assert transition_allowed(JobState.VERIFYING, JobState.SUCCEEDED, "device")
    assert not transition_allowed(JobState.VERIFYING, JobState.COMPLETED, "device")


@pytest.mark.parametrize("state", ["failed", "cancelled", "completed", "succeeded"])
def test_terminal_states_cannot_change(state):
    for target in JobState:
        assert not transition_allowed(JobState(state), target, "device")


@pytest.mark.parametrize(
    "source,target",
    [
        ("queued", "leased"),
        ("leased", "preflight"),
        ("preflight", "ready"),
        ("ready", "running"),
        ("running", "finishing"),
        ("finishing", "verifying"),
        ("needs_attention", "leased"),
        ("running", "cancelling"),
        ("cancelling", "cancelled"),
        ("cancelling", "needs_attention"),
    ],
)
def test_normal_and_recovery_edges(source, target):
    assert transition_allowed(JobState(source), JobState(target), "device")


@pytest.mark.parametrize(
    "source,target",
    [
        ("running", "queued"),
        ("verifying", "running"),
        ("cancelling", "running"),
        ("needs_attention", "running"),
        ("queued", "succeeded"),
        ("running", "cancelled"),
    ],
)
def test_unsafe_shortcuts_are_rejected(source, target):
    assert not transition_allowed(JobState(source), JobState(target), "device")


def test_unknown_mode_is_not_permissive():
    assert not transition_allowed(JobState.QUEUED, JobState.LEASED, "unknown")


@pytest.mark.parametrize(
    "mode,terminal", [("device", JobState.SUCCEEDED), ("simulation", JobState.COMPLETED)]
)
def test_verify_only_recovery_path_never_reenters_running(mode, terminal):
    # Persisted approval/current lease are additional server prerequisites.
    path = [JobState.NEEDS_ATTENTION, JobState.LEASED, JobState.VERIFYING, terminal]
    assert JobState.RUNNING not in path
    assert JobState.PREFLIGHT not in path
    assert JobState.READY not in path
    for current, target in zip(path[:-1], path[1:], strict=True):
        assert transition_allowed(current, target, mode), (current, target)


def test_verification_recovery_does_not_add_direct_unleased_shortcut():
    assert not transition_allowed(JobState.NEEDS_ATTENTION, JobState.VERIFYING, "device")
    assert not transition_allowed(JobState.LEASED, JobState.RUNNING, "device")
