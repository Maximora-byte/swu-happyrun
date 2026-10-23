"""Private, bounded filter-probe protocol and conservative public projection.

No native calls, file access, admission of a build, or runnable entry point. A
ReviewedBuild is evidence to check against a separately reviewed manifest, never
authority to execute. All bytes, identities and errors remain private.
"""

import json
import math
import re
from dataclasses import dataclass, field
from enum import StrEnum

CAPSULE_LIMIT = 262144
REQUEST_LIMIT = 16384
GETTER_LIMIT = 4096
SX_LIMIT = 65536
PATH_LIMIT = 8192
MAGIC = b"SWU110FP1\n"
FOOTER = b"\nSWU110END\n"
SCHEMA = "swu.issue110.filter-capsule.v1"
MODE = "fixed_no_target"
COMPARISONS = frozenset(("not_observed", "equal", "different"))
STAGES = frozenset(
    (
        "not_started",
        "target_before_enumeration",
        "enumerate_filters",
        "target_after_enumeration",
        "register_command",
        "register_flush",
        "target_after_registration",
        "getter_a",
        "target_after_getter_a",
        "display_pre_flush",
        "display_sx",
        "display_post_flush",
        "target_after_display",
        "getter_b",
        "target_after_getter_b",
        "close",
        "observations_complete",
        "validate_request",
        "verify_stage",
        "initialize_search",
        "inspect_modules",
        "load_engine",
        "validate_modules",
        "create_engine",
    )
)
ISSUES = frozenset(
    (
        "none",
        "call_not_s_ok",
        "call_not_observed",
        "callback_violation",
        "target_not_absent",
        "filter_count_invalid",
        "filter_index_invalid",
        "filter_indices_duplicate",
        "av_missing",
        "av_duplicate",
        "getter_length_invalid",
        "getter_terminator_missing",
        "getter_embedded_nul",
        "getter_non_ascii",
        "getter_changed",
        "output_incomplete",
        "output_ambiguous",
        "output_overflow",
        "output_non_ascii",
        "cleanup_incomplete",
        "adapter_exception",
        "invalid_request",
        "loader_blocked",
        "engine_creation_failed",
    )
)
# Independent byte constant, used only to check the child's comparison claim.
EXPECTED_COMMAND = b"$$>a<C:\\SWU_ISSUE110_SYNTHETIC\\terminal.cdb\0"
_HEX = re.compile(r"[0-9a-f]*\Z", re.ASCII)


class CapsuleErrorCode(StrEnum):
    TOO_LARGE = "too_large"
    FRAMING = "framing"
    JSON = "json"
    FIELDS = "fields"
    VALUE = "value"
    CONTEXT = "context"
    INCONSISTENT = "inconsistent"


class CapsuleError(ValueError):
    """Fixed error only. Never include private input or parser exception text."""

    def __init__(self, code: CapsuleErrorCode):
        self.code = code
        super().__init__(code.value)


def _fail(code=CapsuleErrorCode.VALUE):
    raise CapsuleError(code)


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        _fail()
    return value


def _boolean(value):
    if type(value) is not bool:
        _fail()
    return value


def _choice(value, choices):
    if type(value) is not str or value not in choices:
        _fail()
    return value


def _hex(value, limit, *, exact=None):
    if (
        type(value) is not str
        or len(value) % 2
        or len(value) > limit * 2
        or not _HEX.fullmatch(value)
        or (exact is not None and len(value) != exact * 2)
    ):
        _fail()
    return bytes.fromhex(value)


def _fields(value, expected):
    if type(value) is not dict or value.keys() != set(expected.split()):
        _fail(CapsuleErrorCode.FIELDS)
    return value


def _nullable_integer(value, low, high):
    return None if value is None else _integer(value, low, high)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail(CapsuleErrorCode.FIELDS)
        result[key] = value
    return result


def _load_json(data, limit):
    if type(data) is not bytes:
        raise TypeError("protocol input must be bytes")
    if len(data) > limit:
        _fail(CapsuleErrorCode.TOO_LARGE)
    try:
        return json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_constant=lambda _: _fail(CapsuleErrorCode.JSON),
        )
    except (UnicodeError, ValueError, RecursionError) as error:
        if isinstance(error, CapsuleError):
            raise
        raise CapsuleError(CapsuleErrorCode.JSON) from None


@dataclass(frozen=True)
class FileIdentity:
    volume_serial: int
    file_id: bytes = field(repr=False)

    def __post_init__(self):
        _integer(self.volume_serial, 0, 2**64 - 1)
        if type(self.file_id) is not bytes or len(self.file_id) != 16:
            raise ValueError("file identity must contain 16 bytes")


@dataclass(frozen=True)
class ReviewedBuild:
    """Unknown defaults; no digest or manifest is implicitly approved here."""

    manifest_sha256: str | None = None
    exe_sha256: str | None = None
    source_sha256: tuple[tuple[str, str], ...] = ()
    machine: str | None = None
    toolchain: str | None = None
    header_sha256: tuple[tuple[str, str], ...] = ()
    protocol_version: int | None = None

    def __post_init__(self):
        for digest in (self.manifest_sha256, self.exe_sha256):
            if digest is not None:
                _hex(digest, 32, exact=32)
        for evidence in (self.source_sha256, self.header_sha256):
            if type(evidence) is not tuple:
                raise TypeError("evidence must be immutable")
            names = set()
            for entry in evidence:
                if type(entry) is not tuple or len(entry) != 2:
                    raise ValueError("invalid evidence entry")
                name, digest = entry
                if type(name) is not str or not name or len(name) > 256 or name in names:
                    raise ValueError("invalid evidence name")
                names.add(name)
                _hex(digest, 32, exact=32)
        if self.machine is not None:
            _choice(self.machine, {"x64"})
        if self.toolchain is not None and (
            type(self.toolchain) is not str or not 1 <= len(self.toolchain) <= 256
        ):
            raise ValueError("invalid toolchain evidence")
        if self.protocol_version is not None:
            _integer(self.protocol_version, 1, 1)


@dataclass(frozen=True)
class CapsuleContext:
    nonce: str = field(repr=False)
    child_pid: int = field(repr=False)

    def __post_init__(self):
        _hex(self.nonce, 16, exact=16)
        _integer(self.child_pid, 1, 2**32 - 1)


@dataclass(frozen=True)
class BoundFile:
    identity: FileIdentity
    sha256: str


@dataclass(frozen=True)
class ProbeRequest:
    nonce: str = field(repr=False)
    manifest_sha256: str
    exe: BoundFile
    dbgeng: BoundFile
    dbghelp: BoundFile


def parse_request(data: bytes) -> ProbeRequest:
    """Only fixed file roles and identity bindings, never paths or commands."""
    doc = _fields(_load_json(data, REQUEST_LIMIT), "schema mode nonce manifest_sha256 files")
    _choice(doc["schema"], {"swu.issue110.filter-request.v1"})
    _choice(doc["mode"], {MODE})
    _hex(doc["nonce"], 16, exact=16)
    _hex(doc["manifest_sha256"], 32, exact=32)
    files = _fields(doc["files"], "exe dbgeng dbghelp")
    bound = []
    for name in ("exe", "dbgeng", "dbghelp"):
        item = _fields(files[name], "volume_serial file_id_hex sha256")
        identity = FileIdentity(
            _integer(item["volume_serial"], 0, 2**64 - 1), _hex(item["file_id_hex"], 16, exact=16)
        )
        _hex(item["sha256"], 32, exact=32)
        bound.append(BoundFile(identity, item["sha256"]))
    return ProbeRequest(doc["nonce"], doc["manifest_sha256"], *bound)


@dataclass(frozen=True)
class GetterReceipt:
    valid: bool
    hresult: int | None = field(repr=False)
    reported_length: int | None
    data: bytes = field(repr=False)


@dataclass(frozen=True)
class SxReceipt:
    data: bytes = field(repr=False)
    overflow: bool
    association: str


@dataclass(frozen=True)
class HResultObservation:
    stage: str
    hresult: int = field(repr=False)


@dataclass(frozen=True)
class ReleaseReceipt:
    all_owned_release_calls_issued: bool
    engine_disposal_confirmed: bool
    detach_hresult: int | None = field(repr=False)
    control_release_return: int | None = field(repr=False)
    client_release_return: int | None = field(repr=False)
    callback_release_return: int | None = field(repr=False)
    wrong_thread: bool
    callback_violation: bool


@dataclass(frozen=True)
class ChildReceipt:
    nonce: str = field(repr=False)
    child_pid: int = field(repr=False)
    stage: str
    issue: str
    engine_creation_attempted: bool
    observations_complete: bool
    getter_a: GetterReceipt = field(repr=False)
    getter_b: GetterReceipt = field(repr=False)
    sx: SxReceipt = field(repr=False)
    a_expected: str
    b_expected: str
    ab_stability: str
    hresult_trace: tuple[HResultObservation, ...] = field(repr=False)
    module_paths_utf16le: tuple[bytes, ...] = field(repr=False)
    release: ReleaseReceipt = field(repr=False)


def _getter(doc):
    _fields(doc, "valid hresult reported_length bytes_hex")
    valid = _boolean(doc["valid"])
    hr = _nullable_integer(doc["hresult"], -(2**31), 2**31 - 1)
    length = _nullable_integer(doc["reported_length"], 0, 2**32 - 1)
    data = _hex(doc["bytes_hex"], GETTER_LIMIT)
    if valid:
        if (
            hr != 0
            or length != len(data)
            or not data
            or data[-1] != 0
            or any(byte < 0x20 or byte > 0x7E for byte in data[:-1])
        ):
            _fail(CapsuleErrorCode.INCONSISTENT)
    elif data:
        _fail(CapsuleErrorCode.INCONSISTENT)
    return GetterReceipt(valid, hr, length, data)


def _comparison(getter):
    if not getter.valid:
        return "not_observed"
    return "equal" if getter.data == EXPECTED_COMMAND else "different"


def parse_capsule(data: bytes, context: CapsuleContext) -> ChildReceipt:
    """Structure/binding validation only, not process-exit or deadline evidence."""
    if type(data) is not bytes or type(context) is not CapsuleContext:
        raise TypeError("invalid capsule input type")
    if len(data) > CAPSULE_LIMIT:
        _fail(CapsuleErrorCode.TOO_LARGE)
    if (
        len(data) < 30
        or not data.startswith(MAGIC)
        or data[18:19] != b"\n"
        or not data.endswith(FOOTER)
        or not re.fullmatch(b"[0-9a-f]{8}", data[10:18])
    ):
        _fail(CapsuleErrorCode.FRAMING)
    length = int(data[10:18], 16)
    if len(data) != length + 30:
        _fail(CapsuleErrorCode.FRAMING)
    doc = _fields(
        _load_json(data[19 : 19 + length], CAPSULE_LIMIT),
        "schema mode nonce child_pid stage issue engine_creation_attempted "
        "observations_complete getter_a getter_b sx a_expected b_expected ab_stability "
        "hresult_trace module_paths_utf16le_hex release",
    )
    _choice(doc["schema"], {SCHEMA})
    _choice(doc["mode"], {MODE})
    _hex(doc["nonce"], 16, exact=16)
    _integer(doc["child_pid"], 1, 2**32 - 1)
    if doc["nonce"] != context.nonce or doc["child_pid"] != context.child_pid:
        _fail(CapsuleErrorCode.CONTEXT)
    stage = _choice(doc["stage"], STAGES)
    issue = _choice(doc["issue"], ISSUES)
    engine = _boolean(doc["engine_creation_attempted"])
    complete = _boolean(doc["observations_complete"])
    a, b = _getter(doc["getter_a"]), _getter(doc["getter_b"])
    sx = _fields(doc["sx"], "bytes_hex overflow association")
    output = SxReceipt(
        _hex(sx["bytes_hex"], SX_LIMIT),
        _boolean(sx["overflow"]),
        _choice(sx["association"], {"not_observed", "associated", "ambiguous"}),
    )
    comparisons = tuple(
        _choice(doc[key], COMPARISONS) for key in ("a_expected", "b_expected", "ab_stability")
    )
    stability = "not_observed"
    if a.valid and b.valid:
        stability = "equal" if a.data == b.data else "different"
    if comparisons != (_comparison(a), _comparison(b), stability):
        _fail(CapsuleErrorCode.INCONSISTENT)
    trace = doc["hresult_trace"]
    if type(trace) is not list or len(trace) > 32:
        _fail()
    calls = []
    for call in trace:
        _fields(call, "stage hresult")
        calls.append(
            HResultObservation(
                _choice(call["stage"], STAGES), _integer(call["hresult"], -(2**31), 2**31 - 1)
            )
        )
    paths = doc["module_paths_utf16le_hex"]
    if type(paths) is not list or len(paths) > 16:
        _fail()
    raw_paths = tuple(_hex(path, PATH_LIMIT) for path in paths)
    if any(len(path) % 2 for path in raw_paths):
        _fail()
    release = _fields(
        doc["release"],
        "all_owned_release_calls_issued engine_disposal_confirmed "
        "detach_hresult control_release_return client_release_return "
        "callback_release_return wrong_thread callback_violation",
    )
    cleanup = ReleaseReceipt(
        _boolean(release["all_owned_release_calls_issued"]),
        _boolean(release["engine_disposal_confirmed"]),
        _nullable_integer(release["detach_hresult"], -(2**31), 2**31 - 1),
        *(
            _nullable_integer(release[name], 0, 2**32 - 1)
            for name in (
                "control_release_return",
                "client_release_return",
                "callback_release_return",
            )
        ),
        _boolean(release["wrong_thread"]),
        _boolean(release["callback_violation"]),
    )
    # A Release return is not evidence of global engine disposal.
    if cleanup.engine_disposal_confirmed:
        _fail(CapsuleErrorCode.INCONSISTENT)
    if complete and (
        not engine
        or stage != "observations_complete"
        or issue != "none"
        or not a.valid
        or not b.valid
        or stability != "equal"
        or not output.data
        or output.overflow
        or output.association != "associated"
        or any(byte not in (9, 10, 13) and not 0x20 <= byte <= 0x7E for byte in output.data)
        or cleanup.detach_hresult != 0
        or not cleanup.all_owned_release_calls_issued
        or cleanup.wrong_thread
        or cleanup.callback_violation
    ):
        _fail(CapsuleErrorCode.INCONSISTENT)
    return ChildReceipt(
        doc["nonce"],
        doc["child_pid"],
        stage,
        issue,
        engine,
        complete,
        a,
        b,
        output,
        *comparisons,
        tuple(calls),
        raw_paths,
        cleanup,
    )


class HostStage(StrEnum):
    NOT_STARTED = "not_started"
    BUILD = "build"
    BUNDLE = "bundle"
    SIGNATURE = "signature"
    PREFLIGHT = "preflight"
    CREATE = "create"
    IMAGE = "image"
    RESUME = "resume"
    OBSERVE = "observe"
    CAPSULE = "capsule"
    CLEANUP = "cleanup"
    COMPLETE = "complete"


class Blocker(StrEnum):
    NONE = "none"
    NOT_STARTED = "not_started"
    BUILD_UNKNOWN = "build_unknown"
    BUNDLE_REJECTED = "bundle_rejected"
    SIGNATURE_REJECTED = "signature_rejected"
    DEPENDENCIES_UNKNOWN = "dependencies_unknown"
    RESERVATION_UNCERTAIN = "reservation_uncertain"
    UNSUPPORTED = "unsupported"
    CREATE_FAILED = "create_failed"
    CREATE_UNCERTAIN = "create_uncertain"
    IMAGE_MISMATCH = "image_mismatch"
    RESUME_FAILED = "resume_failed"
    RESUME_UNCERTAIN = "resume_uncertain"
    DEADLINE = "deadline"
    OUTPUT_LIMIT = "output_limit"
    CAPSULE_INVALID = "capsule_invalid"
    CHILD_FAILED = "child_failed"
    CHILD_INCOMPLETE = "child_incomplete"
    CLEANUP_UNKNOWN = "cleanup_unknown"
    CANCELLED = "cancelled"
    IO_FAILURE = "io_failure"


def _deadline_rejected(observed, deadline):
    return None if observed is None or deadline is None else observed >= deadline


@dataclass(frozen=True)
class HostObservation:
    stage: HostStage = HostStage.NOT_STARTED
    blocker: Blocker = Blocker.NOT_STARTED
    create_intent: bool = False
    create_succeeded: bool | None = None
    resume_intent: bool = False
    resume_succeeded: bool | None = None
    child_exit_before_cleanup: bool | None = None
    natural_exit_code: int | None = field(default=None, repr=False)
    child_result_valid: bool | None = None
    receipt: ChildReceipt | None = field(default=None, repr=False)
    host_owned_cleanup: bool | None = None
    signature_cleanup: bool | None = None
    observation_complete: bool = False
    observed_at: float | None = None
    host_deadline: float | None = None
    projected_at: float | None = None
    overall_deadline: float | None = None
    private_error: str | None = field(default=None, repr=False)

    def __post_init__(self):
        if type(self.stage) is not HostStage or type(self.blocker) is not Blocker:
            raise TypeError("host labels must be fixed enums")
        for value in (self.create_intent, self.resume_intent, self.observation_complete):
            _boolean(value)
        for value in (
            self.create_succeeded,
            self.resume_succeeded,
            self.child_exit_before_cleanup,
            self.child_result_valid,
            self.host_owned_cleanup,
            self.signature_cleanup,
        ):
            if value is not None:
                _boolean(value)
        _nullable_integer(self.natural_exit_code, 0, 2**32 - 1)
        times = (self.observed_at, self.host_deadline, self.projected_at, self.overall_deadline)
        for value in times:
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
                raise ValueError("deadline observations must be finite")
        if self.receipt is not None and type(self.receipt) is not ChildReceipt:
            raise TypeError("invalid receipt type")
        if self.resume_succeeded is not None and not self.resume_intent:
            raise ValueError("resume result without intent")
        if self.create_succeeded is not None and not self.create_intent:
            raise ValueError("create result without intent")
        if self.resume_intent and self.create_succeeded is not True:
            raise ValueError("resume requires confirmed create")

    @property
    def host_execution_attempted(self) -> bool | None:
        return self.resume_succeeded if self.resume_intent else False

    @property
    def engine_creation_attempted(self) -> bool | None:
        if self.host_execution_attempted is False:
            return False
        if (
            self.host_execution_attempted is True
            and self.child_result_valid is True
            and self.receipt is not None
        ):
            value = self.receipt.engine_creation_attempted
            return value if type(value) is bool else None
        return None

    @property
    def host_deadline_rejected(self) -> bool | None:
        return _deadline_rejected(self.observed_at, self.host_deadline)

    @property
    def overall_deadline_rejected(self) -> bool | None:
        return _deadline_rejected(self.projected_at, self.overall_deadline)


def public_projection(observation: HostObservation) -> dict:
    """Construct a fresh fixed allowlist. Never forward child/exception dictionaries."""
    if type(observation) is not HostObservation:
        raise TypeError("invalid host observation")
    receipt = observation.receipt if observation.child_result_valid is True else None
    complete = (
        observation.observation_complete
        and observation.host_execution_attempted is True
        and observation.child_exit_before_cleanup is True
        and observation.natural_exit_code == 0
        and receipt is not None
        and receipt.observations_complete is True
        and observation.engine_creation_attempted is True
        and observation.host_deadline_rejected is False
        and observation.overall_deadline_rejected is False
    )
    expired = (
        observation.host_deadline_rejected is True or observation.overall_deadline_rejected is True
    )
    blocker = Blocker.DEADLINE if expired else observation.blocker
    public = {
        "schema": "swu.issue110.filter-summary.v1",
        "mode": MODE,
        "status": "observed" if complete else "blocked",
        "stage": observation.stage.value,
        "blocker": blocker.value,
        "host_execution_attempted": observation.host_execution_attempted,
        "engine_creation_attempted": observation.engine_creation_attempted,
        "child_result_valid": observation.child_result_valid,
        "child_exit_before_cleanup": observation.child_exit_before_cleanup,
        "host_owned_cleanup": observation.host_owned_cleanup,
        "signature_cleanup": observation.signature_cleanup,
        "observation_complete": bool(complete),
        "passed": False,
        "execution_ready": False,
        "display_comparison": "format_unknown",
        "disk_hard_cap": False,
    }
    for name in ("a_expected", "b_expected", "ab_stability"):
        value = getattr(receipt, name) if receipt is not None else None
        public[name] = value if type(value) is str and value in COMPARISONS else "not_observed"
    return public
