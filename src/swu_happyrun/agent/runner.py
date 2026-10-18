"""Single-threaded, fail-closed execution. No catch-up ticks or blind action retries."""

import math
import time
from datetime import datetime
from uuid import uuid4

from swu_happyrun.agent.client import ControlError
from swu_happyrun.agent.journal import UnsafeReplay
from swu_happyrun.core.models import JobEvent, LeaseCommand


class LeaseLost(RuntimeError):
    pass


class Cancelled(RuntimeError):
    pass


class AgentRunner:
    def __init__(
        self,
        client,
        driver,
        journal,
        clock,
        *,
        device_id: str,
        sleep=time.sleep,
        run_seconds: float = 1,
        tick_seconds: float = 1,
    ):
        if (
            not math.isfinite(run_seconds)
            or run_seconds <= 0
            or not math.isfinite(tick_seconds)
            or not 0 < tick_seconds <= 10
        ):
            raise ValueError("invalid execution duration")
        self.client, self.driver, self.journal, self.clock = client, driver, journal, clock
        self.device_id, self.sleep = device_id, sleep
        self.run_seconds, self.tick_seconds = run_seconds, tick_seconds
        self.job = None
        self.hello = None
        self._heartbeat_at = 0.0
        self._lease_deadline = 0.0
        self._job_deadline = 0.0
        self._stopped = False

    def _set_expiry(self, expires_at, before, wall):
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        self._lease_deadline = before + min(30, (expires_at - wall).total_seconds())

    def _check_lease(self):
        if self.clock.monotonic() >= self._lease_deadline:
            raise LeaseLost("lease expired")

    def _check(self):
        self._check_lease()
        now = self.clock.monotonic()
        if self.job.desired_state == "cancel":
            raise Cancelled()
        if self.job.recovery_action not in {"verify_only", "stop_only"}:
            if now >= self._job_deadline:
                raise LeaseLost("execution window expired")

    def _effect_guard(self):
        self._check()
        # Reserve the maximum supported bounded driver call plus scheduling margin.
        remaining = min(self._lease_deadline, self._job_deadline) - self.clock.monotonic()
        if remaining <= 5.1:
            raise LeaseLost("insufficient action time budget")

    def _renew(self):
        self._check()
        if self.hello is not None and self.clock.monotonic() - self._heartbeat_at >= 10:
            self.client.heartbeat(self.hello)
            self._check()
            self._heartbeat_at = self.clock.monotonic()
        before, wall = self.clock.monotonic(), self.clock.utcnow()
        result = self.client.renew(self.job.job_id, self.lease)
        # A response arriving after the previous lease deadline cannot restore authority.
        self._check()
        self._set_expiry(result["expires_at"], before, wall)
        if result["desired_state"] == "cancel":
            raise Cancelled()
        self._check()

    def _event(self, state, *, reason=None, evidence=None, phase=None):
        # Reporting uncertainty is not permission to execute device actions.
        # A live lease may report after cancellation or the original start window.
        check = self._check_lease if state == "needs_attention" else self._check
        check()
        event = JobEvent(
            event_id=str(uuid4()),
            expected_revision=self.job.revision,
            state=state,
            reason_code=reason,
            evidence=evidence or [],
            resume_phase=phase,
        )
        updated = self.client.events(self.job.job_id, self.lease, event)
        self._accept_view(updated)
        check()
        return updated

    def _accept_view(self, updated):
        if (
            updated.job_id != self.job.job_id
            or updated.fence != self.lease.fence
            or updated.spec != self.job.spec
            or getattr(updated, "run_session_id", None) != getattr(self.job, "run_session_id", None)
        ):
            raise ControlError("response identity changed")
        self.job = updated

    def _stop(self):
        if not self._stopped:
            self.driver.stop()
            self._stopped = True

    def _cancel(self):
        # Controlled stopping is required even with expired credentials.
        self._stop()
        if self.clock.monotonic() >= self._lease_deadline:
            return
        # Cancellation can increment server revision independently of this runner.
        if hasattr(self.client, "get_job"):
            self._accept_view(self.client.get_job(self.job.job_id))
        if self.job.state != "cancelling":
            event = JobEvent(
                event_id=str(uuid4()),
                expected_revision=self.job.revision,
                state="cancelling",
                reason_code=None,
                evidence=[],
                resume_phase=None,
            )
            self.job = self.client.events(self.job.job_id, self.lease, event)
        event_id = self.journal.stop_ack_intent(
            self.job.job_id, self.lease.fence, self.job.revision
        )
        revision = self.job.revision
        try:
            self.job = self.client.stop_ack(self.job.job_id, self.lease, event_id, revision)
        except ControlError:
            # This is an exact idempotent acknowledgment replay, never a device action.
            if self.clock.monotonic() >= self._lease_deadline:
                raise
            self.job = self.client.stop_ack(self.job.job_id, self.lease, event_id, revision)

    def _attention(self, reason):
        settled = {"completed", "succeeded", "failed", "cancelled", "needs_attention"}
        if self.job is None or self.job.state in settled:
            return
        try:
            self._check_lease()
            # A concurrent cancel increments the server revision, including when
            # controlled stop failed before _cancel could fetch the new view.
            self._accept_view(self.client.get_job(self.job.job_id))
            self._check_lease()
            if self.job.state in settled:
                return
            phase = self.job.state.value
            if self.job.recovery_action in {"verify_only", "stop_only"}:
                phase = self.job.resume_phase or phase
            self._event("needs_attention", reason=reason, phase=phase)
        except Exception:
            # Reporting never restores an expired/replaced lease or allows writes.
            pass

    def run_once(self):
        self._heartbeat_at = self.clock.monotonic()
        self.job = None
        self._stopped = False
        with self.journal.device_lock(self.device_id):
            before, wall = self.clock.monotonic(), self.clock.utcnow()
            grant = self.client.claim(self.device_id)
            if grant is None:
                return None
            self.job = grant.job
            if self.job.spec.device_id != self.device_id:
                raise ControlError("claim returned another device")
            self.lease = LeaseCommand(lease_token=grant.lease_token, fence=grant.fence)
            self._set_expiry(grant.expires_at, before, wall)
            self._job_deadline = before + (self.job.spec.deadline - wall).total_seconds()
            try:
                self.driver.bind_session(self.job)
                self.driver.configure_execution_guard(self._effect_guard)
                if self.job.recovery_action == "stop_only" or self.job.desired_state == "cancel":
                    self._cancel()
                    return self.job
                self._renew()
                if self.job.recovery_action == "verify_only":
                    self._stop()
                    self._event("verifying")
                    self._verify(recovery=True)
                    return self.job
                if self.journal.has_intent(self.job.job_id, "start"):
                    raise UnsafeReplay("start already attempted")
                self._event("preflight")
                self.driver.prepare(self.job.spec)  # Contract: strictly read-only.
                self._renew()
                self._event("ready")
                self._event("running")
                self.journal.record_intent(self.job.job_id, self.lease.fence, "start")
                self._renew()
                self._effect_guard()
                self.driver.start(self.job.spec)
                self.journal.record_result(self.job.job_id, self.lease.fence, "start", "confirmed")
                started = self.clock.monotonic()
                while self.clock.monotonic() - started < self.run_seconds:
                    self._renew()
                    self._effect_guard()
                    self.driver.tick(self.job.spec, self.clock.monotonic() - started)
                    self._check()
                    self.sleep(
                        min(
                            self.tick_seconds,
                            max(0, self.run_seconds - (self.clock.monotonic() - started)),
                        )
                    )
                self._renew()
                self._event("finishing")
                self._stop()
                self._event("verifying")
                self._verify(recovery=False)
            except Cancelled:
                try:
                    self._cancel()
                except Exception:
                    self._attention("stop_unconfirmed")
            except Exception:
                try:
                    self._stop()
                except Exception:
                    self._attention("stop_unconfirmed")
                else:
                    self._attention("execution_uncertain")
            finally:
                try:
                    self._stop()
                except Exception:
                    self._attention("stop_unconfirmed")
            return self.job

    def _verify(self, *, recovery):
        self._renew()
        result = self.driver.verify(self.job.spec)  # Read-only, including recovery.
        self._check()
        if (
            self.job.spec.mode == "simulation"
            and not recovery
            and result.reason_code == "simulation_only"
            and not result.evidence
        ):
            self._event("completed")
        elif self.job.spec.mode == "device" and result.status == "valid":
            self._event("succeeded", evidence=result.evidence)
        else:
            self._attention("verification_pending")
