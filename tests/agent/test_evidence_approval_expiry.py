"""Synthetic lifecycle coverage, not production cleanup authority or device acceptance."""

import mumu_experiment_harness as subject
import pytest
from test_evidence_experiment import case as case

from swu_happyrun.agent.journal import RunJournal, UnsafeReplay
from swu_happyrun.drivers.mumu.experiment_shutdown import SIGNALS


class Approval:
    def __init__(self):
        self.current = True
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.current


def run(case, approval):
    registration, adapter, store, clock = case
    return subject.run_synthetic_experiment(
        registration, adapter=adapter, store=store, clock=clock, current_approval=approval
    )


def expire_during(case, approval, stage, monkeypatch):
    adapter, store = case[1:3]
    if stage == "before_launch":
        approval.current = False
    elif stage in {"launch", "prepare", "location"}:
        original = adapter.action

        def action(name):
            original(name)
            if name == stage:
                approval.current = False

        monkeypatch.setattr(adapter, "action", action)
    elif stage == "location_intent":
        original = store.claim_intent

        def claim(action):
            original(action)
            if action == "location":
                approval.current = False

        monkeypatch.setattr(store, "claim_intent", claim)
    else:
        assert stage == "command_persistence"
        original = store.put_once

        def put(name, data):
            original(name, data)
            if name == "command.json":
                approval.current = False

        monkeypatch.setattr(store, "put_once", put)


def assert_unresolved(registration):
    with RunJournal(registration.journal) as journal:
        with journal.replay_recovery_lock(registration.device_id):
            reservation = journal.read_replay_reservation(registration.device_id)
            assert reservation["status"] == "active"
            assert reservation["generation"] == 1
            assert journal._db.execute("SELECT result FROM intents").fetchall() == [("uncertain",)]
            assert journal._db.execute("SELECT COUNT(*) FROM stop_acks").fetchone() == (0,)
            return reservation


@pytest.mark.parametrize(
    "stage,producers,checks",
    [
        ("before_launch", [], 1),
        ("launch", ["launch"], 2),
        ("prepare", ["launch", "prepare"], 3),
        ("location_intent", ["launch", "prepare"], 3),
        ("location", ["launch", "prepare", "location"], 4),
        ("command_persistence", ["launch", "prepare", "location"], 4),
    ],
    ids=["before-launch", "after-launch", "during-prepare", "intent", "capture", "persistence"],
)
def test_expiry_stops_next_producer_but_not_cleanup(case, monkeypatch, stage, producers, checks):
    approval = Approval()
    expire_during(case, approval, stage, monkeypatch)
    result = run(case, approval)
    registration, adapter, store, _ = case
    assert [
        name for name in adapter.calls if name in {"launch", "prepare", "location"}
    ] == producers
    assert "probe" not in adapter.calls
    assert approval.calls == checks  # Never consulted by any cleanup operation.
    assert result["primary_error"] == "producer_approval_closed"
    assert result["status"] == "needs_attention"
    assert result["stop_status"] == "stop_unconfirmed"
    assert result["replay_enabled"] is False
    assert result["shutdown_attempted"] is bool(producers)
    if producers:
        for name in ("seal", "drain", "identity", "shutdown"):
            assert adapter.calls.count(name) == 1
        assert adapter.calls.index("seal") < adapter.calls.index("drain")
        assert result["shutdown_status"] == "sampled_shutdown_consistent"
        assert (store.root / "shutdown.intent").is_file()
    else:
        assert adapter.calls == ["preflight"]
        assert result["shutdown_status"] == "shutdown_not_attempted"
        assert not (store.root / "shutdown.intent").exists()
    original_reservation = assert_unresolved(registration)

    # Approval restoration cannot erase the original unresolved exclusion.
    approval.current = True
    adapter.calls.clear()
    restarted = run(case, approval)
    assert adapter.calls == []
    assert approval.calls == checks
    assert restarted["shutdown_attempted"] is False
    assert assert_unresolved(registration) == original_reservation


@pytest.mark.parametrize("rejection", [False, None, 1, "yes", RuntimeError, KeyboardInterrupt])
def test_producer_latch_cannot_reopen_even_if_callback_would_restore(rejection):
    calls = []

    def current():
        calls.append(True)
        if len(calls) > 1:
            return True
        if isinstance(rejection, type):
            raise rejection("private details")
        return rejection

    gate = subject._SyntheticProducerGate(current)
    expected = rejection if isinstance(rejection, type) else subject._ProducerApprovalClosed
    with pytest.raises(expected):
        gate.require()
    with pytest.raises(subject._ProducerApprovalClosed):
        gate.require()
    assert len(calls) == 1


def test_restoration_during_seal_is_not_a_new_producer_permission(case, monkeypatch):
    approval = Approval()
    expire_during(case, approval, "prepare", monkeypatch)
    original = case[1].seal

    def seal():
        original()
        approval.current = True

    monkeypatch.setattr(case[1], "seal", seal)
    result = run(case, approval)
    assert approval.current
    assert approval.calls == 3
    assert "location" not in case[1].calls and "probe" not in case[1].calls
    assert case[1].calls.count("shutdown") == 1
    assert result["stop_status"] == "stop_unconfirmed"


@pytest.mark.parametrize("boundary", [1, 2, 3, 4], ids=["launch", "prepare", "capture", "observe"])
@pytest.mark.parametrize("error", [RuntimeError, KeyboardInterrupt], ids=["error", "interrupt"])
def test_callback_errors_close_producers_and_do_not_gate_cleanup(case, boundary, error):
    calls = []

    def approval():
        calls.append(True)
        if len(calls) == boundary:
            raise error("private approval data")
        return True

    result = run(case, approval)
    adapter = case[1]
    assert len(calls) == boundary
    assert [
        name for name in adapter.calls if name in {"launch", "prepare", "location", "probe"}
    ] == ["launch", "prepare", "location"][: boundary - 1]
    assert adapter.calls.count("shutdown") == int(boundary > 1)
    assert result["primary_error"] == (
        "experiment_interrupted" if error is KeyboardInterrupt else "experiment_failed"
    )
    assert result["stop_status"] == "stop_unconfirmed"
    assert "private approval data" not in str(result)
    assert_unresolved(case[0])


def test_expiry_is_seen_at_next_boundary_not_claimed_to_interrupt_prepare(case, monkeypatch):
    approval = Approval()
    adapter = case[1]

    def prepare():
        adapter.action("prepare")
        approval.current = False
        adapter.action("inflight_prepare_returned")

    monkeypatch.setattr(adapter, "prepare", prepare)
    result = run(case, approval)
    assert adapter.calls.index("prepare") < adapter.calls.index("inflight_prepare_returned")
    assert adapter.calls.index("inflight_prepare_returned") < adapter.calls.index("seal")
    assert "location" not in adapter.calls and "probe" not in adapter.calls
    assert result["primary_error"] == "producer_approval_closed"
    assert result["shutdown_attempted"] is True


def test_possible_launch_exception_still_cleans_up_with_expired_approval(case, monkeypatch):
    approval = Approval()
    adapter = case[1]

    def launch():
        adapter.action("launch")
        approval.current = False
        raise RuntimeError("private possible-start details")

    monkeypatch.setattr(adapter, "launch", launch)
    result = run(case, approval)
    assert approval.calls == 1
    assert "prepare" not in adapter.calls and "location" not in adapter.calls
    assert adapter.calls.count("seal") == adapter.calls.count("shutdown") == 1
    assert result["stop_status"] == "stop_unconfirmed"
    assert_unresolved(case[0])


@pytest.mark.parametrize(
    "failure,reason",
    [
        ("drain_false", "capture_cleanup_unconfirmed"),
        ("drain_error", "shutdown_interrupted_or_failed"),
        ("identity_false", "target_identity_unverified"),
        ("identity_error", "shutdown_interrupted_or_failed"),
        ("command_storage", "storage_unreliable"),
        ("location_storage", "storage_unreliable"),
        ("shutdown_intent", "shutdown_intent_failed"),
    ],
    ids=[
        "drain-false",
        "drain-error",
        "identity-false",
        "identity-error",
        "storage",
        "intent",
        "stop",
    ],
)
def test_expiry_does_not_bypass_cleanup_safety(case, monkeypatch, failure, reason):
    approval = Approval()
    expiry = "location" if failure == "command_storage" else "prepare"
    expire_during(case, approval, expiry, monkeypatch)
    registration, adapter, store, _ = case
    if failure == "drain_false":
        adapter.clean = False
    elif failure == "identity_false":
        adapter.identity = False
    elif failure in {"drain_error", "identity_error"}:
        adapter.fail = failure.split("_")[0]
    elif failure == "command_storage":

        def fail_put(*args):
            raise OSError("private path")

        monkeypatch.setattr(store, "put_once", fail_put)
    else:
        original = store.claim_intent
        failed_action = "location" if failure == "location_storage" else "shutdown"

        def claim(action):
            if action == failed_action:
                raise OSError("private path")
            original(action)

        monkeypatch.setattr(store, "claim_intent", claim)
    result = run(case, approval)
    assert adapter.calls.count("seal") == adapter.calls.count("drain") == 1
    assert "shutdown" not in adapter.calls and "probe" not in adapter.calls
    assert result["shutdown_attempted"] is False
    assert result["shutdown_status"] == "shutdown_not_attempted"
    assert result["shutdown_reason"] == reason
    assert result["stop_status"] == "stop_unconfirmed"
    assert "private path" not in str(result)
    assert_unresolved(registration)


def test_existing_shutdown_intent_cannot_be_retried_after_expiry(case, monkeypatch):
    approval = Approval()
    expire_during(case, approval, "launch", monkeypatch)
    case[2].claim_intent("shutdown")
    result = run(case, approval)
    assert "shutdown" not in case[1].calls
    assert result["shutdown_reason"] == "shutdown_intent_failed"
    assert result["shutdown_attempted"] is False
    assert_unresolved(case[0])


def test_expired_cleanup_issues_shutdown_only_after_durable_once_only_intent(case, monkeypatch):
    approval, intents_seen = Approval(), []
    expire_during(case, approval, "prepare", monkeypatch)
    registration, adapter, store, _ = case
    original = adapter.shutdown

    def shutdown(*, timeout, deadline):
        intents_seen.append((store.root / "shutdown.intent").read_bytes())
        original(timeout=timeout, deadline=deadline)

    monkeypatch.setattr(adapter, "shutdown", shutdown)
    result = run(case, approval)
    assert intents_seen == [b"attempt_reserved_v1\n"]
    assert result["shutdown_status"] == "sampled_shutdown_consistent"
    assert adapter.calls.count("shutdown") == 1
    assert_unresolved(registration)


def test_lock_contention_closes_opened_journal_without_producers_or_cleanup(case, monkeypatch):
    approval, closes = Approval(), []
    registration = case[0]

    class TrackedJournal(RunJournal):
        def close(self):
            closes.append(True)
            super().close()

    monkeypatch.setattr(subject, "RunJournal", TrackedJournal)
    with RunJournal(registration.journal) as original:
        with original.device_lock(registration.device_id):
            result = run(case, approval)
    assert closes == [True]
    assert approval.calls == 0
    assert case[1].calls == []
    assert result["shutdown_attempted"] is False


def test_original_lock_covers_cleanup_result_and_journal_close(case, monkeypatch):
    approval, events, lock_checks = Approval(), [], []
    registration, adapter, store, _ = case
    expire_during(case, approval, "prepare", monkeypatch)

    def assert_locked():
        lock_checks.append(False)
        with RunJournal(registration.journal, existing_only=True, read_only=True) as competitor:
            with pytest.raises(UnsafeReplay, match="device already locked"):
                with competitor.replay_recovery_lock(registration.device_id):
                    pytest.fail("original exclusion was released")
        lock_checks[-1] = True

    class TrackedJournal(RunJournal):
        def record_result(self, *args):
            assert_locked()
            events.append("result")
            return super().record_result(*args)

        def close(self):
            assert_locked()
            events.append("close")
            super().close()
            assert_locked()

    monkeypatch.setattr(subject, "RunJournal", TrackedJournal)
    original_action, original_put = adapter.action, store.put_once

    def action(name):
        assert_locked()
        events.append(name)
        original_action(name)

    def put(name, data):
        assert_locked()
        events.append(name)
        original_put(name, data)

    monkeypatch.setattr(adapter, "action", action)
    monkeypatch.setattr(store, "put_once", put)
    run(case, approval)
    assert events[-3:] == ["shutdown.json", "result", "close"]
    assert lock_checks and all(lock_checks)  # Adapter exceptions are caught by the harness.
    assert_unresolved(registration)  # Lock released only after journal closure.


def test_cleanup_preserves_one_deadline_through_all_stages(case, monkeypatch):
    approval, timed = Approval(), []
    _, adapter, store, clock = case
    expire_during(case, approval, "prepare", monkeypatch)
    clock.now = 11.0
    original_seal = adapter.seal

    def seal():
        original_seal()
        clock.now += 2

    monkeypatch.setattr(adapter, "seal", seal)
    for method, elapsed, cap in (
        ("drain", 0.25, 0.5),
        ("verify_shutdown_identity", 0.75, 1),
        ("shutdown", 2, 5),
        ("read", 0.1, 1),
    ):
        original = getattr(adapter, method)

        def bounded(
            *args, _method=method, _original=original, _elapsed=elapsed, _cap=cap, timeout, deadline
        ):
            timed.append((_method, clock.now, timeout, deadline))
            assert timeout == pytest.approx(min(_cap, deadline - clock.now))
            value = _original(*args, timeout=timeout, deadline=deadline)
            clock.now += _elapsed
            return value

        monkeypatch.setattr(adapter, method, bounded)
    original_claim, original_put = store.claim_intent, store.put_once

    def claim(action):
        original_claim(action)
        if action == "shutdown":
            clock.now += 1

    def put(name, data):
        original_put(name, data)
        if name == "shutdown.json":
            clock.now += 3

    monkeypatch.setattr(store, "claim_intent", claim)
    monkeypatch.setattr(store, "put_once", put)
    result = run(case, approval)
    assert result["shutdown_started_monotonic"] == 11
    assert {entry[3] for entry in timed} == {56.0}
    assert timed[0] == ("drain", 13, 0.5, 56)
    assert timed[1] == ("verify_shutdown_identity", 13.25, 1, 56)
    assert timed[2] == ("shutdown", 15, 5, 56)
    assert timed[3] == ("read", 17, 1, 56)
    assert len([entry for entry in timed if entry[0] == "read"]) == 28
    assert result["shutdown_finished_monotonic"] == pytest.approx(50.4)
    assert result["shutdown_status"] == "sampled_shutdown_consistent"
    assert approval.calls == 3


def test_slow_seal_cannot_restart_a_fresh_observation_budget(case, monkeypatch):
    approval = Approval()
    expire_during(case, approval, "prepare", monkeypatch)
    original = case[1].seal

    def seal():
        original()
        case[3].now += 20

    monkeypatch.setattr(case[1], "seal", seal)
    result = run(case, approval)
    assert result["shutdown_attempted"] is True
    assert result["shutdown_status"] == "shutdown_unknown"
    assert case[1].calls.count("manager") == 5  # Only offsets 20/25/30/35/40 fit.
    assert result["shutdown_finished_monotonic"] == 40
    assert result["stop_status"] == "stop_unconfirmed"


def test_every_late_cleanup_adapter_gets_only_the_remaining_budget(case, monkeypatch):
    approval, timed = Approval(), []
    expire_during(case, approval, "prepare", monkeypatch)
    _, adapter, _, clock = case
    original_seal = adapter.seal

    def seal():
        original_seal()
        clock.now += 44.75

    monkeypatch.setattr(adapter, "seal", seal)
    for method in ("drain", "verify_shutdown_identity", "shutdown", "read"):
        original = getattr(adapter, method)

        def bounded(*args, _method=method, _original=original, timeout, deadline):
            timed.append((_method, timeout, deadline))
            assert timeout == 0.25
            assert deadline == 45
            return _original(*args, timeout=timeout, deadline=deadline)

        monkeypatch.setattr(adapter, method, bounded)
    result = run(case, approval)
    assert [entry[0] for entry in timed] == [
        "drain",
        "verify_shutdown_identity",
        "shutdown",
        "read",
        "read",
        "read",
        "read",
    ]
    assert result["shutdown_status"] == "shutdown_unknown"
    assert result["shutdown_finished_monotonic"] == 44.75
    assert result["stop_status"] == "stop_unconfirmed"


@pytest.mark.parametrize(
    "stage",
    [
        "seal",
        "drain",
        "identity",
        "shutdown_intent",
        "shutdown",
        "readback",
        "evidence_persistence",
        "journal_result",
        "journal_close",
    ],
    ids=["seal", "drain", "identity", "intent", "shutdown", "reads", "evidence", "result", "close"],
)
def test_cleanup_overrun_never_claims_stop_or_restarts_budget(case, monkeypatch, stage):
    approval = Approval()
    expire_during(case, approval, "prepare", monkeypatch)
    registration, adapter, store, clock = case
    original_action = adapter.action

    def action(name):
        original_action(name)
        if name == stage or (stage == "readback" and name == "manager"):
            clock.now += 46

    monkeypatch.setattr(adapter, "action", action)
    original_claim, original_put = store.claim_intent, store.put_once

    def claim(action):
        original_claim(action)
        if stage == "shutdown_intent" and action == "shutdown":
            clock.now += 46

    def put(name, data):
        original_put(name, data)
        if stage == "evidence_persistence" and name == "shutdown.json":
            clock.now += 16

    monkeypatch.setattr(store, "claim_intent", claim)
    monkeypatch.setattr(store, "put_once", put)

    class SlowJournal(RunJournal):
        def record_result(self, *args):
            super().record_result(*args)
            if stage == "journal_result":
                clock.now += 16

        def close(self):
            super().close()
            if stage == "journal_close":
                clock.now += 16

    monkeypatch.setattr(subject, "RunJournal", SlowJournal)
    result = run(case, approval)
    attempted = stage in {
        "shutdown",
        "readback",
        "evidence_persistence",
        "journal_result",
        "journal_close",
    }
    assert result["shutdown_attempted"] is attempted
    assert adapter.calls.count("shutdown") == int(attempted)
    assert result["shutdown_status"] == (
        "shutdown_unknown" if attempted else "shutdown_not_attempted"
    )
    assert result["shutdown_reason"] == "shutdown_budget_expired"
    assert result["shutdown_finished_monotonic"] - result["shutdown_started_monotonic"] == 46
    assert result["stop_status"] == "stop_unconfirmed"
    if stage in {"seal", "drain", "identity", "shutdown_intent", "shutdown"}:
        assert not set(SIGNALS).intersection(adapter.calls)
    if stage == "identity":
        assert not (store.root / "shutdown.intent").exists()
    if stage == "readback":
        assert adapter.calls.count("manager") == 1
        assert not set(SIGNALS[1:]).intersection(adapter.calls)
    assert_unresolved(registration)
