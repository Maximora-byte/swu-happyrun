"""Synthetic PE bytes and synthetic review evidence only; no host or loader access."""

import dataclasses
import hashlib
import importlib.util
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIAGNOSTICS = ROOT / "scripts/diagnostics"
MODULE = DIAGNOSTICS / "issue110_filter_pe.py"
# Standard-library unittest is also collected unchanged by pytest.
if str(DIAGNOSTICS) not in sys.path:
    sys.path.insert(0, str(DIAGNOSTICS))

PE = 0x80
OPTIONAL = PE + 24
SECTIONS = OPTIONAL + 240
DIRECTORIES = OPTIONAL + 112


def pe_module():
    assert MODULE.is_file(), "missing bounded PE metadata inspector"
    name = "issue110_filter_pe"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, MODULE)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def rva(offset):
    return offset + 0xE00


def directory(data, index, offset, size):
    struct.pack_into("<II", data, DIRECTORIES + index * 8, rva(offset), size)


def fixture(imports=(), delay=(), manifest=None, marker=0):
    """Hand-built PE32+ metadata, not compiler/inspector-generated expectations."""
    data = bytearray(0x1A00)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, PE)
    data[PE : PE + 4] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", data, PE + 4, 0x8664, 1, marker, 0, 0, 240, 0x22)
    struct.pack_into("<H", data, OPTIONAL, 0x20B)
    struct.pack_into("<Q", data, OPTIONAL + 24, 0x140000000)
    struct.pack_into("<II", data, OPTIONAL + 32, 0x1000, 0x200)
    struct.pack_into("<II", data, OPTIONAL + 56, 0x3000, 0x200)
    struct.pack_into("<I", data, OPTIONAL + 108, 16)
    struct.pack_into(
        "<8sIIIIIIHHI",
        data,
        SECTIONS,
        b".rdata\0\0",
        0x1800,
        0x1000,
        0x1800,
        0x200,
        0,
        0,
        0,
        0,
        0x40000040,
    )
    for names, start, width, namebase, thunkbase in (
        (imports, 0x300, 20, 0x500, 0x700),
        (delay, 0x900, 32, 0xB00, 0xC00),
    ):
        if names:
            directory(data, 1 if width == 20 else 13, start, (len(names) + 1) * width)
        for index, name in enumerate(names):
            name_offset = namebase + index * 64
            lookup = thunkbase + index * 32
            iat = lookup + 16
            data[name_offset : name_offset + len(name) + 1] = name + b"\0"
            # Import by ordinal, terminated 64-bit lookup and IAT arrays.
            struct.pack_into("<QQ", data, lookup, (1 << 63) | 1, 0)
            struct.pack_into("<QQ", data, iat, (1 << 63) | 1, 0)
            if width == 20:
                struct.pack_into(
                    "<IIIII",
                    data,
                    start + index * width,
                    rva(lookup),
                    0,
                    0,
                    rva(name_offset),
                    rva(iat),
                )
            else:
                struct.pack_into(
                    "<IIIIIIII",
                    data,
                    start + index * width,
                    1,
                    rva(name_offset),
                    rva(0xCF0),
                    rva(iat),
                    rva(lookup),
                    0,
                    0,
                    0,
                )
    if manifest is not None:
        directory(data, 2, 0xD00, 0x200)
        # RT_MANIFEST=24 -> ID=1 -> language=1033 -> data entry.
        for offset, identifier, child in ((0xD00, 24, 0x20), (0xD20, 1, 0x40)):
            struct.pack_into(
                "<IIHHHHII", data, offset, 0, 0, 0, 0, 0, 1, identifier, 0x80000000 | child
            )
        struct.pack_into("<IIHHHHII", data, 0xD40, 0, 0, 0, 0, 0, 1, 1033, 0x60)
        struct.pack_into("<IIII", data, 0xD60, rva(0xD80), len(manifest), 0, 0)
        data[0xD80 : 0xD80 + len(manifest)] = manifest
    return bytes(data)


class FilterPeTests(unittest.TestCase):
    def reject(self, data):
        p = pe_module()
        with self.assertRaises(p.PeError) as caught:
            p.inspect_pe(data)
        self.assertIsInstance(caught.exception.code, p.PeErrorCode)
        self.assertNotIn("CANARY", str(caught.exception))

    def reviewed(self, facts, names=None, roles=None):
        """Explicitly fictitious evidence: never a real Windows allowlist."""
        p = pe_module()
        from issue110_filter_contract import BoundFile, FileIdentity

        names = names or tuple(f"synthetic{index}.dll" for index in range(len(facts)))
        roles = roles or ("stage",) * len(facts)
        return tuple(
            p.ReviewedPeFile(
                name,
                BoundFile(FileIdentity(77, bytes([index + 1]) * 16), fact.sha256),
                role,
                reviewed=True,
                adjacent_manifest_absent=True,
                dot_local_absent=True,
                activation_context_verified=True,
                reviewed_manifest_sha256=fact.manifest_sha256,
            )
            for index, (fact, name, role) in enumerate(zip(facts, names, roles, strict=True))
        )

    def evidence(self, facts, names=None, roles=None, mappings=()):
        p = pe_module()
        return p.DependencyEvidence(
            self.reviewed(facts, names, roles), mappings, windows_build="SYNTHETIC-TEST-ONLY"
        )

    def test_literal_x64_facts_preserve_names_and_external_requirements(self):
        p = pe_module()
        data = fixture((b"Example.DLL",), (b"api-ms-synthetic-l1-1-0.dll",))
        facts = p.inspect_pe(data)
        self.assertIs(facts.x64, True)
        self.assertEqual(facts.sha256, hashlib.sha256(data).hexdigest())
        self.assertEqual(facts.imports, ("Example.DLL",))
        self.assertEqual(facts.delay_imports, ("api-ms-synthetic-l1-1-0.dll",))
        self.assertIs(facts.resource_present, False)
        self.assertEqual(facts.manifest_sha256, ())
        self.assertEqual(
            facts.redirection_requirements, ("adjacent_manifest", "dot_local", "activation_context")
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            facts.x64 = False

    def test_truncations_signatures_machine_and_pe32_rejected(self):
        baseline = fixture()
        for size in (0, 1, 2, 63, 0x83, OPTIONAL + 239, SECTIONS + 39, len(baseline) - 1):
            with self.subTest(size=size):
                self.reject(baseline[:size])
        for offset, value in (
            (0, b"NO"),
            (PE, b"PX\0\0"),
            (PE + 4, b"\x4c\x01"),
            (OPTIONAL, b"\x0b\x01"),
        ):
            with self.subTest(offset=offset):
                data = bytearray(baseline)
                data[offset : offset + len(value)] = value
                self.reject(bytes(data))

    def test_input_and_explicit_limits(self):
        p = pe_module()
        for value in (bytearray(fixture()), memoryview(fixture()), "CANARY"):
            with self.assertRaises(TypeError):
                p.inspect_pe(value)
        self.reject(b"MZ" + bytes(p.PE_LIMIT - 1))
        for offset, fmt, value in (
            (PE + 6, "H", 97),
            (OPTIONAL + 108, "I", 17),
            (0x3C, "I", 0xFFFFFFF0),
        ):
            data = bytearray(fixture())
            struct.pack_into("<" + fmt, data, offset, value)
            self.reject(bytes(data))

    def test_rva_out_of_bounds_partial_and_virtual_only_data_rejected(self):
        for address, size in ((0xFFFFFFF0, 40), (0x27F0, 40), (0x1000, 0), (0, 40)):
            data = bytearray(fixture((b"a.dll",)))
            struct.pack_into("<II", data, DIRECTORIES + 8, address, size)
            self.reject(bytes(data))
        data = bytearray(fixture((b"a.dll",)))
        struct.pack_into("<I", data, SECTIONS + 8, 0x2000)
        struct.pack_into("<I", data, 0x30C, 0x2A00)
        self.reject(bytes(data))

    def test_overlapping_sections_and_metadata_tables_rejected(self):
        for raw, virtual in ((0x200, 0x3000), (0x400, 0x1000), (0x100, 0x3000)):
            data = bytearray(fixture((b"a.dll",)))
            struct.pack_into("<H", data, PE + 6, 2)
            struct.pack_into(
                "<8sIIIIIIHHI",
                data,
                SECTIONS + 40,
                b"other\0\0\0",
                0x100,
                virtual,
                0x100,
                raw,
                0,
                0,
                0,
                0,
                0x40000040,
            )
            self.reject(bytes(data))
        data = bytearray(fixture((b"a.dll",), (b"b.dll",)))
        directory(data, 13, 0x310, 64)
        self.reject(bytes(data))
        # Import lookup/IAT aliasing descriptor bytes is not an independent parse.
        data = bytearray(fixture((b"a.dll",)))
        struct.pack_into("<I", data, 0x300, rva(0x300))
        self.reject(bytes(data))

    def test_shared_metadata_table_aliases_and_delay_handle_overlap_rejected(self):
        # Two independent DLL descriptors must not own the same mutable IAT.
        for offset in (0x300 + 20, 0x300 + 20 + 16):
            data = bytearray(fixture((b"a.dll", b"b.dll")))
            struct.pack_into("<I", data, offset, rva(0x700 if offset == 0x314 else 0x710))
            with self.subTest(offset=offset):
                self.reject(bytes(data))
        data = bytearray(fixture(delay=(b"a.dll",)))
        struct.pack_into("<I", data, 0x908, rva(0x900))
        with self.subTest(kind="delay_handle"):
            self.reject(bytes(data))

    def test_single_descriptor_lookup_iat_exact_alias_keeps_the_dependency_edge(self):
        # P3: normal OFT fallback, explicit same-table normal and delay forms
        # normalize ONE descriptor's exact table. This is not Windows acceptance.
        p = pe_module()
        for kind in ("normal_fallback", "normal_explicit", "delay_explicit"):
            with self.subTest(kind=kind):
                data = bytearray(
                    fixture(delay=(b"target.dll",))
                    if kind == "delay_explicit"
                    else fixture((b"target.dll",))
                )
                if kind == "normal_fallback":
                    struct.pack_into("<I", data, 0x300, 0)
                elif kind == "normal_explicit":
                    struct.pack_into("<I", data, 0x310, rva(0x700))
                else:
                    struct.pack_into("<I", data, 0x90C, rva(0xC00))
                facts = (p.inspect_pe(bytes(data)), p.inspect_pe(fixture(marker=19)))
                self.assertEqual(
                    facts[0].delay_imports if kind == "delay_explicit" else facts[0].imports,
                    ("target.dll",),
                )
                mapping = p.DependencyMapping(
                    facts[0].sha256, "target.dll", facts[1].sha256, "stage", verified=True
                )
                evidence = self.evidence(
                    facts, names=("root.exe", "target.dll"), mappings=(mapping,)
                )
                self.assertTrue(p.admit_dependencies(facts, evidence).admitted)
                self.assertFalse(
                    p.admit_dependencies(facts, dataclasses.replace(evidence, mappings=())).admitted
                )

    def test_unterminated_empty_non_ascii_and_overlong_dll_names_rejected(self):
        for name in (b"", b"\xff.dll", b"A" * 256):
            self.reject(fixture((name,)))
        data = bytearray(fixture((b"a.dll",)))
        struct.pack_into("<I", data, 0x30C, 0x27F0)
        data[-16:] = b"A" * 16
        self.reject(bytes(data))

    def test_descriptor_terminators_and_delay_attributes_are_required(self):
        data = bytearray(fixture((b"a.dll",)))
        directory(data, 1, 0x300, 20)
        self.reject(bytes(data))
        for flags in (0, 2, 3):
            data = bytearray(fixture(delay=(b"a.dll",)))
            struct.pack_into("<I", data, 0x900, flags)
            self.reject(bytes(data))
        data = bytearray(fixture(delay=(b"a.dll",)))
        directory(data, 13, 0x900, 32)
        self.reject(bytes(data))

    def test_import_thunks_and_hint_names_are_bounded(self):
        data = bytearray(fixture((b"a.dll",)))
        struct.pack_into("<Q", data, 0x700, 0xFFFFFFF0)
        self.reject(bytes(data))
        data = bytearray(fixture((b"a.dll",)))
        struct.pack_into("<Q", data, 0x700, rva(0x1500))
        data[0x1500:0x1502] = b"\0\0"
        data[0x1502:] = b"X" * (len(data) - 0x1502)
        self.reject(bytes(data))
        data = bytearray(fixture((b"a.dll",)))
        struct.pack_into("<Q", data, 0x700, (1 << 63) | 0x10001)
        self.reject(bytes(data))

    def test_embedded_manifest_is_hashed_not_assumed_safe(self):
        p = pe_module()
        manifest = b"<assembly><!-- SYNTHETIC ONLY --></assembly>"
        facts = p.inspect_pe(fixture(manifest=manifest))
        self.assertIs(facts.resource_present, True)
        self.assertEqual(facts.manifest_sha256, (hashlib.sha256(manifest).hexdigest(),))
        evidence = self.evidence((facts,))
        missing_review = dataclasses.replace(evidence.files[0], reviewed_manifest_sha256=())
        decision = p.admit_dependencies(
            (facts,), dataclasses.replace(evidence, files=(missing_review,))
        )
        self.assertIs(decision.admitted, False)
        self.assertIs(p.admit_dependencies((facts,), evidence).admitted, True)

    def test_resource_cycles_out_of_range_and_overlapping_data_rejected(self):
        for offset, value in (
            (0xD14, 0x80000000),
            (0xD14, 0x800001F8),
            (0xD54, 0x1F8),
            (0xD60, 0xFFFFFFF0),
            (0xD60, rva(0xD00)),
        ):
            data = bytearray(fixture(manifest=b"synthetic"))
            struct.pack_into("<I", data, offset, value)
            self.reject(bytes(data))
        data = bytearray(fixture(manifest=b"synthetic"))
        struct.pack_into("<H", data, 0xD0E, 0xFFFF)
        self.reject(bytes(data))

    def test_no_evidence_unknown_platform_or_unreviewed_file_never_admitted(self):
        p = pe_module()
        facts = (p.inspect_pe(fixture()),)
        for evidence in (p.DependencyEvidence(), self.evidence(facts)):
            if evidence.files:
                evidence = dataclasses.replace(evidence, windows_build=None)
            self.assertIs(p.admit_dependencies(facts, evidence).admitted, False)
        evidence = self.evidence(facts)
        self.assertIs(
            p.admit_dependencies(
                facts,
                dataclasses.replace(
                    evidence, files=(dataclasses.replace(evidence.files[0], reviewed=False),)
                ),
            ).admitted,
            False,
        )
        self.assertIs(p.admit_dependencies((), evidence).admitted, False)

    def test_adjacent_manifest_dot_local_and_activation_context_need_exact_evidence(self):
        p = pe_module()
        facts = (p.inspect_pe(fixture()),)
        evidence = self.evidence(facts)
        for name in ("adjacent_manifest_absent", "dot_local_absent", "activation_context_verified"):
            for value in (None, False):
                file = dataclasses.replace(evidence.files[0], **{name: value})
                self.assertIs(
                    p.admit_dependencies(
                        facts, dataclasses.replace(evidence, files=(file,))
                    ).admitted,
                    False,
                )

    def test_every_system_looking_basename_or_api_prefix_stays_unknown(self):
        p = pe_module()
        for name in (
            b"kernel32.dll",
            b"ntdll.dll",
            b"api-ms-win-core-test-l1-1-0.dll",
            b"ext-ms-synthetic.dll",
            b"dbgeng.dll",
        ):
            facts = (p.inspect_pe(fixture((name,))),)
            evidence = self.evidence(facts)
            self.assertIs(p.admit_dependencies(facts, evidence).admitted, False)

    def test_path_like_names_never_admitted_even_with_exact_synthetic_mapping(self):
        p = pe_module()
        for name in (
            b"../a.dll",
            b"C:\\a.dll",
            b"a/b.dll",
            b"\\\\host\\a.dll",
            b"a.dll:stream",
            b".\\a.dll",
            b"a.dll ",
            b"a.dll.",
            b"a%20.dll",
            b"a..dll",
            b"CON.dll",
            b"nul.dll",
            b"COM1.dll",
            b"lpt9.dll",
        ):
            with self.subTest(name=name):
                facts = (p.inspect_pe(fixture((name,))), p.inspect_pe(fixture(marker=1)))
                mapping = p.DependencyMapping(
                    facts[0].sha256, name.decode(), facts[1].sha256, "stage", verified=True
                )
                evidence = self.evidence(
                    facts, names=("root.exe", name.decode()), mappings=(mapping,)
                )
                self.assertIs(p.admit_dependencies(facts, evidence).admitted, False)

    def test_positive_synthetic_stage_and_system_mapping_graph(self):
        p = pe_module()
        for mechanism in ("stage", "system", "api_set", "known_dll"):
            facts = (p.inspect_pe(fixture((b"target.dll",))), p.inspect_pe(fixture(marker=2)))
            mapping = p.DependencyMapping(
                facts[0].sha256, "target.dll", facts[1].sha256, mechanism, verified=True
            )
            role = "stage" if mechanism == "stage" else "system"
            evidence = self.evidence(
                facts, names=("root.exe", "target.dll"), roles=("stage", role), mappings=(mapping,)
            )
            decision = p.admit_dependencies(facts, evidence)
            self.assertIs(decision.admitted, True)
            self.assertEqual(decision.blocker, p.DependencyBlocker.NONE)
            with self.assertRaises(dataclasses.FrozenInstanceError):
                decision.admitted = False
            for altered in (
                dataclasses.replace(mapping, verified=False),
                dataclasses.replace(mapping, importer_sha256="a" * 64),
                dataclasses.replace(mapping, target_sha256="b" * 64),
            ):
                self.assertIs(
                    p.admit_dependencies(
                        facts, dataclasses.replace(evidence, mappings=(altered,))
                    ).admitted,
                    False,
                )

    def test_delay_imports_need_their_own_evidence(self):
        p = pe_module()
        facts = (p.inspect_pe(fixture(delay=(b"delayed.dll",))), p.inspect_pe(fixture(marker=3)))
        evidence = self.evidence(facts, names=("root.exe", "delayed.dll"))
        self.assertIs(p.admit_dependencies(facts, evidence).admitted, False)
        mapping = p.DependencyMapping(
            facts[0].sha256, "DELAYED.DLL", facts[1].sha256, "stage", verified=True
        )
        self.assertIs(
            p.admit_dependencies(
                facts, dataclasses.replace(evidence, mappings=(mapping,))
            ).admitted,
            True,
        )

    def test_aliases_ambiguous_mappings_and_missing_transitive_facts_rejected(self):
        p = pe_module()
        facts = (
            p.inspect_pe(fixture((b"target.dll",))),
            p.inspect_pe(fixture((b"missing.dll",), marker=4)),
        )
        mapping = p.DependencyMapping(
            facts[0].sha256, "target.dll", facts[1].sha256, "stage", verified=True
        )
        evidence = self.evidence(facts, names=("root.exe", "target.dll"), mappings=(mapping,))
        self.assertIs(p.admit_dependencies(facts, evidence).admitted, False)
        leaf = p.inspect_pe(fixture(marker=5))
        facts = (facts[0], leaf)
        mapping = dataclasses.replace(mapping, target_sha256=leaf.sha256)
        evidence = self.evidence(facts, names=("root.exe", "target.dll"), mappings=(mapping,))
        for files in (
            (evidence.files[0], evidence.files[0]),
            (
                evidence.files[0],
                dataclasses.replace(
                    evidence.files[1],
                    bound=dataclasses.replace(
                        evidence.files[1].bound, identity=evidence.files[0].bound.identity
                    ),
                ),
            ),
        ):
            self.assertIs(
                p.admit_dependencies(facts, dataclasses.replace(evidence, files=files)).admitted,
                False,
            )
        self.assertIs(
            p.admit_dependencies(
                facts, dataclasses.replace(evidence, mappings=(mapping, mapping))
            ).admitted,
            False,
        )
        self.assertIs(p.admit_dependencies(facts[:1], evidence).admitted, False)
        wrong_name = dataclasses.replace(evidence.files[1], name="different.dll")
        self.assertIs(
            p.admit_dependencies(
                facts, dataclasses.replace(evidence, files=(evidence.files[0], wrong_name))
            ).admitted,
            False,
        )

    def test_evidence_rejects_mutability_coercion_and_invalid_identity(self):
        p = pe_module()
        facts = (p.inspect_pe(fixture()),)
        evidence = self.evidence(facts)
        for changes in ({"files": list(evidence.files)}, {"mappings": []}, {"windows_build": True}):
            with self.assertRaises((TypeError, ValueError)):
                dataclasses.replace(evidence, **changes)
        for changes in (
            {"reviewed": 1},
            {"role": "guess"},
            {"reviewed_manifest_sha256": []},
            {"bound": dataclasses.replace(evidence.files[0].bound, sha256="bad")},
        ):
            with self.assertRaises((TypeError, ValueError)):
                dataclasses.replace(evidence.files[0], **changes)
        with self.assertRaises((TypeError, ValueError)):
            dataclasses.replace(facts[0], imports=[])
        with self.assertRaises(TypeError):
            p.admit_dependencies(list(facts), evidence)

    def test_source_is_pure_and_has_no_loader_or_process_entry(self):
        pe_module()
        import ast

        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        imports = {
            item.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for item in node.names
        }
        self.assertFalse(imports & {"ctypes", "subprocess", "os", "winreg"})
        self.assertFalse(
            any(
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "main"
                for node in ast.walk(tree)
            )
        )


if __name__ == "__main__":
    unittest.main()
