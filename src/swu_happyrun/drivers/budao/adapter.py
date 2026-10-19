"""Fail-closed L3 adapter boundary. This candidate never calls ADB.

The adapter is a component for a future DeviceDriver, not another driver or job
state machine. DeviceDriver retains intent, lease/fence guard, bounded transport,
route and stop responsibilities. No sample-backed UI implementation exists yet.
"""

from collections.abc import Callable
from datetime import UTC, datetime

from swu_happyrun.core.models import SchoolProfile, VerificationResult
from swu_happyrun.drivers.adb import AdbClient
from swu_happyrun.drivers.base import DriverError
from swu_happyrun.drivers.budao.records import (
    RecordObservation,
    SessionObservation,
    verify_result,
)
from swu_happyrun.drivers.budao.selectors import PageObservation, page_blocker


class BudaoAdapter:
    def __init__(
        self,
        adb: AdbClient,
        profile: SchoolProfile,
        *,
        page: PageObservation | None = None,
        now: Callable[[], datetime] | None = None,
    ):
        self._adb = adb
        self._profile = SchoolProfile.model_validate(profile.model_dump(mode="python"))
        self._page = page
        self._now = now or (lambda: datetime.now(UTC))
        self.reason_code = "needs_samples"

    def inspect_state(self) -> str:
        self.reason_code = page_blocker(self._page, self._profile, self._now())
        return "unknown"

    def start(self) -> None:
        self.inspect_state()
        raise DriverError(self.reason_code)

    def finish(self) -> None:
        self.inspect_state()
        raise DriverError(self.reason_code)

    def read_result(
        self,
        *,
        record: RecordObservation | None = None,
        session: SessionObservation | None = None,
    ) -> VerificationResult:
        self.inspect_state()
        if self.reason_code != "needs_samples":
            return VerificationResult(status="unknown", evidence=[], reason_code=self.reason_code)
        if session is not None and self._page is not None:
            if session.session_id != self._page.session_id:
                return VerificationResult(
                    status="unknown", evidence=[], reason_code="record_session_mismatch"
                )
        return verify_result(record, session=session, now=self._now())
