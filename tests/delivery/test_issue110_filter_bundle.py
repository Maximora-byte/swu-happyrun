"""Synthetic seam tests only; no Windows, V6, process, loader or real build approval.

Positive cases patch only the expected tool digests to independent synthetic PE
fixtures. They test orchestration, not admission of any production identity.
Standard-library unittest is collected unchanged by pytest when available.
"""

import dataclasses
import hashlib
import importlib
import struct
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from test_issue110_filter_pe import fixture

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts/diagnostics"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

acl = importlib.import_module("issue110_local_acl")
contract = importlib.import_module("issue110_filter_contract")
pe = importlib.import_module("issue110_filter_pe")
Blocker, BoundFile = contract.Blocker, contract.BoundFile
FileIdentity, ReviewedBuild = contract.FileIdentity, contract.ReviewedBuild
DependencyEvidence, ReviewedPeFile = pe.DependencyEvidence, pe.ReviewedPeFile

USER = "S-1-5-21-1-2-3-1001"
VERSION = "10.0.26100.8249"
EXE = "issue110_filter_command_probe.exe"
NAMES = {"exe": EXE, "cdb": "cdb.exe", "dbgeng": "dbgeng.dll", "dbghelp": "dbghelp.dll"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def identity(value):
    return FileIdentity(7, value.to_bytes(16, "little"))


def module():
    assert (SCRIPTS / "issue110_filter_bundle.py").is_file(), "pinned bundle gate missing"
    return importlib.import_module("issue110_filter_bundle")


def security(*, prepared=False, outsider=False):
    def sid(value):
        parts = [int(part) for part in value.split("-")[1:]]
        return (
            bytes((parts[0], len(parts) - 2))
            + parts[1].to_bytes(6, "big")
            + b"".join(struct.pack("<I", part) for part in parts[2:])
        )

    owner = sid(USER)
    users = [USER, "S-1-5-18", "S-1-5-32-544"] if prepared else [USER]
    if outsider:
        users.append("S-1-5-11")
    aces = b"".join(
        struct.pack("<BBHI", 0, 3, 8 + len(sid(who)), 0x1F01FF) + sid(who) for who in users
    )
    dacl = struct.pack("<BBHHH", 2, 0, 8 + len(aces), len(users), 0) + aces
    return (
        struct.pack("<BBHIIII", 1, 0, 0x9004 if prepared else 0x8004, 20, 0, 0, 20 + len(owner))
        + owner
        + dacl
    )


class DirectoryAPI:
    """Standard-library regression double for the existing native ACL helper."""

    def __init__(self):
        self.user_sid = USER
        self.opened, self.closed, self.volumes = [], [], []
        self.attributes, self.unsafe = 0x10, False

    def drive_mapping(self, root):
        return "fixed-volume"

    def open_directory(self, path):
        self.opened.append(path)
        return path

    def inspect(self, handle):
        return self.attributes, handle, security(prepared=len(handle) > 3, outsider=self.unsafe)

    def volume(self, handle):
        self.volumes.append(handle)

    def close(self, handle):
        self.closed.append(handle)


class LegacyRoleTests(unittest.TestCase):
    def test_default_old_child_and_acl_behavior_unchanged(self):
        api = DirectoryAPI()
        made = []
        with patch.object(acl.os, "mkdir", made.append):
            with acl.PrivateDirectory(r"C:\private", api) as owner:
                self.assertEqual(str(owner.path), r"C:\private\issue110-local-config-1")
                self.assertEqual(acl.CHILD, "issue110-local-config-1")
                self.assertEqual(api.closed, [])
        self.assertEqual(made, [r"C:\private\issue110-local-config-1"])
        self.assertEqual(api.closed, list(reversed(api.opened)))

    def test_explicit_filter_probe_role_keeps_strict_prepared_checks(self):
        api = DirectoryAPI()
        with patch.object(acl.os, "mkdir") as mkdir:
            with acl.PrivateDirectory(
                r"C:\private", api, mode="prepared_top_level", child_role="filter_probe"
            ) as owner:
                self.assertEqual(str(owner.path), r"C:\private\issue110-filter-probe-1")
                self.assertEqual(owner.handles[-1][2], "filter_probe")
                self.assertEqual(acl.CHILD, "issue110-local-config-1")
                self.assertTrue(api.volumes)
            mkdir.assert_called_once_with(r"C:\private\issue110-filter-probe-1")

    def test_new_role_cannot_select_arbitrary_child_or_generic_root(self):
        for role, mode, root in (
            ("alternate", "prepared_top_level", r"C:\private"),
            ("filter_probe", "generic", r"C:\private"),
            ("filter_probe", "prepared_top_level", r"C:\a\b"),
        ):
            with self.subTest(role=role, mode=mode, root=root), self.assertRaises(ValueError):
                acl.PrivateDirectory(root, DirectoryAPI(), child_role=role, mode=mode)

    def test_new_role_rejects_reparse_and_unsafe_dacl_before_creation(self):
        for attrs, unsafe in ((0x410, False), (0, False), (0x10, True)):
            api = DirectoryAPI()
            api.attributes, api.unsafe = attrs, unsafe
            with patch.object(acl.os, "mkdir") as mkdir, self.assertRaises(ValueError):
                with acl.PrivateDirectory(
                    r"C:\private", api, mode="prepared_top_level", child_role="filter_probe"
                ):
                    self.fail("unsafe directory admitted")
            mkdir.assert_not_called()

    def test_legacy_helper_pins_match_exact_bytes(self):
        actual = digest((SCRIPTS / "issue110_local_acl.py").read_bytes())
        old = importlib.import_module("issue110_debugger_config_local")
        prep = importlib.import_module("issue110_prepare_private_root")
        self.assertEqual(old.EXPECTED_DEPENDENCIES["issue110_local_acl"], actual)
        self.assertEqual(prep.HELPER_SHA256, actual)

    def test_default_and_explicit_role_never_retry_existing_or_uncertain_mkdir(self):
        for role, mode in (("sample_child", "generic"), ("filter_probe", "prepared_top_level")):
            for original in (FileExistsError("PRIVATE_CANARY"), OSError("uncertain-create")):
                api = DirectoryAPI()
                with patch.object(acl.os, "mkdir", side_effect=original) as mkdir:
                    with (
                        self.subTest(role=role, error=type(original)),
                        self.assertRaises(type(original)) as caught,
                    ):
                        with acl.PrivateDirectory(r"C:\private", api, child_role=role, mode=mode):
                            self.fail("must not adopt or retry")
                self.assertIs(caught.exception, original)
                mkdir.assert_called_once()
                self.assertEqual(api.closed, list(reversed(api.opened)))

    def test_default_primary_exception_survives_ordinary_close_failure(self):
        for original in (KeyboardInterrupt(), SystemExit(7), ValueError("primary")):
            api = DirectoryAPI()

            def close(handle, *, api=api):
                api.closed.append(handle)
                raise OSError("PRIVATE_CANARY")

            with patch.object(acl.os, "mkdir"), self.assertRaises(type(original)) as caught:
                with acl.PrivateDirectory(r"C:\private", api):
                    api.close = close
                    raise original
            self.assertIs(caught.exception, original)
            self.assertEqual(api.closed, list(reversed(api.opened)))

    def test_filter_role_still_rejects_unknown_ntfs_volume(self):
        api = DirectoryAPI()
        api.volume = lambda _: (_ for _ in ()).throw(ValueError("volume-unverified"))
        with patch.object(acl.os, "mkdir") as mkdir, self.assertRaises(ValueError):
            with acl.PrivateDirectory(
                r"C:\private", api, child_role="filter_probe", mode="prepared_top_level"
            ):
                self.fail("unverified volume admitted")
        mkdir.assert_not_called()


class FakeBundleAPI:
    """Opaque in-memory handles; the fake attestation is NOT a real manifest."""

    def __init__(self, b):
        self.b = b
        self.time = 10.0
        self.events, self.opened, self.closed, self.close_deadlines = [], [], [], []
        self.files, self.bindings, self.versions = {}, {}, {}
        self.source = {role: fixture(marker=index + 1) for index, role in enumerate(NAMES)}
        self.hashes = {
            NAMES[role]: digest(data) for role, data in self.source.items() if role != "exe"
        }
        self.build = ReviewedBuild(
            "a" * 64,
            digest(self.source["exe"]),
            (("child.cpp", "b" * 64),),
            "x64",
            "synthetic-toolchain",
            (("DbgEng.h", "c" * 64),),
            1,
        )
        self.reviewed = True
        self.reserve_error = self.write_error = self.flush_error = None
        self.reserve_unknown = False
        self.signature_error = self.close_error = None
        self.signature_valid, self.signature_cleanup = True, None
        self.signature_elapsed = 0
        self.change_source = self.change_stage = None
        self.stage_alias = False
        self.evidence_unknown = False
        self.dep = []
        self.mappings = ()
        self.system_files = {}
        self.close_elapsed = 0

    def now(self):
        return self.time

    def reviewed_build_version(self, build):
        self.events.append(("review",))
        return "1.0.0.0" if self.reviewed and build == self.build else None

    def _open(self, handle):
        self.opened.append(handle)
        return handle

    def open_directory(self, path, *, role):
        self.events.append(("open_directory", path, role))
        return self._open(("directory", path, role))

    def validate_directory(self, handle, *, path, role):
        self.events.append(("validate_directory", path, role))
        return identity(self.opened.index(handle) + 1)

    def reserve_child(self, root, name, *, exclusive):
        self.events.append(("reserve", name, exclusive))
        if self.reserve_error:
            raise self.reserve_error
        if self.reserve_unknown:
            return None
        return self._open(("child", name))

    def create_stage(self, child, *, exclusive):
        self.events.append(("stage", exclusive))
        return self._open(("stage",))

    def write_exclusive(self, child, name, data, *, exclusive):
        self.events.append(("write", name, exclusive, data))
        if self.write_error:
            raise self.write_error
        return self._open(("attempt", name))

    def flush(self, handle):
        self.events.append(("flush", handle))
        if self.flush_error:
            raise self.flush_error
        return True

    def pin_source(self, role, build, *, share_mode, inheritable):
        self.events.append(("pin", role, share_mode, inheritable))
        handle = self._open(("source", role))
        self.files[handle] = self.source[role]
        self.bindings[handle] = BoundFile(
            identity(100 + len(self.files)), digest(self.files[handle])
        )
        self.versions[handle] = "1.0.0.0" if role == "exe" else VERSION
        return handle

    def read_pin(self, handle, *, limit):
        self.events.append(("read", handle, limit))
        return self.files[handle]

    def pin_identity(self, handle):
        return self.bindings[handle].identity

    def revalidate_pin(self, handle):
        self.events.append(("validate_pin", handle))
        binding, version = self.bindings[handle], self.versions[handle]
        change = self.change_source if handle[0] == "source" else self.change_stage
        if change and (handle[0] == "copy" or any(e[0] == "v6" for e in self.events)):
            if change == "identity":
                binding = BoundFile(identity(9000), binding.sha256)
            elif change == "hash":
                binding = BoundFile(binding.identity, "f" * 64)
            elif change == "version":
                version = "changed"
        return binding, version

    def verify_installed_v6(self, pins, *, deadline):
        self.events.append(("v6", pins, deadline))
        self.time += self.signature_elapsed
        if self.signature_error:
            raise self.signature_error
        return self.b.SignatureVerification(self.signature_valid, self.signature_cleanup)

    def dependency_evidence(self, build):
        self.events.append(("dependencies",))
        if self.evidence_unknown:
            return DependencyEvidence()
        files = tuple(
            ReviewedPeFile(
                NAMES[role], self.bindings[("source", role)], "stage", True, True, True, True
            )
            for role in ("exe", "dbgeng", "dbghelp")
        )
        return DependencyEvidence(files + tuple(self.dep), self.mappings, "synthetic-windows-build")

    def pin_dependency(self, reviewed, *, share_mode, inheritable):
        self.events.append(("system_pin", share_mode, inheritable))
        handle = self._open(("system", reviewed.name))
        self.files[handle] = self.system_files[reviewed.name]
        self.bindings[handle] = reviewed.bound
        self.versions[handle] = "10.0.0.0"
        return handle

    def copy_exclusive(self, source, stage, name, *, exclusive, share_mode, inheritable):
        self.events.append(("copy", source, name, exclusive, share_mode, inheritable))
        handle = self._open(("copy", name))
        self.files[handle] = self.files[source]
        source_bound = self.bindings[source]
        file_id = source_bound.identity if self.stage_alias else identity(1000 + len(self.files))
        self.bindings[handle] = BoundFile(file_id, source_bound.sha256)
        self.versions[handle] = self.versions[source]
        return handle

    def drain_pending(self, *, deadline):
        self.events.append(("drain", deadline))
        self.close_deadlines.append(deadline)
        return True

    def close(self, handle, *, deadline):
        self.closed.append(handle)
        self.close_deadlines.append(deadline)
        self.time += self.close_elapsed
        if self.close_error:
            raise self.close_error
        return True


class FilterBundleTests(unittest.TestCase):
    def fake(self):
        b = module()
        return b, FakeBundleAPI(b)

    def prepare(self, api, *, deadline=300.0):
        with patch.object(api.b, "DEBUGGER_HASHES", api.hashes):
            return api.b.prepare_bundle(api.build, r"C:\private", deadline, api)

    def test_owned_pins_immutable_stage_and_fixed_three_files(self):
        b, api = self.fake()
        with self.prepare(api) as owner:
            self.assertIsInstance(owner, b.PinnedBundle)
            self.assertEqual(owner.stage_path, r"C:\private\issue110-filter-probe-1\stage")
            self.assertEqual(
                tuple(name for name, _ in owner.stage_files), (EXE, "dbgeng.dll", "dbghelp.dll")
            )
            self.assertEqual(owner.manifest_sha256, api.build.manifest_sha256)
            self.assertEqual(owner.deadline, 300.0)
            self.assertIsNone(owner.signature_cleanup)
            self.assertEqual(api.closed, [])
            for event in api.events:
                if event[0] == "pin":
                    self.assertEqual(event[2:], (1, False))
                elif event[0] == "copy":
                    self.assertEqual(event[3:], (True, 1, False))
            with self.assertRaises(AttributeError):
                owner.stage_files = ()
            owner.revalidate()
        self.assertTrue(owner.closed)
        self.assertIs(owner.cleanup, True)
        self.assertEqual(api.closed, list(reversed(api.opened)))
        self.assertEqual(set(api.close_deadlines), {15.0})
        with self.assertRaises(b.BundleError):
            owner.revalidate()
        owner.close()
        self.assertEqual(len(api.closed), len(api.opened))

    def test_owner_not_freely_constructible_and_api_has_no_process_method(self):
        b, _ = self.fake()
        with self.assertRaises(TypeError):
            b.PinnedBundle()
        for name in ("create_process", "create_suspended", "resume", "load_library"):
            self.assertFalse(hasattr(b.BundleAPI, name))

    def test_attempt_written_and_flushed_before_one_installed_v6(self):
        _, api = self.fake()
        with self.prepare(api):
            kinds = [event[0] for event in api.events]
            self.assertLess(kinds.index("write"), kinds.index("flush"))
            self.assertLess(kinds.index("flush"), kinds.index("v6"))
            record = next(e for e in api.events if e[0] == "write")
            self.assertEqual(record[1:3], ("attempt.json", True))
            self.assertIn(b'"reservation_is_authorization":false', record[3])
            signatures = [event for event in api.events if event[0] == "v6"]
            self.assertEqual(len(signatures), 1)
            self.assertEqual(
                signatures[0][1], tuple(("source", role) for role in ("cdb", "dbgeng", "dbghelp"))
            )
            self.assertEqual(signatures[0][2], 40.0)
            copies = [e for e in api.events if e[0] == "copy"]
            self.assertEqual(len(copies), 3)
            self.assertNotIn("cdb.exe", [e[2] for e in copies])

    def test_existing_or_uncertain_reservation_is_single_attempt(self):
        for occupied in (True, False):
            b, api = self.fake()
            api.reserve_error = FileExistsError("PRIVATE_CANARY") if occupied else None
            api.reserve_unknown = not occupied
            with self.subTest(occupied=occupied), self.assertRaises(BaseException) as caught:
                self.prepare(api)
            if not occupied:
                self.assertEqual(caught.exception.blocker, Blocker.RESERVATION_UNCERTAIN)
            self.assertEqual(sum(e[0] == "reserve" for e in api.events), 1)
            self.assertFalse(any(e[0] in {"write", "v6", "copy"} for e in api.events))
            self.assertEqual(api.closed, list(reversed(api.opened)))

    def test_write_and_flush_failure_stop_before_v6(self):
        for field in ("write_error", "flush_error"):
            _, api = self.fake()
            original = OSError("PRIVATE_CANARY")
            setattr(api, field, original)
            with self.subTest(field=field), self.assertRaises(OSError) as caught:
                self.prepare(api)
            self.assertIs(caught.exception, original)
            self.assertFalse(any(e[0] == "v6" for e in api.events))

    def test_source_identity_changes_before_copy(self):
        for change in ("identity", "hash", "version"):
            b, api = self.fake()
            api.change_source = change
            with self.subTest(change=change), self.assertRaises(b.BundleError):
                self.prepare(api)
            self.assertFalse(any(e[0] == "copy" for e in api.events))

    def test_changed_stage_identity_hash_version_or_alias_never_admitted(self):
        for change in ("identity", "hash", "version", "alias"):
            b, api = self.fake()
            if change == "alias":
                api.stage_alias = True
            else:
                api.change_stage = change
            with self.subTest(change=change), self.assertRaises(b.BundleError):
                self.prepare(api)
            self.assertEqual(api.closed, list(reversed(api.opened)))

    def test_unknown_build_manifest_and_evidence_fail_closed(self):
        for change in ("empty", "unreviewed", "manifest", "dependencies"):
            b, api = self.fake()
            if change == "empty":
                api.build = ReviewedBuild()
            elif change == "unreviewed":
                api.reviewed = False
            elif change == "manifest":
                original = api.build
                api.build = dataclasses.replace(api.build, manifest_sha256="d" * 64)
                api.reviewed_build_version = lambda build, original=original: (
                    "1.0.0.0" if build == original else None
                )
            else:
                api.evidence_unknown = True
            with self.subTest(change=change), self.assertRaises(b.BundleError):
                self.prepare(api)
            self.assertFalse(any(e[0] == "copy" for e in api.events))
            if change != "dependencies":
                self.assertFalse(any(e[0] == "reserve" for e in api.events))

    def test_signature_rejection_or_equal_deadline_blocks_copy(self):
        for valid, elapsed in ((False, 0), (True, 30), (True, 31)):
            b, api = self.fake()
            api.signature_valid, api.signature_elapsed = valid, elapsed
            with self.subTest(valid=valid, elapsed=elapsed), self.assertRaises(b.BundleError):
                self.prepare(api)
            self.assertEqual(sum(e[0] == "v6" for e in api.events), 1)
            self.assertFalse(any(e[0] == "copy" for e in api.events))

    def test_short_remaining_budget_uses_same_overall_deadline(self):
        _, api = self.fake()
        with self.prepare(api, deadline=28.0):
            self.assertEqual(next(e[2] for e in api.events if e[0] == "v6"), 28.0)

    def test_late_preparation_does_not_produce_bundle_or_reset_deadline(self):
        b, api = self.fake()
        api.signature_elapsed = 5
        with self.assertRaises(b.BundleError):
            self.prepare(api, deadline=15.0)

    def test_primary_cancel_survives_cleanup_exception(self):
        for original in (KeyboardInterrupt(), SystemExit(7), ValueError("primary")):
            _, api = self.fake()
            api.signature_error = original
            api.close_error = OSError("PRIVATE_CANARY")
            with self.subTest(original=type(original)), self.assertRaises(type(original)) as caught:
                self.prepare(api)
            self.assertIs(caught.exception, original)
            self.assertIsNone(caught.exception.bundle_cleanup)
            self.assertIsNone(caught.exception.signature_cleanup)
            self.assertEqual(api.closed, list(reversed(api.opened)))
            self.assertEqual(len(set(api.close_deadlines)), 1)

    def test_close_unknown_does_not_claim_complete_or_retry(self):
        b, api = self.fake()
        owner = self.prepare(api)
        api.close_error = OSError("PRIVATE_CANARY")
        with self.assertRaises(b.BundleError) as caught:
            owner.close()
        self.assertEqual(caught.exception.blocker, Blocker.CLEANUP_UNKNOWN)
        self.assertIsNone(owner.cleanup)
        self.assertEqual(api.closed, list(reversed(api.opened)))
        owner.close()
        self.assertEqual(len(api.closed), len(api.opened))

    def test_current_system_graph_is_pinned_and_bound_before_copy(self):
        _, api = self.fake()
        api.source["exe"] = fixture(imports=(b"KERNEL32.dll",), marker=1)
        api.build = dataclasses.replace(api.build, exe_sha256=digest(api.source["exe"]))
        system = fixture(marker=99)
        api.system_files["KERNEL32.dll"] = system
        system_bound = BoundFile(identity(500), digest(system))
        api.dep = [ReviewedPeFile("KERNEL32.dll", system_bound, "system", True, True, True, True)]
        api.mappings = (
            pe.DependencyMapping(
                api.build.exe_sha256, "KERNEL32.dll", system_bound.sha256, "known_dll", True
            ),
        )
        with self.prepare(api):
            kinds = [e[0] for e in api.events]
            self.assertLess(kinds.index("system_pin"), kinds.index("copy"))
            self.assertEqual(next(e[1:] for e in api.events if e[0] == "system_pin"), (1, False))
            self.assertNotIn(("system", "KERNEL32.dll"), api.closed)

    def test_unknown_import_or_unpinned_dependency_identity_cannot_reach_copy(self):
        for mismatch in (False, True):
            b, api = self.fake()
            api.source["exe"] = fixture(imports=(b"UNKNOWN.dll",), marker=1)
            api.build = dataclasses.replace(api.build, exe_sha256=digest(api.source["exe"]))
            if mismatch:
                original = api.dependency_evidence

                def evidence(build, *, original=original):
                    value = original(build)
                    file = dataclasses.replace(
                        value.files[0], bound=BoundFile(identity(999), value.files[0].bound.sha256)
                    )
                    return dataclasses.replace(value, files=(file,) + value.files[1:])

                api.dependency_evidence = evidence
            with self.subTest(mismatch=mismatch), self.assertRaises(b.BundleError):
                self.prepare(api)
            self.assertFalse(any(e[0] == "copy" for e in api.events))

    def test_original_tool_hashes_remain_required_without_synthetic_patch(self):
        b, api = self.fake()
        with self.assertRaises(b.BundleError):
            b.prepare_bundle(api.build, r"C:\private", 300.0, api)
        self.assertFalse(any(e[0] in {"v6", "copy"} for e in api.events))

    def test_invalid_deadlines_or_non_top_level_root_never_reserve(self):
        for deadline, root in (
            (10.0, r"C:\private"),
            (float("nan"), r"C:\private"),
            (311.0, r"C:\private"),
            (300.0, r"C:\private\nested"),
        ):
            _, api = self.fake()
            with self.subTest(deadline=deadline, root=root), self.assertRaises(ValueError):
                api.b.prepare_bundle(api.build, root, deadline, api)
            self.assertFalse(any(e[0] == "reserve" for e in api.events))

    def test_owner_revalidation_catches_changes_after_return(self):
        b, api = self.fake()
        owner = self.prepare(api)
        api.change_stage = "identity"
        with self.assertRaises(b.BundleError):
            owner.revalidate()
        owner.close()

    def test_all_close_attempts_share_one_budget_and_expiry_is_unknown(self):
        b, api = self.fake()
        owner = self.prepare(api)
        api.close_elapsed = 3
        with self.assertRaises(b.BundleError):
            owner.close()
        self.assertEqual(len(api.closed), 2)
        self.assertEqual(set(api.close_deadlines), {15.0})
        self.assertIsNone(owner.cleanup)
        owner.close()
        self.assertEqual(len(api.closed), 2)

    def test_v6_failure_preserves_independent_cleanup_fact(self):
        _, api = self.fake()
        original = KeyboardInterrupt()
        original.signature_cleanup = False
        api.signature_error = original
        api.close_error = OSError("PRIVATE_CANARY")
        with self.assertRaises(KeyboardInterrupt) as caught:
            self.prepare(api)
        self.assertIs(caught.exception, original)
        self.assertIs(caught.exception.signature_cleanup, False)
        self.assertIsNone(caught.exception.bundle_cleanup)

    def test_host_and_bundle_can_share_cleanup_deadline_without_reset(self):
        b, api = self.fake()
        owner = self.prepare(api)
        owner.begin_cleanup(14.0)
        api.time = 12.0
        with self.assertRaises(b.BundleError):
            owner.revalidate()
        with self.assertRaises(b.BundleError):
            owner.begin_cleanup(17.0)
        owner.close(cleanup_deadline=14.0)
        self.assertEqual(set(api.close_deadlines), {14.0})
        self.assertIs(owner.cleanup, True)

    def test_exhausted_shared_cleanup_budget_never_restarts_bundle_closes(self):
        b, api = self.fake()
        owner = self.prepare(api)
        owner.begin_cleanup(15.0)
        api.time = 15.0
        with self.assertRaises(b.BundleError):
            owner.close()
        self.assertEqual(api.closed, [])
        self.assertIsNone(owner.cleanup)

    def test_expired_signature_window_is_not_entered_even_before_overall_deadline(self):
        b, api = self.fake()
        reads = 0

        def now():
            nonlocal reads
            if sum(e[0] == "validate_pin" for e in api.events) == 8:
                reads += 1
                if reads >= 3:
                    api.time = 41.0
            return api.time

        api.now = now
        with self.assertRaises(b.BundleError):
            self.prepare(api)
        self.assertFalse(any(e[0] == "v6" for e in api.events))

    def test_normal_close_preserves_cleanup_cancel_after_ordinary_error(self):
        for cancel in (KeyboardInterrupt(), SystemExit(7)):
            for context_exit in (False, True):
                _, api = self.fake()
                owner = self.prepare(api)

                def close(handle, *, deadline, api=api, cancel=cancel):
                    api.closed.append(handle)
                    api.close_deadlines.append(deadline)
                    if len(api.closed) == 1:
                        raise OSError("PRIVATE_CANARY")
                    if len(api.closed) == 2:
                        raise cancel
                    return True

                api.close = close
                caught = None
                try:
                    if context_exit:
                        with owner:
                            pass
                    else:
                        owner.close()
                except BaseException as error:
                    caught = error
                with self.subTest(cancel=type(cancel), context_exit=context_exit):
                    self.assertIs(caught, cancel)
                    self.assertIsNone(caught.bundle_cleanup)
                    self.assertIsNone(caught.signature_cleanup)
                    self.assertIsNone(owner.cleanup)
                    self.assertTrue(owner.closed)
                    self.assertEqual(api.closed, list(reversed(api.opened)))
                    self.assertEqual(set(api.close_deadlines), {15.0})
                    owner.close()
                    self.assertEqual(len(api.closed), len(api.opened))

    def test_existing_body_primary_survives_cleanup_error_then_cancel(self):
        for primary in (ValueError("primary"), KeyboardInterrupt(), SystemExit(3)):
            for cancel in (KeyboardInterrupt(), SystemExit(7)):
                _, api = self.fake()
                owner = self.prepare(api)

                def close(handle, *, deadline, api=api, cancel=cancel):
                    api.closed.append(handle)
                    api.close_deadlines.append(deadline)
                    if len(api.closed) == 1:
                        raise OSError("PRIVATE_CANARY")
                    if len(api.closed) == 2:
                        raise cancel
                    return True

                api.close = close
                with self.subTest(primary=type(primary), cancel=type(cancel)):
                    with self.assertRaises(type(primary)) as caught:
                        with owner:
                            raise primary
                    self.assertIs(caught.exception, primary)
                    self.assertIsNone(caught.exception.bundle_cleanup)
                    self.assertIsNone(caught.exception.signature_cleanup)
                    self.assertIsNone(owner.cleanup)
                    self.assertTrue(owner.closed)
                    self.assertEqual(api.closed, list(reversed(api.opened)))
                    self.assertEqual(set(api.close_deadlines), {15.0})

    def test_pending_drain_failure_or_cancel_is_included_without_skipping_owned_closes(self):
        for secondary in (None, OSError("drain"), KeyboardInterrupt(), SystemExit(9)):
            b, api = self.fake()
            owner = self.prepare(api)
            calls = []

            def drain(*, deadline, calls=calls, secondary=secondary):
                calls.append(deadline)
                if secondary is not None:
                    raise secondary
                return None

            api.drain_pending = drain
            expected = (
                type(secondary)
                if secondary is not None and not isinstance(secondary, Exception)
                else b.BundleError
            )
            with self.assertRaises(expected):
                owner.close()
            self.assertIsNone(owner.cleanup)
            self.assertEqual(api.closed, list(reversed(api.opened)))
            self.assertEqual(set(calls + api.close_deadlines), {15.0})
            owner.close()
            self.assertEqual(calls, [15.0])

    def test_pending_drain_consumes_only_the_existing_cleanup_C(self):
        b, api = self.fake()
        owner = self.prepare(api)
        calls = []

        def drain(*, deadline):
            calls.append(deadline)
            api.time = deadline
            return True

        api.drain_pending = drain
        with self.assertRaises(b.BundleError):
            owner.close()
        self.assertEqual(calls, [15.0])
        self.assertEqual(api.closed, [])
        self.assertIsNone(owner.cleanup)


if __name__ == "__main__":
    unittest.main()
