"""R4 composition boundary, not a supported physical MuMu backend.

The real entry remains closed. The explicitly synthetic seam composes the
existing FakeDriver route/session implementation with R2's guarded channel;
it is never advertised as a physical device or exposed in the CLI. No upload
operation is implemented and controlled stop never calls BudaoAdapter.finish.
"""

from collections.abc import Callable
from uuid import uuid4

from swu_happyrun.core.clock import Clock, SystemClock
from swu_happyrun.core.models import DeviceCapability, JobSpec, JobView, VerificationResult
from swu_happyrun.drivers.base import DriverError
from swu_happyrun.drivers.fake import FakeDriver
from swu_happyrun.drivers.mumu.location import MuMuLocation
from swu_happyrun.drivers.mumu.sensors import MuMuSensors, _unguarded


class MuMuDriver:
    def __init__(self, device_id: str):
        self.device_id = device_id
        self._fake: FakeDriver | None = None
        self._clock: Clock = SystemClock()
        self._guard: Callable[[], None] = _unguarded

    @classmethod
    def for_synthetic_testing(
        cls,
        *,
        fake: FakeDriver,
        sensors: MuMuSensors,
        binding_check: Callable[[], None],
        clock: Clock,
        location: MuMuLocation | None = None,
    ) -> "MuMuDriver":
        result = cls(fake.device_id)
        result._fake = fake
        result._sensors = sensors
        result._location = location
        result._binding_check = binding_check
        result._clock = clock
        return result

    def _synthetic(self) -> FakeDriver:
        if self._fake is None:
            raise DriverError("unsupported_by_candidate")
        return self._fake

    def bind_session(self, view: JobView) -> None:
        self._synthetic().bind_session(view)

    def configure_execution_guard(self, check: Callable[[], None]) -> None:
        self._guard = check
        if self._fake is not None:
            self._fake.configure_execution_guard(self._check)
            # Channel observations may block; keep them separate from final authority.
            self._sensors.configure_execution_guard(check, binding_check=self._binding_check)
            if self._location is not None:
                self._location.configure_execution_guard(check, binding_check=self._binding_check)

    def _check(self) -> None:
        self._binding_check()
        self._guard()

    def inspect(self) -> DeviceCapability:
        if self._fake is not None:
            return self._fake.inspect().model_copy(update={"backend": "fake", "capabilities": []})
        return DeviceCapability(
            device_id=self.device_id,
            backend="mumu",
            app_version=None,
            capabilities=[],
            observed_at=self._clock.utcnow(),
            probe_id=str(uuid4()),
        )

    def prepare(self, job: JobSpec) -> None:
        fake = self._synthetic()
        self._binding_check()
        fake.prepare(job)

    def start(self, job: JobSpec) -> None:
        fake = self._synthetic()
        self._check()
        fake.start(job)

    @property
    def route_progress(self):
        return self._fake.route_progress if self._fake is not None else None

    def tick(self, job: JobSpec, elapsed_seconds: float) -> None:
        fake = self._synthetic()
        self._check()
        fake.tick(job, elapsed_seconds)
        if self._location is not None:
            self._location.write(fake.route_progress.position, input_crs="WGS84")
        # This synthetic scalar exercises guards/queue stop only. It is not a
        # pedometer sample, device sensor command, or school fitness evidence.
        self._sensors.write((elapsed_seconds,), deadline=self._clock.monotonic() + 5)

    def stop(self) -> None:
        if self._fake is None:
            raise DriverError("stop_unconfirmed")
        errors = []
        for channel in (self._location, self._sensors, self._fake):
            if channel is not None:
                try:
                    channel.stop()
                except Exception as exc:
                    errors.append(exc)
        if errors:
            raise DriverError("stop_unconfirmed") from errors[0]

    def verify(self, job: JobSpec) -> VerificationResult:
        if self._fake is None:
            return VerificationResult(
                status="unknown", evidence=[], reason_code="unsupported_by_candidate"
            )
        result = self._fake.verify(job)
        if result.status != "unknown" or result.evidence:
            return VerificationResult(
                status="unknown", evidence=[], reason_code="unsupported_by_candidate"
            )
        return result
