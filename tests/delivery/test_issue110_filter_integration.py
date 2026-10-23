"""Closed composition on in-memory seams only, never a Windows/native run."""

import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from test_issue110_filter_bundle import FakeBundleAPI
from test_issue110_filter_bundle import module as bundle_module
from test_issue110_filter_supervisor import FakeHostAPI

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts/diagnostics"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
contract = importlib.import_module("issue110_filter_contract")
supervisor = importlib.import_module("issue110_filter_supervisor")


class PipelineAPI(FakeBundleAPI):
    """Explicit synthetic build evidence. No native capability or real manifest."""

    def __init__(self):
        super().__init__(bundle_module())
        self.host = None
        self.host_changes = {}
        self.factory_error = None
        self.factory_calls = 0
        self.host_modifier = None

    def host_api(self, owner):
        self.factory_calls += 1
        if self.factory_error:
            raise self.factory_error
        self.host = FakeHostAPI(supervisor, owner, self)
        self.host.signal_at = self.time + 1
        for key, value in self.host_changes.items():
            setattr(self.host, key, value)
        if self.host_modifier:
            self.host_modifier(self.host)
        return self.host


class ClosedPipelineTests(unittest.TestCase):
    def run_pipeline(self, api=None, build=None):
        api = api or PipelineAPI()
        operation = getattr(supervisor, "run_closed_pipeline", None)
        self.assertTrue(callable(operation), "missing internal closed pipeline composition")
        with patch.object(api.b, "DEBUGGER_HASHES", api.hashes):
            result = operation(api.build if build is None else build, r"C:\private", api)
        return result, api

    def public(self, observation):
        value = contract.public_projection(observation)
        self.assertIs(value["passed"], False)
        self.assertIs(value["execution_ready"], False)
        self.assertEqual(value["display_comparison"], "format_unknown")
        self.assertIs(value["disk_hard_cap"], False)
        text = json.dumps(value)
        for private in (
            "PRIVATE_CANARY",
            "C:\\private",
            "4242",
            "nonce",
            "bytes_hex",
            "sha256",
            "volume_serial",
            "natural_exit_code",
            "hresult",
        ):
            self.assertNotIn(private, text)
        return value

    def once(self, api):
        self.assertLessEqual(sum(e[0] == "reserve" for e in api.events), 1)
        self.assertLessEqual(sum(e[0] == "v6" for e in api.events), 1)
        self.assertLessEqual(api.factory_calls, 1)
        if api.host:
            self.assertLessEqual(len(api.host.calls("create")), 1)
            self.assertLessEqual(len(api.host.calls("resume")), 1)
        deadlines = api.close_deadlines + (api.host.cleanup_deadlines if api.host else [])
        self.assertLessEqual(len(set(deadlines)), 1, "all cleanup must share original C")
        self.assertEqual(len(api.closed), len(set(api.closed)), "no bundle close retry")

    def test_entire_successful_observation_trace_is_not_runtime_acceptance(self):
        observation, api = self.run_pipeline()
        public = self.public(observation)
        self.assertTrue(observation.observation_complete)
        self.assertEqual(public["status"], "observed")
        self.assertTrue(public["host_owned_cleanup"])
        self.assertIsNone(public["signature_cleanup"])
        self.assertEqual(observation.overall_deadline, 310.0)
        self.assertEqual(observation.host_deadline, 25.0)
        self.assertEqual([e[2] for e in api.events if e[0] == "v6"], [40.0])
        self.assertEqual(
            [e[1] for e in api.events if e[0] == "reserve"], ["issue110-filter-probe-1"]
        )
        self.assertEqual(
            [e[2] for e in api.events if e[0] == "copy"],
            ["issue110_filter_command_probe.exe", "dbgeng.dll", "dbghelp.dll"],
        )
        self.assertEqual(api.factory_calls, 1)
        self.assertEqual(api.closed, list(reversed(api.opened)))
        self.assertEqual(api.host.closed, list(reversed(api.host.opened)))
        self.assertLess(api.host.calls("create")[0][2]["deadline"], 310.0)
        self.assertTrue(api.host.owner.closed)
        self.once(api)

    def test_unknown_build_is_zero_reservation_signature_host(self):
        observation, api = self.run_pipeline(build=contract.ReviewedBuild())
        self.assertEqual(observation.blocker, contract.Blocker.BUILD_UNKNOWN)
        self.assertFalse(self.public(observation)["host_execution_attempted"])
        self.assertEqual(api.events, [])
        self.assertEqual(api.factory_calls, 0)
        self.once(api)

    def test_unknown_production_backend_does_not_accept_synthetic_build(self):
        native = importlib.import_module("issue110_filter_host_win32")
        api = native.WindowsBundleAPI(_kernel=object(), _clock=lambda: 10.0)
        self.assertIsNone(api.reviewed_build_version(PipelineAPI().build))

    def test_existing_and_uncertain_reservation_never_retry_or_adopt(self):
        for error, unknown in ((FileExistsError("PRIVATE_CANARY"), False), (None, True)):
            with self.subTest(error=type(error), unknown=unknown):
                api = PipelineAPI()
                api.reserve_error, api.reserve_unknown = error, unknown
                if error:
                    with self.assertRaises(FileExistsError) as caught:
                        self.run_pipeline(api)
                    self.assertIs(caught.exception, error)
                    self.public(caught.exception.host_observation)
                else:
                    observation, _ = self.run_pipeline(api)
                    self.assertEqual(observation.blocker, contract.Blocker.RESERVATION_UNCERTAIN)
                    self.public(observation)
                self.assertEqual(api.factory_calls, 0)
                self.assertFalse(any(e[0] in ("copy", "v6") for e in api.events))
                self.once(api)

    def test_each_bundle_to_host_handoff_rejects_before_create(self):
        cases = (
            ("reviewed", False, contract.Blocker.BUILD_UNKNOWN),
            ("signature_valid", False, contract.Blocker.SIGNATURE_REJECTED),
            ("signature_cleanup", False, contract.Blocker.SIGNATURE_REJECTED),
            ("change_source", "hash", contract.Blocker.BUNDLE_REJECTED),
            ("evidence_unknown", True, contract.Blocker.DEPENDENCIES_UNKNOWN),
            ("stage_alias", True, contract.Blocker.BUNDLE_REJECTED),
            ("change_stage", "identity", contract.Blocker.BUNDLE_REJECTED),
        )
        for key, value, blocker in cases:
            with self.subTest(key=key):
                api = PipelineAPI()
                setattr(api, key, value)
                observation, _ = self.run_pipeline(api)
                self.assertEqual(observation.blocker, blocker)
                self.assertEqual(api.factory_calls, 0)
                self.public(observation)
                self.once(api)

    def test_bundle_cancellation_preserves_primary_and_independent_cleanup_unknown(self):
        for place in ("write_error", "flush_error", "signature_error"):
            for error in (
                KeyboardInterrupt("PRIVATE_CANARY"),
                SystemExit(9),
                OSError("PRIVATE_CANARY"),
            ):
                with self.subTest(place=place, error=type(error)):
                    api = PipelineAPI()
                    setattr(api, place, error)
                    api.close_error = OSError("PRIVATE_CANARY_SECONDARY")
                    with self.assertRaises(type(error)) as caught:
                        self.run_pipeline(api)
                    self.assertIs(caught.exception, error)
                    self.assertIsNone(error.host_observation.host_owned_cleanup)
                    self.assertIsNone(error.host_observation.signature_cleanup)
                    self.public(error.host_observation)
                    self.once(api)

    def test_every_bundle_operation_failure_stops_at_its_first_handoff(self):
        operations = (
            "reviewed_build_version",
            "open_directory",
            "validate_directory",
            "reserve_child",
            "write_exclusive",
            "flush",
            "create_stage",
            "pin_source",
            "pin_identity",
            "read_pin",
            "revalidate_pin",
            "verify_installed_v6",
            "dependency_evidence",
            "copy_exclusive",
        )
        for name in operations:
            for error in (OSError("PRIVATE_CANARY"), KeyboardInterrupt("PRIVATE_CANARY")):
                with self.subTest(operation=name, error=type(error)):
                    api = PipelineAPI()
                    calls = []

                    def fail(*args, error=error, calls=calls, **kwargs):
                        calls.append((args, kwargs))
                        raise error

                    setattr(api, name, fail)
                    api.close_error = OSError("secondary cleanup failure")
                    with self.assertRaises(type(error)) as caught:
                        self.run_pipeline(api)
                    self.assertIs(caught.exception, error)
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(api.factory_calls, 0)
                    # This fake throws before its first open transfers anything;
                    # its registered pending set is empty and drain is confirmed.
                    self.assertIs(
                        error.host_observation.host_owned_cleanup,
                        True if name == "open_directory" else None,
                    )
                    self.public(error.host_observation)
                    self.once(api)

    def test_host_adapter_handoff_failure_closes_bundle_with_one_C(self):
        for error in (OSError("PRIVATE_CANARY"), KeyboardInterrupt("PRIVATE_CANARY")):
            api = PipelineAPI()
            api.factory_error = error
            with self.assertRaises(type(error)) as caught:
                self.run_pipeline(api)
            self.assertIs(caught.exception, error)
            self.assertTrue(error.host_observation.host_owned_cleanup)
            self.assertEqual(set(api.close_deadlines), {15.0})
            self.assertEqual(api.closed, list(reversed(api.opened)))
            self.public(error.host_observation)
            self.once(api)

    def test_unexpected_private_error_fields_cannot_replace_primary_or_leak(self):
        api = PipelineAPI()
        original = OSError("PRIVATE_CANARY")
        original.bundle_cleanup = "PRIVATE_CANARY"
        original.signature_cleanup = "PRIVATE_CANARY"
        api.reviewed_build_version = lambda build: (_ for _ in ()).throw(original)
        with self.assertRaises(OSError) as caught:
            self.run_pipeline(api)
        self.assertIs(caught.exception, original)
        self.assertIsNone(original.host_observation.host_owned_cleanup)
        self.assertIsNone(original.host_observation.signature_cleanup)
        self.public(original.host_observation)

    def test_each_supervisor_handoff_failure_never_repeats_work(self):
        cases = (
            ("unsupported", "job", contract.Blocker.UNSUPPORTED),
            ("unsupported", "job_list", contract.Blocker.UNSUPPORTED),
            ("unsupported", "handle_list", contract.Blocker.UNSUPPORTED),
            ("intent_result", None, contract.Blocker.IO_FAILURE),
            ("creation", False, contract.Blocker.CREATE_FAILED),
            ("creation", None, contract.Blocker.CREATE_UNCERTAIN),
            ("wrong_image", True, contract.Blocker.IMAGE_MISMATCH),
            ("resumption", False, contract.Blocker.RESUME_FAILED),
            ("resumption", None, contract.Blocker.RESUME_UNCERTAIN),
            ("bad_result", b"PRIVATE_CANARY", contract.Blocker.CAPSULE_INVALID),
            ("complete", False, contract.Blocker.CHILD_INCOMPLETE),
            ("exit_code", 1, contract.Blocker.CHILD_FAILED),
            ("cleanup_result", None, contract.Blocker.CLEANUP_UNKNOWN),
        )
        for key, value, blocker in cases:
            with self.subTest(key=key, value=value):
                api = PipelineAPI()
                api.host_changes[key] = value
                observation, _ = self.run_pipeline(api)
                self.assertEqual(observation.blocker, blocker)
                self.public(observation)
                self.once(api)

    def test_every_host_operation_exception_retains_primary_without_retry(self):
        for label in (
            "job",
            "transport",
            "attributes",
            "intent",
            "create",
            "image",
            "resume",
            "poll",
            "wait",
            "length",
            "read",
        ):
            for error in (OSError("PRIVATE_CANARY"), KeyboardInterrupt("PRIVATE_CANARY")):
                with self.subTest(label=label, error=type(error)):
                    api = PipelineAPI()
                    api.host_changes["errors"] = {label: error, "close": OSError("secondary")}
                    with self.assertRaises(type(error)) as caught:
                        self.run_pipeline(api)
                    self.assertIs(caught.exception, error)
                    self.assertIsNone(error.host_observation.host_owned_cleanup)
                    self.public(error.host_observation)
                    self.once(api)

    def test_unknown_signature_cleanup_never_becomes_host_cleanup(self):
        for cleanup in (None, True):
            api = PipelineAPI()
            api.signature_cleanup = cleanup
            observation, _ = self.run_pipeline(api)
            self.assertIs(observation.signature_cleanup, cleanup)
            self.assertIs(observation.host_owned_cleanup, True)
            self.public(observation)

    def test_single_signature_S_and_remaining_D_never_restart(self):
        api = PipelineAPI()
        api.signature_elapsed = 30.0
        observation, _ = self.run_pipeline(api)
        self.assertEqual(observation.blocker, contract.Blocker.DEADLINE)
        self.assertEqual(observation.overall_deadline, 310.0)
        self.assertEqual(api.factory_calls, 0)
        self.assertEqual([e[2] for e in api.events if e[0] == "v6"], [40.0])
        self.once(api)

    def test_no_full_host_window_after_bundle_never_creates_or_renews_D(self):
        api = PipelineAPI()
        original = api.copy_exclusive

        def copy(*args, **kwargs):
            value = original(*args, **kwargs)
            if len([e for e in api.events if e[0] == "copy"]) == 3:
                api.time = 295.001
            return value

        api.copy_exclusive = copy
        observation, _ = self.run_pipeline(api)
        self.assertEqual(observation.blocker, contract.Blocker.DEADLINE)
        self.assertEqual(observation.overall_deadline, 310.0)
        self.assertEqual(api.host.calls("create"), [])
        self.once(api)

    def test_exact_H_and_D_keep_facts_but_never_complete(self):
        for label, elapsed in (("read", 14.0), ("close", 299.0)):
            with self.subTest(label=label):
                api = PipelineAPI()
                if label == "read":
                    api.host_changes["elapsed"] = {label: elapsed}
                else:
                    api.close_elapsed = elapsed
                observation, _ = self.run_pipeline(api)
                self.assertTrue(observation.child_result_valid)
                self.assertEqual(observation.natural_exit_code, 0)
                self.assertFalse(observation.observation_complete)
                self.assertEqual(observation.blocker, contract.Blocker.DEADLINE)
                self.public(observation)
                self.once(api)

    def test_monitored_result_and_both_stream_limits_are_not_disk_caps(self):
        for role, size in (("result_read", 262145), ("stdout_read", 65537), ("stderr_read", 65537)):
            api = PipelineAPI()
            api.host_changes["lengths"] = {role: size}
            observation, _ = self.run_pipeline(api)
            self.assertEqual(observation.blocker, contract.Blocker.OUTPUT_LIMIT)
            self.assertFalse(observation.observation_complete)
            self.public(observation)
            self.once(api)

    def test_internal_cpp_request_capsule_bridge_cannot_mint_native_capability(self):
        compiler = shutil.which("g++")
        if not compiler:
            self.skipTest("portable compiler unavailable; Windows remains unverified")
        source = ROOT / "tests/delivery/issue110_filter_integration_test.cpp"
        self.assertTrue(source.is_file(), "missing C++ request/capsule bridge fixture")
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "bridge"
            compiled = subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-pedantic",
                    "-pthread",
                    "-I",
                    str(ROOT),
                    str(source),
                    str(SCRIPTS / "issue110_filter_loader.cpp"),
                    "-o",
                    str(binary),
                ],
                capture_output=True,
                timeout=60,
                check=False,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr.decode())
            run = subprocess.run([str(binary)], capture_output=True, timeout=15, check=False)
            self.assertEqual(run.returncode, 0, run.stderr.decode())
            receipt = contract.parse_capsule(
                run.stdout, contract.CapsuleContext("0123456789abcdef0123456789abcdef", 4242)
            )
            self.assertFalse(receipt.engine_creation_attempted)
            self.assertFalse(receipt.observations_complete)
            self.assertEqual(receipt.issue, "loader_blocked")
            self.assertEqual(len(receipt.module_paths_utf16le), 3)
            expected_path = (
                r"C:\private\issue110-filter-probe-1\stage"
                r"\issue110_filter_command_probe.exe"
            )
            self.assertEqual(receipt.module_paths_utf16le[0], expected_path.encode("utf-16le"))
            # Actual sole Python writer -> independent C++ StageEvidence ->
            # actual loader seam -> capsule -> independent Python parser.
            fixture_bundle = SimpleNamespace(
                manifest_sha256="a" * 64,
                stage_files=tuple(
                    (
                        name,
                        contract.BoundFile(
                            contract.FileIdentity(7, bytes([index]) * 16), digest * 64
                        ),
                    )
                    for index, (name, digest) in enumerate(
                        (
                            ("issue110_filter_command_probe.exe", "b"),
                            ("dbgeng.dll", "c"),
                            ("dbghelp.dll", "d"),
                        ),
                        1,
                    )
                ),
            )
            request = supervisor._request(fixture_bundle, "0123456789abcdef0123456789abcdef")
            bridged = subprocess.run(
                [str(binary), "--writer-request"],
                input=request,
                capture_output=True,
                timeout=15,
                check=False,
            )
            self.assertEqual(bridged.returncode, 0, bridged.stderr.decode())
            self.assertEqual(
                contract.parse_capsule(
                    bridged.stdout,
                    contract.CapsuleContext("0123456789abcdef0123456789abcdef", 4242),
                ).issue,
                "loader_blocked",
            )
            run = subprocess.run(
                [str(binary), "--core-success"], capture_output=True, timeout=15, check=False
            )
            self.assertEqual(run.returncode, 0, run.stderr.decode())
            receipt = contract.parse_capsule(
                run.stdout, contract.CapsuleContext("0123456789abcdef0123456789abcdef", 4242)
            )
            self.assertTrue(receipt.engine_creation_attempted)
            self.assertTrue(receipt.observations_complete)
            self.assertEqual(receipt.sx.data, b"PRIVATE_CANARY\n")
            self.assertEqual(
                receipt.getter_a.data, b"$$>a<C:\\SWU_ISSUE110_SYNTHETIC\\terminal.cdb\0"
            )
            self.public(
                contract.HostObservation(
                    receipt=receipt, child_result_valid=True, private_error="PRIVATE_CANARY"
                )
            )

    def test_cpp_getter_receipts_distinguish_unobserved_thrown_and_returned_values(self):
        compiler = shutil.which("g++")
        if not compiler:
            self.skipTest("portable compiler unavailable; Windows remains unverified")
        nonce = "0123456789abcdef0123456789abcdef"
        command = b"$$>a<C:\\SWU_ISSUE110_SYNTHETIC\\terminal.cdb\0"
        unobserved = (False, None, None, b"")
        confirmed = (True, 0, len(command), command)
        scenarios = (
            ("early_target", unobserved, unobserved),
            ("before_a_failure", unobserved, unobserved),
            ("a_throw", unobserved, unobserved),
            ("before_b_failure", confirmed, unobserved),
            ("b_throw", confirmed, unobserved),
            ("returned_a_s_false", (False, 1, 17, b""), unobserved),
            ("returned_b_failure", confirmed, (False, -2147467259, 23, b"")),
            ("returned_a_zero_length", (False, 0, 0, b""), unobserved),
            ("a_return_then_target", (False, 0, len(command), b""), unobserved),
            ("b_return_then_target", confirmed, (False, 0, len(command), b"")),
            ("success", confirmed, confirmed),
        )
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "getter-observations"
            compiled = subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-pedantic",
                    "-pthread",
                    "-I",
                    str(ROOT),
                    str(ROOT / "tests/delivery/issue110_filter_integration_test.cpp"),
                    str(SCRIPTS / "issue110_filter_loader.cpp"),
                    "-o",
                    str(binary),
                ],
                capture_output=True,
                timeout=60,
                check=False,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr.decode())
            for scenario, expected_a, expected_b in scenarios:
                with self.subTest(scenario=scenario):
                    run = subprocess.run(
                        [str(binary), "--getter-observation", scenario],
                        capture_output=True,
                        timeout=15,
                        check=False,
                    )
                    self.assertEqual(run.returncode, 0, run.stderr.decode())
                    receipt = contract.parse_capsule(
                        run.stdout, contract.CapsuleContext(nonce, 4242)
                    )
                    for name, expected in (("getter_a", expected_a), ("getter_b", expected_b)):
                        getter = getattr(receipt, name)
                        self.assertEqual(
                            (getter.valid, getter.hresult, getter.reported_length, getter.data),
                            expected,
                        )
                        returned = expected[1] is not None
                        self.assertEqual(
                            any(item.stage == name for item in receipt.hresult_trace), returned
                        )
                    self.assertEqual(receipt.observations_complete, scenario == "success")
                    self.public(contract.HostObservation(receipt=receipt, child_result_valid=True))

    def test_bound_private_capsule_canary_and_structural_forgery_never_leak(self):
        for mutation in ("canary", "nonce", "pid", "duplicate", "unknown", "bool_pid", "truncated"):
            with self.subTest(mutation=mutation):
                api = PipelineAPI()

                def modify(host, mutation=mutation):
                    original = host.capsule

                    def capsule():
                        data = original()
                        body = json.loads(data[19:-11])
                        if mutation == "canary":
                            body["sx"]["bytes_hex"] = b"PRIVATE_CANARY".hex()
                            body["module_paths_utf16le_hex"] = [
                                "PRIVATE_CANARY".encode("utf-16le").hex()
                            ]
                        elif mutation == "nonce":
                            body["nonce"] = "f" * 32
                        elif mutation == "pid":
                            body["child_pid"] = 4243
                        elif mutation == "unknown":
                            body["PRIVATE_CANARY"] = "PRIVATE_CANARY"
                        elif mutation == "bool_pid":
                            body["child_pid"] = True
                        encoded = json.dumps(body, separators=(",", ":")).encode()
                        if mutation == "duplicate":
                            encoded = encoded.replace(
                                b'{"schema":', b'{"schema":"PRIVATE_CANARY","schema":', 1
                            )
                        framed = (
                            b"SWU110FP1\n"
                            + f"{len(encoded):08x}\n".encode()
                            + encoded
                            + b"\nSWU110END\n"
                        )
                        return framed[:-1] if mutation == "truncated" else framed

                    host.capsule = capsule

                api.host_modifier = modify
                observation, _ = self.run_pipeline(api)
                public = self.public(observation)
                if mutation == "canary":
                    self.assertTrue(observation.child_result_valid)
                    self.assertTrue(public["observation_complete"])
                    self.assertEqual(observation.receipt.sx.data, b"PRIVATE_CANARY")
                else:
                    self.assertEqual(observation.blocker, contract.Blocker.CAPSULE_INVALID)
                    self.assertIs(observation.child_result_valid, False)
                self.once(api)

    def test_native_bridge_binds_real_pid_and_never_appears_in_either_main(self):
        loader = (SCRIPTS / "issue110_filter_loader.cpp").read_text()
        bridge = loader.split("ClosedHostAttempt run_closed_host(", 1)[1]
        self.assertIn("child_pid != GetCurrentProcessId()", bridge)
        self.assertIn("retain_until_exit(api)", bridge)
        native_main = (
            (SCRIPTS / "issue110_filter_command_probe.cpp").read_text().split("int main()", 1)[1]
        )
        python_main = (
            (SCRIPTS / "issue110_filter_supervisor.py").read_text().split("def main()", 1)[1]
        )
        for main in (native_main, python_main):
            self.assertNotIn("run_closed_host", main)
            self.assertNotIn("run_closed_pipeline", main)
            self.assertNotIn("run_verified_probe", main)

    def test_python_main_hostile_arguments_environment_remain_blocked(self):
        env = dict(
            os.environ,
            PYTHONPATH=str(SCRIPTS),
            SWU_ENABLE_NATIVE="1",
            ISSUE110_FILTER_EXECUTE="1",
            SWU_FILTER_REVIEWED_BUILD="PRIVATE_CANARY",
        )
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SCRIPTS / "issue110_filter_supervisor.py"),
                "--run",
                "--force",
                "--reviewed-build",
                "PRIVATE_CANARY",
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(
            json.loads(result.stdout), contract.public_projection(contract.HostObservation())
        )


if __name__ == "__main__":
    unittest.main()
