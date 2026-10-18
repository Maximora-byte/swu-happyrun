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
