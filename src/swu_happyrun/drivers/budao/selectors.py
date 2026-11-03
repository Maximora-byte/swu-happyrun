"""Offline state gate, not a UI parser. No real selectors are available.

Page labels are untrusted candidate observations, not proof of an actual page.
No public registration API is provided. Version support requires reviewed local
samples for the exact package, versionName AND versionCode in a later change.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from types import MappingProxyType

from swu_happyrun.core.models import SchoolProfile

REAL_VERSION_REGISTRY = MappingProxyType({})
MAX_OBSERVATION_AGE = timedelta(seconds=30)


@dataclass(frozen=True)
class PageObservation:
    package: str
    version_name: str
    version_code: int | None
    captured_at: datetime
    state: str
    authorized: bool
    dynamic_points_confirmed: bool
    session_id: str | None


def fresh(captured_at: datetime, now: datetime) -> bool:
    """Reject absent timezones, future observations and the exact expiry boundary."""
    if not isinstance(captured_at, datetime) or not isinstance(now, datetime):
        return False
    if captured_at.utcoffset() is None or now.utcoffset() is None:
        return False
    return timedelta(0) <= now - captured_at < MAX_OBSERVATION_AGE


def page_blocker(page: PageObservation | None, profile: SchoolProfile, now: datetime) -> str:
    """Always return a blocker until sample-backed version support is implemented."""
    if page is None:
        return "page_missing"
    if page.package != profile.app_package or page.version_name != profile.app_version:
        return "app_version_mismatch"
    if type(page.version_code) is not int or page.version_code <= 0:
        return "version_code_missing"
    if not fresh(page.captured_at, now):
        return "stale_page"
    if not profile.confirmed or page.authorized is not True:
        return "authorization_required"
    if not page.session_id or not page.session_id.strip():
        return "session_missing"
    if page.dynamic_points_confirmed is not True:
        return "dynamic_points_missing"
    if page.state not in {"start", "running", "ended", "upload_pending", "valid", "invalid"}:
        return "unknown_page"
    # Candidate labels, boolean assertions and synthetic fixtures cannot activate
    # real execution. Do not turn registry injection into a capability bypass.
    return "needs_samples"
