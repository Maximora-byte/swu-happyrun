"""Transactional ownership, fencing, recovery approvals and event application."""

import hashlib
import json
import secrets
from datetime import datetime, timedelta
from uuid import uuid4

from swu_happyrun.core.models import DeviceCapability, JobView, LeaseGrant
from swu_happyrun.core.states import transition_allowed
from swu_happyrun.server.errors import ApiError

TERMINAL = {"completed", "succeeded", "failed", "cancelled"}
REQUIRED = {"location_read", "location_write", "sensor_probe", "app_ui", "record_read"}


def canonical(value):
    data = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def conflict(message="State or lease conflict"):
    raise ApiError(409, "conflict", message)


class LeaseOperations:
    def _view(self, db, job_id):
        row = db.execute("SELECT view_json FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise ApiError(404, "not_found", "Resource not found")
        return JobView.model_validate_json(row[0])

    def _save(self, db, view, **changes):
        data = view.model_dump() | changes | {"revision": view.revision + 1}
        updated = JobView.model_validate(data)
        db.execute(
            "UPDATE jobs SET view_json=? WHERE job_id=?", (updated.model_dump_json(), view.job_id)
        )
        return updated

    def _runtime(self, db, job_id):
        return db.execute("SELECT * FROM runtime WHERE job_id=?", (job_id,)).fetchone()

    def _release(self, db, view):
        db.execute(
            "UPDATE devices SET reservation=NULL WHERE device_id=? AND reservation=?",
            (view.spec.device_id, view.job_id),
        )

    def _invalidate(self, db, view):
        db.execute(
            "UPDATE runtime SET token_hash=NULL, expires_at=NULL, pending_action=NULL, "
            "active_action=NULL WHERE job_id=?",
            (view.job_id,),
        )

    def expire(self):
        with self.connection(write=True) as db:
            self._expire(db)

    def _expire(self, db):
        now = self.clock.utcnow()
        for row in db.execute("SELECT view_json FROM jobs").fetchall():
            view = JobView.model_validate_json(row[0])
            if view.state in TERMINAL:
                continue
            rt = self._runtime(db, view.job_id)
            if view.state == "queued" and now >= view.spec.deadline:
                self._save(db, view, state="failed", reason_code="window_expired")
                self._release(db, view)
            elif rt["expires_at"] and now >= datetime.fromisoformat(rt["expires_at"]):
                safe = (
                    not rt["started"]
                    and not rt["active_action"]
                    and view.desired_state == "run"
                    and view.state in {"leased", "preflight", "ready"}
                )
                if safe:
                    self._save(
                        db,
                        view,
                        state="queued",
                        reason_code="lease_expired",
                        resume_phase=None,
                        recovery_action=None,
                    )
                    self._release(db, view)
                else:
                    self._save(
                        db,
                        view,
                        state="needs_attention",
                        reason_code="stop_unconfirmed"
                        if view.desired_state == "cancel"
                        else "lease_expired",
                        resume_phase=(view.resume_phase or view.state.value)
                        if rt["active_action"] in {"verify_only", "stop_only"}
                        else view.state.value,
                        recovery_action=None,
                    )
                self._invalidate(db, view)

    def register_device(self, registration):
        with self.connection(write=True) as db:
            if db.execute(
                "SELECT 1 FROM devices WHERE device_id=?", (registration.device_id,)
            ).fetchone():
                conflict("Device already registered")
            db.execute(
                "INSERT INTO devices(device_id,agent_id) VALUES (?,?)",
                (registration.device_id, registration.agent_id),
            )
        return registration

    def list_devices(self):
        with self.connection() as db:
            return [
                dict(row)
                for row in db.execute("SELECT device_id,agent_id FROM devices ORDER BY device_id")
            ]

    def _device(self, db, device_id, agent_id):
        row = db.execute(
            "SELECT * FROM devices WHERE device_id=? AND agent_id=?", (device_id, agent_id)
        ).fetchone()
        if row is None:
            raise ApiError(404, "not_found", "Resource not found")
        return row

    def observe_agent(self, hello, *, heartbeat=False):
        with self.connection(write=True) as db:
            # Preflight DB and in-batch identities before writing any observation.
            batch_probes: dict[str, str] = {}
            for report in hello.devices:
                self._device(db, report.device_id, hello.agent_id)
                if not heartbeat:
                    payload = canonical(report)
                    if report.probe_id in batch_probes and batch_probes[report.probe_id] != payload:
                        conflict("Probe identifier already used")
                    batch_probes[report.probe_id] = payload
                    old = db.execute(
                        "SELECT payload FROM probes WHERE probe_id=?", (report.probe_id,)
                    ).fetchone()
                    if old and old[0] != payload:
                        conflict("Probe identifier already used")
            now = self.clock.utcnow().isoformat()
            if not heartbeat:
                for report in hello.devices:
                    exists = db.execute(
                        "SELECT 1 FROM probes WHERE probe_id=?", (report.probe_id,)
                    ).fetchone()
                    if not exists:
                        db.execute(
                            "INSERT INTO probes VALUES (?,?,?,?)",
                            (report.probe_id, report.device_id, batch_probes[report.probe_id], now),
                        )
                        db.execute(
                            "UPDATE devices SET current_probe=? WHERE device_id=?",
                            (report.probe_id, report.device_id),
                        )
            db.execute(
                "INSERT INTO agents VALUES (?,?,?) ON CONFLICT(agent_id) DO UPDATE "
                "SET hello_json=excluded.hello_json,received_at=excluded.received_at",
                (hello.agent_id, hello.model_dump_json(), now),
            )

    def _capable(self, db, device, view, action):
        if action == "stop_only":
            return True
        if action == "verify_only" and view.spec.mode == "simulation":
            return True
        row = db.execute(
            "SELECT payload,received_at FROM probes WHERE probe_id=?", (device["current_probe"],)
        ).fetchone()
        if row is None:
            return False
        age = (self.clock.utcnow() - datetime.fromisoformat(row["received_at"])).total_seconds()
        if not 0 <= age < 30:
            return False
        report = DeviceCapability.model_validate_json(row["payload"])
        if view.spec.mode == "simulation":
            return report.backend == "fake" and not set(report.capabilities) & {
                "location_write",
                "sensor_probe",
                "app_ui",
            }
        required = {"record_read"} if action == "verify_only" else REQUIRED
        return (
            report.backend in {"mumu", "android"}
            and report.app_version == view.spec.expected_app_version
            and required <= set(report.capabilities)
        )

    def claim(self, agent_id, device_id):
        self.expire()
        with self.connection(write=True) as db:
            self._expire(db)
            device = self._device(db, device_id, agent_id)
            rows = db.execute("SELECT view_json FROM jobs ORDER BY created_at,job_id").fetchall()
            for row in rows:
                view = JobView.model_validate_json(row[0])
                if view.spec.device_id != device_id:
                    continue
                rt = self._runtime(db, view.job_id)
                recovery = view.state == "needs_attention" and rt["pending_action"]
                if not recovery and view.state != "queued":
                    continue
                if device["reservation"] not in (None, view.job_id):
                    continue
                action = rt["pending_action"] if recovery else None
                if recovery and view.agent_id != agent_id:
                    continue
                if view.desired_state == "cancel" and action != "stop_only":
                    continue
                if action not in {"verify_only", "stop_only"} and not (
                    view.spec.not_before <= self.clock.utcnow() < view.spec.deadline
                ):
                    continue
                if action == "retry_preflight" and rt["started"]:
                    continue
                if not self._capable(db, device, view, action):
                    continue
                token = secrets.token_urlsafe(32)
                expires = self.clock.utcnow() + timedelta(seconds=30)
                fence = device["fence"] + 1
                view = self._save(
                    db,
                    view,
                    state="leased",
                    agent_id=agent_id,
                    fence=fence,
                    run_session_id=view.run_session_id or str(uuid4()),
                    recovery_action=action,
                    reason_code=None,
                )
                db.execute(
                    "UPDATE devices SET fence=?,reservation=? WHERE device_id=?",
                    (fence, view.job_id, device_id),
                )
                db.execute(
                    "UPDATE runtime SET token_hash=?,expires_at=?,pending_action=NULL,"
                    "active_action=? WHERE job_id=?",
                    (digest(token), expires.isoformat(), action, view.job_id),
                )
                return LeaseGrant(job=view, lease_token=token, fence=fence, expires_at=expires)
            return None

    def _lease(self, db, job_id, agent_id, lease):
        view = self._view(db, job_id)
        if view.agent_id != agent_id:
            raise ApiError(404, "not_found", "Resource not found")
        device = self._device(db, view.spec.device_id, agent_id)
        rt = self._runtime(db, job_id)
        if (
            device["fence"] != lease.fence
            or view.fence != lease.fence
            or rt["token_hash"] != digest(lease.lease_token)
            or not rt["expires_at"]
            or self.clock.utcnow() >= datetime.fromisoformat(rt["expires_at"])
        ):
            conflict()
        return view, rt

    def renew(self, job_id, agent_id, lease):
        self.expire()
        with self.connection(write=True) as db:
            view, _ = self._lease(db, job_id, agent_id, lease)
            if view.state in TERMINAL or view.state == "needs_attention":
                conflict()
            expires = self.clock.utcnow() + timedelta(seconds=30)
            db.execute(
                "UPDATE runtime SET expires_at=? WHERE job_id=?", (expires.isoformat(), job_id)
            )
            return {
                "expires_at": expires.isoformat().replace("+00:00", "Z"),
                "desired_state": view.desired_state,
            }

    def cancel(self, job_id):
        self.expire()
        with self.connection(write=True) as db:
            view = self._view(db, job_id)
            if view.state in TERMINAL or view.desired_state == "cancel":
                return view
            if view.state == "queued":
                result = self._save(db, view, state="cancelled", desired_state="cancel")
                self._release(db, view)
                self._invalidate(db, view)
            elif view.state == "needs_attention":
                result = self._save(
                    db,
                    view,
                    desired_state="cancel",
                    recovery_action=None,
                    reason_code="stop_unconfirmed",
                )
                self._invalidate(db, view)
            else:
                result = self._save(
                    db,
                    view,
                    state="cancelling",
                    desired_state="cancel",
                    recovery_action="stop_only",
                )
                db.execute(
                    "UPDATE runtime SET pending_action=NULL,active_action=? WHERE job_id=?",
                    ("stop_only", job_id),
                )
            return result

    def resume(self, job_id, expected_revision, action):
        self.expire()
        with self.connection(write=True) as db:
            view = self._view(db, job_id)
            rt = self._runtime(db, job_id)
            if view.state != "needs_attention" or view.revision != expected_revision:
                conflict()
            if view.desired_state == "cancel" and action != "stop_only":
                conflict()
            if action == "retry_preflight" and rt["started"]:
                conflict()
            if action not in {"retry_preflight", "verify_only", "stop_only"}:
                conflict()
            result = self._save(
                db,
                view,
                recovery_action=action,
                desired_state="cancel" if action == "stop_only" else view.desired_state,
            )
            self._invalidate(db, view)
            db.execute("UPDATE runtime SET pending_action=? WHERE job_id=?", (action, job_id))
            return result

    def _replay(self, db, view, event_id, fingerprint):
        row = db.execute(
            "SELECT fingerprint,result FROM events WHERE job_id=? AND event_id=?",
            (view.job_id, event_id),
        ).fetchone()
        if row:
            if row["fingerprint"] != fingerprint:
                conflict("Event identifier already used")
            return JobView.model_validate_json(row["result"])
        return None

    def _remember(self, db, result, event_id, fingerprint):
        db.execute(
            "INSERT INTO events VALUES (?,?,?,?)",
            (result.job_id, event_id, fingerprint, result.model_dump_json()),
        )
        return result

    def _evidence(self, db, view, event):
        statuses = {}
        digest_statuses = {}
        for item in event.evidence:
            if item.kind != "app_record":
                continue
            if (
                view.spec.mode != "device"
                or item.job_id != view.job_id
                or item.run_session_id != view.run_session_id
                or item.profile_revision != view.spec.profile_revision
                or item.app_version != view.spec.expected_app_version
            ):
                conflict("Record binding does not match job")
            key = (item.record_namespace, item.record_id)
            if key in statuses and statuses[key] != item.record_status:
                conflict("Contradictory record status")
            statuses[key] = item.record_status
            if (
                item.sha256 in digest_statuses
                and digest_statuses[item.sha256] != item.record_status
            ):
                conflict("Contradictory artifact status")
            digest_statuses[item.sha256] = item.record_status
            owner = db.execute(
                "SELECT job_id FROM records WHERE namespace=? AND record_id=?", key
            ).fetchone()
            artifact = db.execute(
                "SELECT job_id FROM record_digests WHERE digest=?", (item.sha256,)
            ).fetchone()
            if (owner and owner[0] != view.job_id) or (artifact and artifact[0] != view.job_id):
                conflict("Record already belongs to another job")
        # All evidence validated first; inserts and event result share the same transaction.
        for item in event.evidence:
            if item.kind == "app_record":
                db.execute(
                    "INSERT OR IGNORE INTO records VALUES (?,?,?)",
                    (item.record_namespace, item.record_id, view.job_id),
                )
                db.execute(
                    "INSERT OR IGNORE INTO record_digests VALUES (?,?)", (item.sha256, view.job_id)
                )

    def event(self, job_id, agent_id, lease, event):
        self.expire()
        with self.connection(write=True) as db:
            view, rt = self._lease(db, job_id, agent_id, lease)
            fingerprint = digest(
                canonical(
                    {
                        "op": "event",
                        "lease_digest": digest(lease.lease_token),
                        "fence": lease.fence,
                        "event": event.model_dump(mode="json"),
                    }
                )
            )
            replay = self._replay(db, view, event.event_id, fingerprint)
            if replay:
                return replay
            if view.revision != event.expected_revision or view.state in TERMINAL:
                conflict()
            target = event.state
            action = rt["active_action"]
            if target in {"cancelled", "queued", "leased"} or not transition_allowed(
                view.state, target, view.spec.mode
            ):
                conflict()
            if view.desired_state == "cancel" and target not in {"cancelling", "needs_attention"}:
                conflict()
            if action == "stop_only" and target not in {"cancelling", "needs_attention"}:
                conflict()
            if action == "verify_only" and target not in {
                "verifying",
                "completed",
                "succeeded",
                "needs_attention",
            }:
                conflict()
            if view.state == "leased" and target == "verifying" and action != "verify_only":
                conflict()
            if target == "running" and not (
                view.spec.not_before <= self.clock.utcnow() < view.spec.deadline
            ):
                conflict("Start window expired")
            if target == "failed" and rt["started"]:
                conflict("Possibly active execution requires attention")
            if target == "needs_attention" and event.resume_phase != (
                view.resume_phase
                if action in {"verify_only", "stop_only"} and view.resume_phase
                else view.state.value
            ):
                conflict("Recovery phase must preserve current execution context")
            if target != "needs_attention" and event.resume_phase is not None:
                conflict("Unexpected recovery phase")
            self._evidence(db, view, event)
            result = self._save(
                db,
                view,
                state=target,
                reason_code=event.reason_code,
                resume_phase=event.resume_phase
                if target == "needs_attention"
                else view.resume_phase,
                recovery_action=None
                if target in TERMINAL or target == "needs_attention"
                else view.recovery_action,
            )
            if target == "running":
                db.execute("UPDATE runtime SET started=1 WHERE job_id=?", (job_id,))
            if target == "needs_attention":
                self._invalidate(db, view)
            if target in TERMINAL:
                self._release(db, view)
            return self._remember(db, result, event.event_id, fingerprint)

    def stop_ack(self, job_id, agent_id, request):
        self.expire()
        with self.connection(write=True) as db:
            view, _ = self._lease(db, job_id, agent_id, request.lease)
            fingerprint = digest(
                canonical(
                    {
                        "op": "stop_ack",
                        "fence": request.lease.fence,
                        "lease_digest": digest(request.lease.lease_token),
                        "event_id": request.event_id,
                        "expected_revision": request.expected_revision,
                    }
                )
            )
            replay = self._replay(db, view, request.event_id, fingerprint)
            if replay:
                return replay
            if (
                view.state != "cancelling"
                or view.desired_state != "cancel"
                or view.revision != request.expected_revision
            ):
                conflict()
            result = self._save(db, view, state="cancelled", recovery_action=None, reason_code=None)
            self._release(db, view)
            return self._remember(db, result, request.event_id, fingerprint)
