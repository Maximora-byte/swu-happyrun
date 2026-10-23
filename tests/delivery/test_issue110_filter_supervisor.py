"""Portable host-seam tests. No CreateProcess, Windows, V6 or native host runs.

The real Task 3 owner is prepared using its explicitly synthetic fixture seam.
unittest assertions are also collected unchanged by pytest when it is installed.
"""

import importlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from test_issue110_filter_bundle import FakeBundleAPI, identity
from test_issue110_filter_bundle import module as bundle_module
from test_issue110_filter_contract import document, encoded

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts/diagnostics"
MODULE = SCRIPTS / "issue110_filter_supervisor.py"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
contract = importlib.import_module("issue110_filter_contract")


def module():
    assert MODULE.is_file(), "missing single-attempt host supervisor"
    return importlib.import_module("issue110_filter_supervisor")


class Handle:
    def __init__(self, name):
        self.name = name


class FakeHostAPI:
    """Opaque owned resources and controlled clocks, not a Win32 implementation."""

    def __init__(self, s, owner, bundle_api):
        self.s, self.owner, self.bundle_api = s, owner, bundle_api
        self.events, self.opened, self.closed, self.cleanup_deadlines = [], [], [], []
        self.job, self.attributes = Handle("job"), Handle("attributes")
        self.process, self.thread = Handle("process"), Handle("thread")
        self.unsupported = None
        self.creation = self.resumption = True
        self.wrong_image = False
        self.signal_at, self.exit_code = 11.0, 0
        self.errors, self.elapsed = {}, {}
        self.lengths = {}
        self.bad_result = None
        self.complete = True
        self.cleanup_result, self.close_result = True, True
        self.intent_result = True

    def now(self):
        return self.bundle_api.time

    def event(self, label, *args, **kwargs):
        self.events.append((label, args, kwargs))
        self.bundle_api.time += self.elapsed.get(label, 0)
        if label in self.errors:
            raise self.errors[label]

    def own(self, value):
        self.opened.append(value)
        return value

    def prepare_job(self, **kwargs):
        self.event("job", **kwargs)
        return None if self.unsupported == "job" else self.own(self.job)

    def exclusive_transport(self, directory, request, **kwargs):
        self.event("transport", directory, request, **kwargs)
        self.request = contract.parse_request(request)
        self.transport = self.s.TransportHandles(
            *(
                self.own(Handle(name))
                for name in (
                    "request_read",
                    "result_write",
                    "stdout_write",
                    "stderr_write",
                    "result_read",
                    "stdout_read",
                    "stderr_read",
                )
            )
        )
        return self.transport

    def prepare_attributes(self, job, inheritance, **kwargs):
        self.event("attributes", job, inheritance, **kwargs)
        return (
            None if self.unsupported in ("job_list", "handle_list") else self.own(self.attributes)
        )

    def persist_create_intent(self, directory, record, **kwargs):
        self.event("intent", directory, record, **kwargs)
        return self.intent_result

    def create_suspended(self, **kwargs):
        self.event("create", **kwargs)
        if self.creation is False:
            return self.s.CreationResult(False)
        return self.s.CreationResult(
            self.creation, self.own(self.process), self.own(self.thread), 4242
        )

    def image_identity(self, process, **kwargs):
        self.event("image", process, **kwargs)
        return identity(99999) if self.wrong_image else self.owner.stage_files[0][1].identity

    def resume_once(self, thread, **kwargs):
        self.event("resume", thread, **kwargs)
        return self.resumption

    def poll_exit(self, process, **kwargs):
        self.event("poll", process, **kwargs)
        signaled = self.signal_at is not None and self.now() >= self.signal_at
        return self.s.ExitState(signaled, self.exit_code if signaled else None)

    def wait(self, process, *, deadline):
        self.event("wait", process, deadline=deadline)
        self.bundle_api.time = max(self.now(), min(self.signal_at or deadline, deadline))
        return self.signal_at is not None and self.now() >= self.signal_at

    def capsule(self):
        if self.bad_result is not None:
            return self.bad_result
        doc = document()
        doc["nonce"] = self.request.nonce
        if self.complete:
            command = b"$$>a<C:\\SWU_ISSUE110_SYNTHETIC\\terminal.cdb\0"
            for key in ("getter_a", "getter_b"):
                doc[key] = {
                    "valid": True,
                    "hresult": 0,
                    "reported_length": len(command),
                    "bytes_hex": command.hex(),
                }
            doc.update(
                stage="observations_complete",
                observations_complete=True,
                engine_creation_attempted=True,
                a_expected="equal",
                b_expected="equal",
                ab_stability="equal",
            )
            doc["sx"] = {"bytes_hex": "410a", "overflow": False, "association": "associated"}
            doc["release"]["all_owned_release_calls_issued"] = True
            doc["release"]["detach_hresult"] = 0
        return encoded(doc)

    def read_length(self, handle, **kwargs):
        self.event("length", handle, **kwargs)
        return self.lengths.get(
            handle.name, len(self.capsule()) if handle.name == "result_read" else 0
        )

    def read_result(self, handle, **kwargs):
        self.event("read", handle, **kwargs)
        return self.capsule()

    def terminate_owned(self, job, process, *, deadline):
        self.cleanup_deadlines.append(deadline)
        self.event("terminate", job, process, deadline=deadline)
        # Forced code is deliberately different; no later poll may naturalize it.
        self.exit_code, self.signal_at = 0xBAD, self.now()
        return self.cleanup_result

    def drain_pending(self, *, deadline):
        self.cleanup_deadlines.append(deadline)
        self.event("drain", deadline=deadline)
        return True

    def close(self, handle, *, deadline):
        self.cleanup_deadlines.append(deadline)
        self.closed.append(handle)
        self.event("close", handle, deadline=deadline)
        return self.close_result

    def calls(self, name):
        return [event for event in self.events if event[0] == name]


class FilterSupervisorTests(unittest.TestCase):
    def fake(self, *, deadline=300.0):
        s, b = module(), bundle_module()
        bundle_api = FakeBundleAPI(b)
        with patch.object(b, "DEBUGGER_HASHES", bundle_api.hashes):
            owner = b.prepare_bundle(bundle_api.build, r"C:\private", deadline, bundle_api)
        api = FakeHostAPI(s, owner, bundle_api)
        return s, owner, api

    def observe(self, *, deadline=300.0, **changes):
        s, owner, api = self.fake(deadline=deadline)
        for key, value in changes.items():
            setattr(api, key, value)
        return s.observe_once(owner, deadline, api), owner, api

    def test_insufficient_full_window_never_creates(self):
        obs, owner, api = self.observe(deadline=24.999)
        self.assertEqual(obs.blocker, contract.Blocker.DEADLINE)
        self.assertEqual(api.calls("create"), [])
        self.assertFalse(obs.create_intent)
        self.assertFalse(obs.host_execution_attempted)
        self.assertTrue(owner.closed)

    def test_job_and_attribute_preflight_unsupported_means_zero_create(self):
        for unsupported in ("job", "job_list", "handle_list"):
            with self.subTest(unsupported=unsupported):
                obs, _, api = self.observe(unsupported=unsupported)
                self.assertEqual(obs.blocker, contract.Blocker.UNSUPPORTED)
                self.assertFalse(obs.create_intent)
                self.assertEqual(api.calls("create"), [])

    def test_createprocess_only_failure_is_a_real_attempt_without_fallback(self):
        obs, _, api = self.observe(creation=False)
        self.assertTrue(obs.create_intent)
        self.assertIs(obs.create_succeeded, False)
        self.assertEqual(obs.blocker, contract.Blocker.CREATE_FAILED)
        self.assertEqual(len(api.calls("create")), 1)
        self.assertEqual(api.calls("resume"), [])
        self.assertFalse(obs.host_execution_attempted)
        self.assertFalse(obs.engine_creation_attempted)

    def test_wrong_image_is_never_resumed(self):
        obs, _, api = self.observe(wrong_image=True)
        self.assertEqual(obs.blocker, contract.Blocker.IMAGE_MISMATCH)
        self.assertTrue(obs.create_succeeded)
        self.assertEqual(api.calls("resume"), [])
        self.assertEqual(api.calls("terminate")[0][1], (api.job, api.process))

    def test_fixed_application_one_job_and_exact_least_privilege_inheritance(self):
        obs, owner, api = self.observe()
        job = api.calls("job")
        self.assertEqual(len(job), 1)
        self.assertEqual(
            job[0][2],
            {
                "name": None,
                "kill_on_close": True,
                "active_process_limit": 1,
                "breakaway": False,
                "inheritable": False,
                "deadline": 300.0,
            },
        )
        attributes = api.calls("attributes")[0]
        grants = attributes[1][1]
        self.assertEqual(
            [(g.role, g.access) for g in grants],
            [("request", "read"), ("result", "write"), ("stdout", "write"), ("stderr", "write")],
        )
        self.assertEqual(
            tuple(g.handle for g in grants),
            (
                api.transport.request_read,
                api.transport.result_write,
                api.transport.stdout_write,
                api.transport.stderr_write,
            ),
        )
        self.assertIsNone(attributes[2]["stdin"])
        create = api.calls("create")[0][2]
        self.assertEqual(
            create["application_name"],
            owner.stage_path + "\\" + "issue110_filter_command_probe.exe",
        )
        self.assertTrue(create["suspended"])
        self.assertTrue(create["inherit_handles"])
        self.assertEqual(create["working_directory"], owner.stage_path)
        self.assertIs(create["attributes"], api.attributes)
        self.assertIsNone(create["stdin"])
        self.assertEqual(len(api.calls("resume")), 1)
        self.assertTrue(obs.host_execution_attempted)
        self.assertTrue(obs.engine_creation_attempted)

    def test_request_uses_only_existing_contract_and_pinned_stage_bindings(self):
        _, owner, api = self.observe()
        request = api.request
        self.assertEqual(request.manifest_sha256, owner.manifest_sha256)
        self.assertEqual(
            (request.exe, request.dbgeng, request.dbghelp),
            tuple(bound for _, bound in owner.stage_files),
        )
        transport = api.calls("transport")[0]
        self.assertEqual(transport[1][0], r"C:\private\issue110-filter-probe-1")
        self.assertIs(transport[2]["exclusive"], True)
        self.assertNotIn("command", json.loads(transport[1][1]))

    def test_flushed_intent_precedes_create_and_uncertain_intent_stops(self):
        _, _, api = self.observe()
        kinds = [event[0] for event in api.events]
        self.assertLess(kinds.index("intent"), kinds.index("create"))
        record = json.loads(api.calls("intent")[0][1][1])
        self.assertTrue(record["host_invocation_attempted"])
        self.assertFalse(record["reservation_is_authorization"])
        obs, _, api = self.observe(intent_result=None)
        self.assertEqual(obs.blocker, contract.Blocker.IO_FAILURE)
        self.assertEqual(api.calls("create"), [])
        self.assertIsNone(obs.host_owned_cleanup)

    def test_ambiguous_create_and_resume_never_retry(self):
        for field, blocker, host in (
            ("creation", contract.Blocker.CREATE_UNCERTAIN, False),
            ("resumption", contract.Blocker.RESUME_UNCERTAIN, None),
        ):
            with self.subTest(field=field):
                obs, _, api = self.observe(**{field: None})
                self.assertEqual(obs.blocker, blocker)
                self.assertEqual(len(api.calls("create")), 1)
                self.assertLessEqual(len(api.calls("resume")), 1)
                self.assertIs(obs.host_execution_attempted, host)
                self.assertIs(obs.engine_creation_attempted, False if host is False else None)
                self.assertEqual(set(api.opened), set(api.closed))

    def test_resume_failed_is_not_host_execution(self):
        obs, _, api = self.observe(resumption=False)
        self.assertTrue(obs.resume_intent)
        self.assertFalse(obs.resume_succeeded)
        self.assertEqual(obs.blocker, contract.Blocker.RESUME_FAILED)
        self.assertFalse(obs.host_execution_attempted)
        self.assertEqual(len(api.calls("resume")), 1)

    def test_no_receipt_after_resume_leaves_engine_unknown(self):
        obs, _, api = self.observe(signal_at=None)
        self.assertTrue(obs.host_execution_attempted)
        self.assertIsNone(obs.engine_creation_attempted)
        self.assertIsNone(obs.child_result_valid)
        self.assertIs(obs.child_exit_before_cleanup, False)
        self.assertIsNone(obs.natural_exit_code)
        self.assertEqual(api.calls("read"), [])

    def test_valid_capsule_at_deadline_is_not_complete(self):
        for signal_at, accepted in ((24.999, True), (25.0, False), (25.001, False)):
            with self.subTest(signal_at=signal_at):
                obs, _, api = self.observe(signal_at=signal_at)
                public = contract.public_projection(obs)
                self.assertEqual(public["observation_complete"], accepted)
                self.assertEqual(obs.host_deadline, 25.0)
                if signal_at <= 25.0:
                    self.assertTrue(obs.child_result_valid)
                    self.assertEqual(obs.natural_exit_code, 0)
                else:
                    self.assertEqual(api.calls("read"), [])

    def test_parse_finishing_after_H_retains_valid_facts_not_completeness(self):
        for end in (24.999, 25.0, 25.001):
            obs, _, _ = self.observe(signal_at=24.0, elapsed={"read": end - 24.0})
            self.assertTrue(obs.child_result_valid)
            self.assertTrue(obs.child_exit_before_cleanup)
            self.assertEqual(obs.observed_at, end)
            self.assertEqual(contract.public_projection(obs)["observation_complete"], end < 25.0)

    def test_final_projection_strict_D_does_not_reset_after_cleanup(self):
        for end in (24.999, 25.0, 25.001):
            # Full host window is exactly available at time 10; observation is at 24.
            obs, _, _ = self.observe(
                deadline=25.0, signal_at=24.0, elapsed={"terminate": end - 24.0}
            )
            self.assertTrue(obs.child_result_valid)
            self.assertEqual(obs.projected_at, end)
            self.assertEqual(obs.overall_deadline, 25.0)
            self.assertEqual(contract.public_projection(obs)["observation_complete"], end < 25.0)

    def test_preflight_time_cannot_leave_less_than_full_window_for_create(self):
        obs, _, api = self.observe(deadline=30.0, elapsed={"attributes": 5.001})
        self.assertEqual(obs.blocker, contract.Blocker.DEADLINE)
        self.assertEqual(api.calls("create"), [])

    def test_final_window_and_H_use_the_same_clock_sample(self):
        # A separate H sample at 11 would silently shorten the admitted window
        # from 15 to 14 seconds. The single admission/H sample must be 10.
        s, owner, api = self.fake(deadline=25.0)
        samples = []

        def now():
            if api.calls("attributes") and not api.calls("intent"):
                api.bundle_api.time = 10.0 if not samples else 11.0
                samples.append(api.bundle_api.time)
            return api.bundle_api.time

        api.now = now
        obs = s.observe_once(owner, 25.0, api)
        self.assertEqual(samples, [10.0])
        self.assertEqual(obs.host_deadline, 25.0)
        self.assertEqual(obs.overall_deadline, 25.0)
        self.assertEqual(len(api.calls("intent")), 1)
        self.assertEqual(len(api.calls("create")), 1)
        self.assertTrue(obs.observation_complete)

    def test_final_window_sample_accepts_equality_but_not_shortage(self):
        for final_time, accepted in ((10.0, True), (10.000001, False), (11.0, False)):
            with self.subTest(final_time=final_time):
                s, owner, api = self.fake(deadline=25.0)

                def now(*, api=api, final_time=final_time):
                    if api.calls("attributes") and not api.calls("intent"):
                        api.bundle_api.time = final_time
                    return api.bundle_api.time

                api.now = now
                obs = s.observe_once(owner, 25.0, api)
                self.assertEqual(len(api.calls("intent")), int(accepted))
                self.assertEqual(len(api.calls("create")), int(accepted))
                self.assertEqual(obs.host_deadline, 25.0 if accepted else None)
                self.assertEqual(
                    obs.blocker, contract.Blocker.NONE if accepted else contract.Blocker.DEADLINE
                )
                self.assertEqual(obs.overall_deadline, 25.0)
                self.assertEqual(
                    len(set(api.cleanup_deadlines + api.bundle_api.close_deadlines)), 1
                )

    def test_creation_consumes_original_H_and_never_receives_a_new_window(self):
        obs, _, api = self.observe(elapsed={"create": 15.0})
        self.assertTrue(obs.create_succeeded)
        self.assertEqual(obs.blocker, contract.Blocker.DEADLINE)
        self.assertEqual(obs.host_deadline, 25.0)
        self.assertEqual(api.calls("resume"), [])

    def test_exit0_capsule_and_owned_cleanup_are_independent(self):
        obs, _, _ = self.observe(bad_result=b"truncated")
        self.assertEqual(obs.natural_exit_code, 0)
        self.assertFalse(obs.child_result_valid)
        self.assertTrue(obs.host_owned_cleanup)
        self.assertFalse(obs.observation_complete)
        obs, _, _ = self.observe(exit_code=7)
        self.assertTrue(obs.child_result_valid)
        self.assertEqual(obs.natural_exit_code, 7)
        self.assertEqual(obs.blocker, contract.Blocker.CHILD_FAILED)
        self.assertFalse(obs.observation_complete)
        obs, _, _ = self.observe(cleanup_result=None)
        self.assertTrue(obs.child_result_valid)
        self.assertTrue(obs.observation_complete)
        self.assertIsNone(obs.host_owned_cleanup)
        self.assertIsNone(obs.signature_cleanup)

    def test_forced_kill_code_is_never_a_natural_exit(self):
        obs, _, api = self.observe(signal_at=None)
        self.assertTrue(api.calls("terminate"))
        self.assertIsNone(obs.natural_exit_code)
        self.assertFalse(obs.child_exit_before_cleanup)
        kinds = [event[0] for event in api.events]
        self.assertNotIn("poll", kinds[kinds.index("terminate") + 1 :])

    def test_result_is_never_read_before_signal_and_is_bounded(self):
        obs, _, api = self.observe()
        kinds = [event[0] for event in api.events]
        self.assertLess(kinds.index("poll"), kinds.index("read"))
        self.assertEqual(api.calls("read")[0][2]["limit"], 262144)
        self.assertTrue(obs.child_result_valid)

    def test_file_overshoot_stops_work_without_disk_hard_cap_claim(self):
        for name, length in (
            ("result_read", 262145),
            ("stdout_read", 65537),
            ("stderr_read", 65537),
        ):
            with self.subTest(name=name):
                obs, _, api = self.observe(lengths={name: length})
                self.assertEqual(obs.blocker, contract.Blocker.OUTPUT_LIMIT)
                self.assertEqual(api.calls("read"), [])
                self.assertFalse(contract.public_projection(obs)["disk_hard_cap"])

    def test_output_threshold_is_inclusive_and_faulty_oversized_read_rejected(self):
        obs, _, _ = self.observe(lengths={"stdout_read": 65536, "stderr_read": 65536})
        self.assertTrue(obs.child_result_valid)
        obs, _, _ = self.observe(bad_result=b"X" * 262145, lengths={"result_read": 100})
        self.assertFalse(obs.child_result_valid)
        self.assertFalse(obs.observation_complete)

    def test_one_cleanup_C_shared_with_bundle_including_partial_create(self):
        for creation in (True, False, None):
            with self.subTest(creation=creation):
                obs, owner, api = self.observe(creation=creation)
                deadlines = api.cleanup_deadlines + api.bundle_api.close_deadlines
                self.assertEqual(len(set(deadlines)), 1)
                self.assertTrue(owner.closed)
                self.assertTrue(obs.host_owned_cleanup)
                self.assertEqual(len(api.closed), len(api.opened))
                self.assertEqual(api.closed, list(reversed(api.opened)))
                self.assertLessEqual(max(deadlines), api.now() + 5.0)

    def test_exhausted_C_never_grants_bundle_another_five_seconds(self):
        obs, owner, api = self.observe(elapsed={"terminate": 5.0})
        self.assertTrue(owner.closed)
        self.assertIsNone(owner.cleanup)
        self.assertIsNone(obs.host_owned_cleanup)
        self.assertEqual(api.closed, [])
        self.assertEqual(api.bundle_api.closed, [])

    def test_primary_cancel_survives_cleanup_exception(self):
        for primary in (KeyboardInterrupt(), SystemExit(7), ValueError("PRIMARY_CANARY")):
            for secondary in (OSError("CLOSE_CANARY"), KeyboardInterrupt(), SystemExit(9)):
                with self.subTest(primary=type(primary), secondary=type(secondary)):
                    s, owner, api = self.fake()
                    api.errors = {"resume": primary, "close": secondary}
                    with self.assertRaises(type(primary)) as caught:
                        s.observe_once(owner, 300.0, api)
                    self.assertIs(caught.exception, primary)
                    observation = caught.exception.host_observation
                    self.assertIsNone(observation.resume_succeeded)
                    self.assertIsNone(observation.host_owned_cleanup)
                    self.assertTrue(owner.closed)
                    self.assertEqual(
                        set(api.cleanup_deadlines + api.bundle_api.close_deadlines), {15.0}
                    )

    def test_cleanup_cancel_is_not_swallowed_after_ordinary_close_error(self):
        s, owner, api = self.fake()
        primary = KeyboardInterrupt()
        errors = iter((OSError("first-close"), primary))

        def close(handle, *, deadline):
            api.cleanup_deadlines.append(deadline)
            api.closed.append(handle)
            error = next(errors, None)
            if error is not None:
                raise error
            return True

        api.close = close
        with self.assertRaises(KeyboardInterrupt) as caught:
            s.observe_once(owner, 300.0, api)
        self.assertIs(caught.exception, primary)
        self.assertIsNone(primary.host_observation.host_owned_cleanup)
        self.assertTrue(owner.closed)

    def test_unexpected_create_exception_is_not_retried_and_preserves_primary(self):
        s, owner, api = self.fake()
        primary = OSError("CREATE_CANARY")
        api.errors = {"create": primary, "close": OSError("secondary")}
        with self.assertRaises(OSError) as caught:
            s.observe_once(owner, 300.0, api)
        self.assertIs(caught.exception, primary)
        self.assertTrue(primary.host_observation.create_intent)
        self.assertIsNone(primary.host_observation.create_succeeded)
        self.assertEqual(len(api.calls("create")), 1)
        self.assertEqual(api.calls("resume"), [])

    def test_closed_bundle_never_replays_host_attempt(self):
        s, owner, api = self.fake()
        s.observe_once(owner, 300.0, api)
        second = s.observe_once(owner, 300.0, api)
        self.assertEqual(second.blocker, contract.Blocker.BUNDLE_REJECTED)
        self.assertEqual(len(api.calls("create")), 1)

    def test_partial_failed_creation_handles_are_owned_and_share_cleanup_C(self):
        s, owner, api = self.fake()

        def create(**kwargs):
            api.event("create", **kwargs)
            return s.CreationResult(False, api.own(api.process), api.own(api.thread), 4242)

        api.create_suspended = create
        obs = s.observe_once(owner, 300.0, api)
        self.assertFalse(obs.create_succeeded)
        self.assertFalse(obs.host_execution_attempted)
        self.assertEqual(api.calls("resume"), [])
        self.assertEqual(api.calls("terminate")[0][1], (api.job, api.process))
        self.assertEqual(api.closed, list(reversed(api.opened)))
        self.assertEqual(set(api.cleanup_deadlines + api.bundle_api.close_deadlines), {15.0})

    def test_bundle_error_from_ownership_calls_never_claims_cleanup(self):
        stages = (
            ("prepare_job", "job"),
            ("exclusive_transport", "transport"),
            ("prepare_attributes", "attributes"),
            ("persist_create_intent", "intent"),
            ("create_suspended", "create"),
        )
        for method, label in stages:
            with self.subTest(method=method):
                s, owner, api = self.fake()
                leaked = Handle("unreturned_" + label)
                error = bundle_module().BundleError(contract.Blocker.RESERVATION_UNCERTAIN)

                def fail(*args, api=api, label=label, leaked=leaked, error=error, **kwargs):
                    api.event(label, *args, **kwargs)
                    api.own(leaked)
                    raise error

                setattr(api, method, fail)
                obs = s.observe_once(owner, 300.0, api)
                self.assertIsNone(obs.host_owned_cleanup)
                self.assertEqual(obs.blocker, contract.Blocker.RESERVATION_UNCERTAIN)
                self.assertTrue(owner.closed)
                self.assertEqual(set(api.opened) - {leaked}, set(api.closed))
                self.assertNotIn(leaked, api.closed)
                self.assertEqual(
                    set(api.cleanup_deadlines + api.bundle_api.close_deadlines), {15.0}
                )
                self.assertEqual(len(api.calls("create")), int(label == "create"))
                self.assertEqual(api.calls("resume"), [])
                self.assertFalse(obs.host_execution_attempted)
                self.assertFalse(obs.engine_creation_attempted)

    def test_successful_creation_missing_owned_handle_keeps_cleanup_unknown(self):
        for missing in ("process", "thread"):
            with self.subTest(missing=missing):
                s, owner, api = self.fake()

                def create(*, api=api, s=s, missing=missing, **kwargs):
                    api.event("create", **kwargs)
                    api.own(api.process)
                    api.own(api.thread)
                    return s.CreationResult(
                        True,
                        None if missing == "process" else api.process,
                        None if missing == "thread" else api.thread,
                        4242,
                    )

                api.create_suspended = create
                obs = s.observe_once(owner, 300.0, api)
                self.assertIsNone(obs.host_owned_cleanup)
                self.assertEqual(obs.blocker, contract.Blocker.CREATE_UNCERTAIN)
                self.assertIsNone(obs.create_succeeded)
                self.assertEqual(len(api.calls("create")), 1)
                self.assertEqual(api.calls("resume"), [])
                self.assertFalse(obs.host_execution_attempted)
                self.assertFalse(obs.engine_creation_attempted)
                leaked = api.process if missing == "process" else api.thread
                self.assertEqual(set(api.opened) - {leaked}, set(api.closed))
                self.assertNotIn(leaked, api.closed)
                self.assertTrue(owner.closed)
                self.assertEqual(
                    set(api.cleanup_deadlines + api.bundle_api.close_deadlines), {15.0}
                )

    def test_missing_PID_binding_with_both_handles_is_not_a_resource_leak(self):
        s, owner, api = self.fake()

        def create(**kwargs):
            api.event("create", **kwargs)
            return s.CreationResult(True, api.own(api.process), api.own(api.thread), None)

        api.create_suspended = create
        obs = s.observe_once(owner, 300.0, api)
        self.assertIs(obs.host_owned_cleanup, True)
        self.assertEqual(obs.blocker, contract.Blocker.CREATE_UNCERTAIN)
        self.assertIsNone(obs.create_succeeded)
        self.assertEqual(api.closed, list(reversed(api.opened)))
        self.assertEqual(len(api.calls("create")), 1)
        self.assertEqual(api.calls("resume"), [])
        self.assertTrue(owner.closed)
        self.assertEqual(set(api.cleanup_deadlines + api.bundle_api.close_deadlines), {15.0})

    def test_malformed_resource_return_never_claims_cleanup_or_uses_null_handle(self):
        for method, bad in (
            ("prepare_job", 0),
            ("exclusive_transport", object()),
            ("create_suspended", object()),
        ):
            s, owner, api = self.fake()
            setattr(api, method, lambda *args, bad=bad, **kwargs: bad)
            obs = s.observe_once(owner, 300.0, api)
            with self.subTest(method=method):
                self.assertIsNone(obs.host_owned_cleanup)
                self.assertFalse(obs.observation_complete)
                for event in api.calls("terminate"):
                    self.assertIs(event[1][0], api.job)

    def test_all_returned_transport_handles_are_retained_after_duplicate_role(self):
        s, owner, api = self.fake()
        allocate = api.exclusive_transport

        def transport(*args, **kwargs):
            result = allocate(*args, **kwargs)
            return s.TransportHandles(
                result.request_read,
                result.request_read,
                result.stdout_write,
                result.stderr_write,
                result.result_read,
                result.stdout_read,
                result.stderr_read,
            )

        api.exclusive_transport = transport
        obs = s.observe_once(owner, 300.0, api)
        self.assertIsNone(obs.host_owned_cleanup)
        self.assertEqual(api.calls("create"), [])
        # The fake's omitted result_write was never returned, so is not adopted.
        returned = [handle for handle in api.opened if handle.name != "result_write"]
        self.assertEqual(set(api.closed), set(returned))
        self.assertEqual(len(api.closed), len(set(api.closed)))

    def test_result_length_must_match_complete_read(self):
        obs, _, _ = self.observe(lengths={"result_read": 1})
        self.assertFalse(obs.child_result_valid)
        self.assertFalse(obs.observation_complete)

    def test_stream_growth_during_completed_result_read_is_still_rejected(self):
        s, owner, api = self.fake()
        read = api.read_result

        def grow(*args, **kwargs):
            result = read(*args, **kwargs)
            api.lengths["stdout_read"] = 65537
            return result

        api.read_result = grow
        obs = s.observe_once(owner, 300.0, api)
        self.assertEqual(obs.blocker, contract.Blocker.OUTPUT_LIMIT)
        self.assertFalse(obs.observation_complete)

    def test_final_result_growth_invalidates_all_receipt_derived_facts(self):
        for oversized in (False, True):
            for stream_growth in (False, True):
                with self.subTest(oversized=oversized, stream_growth=stream_growth):
                    s, owner, api = self.fake()
                    read = api.read_result

                    def grow(
                        *args,
                        read=read,
                        api=api,
                        oversized=oversized,
                        stream_growth=stream_growth,
                        **kwargs,
                    ):
                        data = read(*args, **kwargs)
                        api.lengths["result_read"] = 262145 if oversized else len(data) + 1
                        if stream_growth:
                            api.lengths["stdout_read"] = 65537
                        return data

                    api.read_result = grow
                    obs = s.observe_once(owner, 300.0, api)
                    self.assertIs(obs.child_result_valid, False)
                    self.assertIsNone(obs.receipt)
                    self.assertIsNone(obs.engine_creation_attempted)
                    self.assertEqual(
                        obs.blocker,
                        contract.Blocker.OUTPUT_LIMIT
                        if oversized
                        else contract.Blocker.CAPSULE_INVALID,
                    )
                    self.assertFalse(obs.observation_complete)
                    self.assertTrue(obs.child_exit_before_cleanup)
                    self.assertEqual(obs.natural_exit_code, 0)
                    self.assertEqual(obs.host_deadline, 25.0)
                    self.assertEqual(len(api.calls("create")), 1)
                    self.assertEqual(len(api.calls("read")), 1)
                    public = contract.public_projection(obs)
                    self.assertIsNone(public["engine_creation_attempted"])
                    for key in ("a_expected", "b_expected", "ab_stability"):
                        self.assertEqual(public[key], "not_observed")

    def test_final_stream_only_growth_retains_confirmed_capsule_not_completion(self):
        for role in ("stdout_read", "stderr_read"):
            with self.subTest(role=role):
                s, owner, api = self.fake()
                read = api.read_result

                def grow(*args, read=read, api=api, role=role, **kwargs):
                    data = read(*args, **kwargs)
                    api.lengths[role] = 65537
                    return data

                api.read_result = grow
                obs = s.observe_once(owner, 300.0, api)
                self.assertEqual(obs.blocker, contract.Blocker.OUTPUT_LIMIT)
                self.assertIs(obs.child_result_valid, True)
                self.assertIsNotNone(obs.receipt)
                self.assertIs(obs.engine_creation_attempted, True)
                self.assertFalse(obs.observation_complete)
                self.assertEqual(obs.host_deadline, 25.0)
                public = contract.public_projection(obs)
                for key in ("a_expected", "b_expected", "ab_stability"):
                    self.assertEqual(public[key], "equal")
                self.assertIs(public["passed"], False)
                self.assertIs(public["execution_ready"], False)

    def test_final_result_rejection_retains_strict_H_observation_time(self):
        for final_time in (24.999, 25.0, 25.001):
            for oversized in (False, True):
                with self.subTest(final_time=final_time, oversized=oversized):
                    s, owner, api = self.fake()
                    read_length = api.read_length

                    def grow(
                        handle,
                        *,
                        read_length=read_length,
                        api=api,
                        final_time=final_time,
                        oversized=oversized,
                        **kwargs,
                    ):
                        size = read_length(handle, **kwargs)
                        if api.calls("read") and handle is api.transport.result_read:
                            api.bundle_api.time = final_time
                            return 262145 if oversized else size + 1
                        return size

                    api.read_length = grow
                    obs = s.observe_once(owner, 300.0, api)
                    self.assertEqual(obs.observed_at, final_time)
                    self.assertEqual(obs.host_deadline, 25.0)
                    self.assertFalse(obs.child_result_valid)
                    self.assertIsNone(obs.receipt)
                    self.assertFalse(obs.observation_complete)
                    self.assertEqual(
                        obs.blocker,
                        contract.Blocker.DEADLINE
                        if final_time >= 25.0
                        else contract.Blocker.OUTPUT_LIMIT
                        if oversized
                        else contract.Blocker.CAPSULE_INVALID,
                    )

    def test_bundle_drift_and_different_D_never_create(self):
        s, owner, api = self.fake()
        api.bundle_api.change_stage = "identity"
        obs = s.observe_once(owner, 300.0, api)
        self.assertEqual(obs.blocker, contract.Blocker.BUNDLE_REJECTED)
        self.assertEqual(api.calls("create"), [])
        s, owner, api = self.fake()
        obs = s.observe_once(owner, 301.0, api)
        self.assertEqual(obs.blocker, contract.Blocker.BUNDLE_REJECTED)
        self.assertEqual(api.calls("create"), [])

    def test_valid_incomplete_receipt_proves_engine_not_attempted(self):
        obs, _, _ = self.observe(complete=False)
        self.assertTrue(obs.child_result_valid)
        self.assertTrue(obs.host_execution_attempted)
        self.assertFalse(obs.engine_creation_attempted)
        self.assertFalse(obs.observation_complete)
        self.assertEqual(obs.blocker, contract.Blocker.CHILD_INCOMPLETE)

    def test_uncertain_signal_and_missing_natural_code_never_imply_success(self):
        s, owner, api = self.fake()
        api.poll_exit = lambda *args, **kwargs: s.ExitState(None)
        obs = s.observe_once(owner, 300.0, api)
        self.assertIsNone(obs.child_exit_before_cleanup)
        self.assertIsNone(obs.natural_exit_code)
        self.assertFalse(obs.observation_complete)
        self.assertEqual(api.calls("read"), [])
        obs, _, _ = self.observe(exit_code=None)
        self.assertTrue(obs.child_result_valid)
        self.assertIsNone(obs.natural_exit_code)
        self.assertFalse(obs.observation_complete)

    def test_control_calls_use_only_owned_handles_never_capsule_PID(self):
        _, _, api = self.observe()
        for name in ("image", "poll", "wait"):
            for event in api.calls(name):
                self.assertIs(event[1][0], api.process)
        for event in api.calls("resume"):
            self.assertIs(event[1][0], api.thread)
        for event in api.calls("terminate"):
            self.assertEqual(event[1], (api.job, api.process))

    def test_invalid_outcome_scalar_types_cannot_become_success(self):
        s = module()
        for invalid in (0, 1, "true"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(TypeError):
                    s.CreationResult(invalid)
                with self.assertRaises(TypeError):
                    s.ExitState(invalid)
        for code in (True, -1, 2**32):
            with self.assertRaises(ValueError):
                s.ExitState(True, code)
        with self.assertRaises(ValueError):
            s.ExitState(False, 0)

    def test_public_summary_drops_private_details_and_keeps_fixed_false_values(self):
        obs, _, _ = self.observe()
        public = contract.public_projection(obs)
        text = json.dumps(public)
        for private in ("4242", "C:\\private", "nonce", "file_id", "HRESULT"):
            self.assertNotIn(private, text)
        self.assertFalse(public["passed"])
        self.assertFalse(public["execution_ready"])
        self.assertEqual(public["display_comparison"], "format_unknown")

    def test_blocked_main_ignores_all_arguments_environment_and_apis(self):
        s = module()
        with patch.object(s, "observe_once", side_effect=AssertionError("must not observe")):
            with patch.object(sys, "argv", [str(MODULE), "--enable", "--run", "--target=1"]):
                with patch.dict(os.environ, {"SWU_ISSUE110_ENABLE": "1", "SWU_FILTER_RUN": "1"}):
                    with patch("sys.stdout"):
                        self.assertNotEqual(s.main(), 0)
        for flags in ([], ["--help"], ["--enable", "--run", "--unsafe", "--target=4242"]):
            env = dict(
                os.environ,
                SWU_ISSUE110_ENABLE="1",
                SWU_FILTER_RUN="1",
                ISSUE110_FILTER_PROBE="enabled",
                ISSUE110_EXECUTION_READY="true",
            )
            result = subprocess.run(
                [sys.executable, "-B", str(MODULE), *flags],
                env=env,
                capture_output=True,
                check=False,
                timeout=5,
            )
            self.assertNotEqual(result.returncode, 0)
            public = json.loads(result.stdout)
            self.assertEqual(public["status"], "blocked")
            self.assertFalse(public["host_execution_attempted"])
            self.assertFalse(public["execution_ready"])
            self.assertFalse(public["passed"])
            self.assertEqual(result.stderr, b"")

    def test_pending_drain_runs_at_zero_transfers_and_preserves_acquisition_unknown(self):
        s, owner, api = self.fake()
        api.errors["job"] = OSError("acquisition outcome unknown")
        with self.assertRaises(OSError) as caught:
            s.observe_once(owner, 300.0, api)
        self.assertIs(caught.exception, api.errors["job"])
        observation = caught.exception.host_observation
        self.assertEqual(len(api.calls("drain")), 1)
        self.assertEqual(api.closed, [])
        self.assertIsNone(observation.host_owned_cleanup)
        self.assertEqual(set(api.cleanup_deadlines + api.bundle_api.close_deadlines), {15.0})

    def test_pending_drain_cancel_preserves_primary_and_closes_returned_resources(self):
        for secondary in (OSError("drain"), KeyboardInterrupt(), SystemExit(9)):
            s, owner, api = self.fake()
            primary = KeyboardInterrupt("primary")
            api.errors = {"resume": primary, "drain": secondary}
            with self.assertRaises(KeyboardInterrupt) as caught:
                s.observe_once(owner, 300.0, api)
            self.assertIs(caught.exception, primary)
            self.assertEqual(api.closed, list(reversed(api.opened)))
            self.assertIsNone(primary.host_observation.host_owned_cleanup)
            self.assertEqual(set(api.cleanup_deadlines + api.bundle_api.close_deadlines), {15.0})

    def test_pending_drain_exhaustion_never_restarts_bundle_C(self):
        observation, owner, api = self.observe(elapsed={"drain": 5.0})
        self.assertIsNone(observation.host_owned_cleanup)
        self.assertIsNone(owner.cleanup)
        self.assertEqual(api.closed, [])
        self.assertEqual(api.bundle_api.closed, [])
        self.assertEqual(len(set(api.cleanup_deadlines + api.bundle_api.close_deadlines)), 1)


if __name__ == "__main__":
    unittest.main()
