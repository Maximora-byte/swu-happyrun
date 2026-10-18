from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

AGENT_A = "00000000-0000-0000-0000-000000000001"
AGENT_B = "00000000-0000-0000-0000-000000000002"
ADMIN = {"Authorization": "Bearer test-admin"}
AGENT = {"Authorization": "Bearer test-agent-a"}


class FakeClock:
    def utcnow(self):
        return datetime(2026, 10, 19, tzinfo=UTC)

    def monotonic(self):
        return 0.0


@pytest.fixture
def spec():
    return dict(
        protocol_version=1,
        mode="simulation",
        profile_id=str(UUID(int=3)),
        profile_revision="a" * 64,
        route_id=str(UUID(int=4)),
        route_revision="b" * 64,
        device_id=str(UUID(int=5)),
        not_before="2026-10-19T00:00:00Z",
        deadline="2026-10-19T01:00:00Z",
    )


@pytest.fixture
def settings(tmp_path):
    from swu_happyrun.server.settings import ServerSettings

    return ServerSettings(
        database_path=tmp_path / "jobs.sqlite3",
        admin_token="test-admin",
        agent_tokens={AGENT_A: "test-agent-a", AGENT_B: "test-agent-b"},
    )


@pytest.fixture
def app(settings):
    from swu_happyrun.server.app import create_app

    return create_app(settings, clock=FakeClock())


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


def create_job(client, spec, key="test-key"):
    return client.post("/api/v1/jobs", json=spec, headers={**ADMIN, "Idempotency-Key": key})
