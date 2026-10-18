"""Injectable wall and monotonic clocks for lease/schedule tests."""

import time
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    def utcnow(self) -> datetime: ...

    def monotonic(self) -> float: ...


class SystemClock:
    def utcnow(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()
