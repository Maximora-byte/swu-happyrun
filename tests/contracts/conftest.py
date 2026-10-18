from datetime import UTC, datetime, timedelta

import pytest


@pytest.fixture
def spec_data():
    now = datetime(2026, 10, 18, 8, tzinfo=UTC)
    return dict(
        protocol_version=1,
        mode="simulation",
        profile_id="00000000-0000-4000-8000-000000000001",
        profile_revision="a" * 64,
        route_id="00000000-0000-4000-8000-000000000002",
        route_revision="b" * 64,
        device_id="00000000-0000-4000-8000-000000000003",
        not_before=now,
        deadline=now + timedelta(hours=1),
    )
