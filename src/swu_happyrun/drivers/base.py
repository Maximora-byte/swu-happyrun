"""Device interface; the agent owns durable intent, lease and fence enforcement."""

from collections.abc import Callable
from typing import Protocol, runtime_checkable

from swu_happyrun.core.models import DeviceCapability, JobSpec, JobView, VerificationResult


class DriverError(ValueError):
    def __init__(self, reason_code: str):
        self.reason_code = reason_code
        super().__init__(reason_code)


@runtime_checkable
class DeviceDriver(Protocol):
    def bind_session(self, view: JobView) -> None:
        """Bind immutable job/session context; recovery must retain its session.

        Binding is not evidence of an app record: real adapters must separately
        establish observed record correlation before emitting app_record.
        """
        ...

    def configure_execution_guard(self, check: Callable[[], None]) -> None:
        """Bind the current agent lease/fence/cancel check before any side effect.

        A physical adapter must invoke it immediately before EVERY write, not
        just method entry, and bound transport calls by the agent action budget.
        Stop must remain available without a live lease. The fake has no device
        transport; its filesystem persistence is not a bounded physical action.
        """
        ...

    def inspect(self) -> DeviceCapability: ...

    def prepare(self, job: JobSpec) -> None:
        """Read-only preflight; MUST NOT start, write location or upload."""
        ...

    def start(self, job: JobSpec) -> None: ...

    def tick(self, job: JobSpec, elapsed_seconds: float) -> None: ...

    def stop(self) -> None:
        """Idempotently quiesce local actions, including after lease loss."""
        ...

    def verify(self, job: JobSpec) -> VerificationResult: ...
