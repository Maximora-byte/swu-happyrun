"""One-shot private bundle orchestration, with no native backend or entry point.

There is deliberately no approved build manifest here. The abstract backend must
independently bind a ReviewedBuild to an exact reviewed manifest and executable;
synthetic seam tests are not production identity admission or runtime authority.
V6 verifies installed sources once, NOT stage. Stage trust is the same-byte copy
binding to those retained source pins. No process/loader methods exist here.

Pins deny WRITE/DELETE sharing. Directory checks still trust the current user,
administrators and current Windows; this is not a dynamic-DLL execution sandbox.
File and close budgets are monitored, not synchronous-call hard wall guarantees.
No deletion, root provisioning, ACL repair, installation or retry is performed.
"""

import math
import ntpath
from dataclasses import dataclass
from typing import Protocol

from issue110_debugger_config import VERSION
from issue110_debugger_config_local import DEBUGGER_HASHES
from issue110_filter_contract import Blocker, BoundFile, FileIdentity, ReviewedBuild
from issue110_filter_pe import (
    PE_LIMIT,
    DependencyEvidence,
    ReviewedPeFile,
    admit_dependencies,
    inspect_pe,
)
from issue110_local_acl import FILTER_PROBE_CHILD, components

EXE_NAME = "issue110_filter_command_probe.exe"
_STAGE_NAMES = (("exe", EXE_NAME), ("dbgeng", "dbgeng.dll"), ("dbghelp", "dbghelp.dll"))
_TOKEN = object()
_ATTEMPT = (
    b'{"schema":"swu.issue110.filter-attempt.v1",'
    b'"reservation_is_authorization":false,"host_invocation_attempted":false}\n'
)


class BundleError(ValueError):
    """Fixed private error with independently retained cleanup facts."""

    def __init__(self, blocker: Blocker):
        self.blocker = blocker
        self.bundle_cleanup = None
        self.signature_cleanup = None
        super().__init__(blocker.value)


@dataclass(frozen=True)
class SignatureVerification:
    verified: bool
    cleanup: bool | None = None

    def __post_init__(self):
        if type(self.verified) is not bool or (
            self.cleanup is not None and type(self.cleanup) is not bool
        ):
            raise TypeError("invalid signature facts")


class BundleAPI(Protocol):
    """Seam only. No implementation, manifest allowlist, or process creation.

    Directory validation must perform the existing strict ACL helper role checks,
    NTFS/persistent ACL and drive mapping checks at the volume root, no reparse,
    and original-path/held-identity binding. `stage` uses the private child ACL.
    Every open returns a non-inheritable owned handle, or raises. Creation is
    exclusive relative to the held parent; an uncertain result must not retry.

    Source roles resolve ONLY the reviewed EXE and fixed installed x64 Kits three
    files. No PATH search, alternate versions, installation or stage V6 is allowed.
    `read_pin` is bounded on the SAME handle. `revalidate_pin` rechecks original
    path/identity, same-handle SHA256 and full file version; it never reopens an
    unbound replacement. All file pins allow READ sharing only, never WRITE/DELETE.
    `copy_exclusive` copies from the held source, flushes and verifies the completed
    write, closes its writer, then returns a retained read-only non-inherited pin.
    Any uncertainty raises; the adapter owns handles not yet returned to us.
    """

    def now(self) -> float: ...

    def reviewed_build_version(self, build: ReviewedBuild) -> str | None:
        """Full EXE version only after independent exact manifest approval; else None."""
        ...

    def open_directory(self, path: str, *, role: str) -> object: ...

    def validate_directory(self, handle: object, *, path: str, role: str) -> FileIdentity: ...

    def reserve_child(self, root: object, name: str, *, exclusive: bool) -> object | None: ...

    def create_stage(self, child: object, *, exclusive: bool) -> object | None: ...

    def write_exclusive(
        self,
        child: object,
        name: str,
        data: bytes,
        *,
        exclusive: bool,
    ) -> object: ...

    def flush(self, handle: object) -> bool: ...

    def pin_source(
        self, role: str, build: ReviewedBuild, *, share_mode: int, inheritable: bool
    ) -> object: ...

    def pin_identity(self, handle: object) -> FileIdentity: ...

    def read_pin(self, handle: object, *, limit: int) -> bytes: ...

    def revalidate_pin(self, handle: object) -> tuple[BoundFile, str]: ...

    def verify_installed_v6(
        self,
        pins: tuple[object, ...],
        *,
        deadline: float,
    ) -> SignatureVerification:
        """ONE installed cdb/dbgeng/dbghelp V6 call, sharing absolute deadline S.

        Pins stay open throughout. Use current fixed V6 signatures/identity logic,
        and preserve its separate cleanup uncertainty even when it raises.
        Never start cdb.exe or claim the original verifier inspected stage.
        """
        ...

    def dependency_evidence(self, build: ReviewedBuild) -> DependencyEvidence: ...

    def pin_dependency(
        self, reviewed: ReviewedPeFile, *, share_mode: int, inheritable: bool
    ) -> object:
        """Resolve only independently reviewed exact Windows system evidence."""
        ...

    def copy_exclusive(
        self,
        source: object,
        stage: object,
        name: str,
        *,
        exclusive: bool,
        share_mode: int,
        inheritable: bool,
    ) -> object: ...

    def drain_pending(self, *, deadline: float) -> bool | None:
        """Close registered, untransferred resources once under the same C.

        True covers only registered ownership, never an uncertain API outcome.
        """
        ...

    def close(self, handle: object, *, deadline: float) -> bool:
        """True only for a confirmed close. All calls share the same cleanup C."""
        ...


def _time(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise BundleError(Blocker.DEADLINE)
    return value


def _bound(value):
    if (
        type(value) is not BoundFile
        or type(value.identity) is not FileIdentity
        or type(value.sha256) is not str
        or len(value.sha256) != 64
        or any(char not in "0123456789abcdef" for char in value.sha256)
    ):
        raise BundleError(Blocker.BUNDLE_REJECTED)
    return value


class PinnedBundle:
    """Factory-only resource owner, not user authorization or a native capability.

    Immutable stage bindings can feed the shared ProbeRequest. Revalidate while
    still owning the pins; keep this context open through host cleanup. Closing is
    one-shot, never retries failed closes and never removes the reservation.
    Python object privacy is not an in-process security boundary.
    """

    __slots__ = (
        "_api",
        "_deadline",
        "_stage_path",
        "_manifest",
        "_handles",
        "_directories",
        "_pins",
        "_stage_files",
        "_signature_cleanup",
        "_closed",
        "_cleanup",
        "_cleanup_deadline",
    )

    def __init__(self, token, api, deadline, stage_path, manifest):
        if token is not _TOKEN:
            raise TypeError("use prepare_bundle")
        self._api, self._deadline = api, deadline
        self._stage_path, self._manifest = stage_path, manifest
        self._handles, self._directories, self._pins = [], [], []
        self._stage_files = ()
        self._signature_cleanup = self._cleanup = self._cleanup_deadline = None
        self._closed = False

    @property
    def stage_path(self):
        return self._stage_path

    @property
    def stage_files(self):
        return self._stage_files

    @property
    def manifest_sha256(self):
        return self._manifest

    @property
    def deadline(self):
        return self._deadline

    @property
    def signature_cleanup(self):
        return self._signature_cleanup

    @property
    def closed(self):
        return self._closed

    @property
    def cleanup(self):
        return self._cleanup

    def _checkpoint(self):
        if self._cleanup_deadline is not None:
            raise BundleError(Blocker.CLEANUP_UNKNOWN)
        if self._closed or _time(self._api.now()) >= self._deadline:
            raise BundleError(Blocker.DEADLINE if not self._closed else Blocker.BUNDLE_REJECTED)

    def _own(self, handle):
        if handle is None or type(handle) is bool or handle == 0:
            raise BundleError(Blocker.RESERVATION_UNCERTAIN)
        if handle in self._handles:
            raise BundleError(Blocker.BUNDLE_REJECTED)
        self._handles.append(handle)
        return handle

    def _directory(self, handle, path, role):
        value = self._api.validate_directory(handle, path=path, role=role)
        if type(value) is not FileIdentity or value in self._identities():
            raise BundleError(Blocker.BUNDLE_REJECTED)
        self._directories.append((handle, path, role, value))
        self._checkpoint()

    def _identities(self):
        return {entry[3] for entry in self._directories} | {
            entry[1].identity for entry in self._pins
        }

    def _snapshot(self, handle, expected_hash=None, expected_version=None):
        first = self._api.pin_identity(handle)
        data = self._api.read_pin(handle, limit=PE_LIMIT)
        facts = inspect_pe(data)
        binding, version = self._api.revalidate_pin(handle)
        _bound(binding)
        if (
            type(first) is not FileIdentity
            or binding.identity != first
            or binding.identity in self._identities()
            or binding.sha256 != facts.sha256
            or (expected_hash is not None and binding.sha256 != expected_hash)
            or type(version) is not str
            or not 1 <= len(version) <= 256
            or (expected_version is not None and version != expected_version)
        ):
            raise BundleError(Blocker.BUNDLE_REJECTED)
        self._pins.append((handle, binding, version))
        self._checkpoint()
        return binding, facts

    def revalidate(self):
        self._checkpoint()
        for handle, path, role, expected in self._directories:
            if self._api.validate_directory(handle, path=path, role=role) != expected:
                raise BundleError(Blocker.BUNDLE_REJECTED)
            self._checkpoint()
        for handle, expected, version in self._pins:
            if self._api.revalidate_pin(handle) != (expected, version):
                raise BundleError(Blocker.BUNDLE_REJECTED)
            self._checkpoint()

    def _close(self):
        if self._closed:
            return None
        self._closed = True  # Failure/uncertainty must never permit another attempt.
        failure = None
        try:
            if self._cleanup_deadline is None:
                self._cleanup_deadline = _time(self._api.now()) + 5.0
            complete = True
            try:
                if self._api.drain_pending(deadline=self._cleanup_deadline) is not True:
                    complete = False
            except BaseException as error:
                complete, failure = False, error
            for handle in reversed(self._handles):
                try:
                    if _time(self._api.now()) >= self._cleanup_deadline:
                        complete = False
                        continue
                    if self._api.close(handle, deadline=self._cleanup_deadline) is not True:
                        complete = False
                except BaseException as error:
                    complete = False
                    # Keep the first cancellation even after an ordinary close error.
                    # Callers with an existing body primary still ignore this result.
                    if failure is None or (
                        isinstance(failure, Exception) and not isinstance(error, Exception)
                    ):
                        failure = error
            if complete and _time(self._api.now()) < self._cleanup_deadline:
                self._cleanup = True
        except BaseException as error:
            failure = failure or error
        return failure

    def _attach_facts(self, primary):
        # Cleanup is secondary even if an unusual exception forbids extra fields.
        try:
            primary.bundle_cleanup = self._cleanup
            if not hasattr(primary, "signature_cleanup") or primary.signature_cleanup is None:
                primary.signature_cleanup = self._signature_cleanup
        except Exception:
            pass

    def begin_cleanup(self, deadline: float):
        """Bind the host's single C before any cleanup; cannot restart work/C.

        A supervisor must call this when its cleanup starts so context exit later
        shares the SAME budget, rather than allocating another five seconds.
        Expired C is retained: it does not authorize late close attempts.
        """
        deadline = _time(deadline)
        if (
            self._closed
            or deadline > _time(self._api.now()) + 5.0
            or (self._cleanup_deadline is not None and self._cleanup_deadline != deadline)
        ):
            raise BundleError(Blocker.CLEANUP_UNKNOWN)
        self._cleanup_deadline = deadline

    def close(self, *, cleanup_deadline: float | None = None):
        if self._closed:
            return
        if cleanup_deadline is not None:
            self.begin_cleanup(cleanup_deadline)
        failure = self._close()
        if failure is not None and not isinstance(failure, Exception):
            self._attach_facts(failure)
            raise failure
        if self._cleanup is not True:
            error = BundleError(Blocker.CLEANUP_UNKNOWN)
            self._attach_facts(error)
            raise error

    def __enter__(self):
        self._checkpoint()
        return self

    def __exit__(self, kind, error, traceback):
        if kind is None:
            self.close()
        else:
            self._close()
            self._attach_facts(error)
        return False


def _dependencies(owner, reviewed_build, source):
    api = owner._api
    evidence = api.dependency_evidence(reviewed_build)
    if type(evidence) is not DependencyEvidence:
        raise BundleError(Blocker.DEPENDENCIES_UNKNOWN)
    expected = {bound.sha256: (name, bound) for name, (_, bound, _) in source.items()}
    if len(expected) != 3:
        raise BundleError(Blocker.DEPENDENCIES_UNKNOWN)
    facts = {bound.sha256: fact for _, bound, fact in source.values()}
    seen = set()
    for reviewed in evidence.files:
        digest = reviewed.bound.sha256
        if digest in expected:
            name, bound = expected[digest]
            if reviewed.name != name or reviewed.bound != bound or reviewed.role != "stage":
                raise BundleError(Blocker.DEPENDENCIES_UNKNOWN)
            seen.add(digest)
        else:
            if reviewed.role != "system" or not reviewed.reviewed:
                raise BundleError(Blocker.DEPENDENCIES_UNKNOWN)
            owner._checkpoint()
            handle = owner._own(api.pin_dependency(reviewed, share_mode=1, inheritable=False))
            bound, fact = owner._snapshot(handle, expected_hash=digest)
            if bound != reviewed.bound:
                raise BundleError(Blocker.DEPENDENCIES_UNKNOWN)
            facts[digest] = fact
    if seen != expected.keys() or not admit_dependencies(tuple(facts.values()), evidence).admitted:
        raise BundleError(Blocker.DEPENDENCIES_UNKNOWN)


def prepare_bundle(
    reviewed_build: ReviewedBuild, private_root: str, deadline: float, api: BundleAPI
) -> PinnedBundle:
    """Prepare one fixed, held, exclusive bundle or raise without retry/deletion.

    Caller supplies the already-started shared D (at most 300 seconds remaining).
    Only this factory constructs owners. No manifest is accepted from shape alone.
    """
    now, deadline = _time(api.now()), _time(deadline)
    if not now < deadline <= now + 300.0:
        raise BundleError(Blocker.DEADLINE)
    if (
        type(reviewed_build) is not ReviewedBuild
        or not reviewed_build.manifest_sha256
        or not reviewed_build.exe_sha256
        or not reviewed_build.source_sha256
        or not reviewed_build.header_sha256
        or reviewed_build.machine != "x64"
        or not reviewed_build.toolchain
        or reviewed_build.protocol_version != 1
    ):
        raise BundleError(Blocker.BUILD_UNKNOWN)
    exe_version = api.reviewed_build_version(reviewed_build)
    if type(exe_version) is not str or not 1 <= len(exe_version) <= 256:
        raise BundleError(Blocker.BUILD_UNKNOWN)
    paths = components(private_root, mode="prepared_top_level")
    child_path = ntpath.join(private_root, FILTER_PROBE_CHILD)
    owner = PinnedBundle(
        _TOKEN, api, deadline, ntpath.join(child_path, "stage"), reviewed_build.manifest_sha256
    )
    try:
        for path, role in zip(paths, ("volume_root", "prepared_private_root"), strict=True):
            owner._checkpoint()
            handle = owner._own(api.open_directory(path, role=role))
            owner._directory(handle, path, role)
        owner._checkpoint()
        child = owner._own(api.reserve_child(handle, FILTER_PROBE_CHILD, exclusive=True))
        owner._directory(child, child_path, "filter_probe")
        owner.revalidate()
        attempt = owner._own(api.write_exclusive(child, "attempt.json", _ATTEMPT, exclusive=True))
        if api.flush(attempt) is not True:
            raise BundleError(Blocker.IO_FAILURE)
        owner._checkpoint()
        stage = owner._own(api.create_stage(child, exclusive=True))
        owner._directory(stage, owner.stage_path, "stage")
        pins, all_source = {}, {}
        for role in ("exe", "cdb", "dbgeng", "dbghelp"):
            owner._checkpoint()
            handle = owner._own(
                api.pin_source(role, reviewed_build, share_mode=1, inheritable=False)
            )
            name = EXE_NAME if role == "exe" else role + (".exe" if role == "cdb" else ".dll")
            expected_hash = reviewed_build.exe_sha256 if role == "exe" else DEBUGGER_HASHES[name]
            bound, fact = owner._snapshot(
                handle, expected_hash, exe_version if role == "exe" else VERSION
            )
            pins[role] = handle
            all_source[name] = (handle, bound, fact)
        owner.revalidate()
        signature_deadline = min(deadline, _time(api.now()) + 30.0)
        owner._checkpoint()
        if _time(api.now()) >= signature_deadline:
            raise BundleError(Blocker.DEADLINE)
        verification = api.verify_installed_v6(
            tuple(pins[role] for role in ("cdb", "dbgeng", "dbghelp")), deadline=signature_deadline
        )
        if type(verification) is not SignatureVerification:
            raise BundleError(Blocker.SIGNATURE_REJECTED)
        owner._signature_cleanup = verification.cleanup
        if not verification.verified or verification.cleanup is False:
            raise BundleError(Blocker.SIGNATURE_REJECTED)
        if _time(api.now()) >= signature_deadline:
            raise BundleError(Blocker.DEADLINE)
        owner.revalidate()  # A changed signed source cannot reach the copy seam.
        source = {name: all_source[name] for _, name in _STAGE_NAMES}
        _dependencies(owner, reviewed_build, source)
        bindings = []
        for role, name in _STAGE_NAMES:
            owner.revalidate()
            handle = owner._own(
                api.copy_exclusive(
                    pins[role], stage, name, exclusive=True, share_mode=1, inheritable=False
                )
            )
            source_handle, source_bound, _ = source[name]
            source_version = next(
                version for pin, _, version in owner._pins if pin == source_handle
            )
            bound, _ = owner._snapshot(handle, source_bound.sha256, source_version)
            bindings.append((name, bound))
        owner._stage_files = tuple(bindings)
        owner.revalidate()
        return owner
    except BaseException as primary:
        owner._close()
        owner._attach_facts(primary)
        raise
