"""Exercise the probe against real local HTTP, explicitly without Docker evidence."""

import os
import socket
import uuid

import pytest
from test_smoke_contract import smoke


def test_probe_protocol_over_real_http_without_docker(tmp_path):
    with socket.socket() as sock:
        if sock.connect_ex(("127.0.0.1", 8080)) == 0:
            pytest.skip("Fixed disposable probe port in use; do not touch existing service")
    agent_id, device_id, other_id = (str(uuid.uuid4()) for _ in range(3))
    admin, agent, other = "container-test-admin", "container-test-agent", "container-test-other"
    env = {
        **os.environ,
        "PYTHONPATH": str(smoke.ROOT / "src"),
        "HAPPYRUN_ADMIN_TOKEN": admin,
        "HAPPYRUN_AGENT_TOKENS": smoke.json.dumps({agent_id: agent, other_id: other}),
        "HAPPYRUN_AGENT_TOKEN": agent,
        "SWU_HAPPYRUN_HOST_ID_FILE": str(tmp_path / "host-id"),
    }
    api = smoke.Api(smoke.BASE, admin, agent, other)
    with (tmp_path / "local-server.log").open("w", encoding="utf-8") as log:
        process, _ = smoke._fixture.start(tmp_path, 8080, env, log)

        def recreate():
            nonlocal process
            smoke._fixture.stop(process)
            process, _ = smoke._fixture.start(tmp_path, 8080, env, log)

        try:
            checks = smoke.exercise(api, tmp_path, env, agent_id, device_id, recreate)
            assert "lease_expiry_and_fence" in checks
            assert "schedule_occurrence_dedup" in checks
        finally:
            api.http.close()
            smoke._fixture.stop(process)
