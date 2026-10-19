"""Synthetic PR35 probe-batch defect reproduction; no device or private data.

Expected current behavior: first hello 200, identical retry 409, only device A
gets a current probe. These assertions reproduce a defect, not a passing
acceptance test. SQLite exists only inside a temporary directory.
"""

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from fastapi.testclient import TestClient
from swu_happyrun.server.app import create_app
from swu_happyrun.server.settings import ServerSettings


class FixedClock:
    def utcnow(self):
        return datetime(2026, 10, 19, tzinfo=UTC)

    def monotonic(self):
        return 0.0


def uid(number):
    return str(UUID(int=number))


def main():
    with TemporaryDirectory(prefix="happyrun-probe-batch-") as temporary:
        settings = ServerSettings(
            database_path=Path(temporary) / "synthetic.sqlite3",
            admin_token="synthetic-admin",
            agent_tokens={uid(1): "synthetic-agent"},
        )
        app = create_app(settings, clock=FixedClock())
        # No lifespan is needed: exercise the HTTP endpoints without a scheduler.
        client = TestClient(app)
        for device in (2, 3):
            response = client.post(
                "/api/v1/devices",
                headers={"Authorization": "Bearer synthetic-admin"},
                json={"device_id": uid(device), "agent_id": uid(1)},
            )
            assert response.status_code == 201, response.text

        payload = {
            "protocol_version": 1,
            "agent_id": uid(1),
            "devices": [
                {
                    "device_id": uid(device),
                    "backend": "fake",
                    "app_version": None,
                    "capabilities": [],
                    "observed_at": "2026-10-19T00:00:00Z",
                    "probe_id": uid(4),
                }
                for device in (2, 3)
            ],
        }
        headers = {"Authorization": "Bearer synthetic-agent"}
        first = client.post("/api/v1/agents/hello", headers=headers, json=payload)
        assert first.status_code == 200, first.text

        with app.state.store.connection() as database:
            observed = [
                (row["device_id"], row["current_probe"])
                for row in database.execute(
                    "SELECT device_id,current_probe FROM devices ORDER BY device_id"
                )
            ]
            probe_count = database.execute("SELECT count(*) FROM probes").fetchone()[0]
        assert observed == [(uid(2), uid(4)), (uid(3), None)], observed
        assert probe_count == 1, probe_count

        repeated = client.post("/api/v1/agents/hello", headers=headers, json=payload)
        assert repeated.status_code == 409, repeated.text
        assert repeated.json()["error"]["message"] == "Probe identifier already used"
        client.close()

        print("DEFECT REPRODUCED: initial HTTP 200; identical retry HTTP 409.")
        print("Persisted: device A probe present; device B probe absent; one probe row.")
        print("Expected contract: reject the conflicting first batch with HTTP 409 and no writes.")


if __name__ == "__main__":
    main()
