"""Bounded static PE metadata and separately supplied dependency review evidence.

No file, registry, process, or loader API is called here. An admitted synthetic
review is not a build approval, runtime authorization, or dynamic-DLL sandbox.
The caller must obtain current, independent evidence while holding its file pins.
PE layout: https://learn.microsoft.com/en-us/windows/win32/debug/pe-format
"""

import hashlib
import re
import struct
from dataclasses import dataclass, field
from enum import StrEnum

from issue110_filter_contract import BoundFile, FileIdentity

PE_LIMIT = 64 * 1024 * 1024
_SECTION_LIMIT = 96
_IMPORT_LIMIT = 512
_THUNK_LIMIT = 4096
_RESOURCE_LIMIT = 4096
_MANIFEST_LIMIT = 32
_FILE_LIMIT = 64
_MAPPING_LIMIT = 4096
_REDIRECTION = ("adjacent_manifest", "dot_local", "activation_context")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_BASENAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*\.(?:dll|exe)\Z", re.ASCII | re.I)


class PeErrorCode(StrEnum):
    MALFORMED = "malformed"
    BOUNDS = "bounds"
    OVERLAP = "overlap"
    LIMIT = "limit"
    UNSUPPORTED = "unsupported"


class PeError(ValueError):
    """Fixed diagnostics only; never echo private input or struct exceptions."""

    def __init__(self, code: PeErrorCode):
        self.code = code
        super().__init__(code.value)


def _fail(code=PeErrorCode.MALFORMED):
    raise PeError(code)


def _digest(value):
    if type(value) is not str or not _DIGEST.fullmatch(value):
        raise ValueError("invalid SHA256 evidence")


def _boolean(value, *, nullable=False):
    if not (nullable and value is None) and type(value) is not bool:
        raise TypeError("evidence booleans must not be coerced")


def _tuple(value, item_type, limit):
    if type(value) is not tuple or len(value) > limit:
        raise TypeError("evidence must be a bounded immutable tuple")
    if any(type(item) is not item_type for item in value):
        raise TypeError("invalid evidence component")


def _names(value):
    _tuple(value, str, _IMPORT_LIMIT)
    for name in value:
        if not 1 <= len(name) <= 255 or any(not 0x20 <= ord(c) <= 0x7E for c in name):
            raise ValueError("invalid import-name metadata")


def _digests(value):
    _tuple(value, str, _MANIFEST_LIMIT)
    for digest in value:
        _digest(digest)


@dataclass(frozen=True)
class PeFacts:
    sha256: str
    x64: bool
    imports: tuple[str, ...] = field(repr=False)
    delay_imports: tuple[str, ...] = field(repr=False)
    resource_present: bool
    manifest_sha256: tuple[str, ...] = ()
    # Bytes alone never establish these three external facts.
    redirection_requirements: tuple[str, ...] = _REDIRECTION

    def __post_init__(self):
        _digest(self.sha256)
        _boolean(self.x64)
        _boolean(self.resource_present)
        _names(self.imports)
        _names(self.delay_imports)
        _digests(self.manifest_sha256)
        if (
            type(self.redirection_requirements) is not tuple
            or self.redirection_requirements != _REDIRECTION
            or (self.manifest_sha256 and not self.resource_present)
        ):
            raise ValueError("invalid resource/redirection metadata")


@dataclass(frozen=True)
class ReviewedPeFile:
    """External review assertion, not authority created by inspect_pe.

    Adjacent manifests and .local must be confirmed absent for this closed slice.
    Embedded manifests require exact digest review plus independently established
    activation-context behavior; this parser never interprets XML as proof.
    """

    name: str = field(repr=False)
    bound: BoundFile = field(repr=False)
    role: str = "stage"
    reviewed: bool = False
    adjacent_manifest_absent: bool | None = None
    dot_local_absent: bool | None = None
    activation_context_verified: bool | None = None
    reviewed_manifest_sha256: tuple[str, ...] = ()

    def __post_init__(self):
        _names((self.name,))
        if type(self.bound) is not BoundFile or type(self.bound.identity) is not FileIdentity:
            raise TypeError("review requires shared exact BoundFile identity")
        _digest(self.bound.sha256)
        if type(self.role) is not str or self.role not in {"stage", "system"}:
            raise ValueError("invalid reviewed file role")
        _boolean(self.reviewed)
        for value in (
            self.adjacent_manifest_absent,
            self.dot_local_absent,
            self.activation_context_verified,
        ):
            _boolean(value, nullable=True)
        _digests(self.reviewed_manifest_sha256)


@dataclass(frozen=True)
class DependencyMapping:
    """One reviewed resolution in one exact importing image's context."""

    importer_sha256: str
    name: str = field(repr=False)
    target_sha256: str
    mechanism: str
    verified: bool = False

    def __post_init__(self):
        _digest(self.importer_sha256)
        _digest(self.target_sha256)
        _names((self.name,))
        if type(self.mechanism) is not str or self.mechanism not in {
            "stage",
            "system",
            "api_set",
            "known_dll",
        }:
            raise ValueError("invalid resolution mechanism")
        _boolean(self.verified)


@dataclass(frozen=True)
class DependencyEvidence:
    files: tuple[ReviewedPeFile, ...] = ()
    mappings: tuple[DependencyMapping, ...] = ()
    # Caller-supplied current Windows observation/review binding, never inferred.
    windows_build: str | None = field(default=None, repr=False)

    def __post_init__(self):
        _tuple(self.files, ReviewedPeFile, _FILE_LIMIT)
        _tuple(self.mappings, DependencyMapping, _MAPPING_LIMIT)
        if self.windows_build is not None and (
            type(self.windows_build) is not str or not 1 <= len(self.windows_build) <= 256
        ):
            raise ValueError("invalid platform observation evidence")


class DependencyBlocker(StrEnum):
    NONE = "none"
    EVIDENCE_UNKNOWN = "evidence_unknown"
    FILE_UNKNOWN = "file_unknown"
    IDENTITY_ALIAS = "identity_alias"
    ARCHITECTURE = "architecture"
    PATH_NAME = "path_name"
    REDIRECTION_UNKNOWN = "redirection_unknown"
    MAPPING_UNKNOWN = "mapping_unknown"
    MAPPING_AMBIGUOUS = "mapping_ambiguous"
    GRAPH_INCOMPLETE = "graph_incomplete"


@dataclass(frozen=True)
class DependencyDecision:
    admitted: bool
    blocker: DependencyBlocker

    def __post_init__(self):
        _boolean(self.admitted)
        if type(self.blocker) is not DependencyBlocker or self.admitted != (
            self.blocker is DependencyBlocker.NONE
        ):
            raise ValueError("inconsistent dependency decision")


class _Reader:
    def __init__(self, data):
        self.data = data
        self.sections = []
        self.regions = []
        self.thunks = 0

    def bounds(self, offset, size):
        if offset < 0 or size < 0 or offset > len(self.data) - size:
            _fail(PeErrorCode.BOUNDS)

    def unpack(self, fmt, offset):
        self.bounds(offset, struct.calcsize(fmt))
        return struct.unpack_from(fmt, self.data, offset)

    def claim(self, offset, size, kind, regions=None, *, shared=False):
        self.bounds(offset, size)
        ranges = self.regions if regions is None else regions
        for start, end, previous in ranges:
            if offset < end and start < offset + size:
                # Only explicitly shared literal bytes/container reservations may alias.
                if shared and (offset, offset + size, kind) == (start, end, previous):
                    return
                _fail(PeErrorCode.OVERLAP)
        ranges.append((offset, offset + size, kind))

    def mapped(self, address, size):
        if address <= 0 or size <= 0 or address > 2**32 - size:
            _fail(PeErrorCode.BOUNDS)
        matches = [
            (raw + address - base)
            for base, span, raw, length in self.sections
            if base <= address and address + size <= base + span and address + size <= base + length
        ]
        if len(matches) != 1:
            _fail(PeErrorCode.BOUNDS)
        offset = matches[0]
        self.bounds(offset, size)
        return offset

    def string(self, address, limit, kind, skip=0):
        offset = self.mapped(address, skip + 1)
        # No scan may leave the containing raw-backed RVA span.
        available = next(
            length - (address - base)
            for base, _, _, length in self.sections
            if base <= address < base + length
        )
        end = self.data.find(b"\0", offset + skip, offset + min(available, skip + limit + 1))
        if end < 0 or end == offset + skip:
            _fail()
        value = self.data[offset + skip : end]
        if any(not 0x20 <= byte <= 0x7E for byte in value):
            _fail()
        self.claim(offset, end + 1 - offset, kind, shared=True)
        return value.decode("ascii")

    def lookup(self, address):
        for count in range(_THUNK_LIMIT + 1):
            offset = self.mapped(address + count * 8, 8)
            (value,) = self.unpack("<Q", offset)
            if not value:
                self.claim(self.mapped(address, (count + 1) * 8), (count + 1) * 8, "lookup")
                return count
            self.thunks += 1
            if self.thunks > _THUNK_LIMIT:
                _fail(PeErrorCode.LIMIT)
            if value & (1 << 63):
                if value & ~((1 << 63) | 0xFFFF):
                    _fail()
            elif value > 0xFFFFFFFF:
                _fail(PeErrorCode.UNSUPPORTED)
            else:
                self.string(value, 4096, "symbol", skip=2)
        _fail(PeErrorCode.LIMIT)

    def imports(self, address, size, delay=False):
        if not address and not size:
            return ()
        width = 32 if delay else 20
        if not address or not size or size % width:
            _fail()
        if size > (_IMPORT_LIMIT + 1) * width:
            _fail(PeErrorCode.LIMIT)
        start = self.mapped(address, size)
        self.claim(start, size, "delay_descriptors" if delay else "import_descriptors", shared=True)
        result = []
        for relative in range(0, size, width):
            values = self.unpack("<8I" if delay else "<5I", start + relative)
            if not any(values):
                if any(self.data[start + relative + width : start + size]):
                    _fail()
                return tuple(result)
            if len(result) >= _IMPORT_LIMIT:
                _fail(PeErrorCode.LIMIT)
            if delay:
                flags, name, handle, iat, lookup, bound, unload, _ = values
                if flags != 1:
                    _fail(PeErrorCode.UNSUPPORTED)
                self.claim(self.mapped(handle, 8), 8, "delay_handle")
            else:
                lookup, _, _, name, iat = values
                lookup = lookup or iat
                bound = unload = 0
            result.append(self.string(name, 255, "dll_name"))
            count = self.lookup(lookup)
            length = (count + 1) * 8
            iat_offset = self.mapped(iat, length)
            # A single descriptor may represent lookup/IAT with the exact same
            # table (including normal OFT fallback). It still contributes its DLL
            # edge; distinct tables/descriptors and partial overlap cannot share.
            # This metadata normalization is not proof Windows will load the PE.
            if iat != lookup:
                self.claim(iat_offset, length, "iat")
            entries = self.unpack("<" + "Q" * (count + 1), iat_offset)
            if entries[-1] or any(not value for value in entries[:-1]):
                _fail()
            for optional in (bound, unload):
                if optional:
                    self.claim(self.mapped(optional, length), length, "delay_aux")
        _fail()

    def resources(self, address, size):
        if not address and not size:
            return ()
        if not address or size < 16:
            _fail()
        start = self.mapped(address, size)
        self.claim(start, size, "resource_container", shared=True)
        regions, visited, manifests = [], set(), []
        budget = 0

        def relative(offset, length):
            if offset < 0 or length <= 0 or offset > size - length:
                _fail(PeErrorCode.BOUNDS)
            return start + offset

        def walk(offset, depth, resource_type=None):
            nonlocal budget
            if offset in visited or depth > 2:
                _fail()
            visited.add(offset)
            table = relative(offset, 16)
            _, _, _, _, named, numbered = self.unpack("<IIHHHH", table)
            count = named + numbered
            budget += count + 1
            if budget > _RESOURCE_LIMIT:
                _fail(PeErrorCode.LIMIT)
            relative(offset, 16 + count * 8)
            self.claim(table, 16 + count * 8, "resource_table", regions)
            identifiers = set()
            for index in range(count):
                identifier, target = self.unpack("<II", table + 16 + index * 8)
                if bool(identifier & 0x80000000) != (index < named):
                    _fail()
                if identifier & 0x80000000:
                    name_offset = identifier & 0x7FFFFFFF
                    name = relative(name_offset, 2)
                    (length,) = self.unpack("<H", name)
                    if not length or length > 255:
                        _fail(PeErrorCode.LIMIT)
                    relative(name_offset, 2 + length * 2)
                    self.claim(name, 2 + length * 2, "resource_name", regions, shared=True)
                    try:
                        key = self.data[name + 2 : name + 2 + length * 2].decode("utf-16le")
                    except UnicodeError:
                        _fail()
                else:
                    if identifier > 0xFFFF:
                        _fail()
                    key = identifier
                if key in identifiers:
                    _fail()
                identifiers.add(key)
                kind = key if depth == 0 else resource_type
                if target & 0x80000000:
                    if depth == 2:
                        _fail()
                    walk(target & 0x7FFFFFFF, depth + 1, kind)
                else:
                    if depth != 2:
                        _fail(PeErrorCode.UNSUPPORTED)
                    entry = relative(target, 16)
                    self.claim(entry, 16, "resource_entry", regions)
                    payload_rva, length, _, reserved = self.unpack("<IIII", entry)
                    if reserved or not length:
                        _fail()
                    payload = self.mapped(payload_rva, length)
                    relative(payload - start, length)
                    self.claim(payload, length, "resource_payload", regions)
                    if kind == 24:
                        if len(manifests) >= _MANIFEST_LIMIT:
                            _fail(PeErrorCode.LIMIT)
                        payload_bytes = self.data[payload : payload + length]
                        manifests.append(hashlib.sha256(payload_bytes).hexdigest())

        walk(0, 0)
        return tuple(manifests)


def inspect_pe(data: bytes) -> PeFacts:
    """Inspect raw-backed x64 PE32+ import/resource metadata, or reject.

    Conservative unsupported/ambiguous layouts are errors, not missing imports.
    No claim covers runtime LoadLibrary calls, SxS resolution, or transient DLLs.
    """
    if type(data) is not bytes:
        raise TypeError("PE input must be bytes")
    if len(data) > PE_LIMIT:
        _fail(PeErrorCode.LIMIT)
    reader = _Reader(data)
    reader.bounds(0, 64)
    if data[:2] != b"MZ":
        _fail()
    (pe,) = reader.unpack("<I", 0x3C)
    if pe < 64:
        _fail()
    reader.bounds(pe, 24)
    if data[pe : pe + 4] != b"PE\0\0":
        _fail()
    machine, count, _, _, _, optional_size, _ = reader.unpack("<HHIIIHH", pe + 4)
    if machine != 0x8664:
        _fail(PeErrorCode.UNSUPPORTED)
    if not 1 <= count <= _SECTION_LIMIT:
        _fail(PeErrorCode.LIMIT)
    optional = pe + 24
    reader.bounds(optional, optional_size)
    (magic,) = reader.unpack("<H", optional)
    if magic != 0x20B or optional_size < 112:
        _fail(PeErrorCode.UNSUPPORTED)
    (directories,) = reader.unpack("<I", optional + 108)
    if directories > 16 or optional_size < 112 + directories * 8:
        _fail(PeErrorCode.LIMIT)
    image_size, headers_size = reader.unpack("<II", optional + 56)
    sections = optional + optional_size
    reader.bounds(sections, count * 40)
    if headers_size < sections + count * 40 or headers_size > len(data):
        _fail(PeErrorCode.BOUNDS)
    raw_regions, virtual_regions = [], []
    for index in range(count):
        _, virtual_size, base, raw_size, raw, _, _, _, _, _ = reader.unpack(
            "<8sIIIIIIHHI", sections + index * 40
        )
        span = max(virtual_size, raw_size)
        if not span or base < headers_size or base > 2**32 - span or base + span > image_size:
            _fail(PeErrorCode.BOUNDS)
        for previous, end in virtual_regions:
            if base < end and previous < base + span:
                _fail(PeErrorCode.OVERLAP)
        virtual_regions.append((base, base + span))
        if raw_size:
            if raw < headers_size:
                _fail(PeErrorCode.OVERLAP)
            reader.bounds(raw, raw_size)
            for previous, end in raw_regions:
                if raw < end and previous < raw + raw_size:
                    _fail(PeErrorCode.OVERLAP)
            raw_regions.append((raw, raw + raw_size))
        reader.sections.append((base, span, raw, raw_size))

    def directory(index):
        return reader.unpack("<II", optional + 112 + index * 8) if index < directories else (0, 0)

    # Preclaim all three containers so parsing order cannot hide overlap.
    for index, kind in (
        (1, "import_descriptors"),
        (13, "delay_descriptors"),
        (2, "resource_container"),
    ):
        address, size = directory(index)
        if address or size:
            reader.claim(reader.mapped(address, size), size, kind)
    imports = reader.imports(*directory(1))
    delay = reader.imports(*directory(13), delay=True)
    resources = directory(2)
    manifests = reader.resources(*resources)
    return PeFacts(
        hashlib.sha256(data).hexdigest(), True, imports, delay, bool(resources[0]), manifests
    )


def _basename(name):
    stem = name.split(".", 1)[0].upper()
    reserved = {"CON", "PRN", "AUX", "NUL"}
    reserved.update(f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10))
    return (
        len(name) <= 255
        and ".." not in name
        and stem not in reserved
        and _BASENAME.fullmatch(name) is not None
    )


def admit_dependencies(
    facts: tuple[PeFacts, ...],
    evidence: DependencyEvidence,
) -> DependencyDecision:
    """Require exact reviewed files and all edges, never a basename allowlist.

    All target images, including reviewed system images, must have their own
    facts/evidence in this closed graph. Mapping and redirection assertions are
    supplied by the independent reviewer, not manufactured by this pure module.
    They do not authorize execution or make dynamic imports a complete sandbox.
    """
    _tuple(facts, PeFacts, _FILE_LIMIT)
    if type(evidence) is not DependencyEvidence:
        raise TypeError("invalid dependency evidence")

    def blocked(reason):
        return DependencyDecision(False, reason)

    if not facts or not evidence.files or not evidence.windows_build:
        return blocked(DependencyBlocker.EVIDENCE_UNKNOWN)
    images = {item.sha256: item for item in facts}
    files = {item.bound.sha256: item for item in evidence.files}
    if len(images) != len(facts) or len(files) != len(evidence.files):
        return blocked(DependencyBlocker.IDENTITY_ALIAS)
    if images.keys() != files.keys():
        return blocked(DependencyBlocker.FILE_UNKNOWN)
    identities, names = set(), set()
    for digest, image in images.items():
        file = files[digest]
        if not image.x64:
            return blocked(DependencyBlocker.ARCHITECTURE)
        if not file.reviewed:
            return blocked(DependencyBlocker.FILE_UNKNOWN)
        if not _basename(file.name) or any(
            not _basename(name) or not name.lower().endswith(".dll")
            for name in image.imports + image.delay_imports
        ):
            return blocked(DependencyBlocker.PATH_NAME)
        if file.bound.identity in identities or file.name.lower() in names:
            return blocked(DependencyBlocker.IDENTITY_ALIAS)
        identities.add(file.bound.identity)
        names.add(file.name.lower())
        if (
            file.adjacent_manifest_absent is not True
            or file.dot_local_absent is not True
            or file.activation_context_verified is not True
            or file.reviewed_manifest_sha256 != image.manifest_sha256
        ):
            return blocked(DependencyBlocker.REDIRECTION_UNKNOWN)
    mappings = {}
    for mapping in evidence.mappings:
        key = (mapping.importer_sha256, mapping.name.lower())
        if key in mappings:
            return blocked(DependencyBlocker.MAPPING_AMBIGUOUS)
        mappings[key] = mapping
    needed = {
        (image.sha256, name.lower())
        for image in facts
        for name in image.imports + image.delay_imports
    }
    if mappings.keys() != needed:
        return blocked(DependencyBlocker.MAPPING_UNKNOWN)
    for (_, name), mapping in mappings.items():
        target = files.get(mapping.target_sha256)
        if not mapping.verified:
            return blocked(DependencyBlocker.MAPPING_UNKNOWN)
        if target is None:
            return blocked(DependencyBlocker.GRAPH_INCOMPLETE)
        expected_role = "stage" if mapping.mechanism == "stage" else "system"
        if target.role != expected_role or (
            mapping.mechanism != "api_set" and target.name.lower() != name
        ):
            return blocked(DependencyBlocker.MAPPING_UNKNOWN)
    return DependencyDecision(True, DependencyBlocker.NONE)
