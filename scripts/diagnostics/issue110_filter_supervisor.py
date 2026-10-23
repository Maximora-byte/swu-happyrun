"""One closed host attempt through a fakeable seam, with no native backend.

Importing this module or invoking its main cannot create a process. Internal
callers must supply an explicit API; neither composition nor observe_once grants
runtime authorization. The entry point stays unconditionally blocked.
The budgets below are monitored deadlines, not OS hard-wall or disk guarantees.
"""

import json
import math
import ntpath
import secrets
from dataclasses import dataclass, replace
from typing import Protocol

from issue110_filter_bundle import EXE_NAME, BundleAPI, BundleError, PinnedBundle, prepare_bundle
from issue110_filter_contract import (
    CAPSULE_LIMIT,
    MODE,
    Blocker,
    CapsuleContext,
    CapsuleError,
    FileIdentity,
    HostObservation,
    HostStage,
    ReviewedBuild,
    parse_capsule,
    parse_request,
    public_projection,
)

HOST_WINDOW = 15.0
CLEANUP_WINDOW = 5.0
STREAM_LIMIT = 64 * 1024
POLL_INTERVAL = 0.05
_INTENT = (
    b'{"schema":"swu.issue110.filter-invocation.v1",'
    b'"reservation_is_authorization":false,"host_invocation_attempted":true}\n'
)


@dataclass(frozen=True)
class InheritedHandle:
    role: str
    access: str
    handle: object


@dataclass(frozen=True)
class TransportHandles:
    request_read: object
    result_write: object
    stdout_write: object
    stderr_write: object
    result_read: object
    stdout_read: object
    stderr_read: object

    @property
    def owned(self):
        return (
            self.request_read,
            self.result_write,
            self.stdout_write,
            self.stderr_write,
            self.result_read,
            self.stdout_read,
            self.stderr_read,
        )

    @property
    def inheritance(self):
        return tuple(
            InheritedHandle(role, access, handle)
            for role, access, handle in (
                ("request", "read", self.request_read),
                ("result", "write", self.result_write),
                ("stdout", "write", self.stdout_write),
                ("stderr", "write", self.stderr_write),
            )
        )


@dataclass(frozen=True)
class CreationResult:
    """A failed/uncertain call may still transfer partial owned handles.

    PID is solely a capsule binding. It is never accepted by a control method.
    A thrown call without an outcome is uncertain, not a confirmed failure.
    """

    succeeded: bool | None
    process: object | None = None
    thread: object | None = None
    child_pid: int | None = None

    def __post_init__(self):
        if self.succeeded is not None and type(self.succeeded) is not bool:
            raise TypeError("invalid creation outcome")
        if self.child_pid is not None and (
            type(self.child_pid) is not int or not 1 <= self.child_pid <= 2**32 - 1
        ):
            raise ValueError("invalid capsule PID binding")


@dataclass(frozen=True)
class ExitState:
    signaled: bool | None
    natural_exit_code: int | None = None

    def __post_init__(self):
        if self.signaled is not None and type(self.signaled) is not bool:
            raise TypeError("invalid signal observation")
        if self.natural_exit_code is not None and (
            self.signaled is not True
            or type(self.natural_exit_code) is not int
            or not 0 <= self.natural_exit_code <= 2**32 - 1
        ):
            raise ValueError("invalid natural exit observation")


class HostAPI(Protocol):
    """Seam only, not a Win32 implementation or an admission allowlist.

    All handles returned here are opaque, newly owned and initially non-inherited
    except the four exact child transport grants. No PID-based control exists.
    None from Job/attribute preparation means unsupported BEFORE CreateProcess,
    with no unreturned resources. No method retries or uses an alternate path.

    JOB_LIST is the official creation-time attribute, never post-create assign.
    HANDLE_LIST is restricted to the four grants, no stdin or other inheritance.
    Handles must enforce request READ-only and result/stdout/stderr WRITE-only;
    the parent readers are separate non-inheritable handles. Exclusive transport
    creates only request/result/stdout/stderr in the reserved private directory,
    writes and flushes request bytes, then closes its temporary writer. It must
    reject existing/uncertain files without adoption, replacement or repair.
    Directory paths resolve ONLY through the bundle backend's retained and
    identity-checked reservation, never an unbound pathname. Absent that binding,
    transport and intent operations must reject, not open a replacement directory.

    Each successful preparation transfers ALL of its resource ownership. On an
    unexpected exception unreturned ownership is unknown, so cleanup cannot be
    asserted complete. Partial CreateProcess outcomes must return every known
    process/thread handle in CreationResult, even when succeeded is False/None.
    """

    def now(self) -> float: ...

    def prepare_job(
        self,
        *,
        name: None,
        kill_on_close: bool,
        active_process_limit: int,
        breakaway: bool,
        inheritable: bool,
        deadline: float,
    ) -> object | None: ...

    def exclusive_transport(
        self, directory: str, request: bytes, *, exclusive: bool, deadline: float
    ) -> TransportHandles: ...

    def prepare_attributes(
        self, job: object, inheritance: tuple[InheritedHandle, ...], *, stdin: None, deadline: float
    ) -> object | None: ...

    def persist_create_intent(
        self, directory: str, record: bytes, *, exclusive: bool, deadline: float
    ) -> bool | None:
        """Exclusive fixed invocation record; True only after a confirmed flush."""
        ...

    def create_suspended(
        self,
        *,
        application_name: str,
        working_directory: str,
        attributes: object,
        inherit_handles: bool,
        suspended: bool,
        stdin: None,
        deadline: float,
    ) -> CreationResult:
        """One absolute lpApplicationName, CREATE_SUSPENDED, extended attributes.

        No shell/search/breakaway/fallback, no target/script/command selection.
        Creation-time compatibility failure is a real call and must be reported.
        """
        ...

    def image_identity(self, process: object, *, deadline: float) -> FileIdentity:
        """Bind actual image/original path to the still-held staged EXE file."""
        ...

    def resume_once(self, thread: object, *, deadline: float) -> bool | None: ...

    def poll_exit(self, process: object, *, deadline: float) -> ExitState:
        """Natural exit only; never called after injecting termination."""
        ...

    def wait(self, process: object, *, deadline: float) -> bool | None: ...

    def read_length(self, handle: object, *, deadline: float) -> int: ...

    def read_result(self, handle: object, *, limit: int, deadline: float) -> bytes: ...

    def terminate_owned(
        self, job: object, process: object | None, *, deadline: float
    ) -> bool | None:
        """Terminate/wait only the owned Job/returned process, sharing C.

        True requires confirmed Job empty/host stopped, not just successful kill
        submission. A forced exit code must never become a natural-exit fact.
        """
        ...

    def drain_pending(self, *, deadline: float) -> bool | None:
        """Drain registered untransferred ownership under C, not unknown outcomes."""
        ...

    def close(self, handle: object, *, deadline: float) -> bool | None: ...


class _Stop(Exception):
    def __init__(self, blocker):
        self.blocker = blocker


def _time(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("invalid monotonic deadline")
    return value


def _request(bundle, nonce):
    # Serialization only: validation and binding types remain the Task 1 contract.
    files = {
        role: {
            "volume_serial": bound.identity.volume_serial,
            "file_id_hex": bound.identity.file_id.hex(),
            "sha256": bound.sha256,
        }
        for role, (_, bound) in zip(("exe", "dbgeng", "dbghelp"), bundle.stage_files, strict=True)
    }
    data = json.dumps(
        {
            "schema": "swu.issue110.filter-request.v1",
            "mode": MODE,
            "nonce": nonce,
            "manifest_sha256": bundle.manifest_sha256,
            "files": files,
        },
        separators=(",", ":"),
    ).encode("ascii")
    parse_request(data)
    return data


class _Supervisor:
    def __init__(self, bundle, deadline, api):
        self.bundle, self.deadline, self.api = bundle, deadline, api
        self.observation = HostObservation(
            overall_deadline=deadline, signature_cleanup=bundle.signature_cleanup
        )
        self.handles = []
        self.job = self.process = None
        self.unknown_resources = False

    def update(self, **facts):
        self.observation = replace(self.observation, **facts)

    def now(self):
        return _time(self.api.now())

    def checkpoint(self, deadline):
        if self.now() >= deadline:
            raise _Stop(Blocker.DEADLINE)

    def own(self, handle):
        self.adopt((handle,))
        return handle

    def acquire(self, operation, *args, **kwargs):
        # Exception type does not prove that a resource-producing call was atomic.
        # Mark before dispatch to the outer fixed-blocker/primary-error handling.
        try:
            return operation(*args, **kwargs)
        except BaseException:
            self.unknown_resources = True
            raise

    def adopt(self, handles):
        invalid = False
        # Even a malformed collection may contain later, genuinely owned handles.
        # Retain all distinct valid resources before stopping, never double-close.
        for handle in handles:
            if handle is None or type(handle) is bool or handle == 0 or handle in self.handles:
                invalid = True
            else:
                self.handles.append(handle)
        if invalid:
            self.unknown_resources = True
            raise _Stop(Blocker.IO_FAILURE)

    def full_window(self):
        now = self.now()
        if self.deadline - now < HOST_WINDOW:
            raise _Stop(Blocker.DEADLINE)
        return now

    def sample_exit(self, deadline):
        result = self.api.poll_exit(self.process, deadline=deadline)
        if type(result) is not ExitState:
            raise _Stop(Blocker.IO_FAILURE)
        self.update(
            child_exit_before_cleanup=result.signaled, natural_exit_code=result.natural_exit_code
        )
        return result.signaled

    def lengths(self, transport, deadline, *, expected_result_size=None):
        result_size = None
        for handle, limit in (
            (transport.result_read, CAPSULE_LIMIT),
            (transport.stdout_read, STREAM_LIMIT),
            (transport.stderr_read, STREAM_LIMIT),
        ):
            size = self.api.read_length(handle, deadline=deadline)
            result_changed = (
                handle is transport.result_read
                and expected_result_size is not None
                and size != expected_result_size
            )
            if result_changed:
                # A rejected final result cannot leave proof from its old prefix.
                # Do this before either result or independent stream limit stops.
                self.update(child_result_valid=False, receipt=None)
                self.update(observed_at=self.now())
            if type(size) is not int or size < 0:
                raise _Stop(Blocker.IO_FAILURE)
            if size > limit:
                raise _Stop(Blocker.OUTPUT_LIMIT)
            if result_changed:
                raise _Stop(Blocker.CAPSULE_INVALID)
            if handle is transport.result_read:
                result_size = size
        return result_size

    def run(self):
        self.update(stage=HostStage.BUNDLE, blocker=Blocker.NONE)
        if self.deadline != self.bundle.deadline:
            raise _Stop(Blocker.BUNDLE_REJECTED)
        self.bundle.revalidate()
        self.checkpoint(self.deadline)
        self.full_window()
        self.update(stage=HostStage.PREFLIGHT)
        job = self.acquire(
            self.api.prepare_job,
            name=None,
            kill_on_close=True,
            active_process_limit=1,
            breakaway=False,
            inheritable=False,
            deadline=self.deadline,
        )
        if job is None:
            raise _Stop(Blocker.UNSUPPORTED)
        self.job = self.own(job)
        self.checkpoint(self.deadline)
        nonce = secrets.token_hex(16)
        directory = ntpath.dirname(self.bundle.stage_path)
        transport = self.acquire(
            self.api.exclusive_transport,
            directory,
            _request(self.bundle, nonce),
            exclusive=True,
            deadline=self.deadline,
        )
        if type(transport) is not TransportHandles:
            self.unknown_resources = True
            raise _Stop(Blocker.IO_FAILURE)
        self.adopt(transport.owned)
        self.checkpoint(self.deadline)
        attributes = self.acquire(
            self.api.prepare_attributes,
            self.job,
            transport.inheritance,
            stdin=None,
            deadline=self.deadline,
        )
        if attributes is None:
            raise _Stop(Blocker.UNSUPPORTED)
        self.own(attributes)
        self.bundle.revalidate()
        # Admit and start H from one sample; a second read could hide a shortage.
        host_start = self.full_window()
        host_deadline = min(self.deadline, host_start + HOST_WINDOW)
        self.update(host_deadline=host_deadline, stage=HostStage.CREATE)
        if (
            self.acquire(
                self.api.persist_create_intent,
                directory,
                _INTENT,
                exclusive=True,
                deadline=host_deadline,
            )
            is not True
        ):
            self.unknown_resources = True
            raise _Stop(Blocker.IO_FAILURE)
        self.update(create_intent=True)
        self.checkpoint(host_deadline)
        creation = self.acquire(
            self.api.create_suspended,
            application_name=ntpath.join(self.bundle.stage_path, EXE_NAME),
            working_directory=self.bundle.stage_path,
            attributes=attributes,
            inherit_handles=True,
            suspended=True,
            stdin=None,
            deadline=host_deadline,
        )
        if type(creation) is not CreationResult:
            self.unknown_resources = True
            raise _Stop(Blocker.CREATE_UNCERTAIN)
        self.adopt(
            tuple(handle for handle in (creation.process, creation.thread) if handle is not None)
        )
        self.process = creation.process
        self.update(create_succeeded=creation.succeeded)
        if creation.succeeded is not True:
            raise _Stop(
                Blocker.CREATE_FAILED if creation.succeeded is False else Blocker.CREATE_UNCERTAIN
            )
        if self.process is None or creation.thread is None:
            self.unknown_resources = True
        if self.process is None or creation.thread is None or creation.child_pid is None:
            self.update(create_succeeded=None)
            raise _Stop(Blocker.CREATE_UNCERTAIN)
        self.checkpoint(host_deadline)
        self.update(stage=HostStage.IMAGE)
        image = self.api.image_identity(self.process, deadline=host_deadline)
        if type(image) is not FileIdentity or image != self.bundle.stage_files[0][1].identity:
            raise _Stop(Blocker.IMAGE_MISMATCH)
        self.checkpoint(host_deadline)
        self.update(stage=HostStage.RESUME, resume_intent=True)
        resumed = self.api.resume_once(creation.thread, deadline=host_deadline)
        if resumed is not None and type(resumed) is not bool:
            raise _Stop(Blocker.RESUME_UNCERTAIN)
        self.update(resume_succeeded=resumed)
        if resumed is not True:
            raise _Stop(Blocker.RESUME_FAILED if resumed is False else Blocker.RESUME_UNCERTAIN)
        self.update(stage=HostStage.OBSERVE)
        while True:
            self.checkpoint(host_deadline)
            signaled = self.sample_exit(host_deadline)
            result_size = self.lengths(transport, host_deadline)
            if signaled is True:
                break
            if signaled is None:
                raise _Stop(Blocker.IO_FAILURE)
            self.checkpoint(host_deadline)
            waited = self.api.wait(
                self.process, deadline=min(host_deadline, self.now() + POLL_INTERVAL)
            )
            if waited is True:
                # Retain a completed signal/capsule that arrives exactly at H;
                # final projection rejects it, but does not erase observed facts.
                if self.sample_exit(host_deadline) is not True:
                    raise _Stop(Blocker.IO_FAILURE)
                result_size = self.lengths(transport, host_deadline)
                break
            if waited is not False:
                raise _Stop(Blocker.IO_FAILURE)
        self.update(stage=HostStage.CAPSULE)
        data = self.api.read_result(
            transport.result_read, limit=CAPSULE_LIMIT, deadline=host_deadline
        )
        if type(data) is not bytes or len(data) != result_size:
            self.update(child_result_valid=False, observed_at=self.now())
            raise _Stop(Blocker.CAPSULE_INVALID)
        try:
            receipt = parse_capsule(data, CapsuleContext(nonce, creation.child_pid))
        except (CapsuleError, TypeError):
            self.update(child_result_valid=False, observed_at=self.now())
            raise _Stop(Blocker.CAPSULE_INVALID) from None
        self.update(child_result_valid=True, receipt=receipt, observed_at=self.now())
        self.lengths(transport, host_deadline, expected_result_size=len(data))
        self.update(observed_at=self.now())
        if self.observation.natural_exit_code != 0:
            raise _Stop(Blocker.CHILD_FAILED)
        if not receipt.observations_complete:
            raise _Stop(Blocker.CHILD_INCOMPLETE)
        self.update(observation_complete=True)

    def cleanup(self):
        """One C, bound before any cleanup; no retry and no naturalization of kill."""
        failure = None
        complete = not self.unknown_resources

        def failed(error):
            nonlocal failure, complete
            complete = False
            if failure is None or (
                isinstance(failure, Exception) and not isinstance(error, Exception)
            ):
                failure = error

        try:
            cleanup_deadline = self.now() + CLEANUP_WINDOW
            self.bundle.begin_cleanup(cleanup_deadline)
        except BaseException as error:
            failed(error)
            self.update(host_owned_cleanup=None)
            return failure
        if self.process is not None and self.observation.child_exit_before_cleanup is not True:
            try:
                if self.now() < cleanup_deadline:
                    self.sample_exit(cleanup_deadline)
                else:
                    complete = False
            except BaseException as error:
                failed(error)
        if self.job is not None:
            try:
                if (
                    self.now() >= cleanup_deadline
                    or self.api.terminate_owned(self.job, self.process, deadline=cleanup_deadline)
                    is not True
                ):
                    complete = False
            except BaseException as error:
                failed(error)
        try:
            if self.api.drain_pending(deadline=cleanup_deadline) is not True:
                complete = False
        except BaseException as error:
            failed(error)
        for handle in reversed(self.handles):
            try:
                if (
                    self.now() >= cleanup_deadline
                    or self.api.close(handle, deadline=cleanup_deadline) is not True
                ):
                    complete = False
            except BaseException as error:
                failed(error)
        try:
            self.bundle.close(cleanup_deadline=cleanup_deadline)
            if self.bundle.cleanup is not True or self.now() >= cleanup_deadline:
                complete = False
        except BaseException as error:
            failed(error)
        self.update(host_owned_cleanup=True if complete else None)
        return failure


def observe_once(bundle: PinnedBundle, deadline: float, api: HostAPI) -> HostObservation:
    """Consume one bundle and supervise at most one create and one resume.

    Expected negative outcomes return fixed facts; unexpected errors/cancellation
    preserve the exact primary instance, with private host_observation attached
    where possible. Close errors cannot replace that primary. No native API is
    implemented or selected here. The caller must separately hold runtime grant.
    """
    if type(bundle) is not PinnedBundle:
        raise TypeError("expected pinned bundle owner")
    deadline = _time(deadline)
    if bundle.closed:
        return HostObservation(
            stage=HostStage.BUNDLE,
            blocker=Blocker.BUNDLE_REJECTED,
            overall_deadline=deadline,
            projected_at=_time(api.now()),
            signature_cleanup=bundle.signature_cleanup,
        )
    state = _Supervisor(bundle, deadline, api)
    primary = None
    try:
        state.run()
    except _Stop as error:
        state.update(blocker=error.blocker)
    except BundleError as error:
        state.update(blocker=error.blocker)
    except BaseException as error:
        primary = error
        state.unknown_resources = True
        state.update(
            blocker=Blocker.CANCELLED if not isinstance(error, Exception) else Blocker.IO_FAILURE
        )
    cleanup_error = state.cleanup()
    if cleanup_error is not None and primary is None and not isinstance(cleanup_error, Exception):
        primary = cleanup_error
        state.update(blocker=Blocker.CANCELLED)
    elif (
        state.observation.host_owned_cleanup is not True
        and state.observation.blocker is Blocker.NONE
    ):
        state.update(blocker=Blocker.CLEANUP_UNKNOWN)
    try:
        state.update(projected_at=state.now())
    except BaseException as error:
        primary = primary or error
        state.update(observation_complete=False, blocker=Blocker.IO_FAILURE)
    public = public_projection(state.observation)
    state.update(
        observation_complete=public["observation_complete"], blocker=Blocker(public["blocker"])
    )
    if state.observation.observation_complete:
        state.update(stage=HostStage.COMPLETE)
    if primary is not None:
        try:
            primary.host_observation = state.observation
        except Exception:
            pass
        raise primary
    return state.observation


class ClosedPipelineAPI(BundleAPI, Protocol):
    """One shared monotonic clock and one resource-owning bundle backend.

    host_api is a side-effect-free constructor bound to this SAME retained bundle
    backend. It must not acquire resources or start work before returning. The
    concrete Windows implementation has no admitted build; no default is selected.
    This seam is not a runtime grant, manifest, or callable native capability.
    """

    def host_api(self, bundle: PinnedBundle) -> HostAPI: ...


def run_closed_pipeline(
    reviewed_build: ReviewedBuild, private_root: str, api: ClosedPipelineAPI
) -> HostObservation:
    """Internal-only composition: one D, reservation, V6 phase and host attempt.

    Not reached by either main. Expected rejection returns fixed observations;
    cancellation/unexpected errors keep their primary instance and private facts.
    prepare_bundle owns its failures and observe_once consumes a successful bundle.
    No outer context manager is used to allocate or restart a second cleanup C.
    """
    deadline = _time(api.now()) + 300.0
    bundle = None
    try:
        bundle = prepare_bundle(reviewed_build, private_root, deadline, api)
        host = api.host_api(bundle)
    except BaseException as primary:
        # A constructor failure has no host resources by the seam contract, but
        # the already-transferred bundle must still close once under one C.
        if bundle is not None:
            try:
                bundle.close(cleanup_deadline=_time(api.now()) + CLEANUP_WINDOW)
            except BaseException:
                pass  # Cleanup must not replace the exact primary instance.
        cleanup = bundle.cleanup if bundle is not None else getattr(primary, "bundle_cleanup", None)
        signature = (
            bundle.signature_cleanup
            if bundle is not None
            else getattr(primary, "signature_cleanup", None)
        )
        blocker = (
            primary.blocker
            if isinstance(primary, BundleError)
            else Blocker.CANCELLED
            if not isinstance(primary, Exception)
            else Blocker.IO_FAILURE
        )
        observation = HostObservation(
            stage=HostStage.BUNDLE,
            blocker=blocker if type(blocker) is Blocker else Blocker.IO_FAILURE,
            host_owned_cleanup=cleanup if type(cleanup) is bool else None,
            signature_cleanup=signature if type(signature) is bool else None,
            overall_deadline=deadline,
        )
        try:
            observation = replace(observation, projected_at=_time(api.now()))
            public = public_projection(observation)
            observation = replace(observation, blocker=Blocker(public["blocker"]))
        except BaseException:
            pass
        if isinstance(primary, BundleError):
            return observation
        try:
            primary.host_observation = observation
        except Exception:
            pass
        raise
    return observe_once(bundle, deadline, host)


def main() -> int:
    """No flags, environment or backend can enable this entry point."""
    print(json.dumps(public_projection(HostObservation()), separators=(",", ":")))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
