"""Independent literal protocol fixtures; portable code only, no native API calls."""

import copy
import dataclasses
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "scripts/diagnostics/issue110_filter_contract.py"
# Written independently of the C++ encoder and its separate literal fixture.
GOLDEN_BODY = (
    b'{"schema":"swu.issue110.filter-capsule.v1","mode":"fixed_no_target",'
    b'"nonce":"0123456789abcdef0123456789abcdef","child_pid":4242,'
    b'"stage":"not_started","issue":"none","engine_creation_attempted":false,'
    b'"observations_complete":false,'
    b'"getter_a":{"valid":false,"hresult":null,"reported_length":null,"bytes_hex":""},'
    b'"getter_b":{"valid":false,"hresult":null,"reported_length":null,"bytes_hex":""},'
    b'"sx":{"bytes_hex":"","overflow":false,"association":"not_observed"},'
    b'"a_expected":"not_observed","b_expected":"not_observed",'
    b'"ab_stability":"not_observed","hresult_trace":[],"module_paths_utf16le_hex":[], '
    b'"release":{"all_owned_release_calls_issued":false,"engine_disposal_confirmed":false,'
    b'"detach_hresult":null,"control_release_return":null,"client_release_return":null,'
    b'"callback_release_return":null,"wrong_thread":false,"callback_violation":false}}'
)
NONCE = "0123456789abcdef0123456789abcdef"
PUBLIC_KEYS = {
    "schema",
    "mode",
    "status",
    "stage",
    "blocker",
    "host_execution_attempted",
    "engine_creation_attempted",
    "child_result_valid",
    "child_exit_before_cleanup",
    "host_owned_cleanup",
    "signature_cleanup",
    "observation_complete",
    "a_expected",
    "b_expected",
    "ab_stability",
    "passed",
    "execution_ready",
    "display_comparison",
    "disk_hard_cap",
}


def frame(body):
    return b"SWU110FP1\n" + f"{len(body):08x}\n".encode() + body + b"\nSWU110END\n"


def document():
    return json.loads(GOLDEN_BODY)


def encoded(doc):
    return frame(json.dumps(doc, separators=(",", ":"), allow_nan=True).encode())


def contract():
    assert MODULE.is_file(), "missing private filter protocol contract"
    name = "issue110_filter_contract"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, MODULE)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


class FilterContractTests(unittest.TestCase):
    def parse(self, data):
        c = contract()
        return c.parse_capsule(data, c.CapsuleContext(NONCE, 4242))

    def reject(self, data):
        c = contract()
        with self.assertRaises(c.CapsuleError) as caught:
            self.parse(data)
        self.assertIsInstance(caught.exception.code, c.CapsuleErrorCode)
        self.assertNotIn("CANARY", str(caught.exception))

    def test_literal_capsule_is_immutable_and_lossless(self):
        c = contract()
        receipt = self.parse(frame(GOLDEN_BODY))
        self.assertEqual(receipt.nonce, NONCE)
        self.assertEqual(receipt.child_pid, 4242)
        self.assertIsNone(receipt.getter_a.hresult)
        self.assertIsNone(receipt.getter_a.reported_length)
        self.assertEqual(receipt.getter_a.data, b"")
        self.assertFalse(receipt.engine_creation_attempted)
        self.assertEqual(receipt.hresult_trace, ())
        self.assertNotIn(NONCE, repr(receipt))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            receipt.child_pid = 1
        self.assertFalse(c.public_projection(c.HostObservation())["passed"])

    def test_duplicate_bool_and_private_canary(self):
        duplicate = GOLDEN_BODY.replace(b'"child_pid":4242', b'"child_pid":4242,"child_pid":4242')
        self.reject(frame(duplicate))
        self.reject(frame(GOLDEN_BODY.replace(b'"valid":false', b'"valid":false,"valid":false', 1)))
        paths = [
            ("child_pid",),
            ("getter_a", "reported_length"),
            ("getter_b", "hresult"),
            ("release", "control_release_return"),
        ]
        for path in paths:
            for invalid in (True, 1.0, "1"):
                with self.subTest(path=path, invalid=invalid):
                    doc = document()
                    target = doc
                    for key in path[:-1]:
                        target = target[key]
                    target[path[-1]] = invalid
                    self.reject(encoded(doc))
        doc = document()
        doc["hresult_trace"] = [{"stage": "getter_a", "hresult": True}]
        self.reject(encoded(doc))
        doc = document()
        canaries = (b"RAW_CANARY", b"C:\\PATH_CANARY", b"HRESULT_CANARY")
        doc["sx"]["bytes_hex"] = b"|".join(canaries).hex()
        doc["module_paths_utf16le_hex"] = ["C:\\PATH_CANARY".encode("utf-16-le").hex()]
        doc["hresult_trace"] = [{"stage": "getter_a", "hresult": -2147467259}]
        receipt = self.parse(encoded(doc))
        c = contract()
        obs = c.HostObservation(
            create_intent=True,
            create_succeeded=True,
            resume_intent=True,
            resume_succeeded=True,
            child_result_valid=True,
            receipt=receipt,
            private_error="EXCEPTION_CANARY",
        )
        public = c.public_projection(obs)
        text = json.dumps(public)
        markers = (
            *[s.decode() for s in canaries],
            NONCE,
            "4242",
            "-2147467259",
            "EXCEPTION_CANARY",
        )
        for marker in markers:
            self.assertNotIn(marker, text)
        self.assertEqual(set(public), PUBLIC_KEYS)
        self.assertFalse(public["passed"])
        self.assertFalse(public["execution_ready"])
        self.assertFalse(public["disk_hard_cap"])
        self.assertEqual(public["display_comparison"], "format_unknown")

    def test_exact_fields_at_every_level(self):
        for path in ((), ("getter_a",), ("getter_b",), ("sx",), ("release",)):
            for mutation in ("missing", "unknown"):
                with self.subTest(path=path, mutation=mutation):
                    doc = document()
                    target = doc
                    for key in path:
                        target = target[key]
                    if mutation == "missing":
                        del target[next(iter(target))]
                    else:
                        target["PRIVATE_CANARY"] = "CANARY"
                    self.reject(encoded(doc))
        for trace in ({"stage": "getter_a"}, {"stage": "getter_a", "hresult": 0, "extra": 0}):
            doc = document()
            doc["hresult_trace"] = [trace]
            self.reject(encoded(doc))

    def test_scalar_types_constants_and_numeric_bounds(self):
        for key, values in {
            "schema": ("v2", None),
            "mode": ("dynamic", None),
            "nonce": ("0" * 32, NONCE.upper(), 1, "x" * 32),
            "child_pid": (0, 4294967296, -1, 4243),
            "stage": ("CANARY", None),
            "issue": ("CANARY", None),
            "engine_creation_attempted": (0, None),
            "observations_complete": (1, None),
            "a_expected": (True, "unknown"),
            "b_expected": (None,),
            "ab_stability": (0,),
        }.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    doc = document()
                    doc[key] = value
                    self.reject(encoded(doc))
        for value in (float("nan"), float("inf"), -float("inf"), -2147483649, 2147483648):
            doc = document()
            doc["getter_a"]["hresult"] = value
            self.reject(encoded(doc))
        for value in (-1, 4294967296):
            doc = document()
            doc["getter_a"]["reported_length"] = value
            self.reject(encoded(doc))
        for key in ("overflow", "association"):
            doc = document()
            doc["sx"][key] = 0
            self.reject(encoded(doc))

    def test_framing_utf8_hex_and_total_limits(self):
        good = frame(GOLDEN_BODY)
        for data in (
            b"",
            good + b"\n",
            good[:-1],
            good[:-5],
            good.replace(b"FP1", b"FP2", 1),
            good[:10] + b"0000000G\n" + good[19:],
            good[:10] + b"00000000\n" + good[19:],
            good[:10] + b"000003FF\n" + good[19:],
            frame(b"\xff"),
            frame(b"\xef\xbb\xbf" + GOLDEN_BODY),
            frame(b"[]"),
        ):
            with self.subTest(data=data[:20]):
                self.reject(data)
        for value in ("a", "gg", "AA", "00 00", 12, None):
            doc = document()
            doc["sx"]["bytes_hex"] = value
            self.reject(encoded(doc))
        doc = document()
        doc["module_paths_utf16le_hex"] = ["00"]
        self.reject(encoded(doc))
        doc["module_paths_utf16le_hex"] = ["00" * 8194]
        self.reject(encoded(doc))
        doc["module_paths_utf16le_hex"] = [""] * 17
        self.reject(encoded(doc))
        for total in (262143, 262144, 262145):
            data = frame(GOLDEN_BODY + b" " * (total - len(good)))
            self.assertEqual(len(data), total)
            if total <= 262144:
                self.parse(data)
            else:
                self.reject(data)
        with self.assertRaises(TypeError):
            self.parse(bytearray(good))

    def test_getter_confirmed_bytes_and_output_limits(self):
        doc = document()
        getter = {
            "valid": True,
            "hresult": 0,
            "reported_length": 4096,
            "bytes_hex": (b"A" * 4095 + b"\0").hex(),
        }
        doc["getter_a"] = getter
        doc["a_expected"] = "different"
        self.assertEqual(len(self.parse(encoded(doc)).getter_a.data), 4096)
        for update in (
            {"bytes_hex": (b"A" * 4096 + b"\0").hex(), "reported_length": 4097},
            {"reported_length": 4095},
            {"hresult": 1},
            {"bytes_hex": "00" * 4096},
            {"bytes_hex": "ff" * 4095 + "00"},
            {"valid": False},
        ):
            bad = copy.deepcopy(doc)
            bad["getter_a"].update(update)
            self.reject(encoded(bad))
        invalid = document()
        invalid["getter_a"]["reported_length"] = 4294967295
        invalid["getter_a"]["hresult"] = -1
        receipt = self.parse(encoded(invalid))
        self.assertEqual(receipt.getter_a.data, b"")
        self.assertEqual(receipt.getter_a.reported_length, 4294967295)
        for size in (65536, 65537):
            output = document()
            output["sx"]["bytes_hex"] = (b"\xff" * size).hex()
            if size == 65536:
                self.assertEqual(self.parse(encoded(output)).sx.data, b"\xff" * size)
            else:
                self.reject(encoded(output))

    def complete_receipt(self):
        doc = document()
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
        doc["sx"] = {
            "bytes_hex": b"display\n".hex(),
            "overflow": False,
            "association": "associated",
        }
        doc["release"]["all_owned_release_calls_issued"] = True
        doc["release"]["detach_hresult"] = 0
        return self.parse(encoded(doc))

    def complete_observation(self):
        c = contract()
        return c.HostObservation(
            stage=c.HostStage.COMPLETE,
            blocker=c.Blocker.NONE,
            create_intent=True,
            create_succeeded=True,
            resume_intent=True,
            resume_succeeded=True,
            child_exit_before_cleanup=True,
            natural_exit_code=0,
            child_result_valid=True,
            receipt=self.complete_receipt(),
            host_owned_cleanup=True,
            signature_cleanup=None,
            observation_complete=True,
            observed_at=14.0,
            host_deadline=15.0,
            projected_at=299.0,
            overall_deadline=300.0,
        )

    def test_valid_capsule_at_deadline_is_not_complete(self):
        c = contract()
        obs = self.complete_observation()
        public = c.public_projection(obs)
        self.assertTrue(public["observation_complete"])
        self.assertIsNone(public["signature_cleanup"])
        self.assertTrue(public["host_owned_cleanup"])
        self.assertFalse(public["passed"])
        self.assertFalse(public["execution_ready"])
        for fields in (
            {"observed_at": 15.0},
            {"observed_at": 15.1},
            {"projected_at": 300.0},
            {"projected_at": 301.0},
            {"observed_at": None},
            {"host_deadline": None},
        ):
            late = dataclasses.replace(obs, **fields)
            public = c.public_projection(late)
            self.assertFalse(public["observation_complete"])
            self.assertTrue(public["child_result_valid"])
            self.assertTrue(public["child_exit_before_cleanup"])
            self.assertEqual(public["a_expected"], "equal")
        for fields in (
            {"natural_exit_code": 7},
            {"child_result_valid": None},
            {"receipt": None},
            {"child_exit_before_cleanup": None},
            {"observation_complete": False},
        ):
            public = c.public_projection(dataclasses.replace(obs, **fields))
            self.assertFalse(public["observation_complete"])

    def test_attempt_unknowns_never_become_false_or_success(self):
        c = contract()
        for intent, result, expected in (
            (False, None, False),
            (True, False, False),
            (True, None, None),
            (True, True, True),
        ):
            obs = c.HostObservation(
                create_intent=True,
                create_succeeded=True,
                resume_intent=intent,
                resume_succeeded=result,
            )
            public = c.public_projection(obs)
            self.assertIs(public["host_execution_attempted"], expected)
            self.assertIs(public["engine_creation_attempted"], False if expected is False else None)
            self.assertIsNone(public["child_result_valid"])
        complete = self.complete_observation()
        self.assertTrue(c.public_projection(complete)["engine_creation_attempted"])
        invalid = c.public_projection(dataclasses.replace(complete, child_result_valid=False))
        self.assertIsNone(invalid["engine_creation_attempted"])
        self.assertFalse(c.public_projection(c.HostObservation())["observation_complete"])
        for fields in (
            {"stage": "PATH_CANARY"},
            {"blocker": "RAW_CANARY"},
            {"resume_succeeded": 1},
            {"host_owned_cleanup": 1},
            {"observed_at": float("nan")},
            {"overall_deadline": float("inf")},
        ):
            with self.assertRaises((TypeError, ValueError)):
                dataclasses.replace(complete, **fields)

    def test_public_forged_receipt_never_forwards_private_fields(self):
        c = contract()
        obs = self.complete_observation()
        receipt = dataclasses.replace(
            obs.receipt,
            engine_creation_attempted="ENGINE_CANARY",
            observations_complete="COMPLETE_CANARY",
            a_expected="COMPARISON_CANARY",
        )
        public = c.public_projection(dataclasses.replace(obs, receipt=receipt))
        self.assertNotIn("CANARY", json.dumps(public))
        self.assertIsNone(public["engine_creation_attempted"])
        self.assertFalse(public["observation_complete"])
        self.assertEqual(public["a_expected"], "not_observed")

    def test_complete_requires_detach_and_confirmed_ascii_output(self):
        receipt = self.complete_receipt()
        doc = document()
        for key in ("getter_a", "getter_b"):
            getter = getattr(receipt, key)
            doc[key] = {
                "valid": True,
                "hresult": 0,
                "reported_length": len(getter.data),
                "bytes_hex": getter.data.hex(),
            }
        doc.update(
            stage="observations_complete",
            observations_complete=True,
            engine_creation_attempted=True,
            a_expected="equal",
            b_expected="equal",
            ab_stability="equal",
        )
        doc["release"]["all_owned_release_calls_issued"] = True
        doc["release"]["detach_hresult"] = 0
        doc["sx"] = {"bytes_hex": "410a", "overflow": False, "association": "associated"}
        self.parse(encoded(doc))
        for value in (None, 1, -1):
            invalid = copy.deepcopy(doc)
            invalid["release"]["detach_hresult"] = value
            self.reject(encoded(invalid))
        for value in ("ff", "00", "01", "7f"):
            invalid = copy.deepcopy(doc)
            invalid["sx"]["bytes_hex"] = value
            self.reject(encoded(invalid))

    def test_claimed_complete_contradictions_are_rejected(self):
        for fields in (
            {"observations_complete": True},
            {"a_expected": "equal"},
            {"ab_stability": "equal"},
        ):
            doc = document()
            doc.update(fields)
            self.reject(encoded(doc))

    def test_binding_types_and_fixed_request_reject_dynamic_content(self):
        c = contract()
        identity = c.FileIdentity(7, bytes(range(16)))
        self.assertEqual(identity.file_id, bytes(range(16)))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            identity.volume_serial = 1
        for args in ((True, bytes(16)), (1, bytearray(16)), (1, bytes(15)), (-1, bytes(16))):
            with self.assertRaises((TypeError, ValueError)):
                c.FileIdentity(*args)
        for args in ((NONCE, True), (NONCE, 0), ("bad", 1)):
            with self.assertRaises((TypeError, ValueError)):
                c.CapsuleContext(*args)
        build = c.ReviewedBuild()
        self.assertIsNone(build.manifest_sha256)
        self.assertIsNone(build.exe_sha256)
        self.assertIsNone(build.machine)
        self.assertEqual(build.source_sha256, ())
        self.assertIsNone(build.protocol_version)
        invalid_builds = (
            {"manifest_sha256": "bad"},
            {"source_sha256": []},
            {"protocol_version": True},
        )
        for fields in invalid_builds:
            with self.assertRaises((TypeError, ValueError)):
                c.ReviewedBuild(**fields)
        request = {
            "schema": "swu.issue110.filter-request.v1",
            "mode": "fixed_no_target",
            "nonce": NONCE,
            "manifest_sha256": "a" * 64,
            "files": {
                name: {
                    "volume_serial": 7,
                    "file_id_hex": bytes(range(16)).hex(),
                    "sha256": char * 64,
                }
                for name, char in (("exe", "b"), ("dbgeng", "c"), ("dbghelp", "d"))
            },
        }
        parsed = c.parse_request(json.dumps(request).encode())
        self.assertEqual(parsed.exe.identity, identity)
        self.assertEqual(parsed.nonce, NONCE)
        for key in ("target", "script", "command", "path", "output_path"):
            bad = copy.deepcopy(request)
            bad[key] = "PRIVATE_CANARY"
            with self.assertRaises(c.CapsuleError):
                c.parse_request(json.dumps(bad).encode())
        for key in ("exe", "dbgeng", "dbghelp"):
            bad = copy.deepcopy(request)
            del bad["files"][key]
            with self.assertRaises(c.CapsuleError):
                c.parse_request(json.dumps(bad).encode())

    def test_portable_cpp_encoder_independent_fixture(self):
        header = ROOT / "scripts/diagnostics/issue110_filter_capsule.hpp"
        self.assertTrue(header.is_file(), "missing bounded portable capsule encoder")
        compiler = shutil.which("g++")
        if not compiler:
            self.skipTest("g++ unavailable; no portable/native compilation claimed")
        with tempfile.TemporaryDirectory(prefix="filter-capsule-test-") as directory:
            binary = Path(directory) / "capsule-test"
            compiled = subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-pedantic",
                    "-I",
                    str(ROOT),
                    str(ROOT / "tests/delivery/issue110_filter_capsule_test.cpp"),
                    "-o",
                    str(binary),
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            run = subprocess.run([str(binary)], capture_output=True, timeout=15, check=False)
            self.assertEqual(run.returncode, 0, run.stderr.decode())
            self.assertEqual(self.parse(run.stdout), self.parse(frame(GOLDEN_BODY)))
            boundary = subprocess.run(
                [str(binary), "--boundaries"], capture_output=True, timeout=15, check=False
            )
            self.assertEqual(boundary.returncode, 0, boundary.stderr.decode())
            self.assertEqual(len(boundary.stdout), 262143 + 262144)
            for data, pid in (
                (boundary.stdout[:262143], 42424),
                (boundary.stdout[262143:], 424242),
            ):
                receipt = contract().parse_capsule(data, contract().CapsuleContext(NONCE, pid))
                self.assertEqual(receipt.sx.data, b"A" * 65536)
                self.assertEqual(receipt.module_paths_utf16le, (b"A" * 8192,) * 7 + (b"A" * 7746,))


if __name__ == "__main__":
    unittest.main()
