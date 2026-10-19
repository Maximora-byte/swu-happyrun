"""Synthetic runner-level QA only; no HTTP, device, or school acceptance claim.

Default: print the observed result and check the reproduction's prerequisites.
--expect-recovery-completed: additionally assert the contract's expected outcome.
--expect-persisted-agent-rejected: change only a synthetic persisted binding before
reconstruction; require fail-closed recovery without replacing its provenance.
All generated profiles, the journal, and fake state use a temporary directory.
"""

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    expectation = parser.add_mutually_exclusive_group()
    expectation.add_argument("--expect-recovery-completed", action="store_true")
    expectation.add_argument("--expect-persisted-agent-rejected", action="store_true")
    args = parser.parse_args()
    root = args.source_root.resolve(strict=True)
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(root / "src"))

    from swu_happyrun.agent.journal import RunJournal
    from swu_happyrun.agent.runner import AgentRunner
    from swu_happyrun.core.profiles import LocalProfileStore
    from swu_happyrun.drivers.fake import FakeDriver

    from swu_happyrun.core.canonical import profile_revision
    from swu_happyrun.core.models import JobSpec, JobView, LeaseGrant, RouteProfile, SchoolProfile
    from swu_happyrun.core.states import transition_allowed

    class Clock:
        def utcnow(self):
            return datetime(2026, 10, 18, tzinfo=UTC)

        def monotonic(self):
            return 0.0

    class RecoveryControl:
        """A preapproved recovery grant; this reproduces runner logic, not HTTP."""

        def __init__(self, view):
            self.job, self.states = view, []

        def claim(self, device_id):
            assert device_id == self.job.spec.device_id
            return LeaseGrant(
                job=self.job,
                lease_token="synthetic-local-only",
                fence=self.job.fence,
                expires_at=clock.utcnow() + timedelta(seconds=30),
            )

        def renew(self, job_id, lease):
            assert job_id == self.job.job_id and lease.fence == self.job.fence
            return {"expires_at": clock.utcnow() + timedelta(seconds=30), "desired_state": "run"}

        def get_job(self, job_id):
            assert job_id == self.job.job_id
            return self.job

        def events(self, job_id, lease, event):
            assert job_id == self.job.job_id and lease.fence == self.job.fence
            assert event.expected_revision == self.job.revision
            assert transition_allowed(self.job.state, event.state, self.job.spec.mode)
            self.states.append(event.state.value)
            self.job = JobView.model_validate(
                {
                    **self.job.model_dump(mode="python"),
                    "state": event.state,
                    "revision": self.job.revision + 1,
                    "reason_code": event.reason_code,
                    "resume_phase": event.resume_phase,
                }
            )
            return self.job

    clock = Clock()
    with tempfile.TemporaryDirectory(prefix="happyrun-finished-recovery-") as directory:
        private = Path(directory)
        school = SchoolProfile(
            profile_id=str(uuid4()),
            revision="0" * 64,
            campus="synthetic",
            app_package="test.fake",
            app_version="test-1",
            confirmed=True,
            allowed_region=[
                {"longitude": x, "latitude": y} for x, y in [(0, 0), (1, 0), (1, 1), (0, 1)]
            ],
            rules={
                "minimum_distance_m": 1.0,
                "maximum_duration_seconds": 100.0,
                "minimum_speed_mps": 0.0,
                "maximum_speed_mps": 2.0,
            },
            checkpoint_source="manual_confirmed",
        )
        route = RouteProfile(
            route_id=str(uuid4()),
            revision="0" * 64,
            input_crs="WGS84",
            points=[{"longitude": 0.2, "latitude": 0.2}, {"longitude": 0.20002, "latitude": 0.2}],
            source_ref="synthetic-only",
        )
        for folder, model, identifier in [
            ("schools", school, school.profile_id),
            ("routes", route, route.route_id),
        ]:
            model.revision = profile_revision(model)
            path = private / "profiles" / folder / identifier / f"{model.revision}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(model.model_dump_json(), encoding="utf-8")
        spec = JobSpec(
            protocol_version=1,
            mode="simulation",
            expected_app_version=None,
            profile_id=school.profile_id,
            profile_revision=school.revision,
            route_id=route.route_id,
            route_revision=route.revision,
            device_id=str(uuid4()),
            not_before=clock.utcnow(),
            deadline=clock.utcnow() + timedelta(hours=1),
        )
        view = JobView(
            job_id=str(uuid4()),
            spec=spec,
            state="leased",
            revision=1,
            desired_state="run",
            fence=1,
            agent_id=str(uuid4()),
            reason_code=None,
            resume_phase=None,
            recovery_action=None,
            run_session_id=str(uuid4()),
        )
        options = {"app_version": school.app_version, "state_path": private / "fake.json"}
        store = LocalProfileStore(private / "profiles")
        first = FakeDriver(spec.device_id, store, **options)
        first.bind_session(view)
        first.prepare(spec)
        first.bind_session(
            JobView.model_validate(
                {
                    **view.model_dump(mode="python"),
                    "state": "running",
                    "revision": 4,
                }
            )
        )
        with RunJournal(private / "journal.sqlite") as journal:
            journal.record_intent(view.job_id, view.fence, "start")
            first.start(spec)
            first.tick(spec, 2.0)
            first.stop()
            before_restart = first.verify(spec)
            assert before_restart.reason_code == "simulation_only" and not before_restart.evidence
            persisted_agent = view.agent_id
            if args.expect_persisted_agent_rejected:
                # Deliberately inconsistent synthetic input; no real account or device.
                state_path = options["state_path"]
                state = json.loads(state_path.read_text(encoding="utf-8"))
                persisted_agent = str(uuid4())
                assert persisted_agent != view.agent_id
                state["bound_view"]["agent_id"] = persisted_agent
                state_path.write_text(json.dumps(state), encoding="utf-8")
            # Model a restart after finishing/stopping but before reporting completion.
            control = RecoveryControl(
                JobView.model_validate(
                    {
                        **view.model_dump(mode="python"),
                        "fence": 2,
                        "revision": 8,
                        "recovery_action": "verify_only",
                        "resume_phase": "verifying",
                    }
                )
            )
            recovered = FakeDriver(spec.device_id, store, **options)
            after_restart = recovered.verify(spec)
            assert after_restart.reason_code == "simulation_only" and not after_restart.evidence
            result = AgentRunner(
                control,
                recovered,
                journal,
                clock,
                device_id=spec.device_id,
            ).run_once()
            observed = {
                "tested_commit": subprocess.check_output(
                    ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
                ).strip(),
                "scope": "synthetic_runner_only",
                "finished_before_restart": before_restart.reason_code,
                "finished_after_restart": after_restart.reason_code,
                "recovery_states": control.states,
                "final_state": result.state.value,
                "reason": result.reason_code,
                "start_count": recovered.start_count,
                "tick_count": recovered.tick_count,
                "stop_count": recovered.stop_count,
                "persisted_agent_before_rebind": persisted_agent,
                "authorized_agent": view.agent_id,
                "expected": (
                    "reject mismatching persisted agent before completion"
                    if args.expect_persisted_agent_rejected
                    else "completed after verify_only; no additional start, tick, or upload"
                ),
            }
            print(json.dumps(observed, sort_keys=True), flush=True)
            assert recovered.start_count == 1 and recovered.tick_count == 1
            assert not journal.has_intent(view.job_id, "upload")
            if args.expect_recovery_completed:
                assert result.state == "completed", (
                    f"Expected completed for the finished/stopped recovered simulation; "
                    f"observed {result.state.value}/{result.reason_code}"
                )
            if args.expect_persisted_agent_rejected:
                assert result.state != "completed", (
                    "Mismatching persisted agent was overwritten before completion proof"
                )
                persisted = json.loads(options["state_path"].read_text(encoding="utf-8"))
                assert persisted["bound_view"]["agent_id"] == persisted_agent, (
                    "Recovery replaced the mismatching historical agent"
                )


if __name__ == "__main__":
    main()
