"""Probe batch atomicity against SQLite and an actual loopback HTTP listener."""

import copy
import socket
import sqlite3
import threading
import time
from contextlib import contextmanager
from uuid import uuid4

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from swu_happyrun.server.app import create_app

from .conftest import ADMIN, AGENT, AGENT_A, AGENT_B, FakeClock


@contextmanager
def serving(settings, clock, network):
    app = create_app(settings, clock=clock)
    if not network:
        with TestClient(app) as client:
            yield client
        return
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", timeout=5, trust_env=False
        ) as client:
            yield client
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive()


def snapshot(settings):
    with sqlite3.connect(settings.database_path) as db:
        return {
            table: db.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
            for table in ("agents", "devices", "probes")
        }


def assert_device_probe_mapping(settings, report):
    with sqlite3.connect(settings.database_path) as db:
        actual = dict(db.execute("SELECT device_id, current_probe FROM devices"))
    assert actual == {item["device_id"]: item["probe_id"] for item in report["devices"]}


def batch(devices):
    return {
        "protocol_version": 1,
        "agent_id": AGENT_A,
        "devices": [
            {
                "device_id": device,
                "backend": "fake",
                "app_version": None,
                "capabilities": [],
                "observed_at": "2026-10-19T00:00:00Z",
                "probe_id": str(uuid4()),
            }
            for device in devices
        ],
    }


def register(client, device, agent=AGENT_A):
    assert (
        client.post(
            "/api/v1/devices",
            headers=ADMIN,
            json={"device_id": device, "agent_id": agent},
        ).status_code
        == 201
    )


@pytest.mark.parametrize("network", [False, True], ids=["sqlite-testclient", "real-http"])
def test_conflicting_new_probe_batch_is_atomic_across_restart(settings, network):
    clock = FakeClock()
    devices = [str(uuid4()), str(uuid4())]
    valid = batch(devices)
    bad = copy.deepcopy(valid)
    bad["devices"][1]["probe_id"] = bad["devices"][0]["probe_id"]
    for restart in range(2):
        with serving(settings, clock, network) as client:
            if not restart:
                for device in devices:
                    register(client, device)
            before = snapshot(settings)
            clock.advance(1)
            for _ in range(2):
                assert (
                    client.post("/api/v1/agents/hello", headers=AGENT, json=bad).status_code == 409
                )
                assert snapshot(settings) == before
            if not restart:
                assert (
                    client.post("/api/v1/agents/hello", headers=AGENT, json=valid).status_code
                    == 200
                )
                stored = snapshot(settings)
                assert len(stored["agents"]) == 1
                assert len(stored["probes"]) == 2
                assert_device_probe_mapping(settings, valid)
            else:
                stored = before
            fresh_conflict = copy.deepcopy(valid)
            shared_probe = str(uuid4())
            for report in fresh_conflict["devices"]:
                report["probe_id"] = shared_probe
            clock.advance(1)
            assert (
                client.post("/api/v1/agents/hello", headers=AGENT, json=fresh_conflict).status_code
                == 409
            )
            assert snapshot(settings) == stored
            clock.advance(10)
            assert client.post("/api/v1/agents/hello", headers=AGENT, json=valid).status_code == 200
            replay = snapshot(settings)
            assert replay["devices"] == stored["devices"]
            assert replay["probes"] == stored["probes"]  # no refreshed first-received time


@pytest.mark.parametrize("network", [False, True], ids=["sqlite-testclient", "real-http"])
def test_persisted_conflict_and_foreign_device_roll_back_complete_batch(settings, network):
    clock = FakeClock()
    devices = [str(uuid4()) for _ in range(3)]
    original = batch(devices[:2])
    with serving(settings, clock, network) as client:
        for device in devices[:2]:
            register(client, device)
        register(client, devices[2], AGENT_B)
        assert client.post("/api/v1/agents/hello", headers=AGENT, json=original).status_code == 200
    with serving(settings, clock, network) as client:
        before = snapshot(settings)
        clock.advance(10)
        changed = batch(devices[:2])
        changed["devices"][1] = copy.deepcopy(original["devices"][1])
        changed["devices"][1]["capabilities"] = ["location_write"]
        assert client.post("/api/v1/agents/hello", headers=AGENT, json=changed).status_code == 409
        assert snapshot(settings) == before
        foreign = batch([devices[0], devices[2]])
        assert client.post("/api/v1/agents/hello", headers=AGENT, json=foreign).status_code == 404
        assert snapshot(settings) == before
        # Existing heartbeat semantics: observations do not insert/replace capability probes.
        assert (
            client.post("/api/v1/agents/heartbeat", headers=AGENT, json=original).status_code == 200
        )
        after = snapshot(settings)
        assert after["probes"] == before["probes"]
        assert after["devices"] == before["devices"]


@pytest.mark.parametrize("existing_agent", [False, True])
def test_sqlite_abort_after_first_probe_write_rolls_back_entire_batch(settings, existing_agent):
    from swu_happyrun.core.models import AgentHello, DeviceRegistration
    from swu_happyrun.server.store import SqliteJobStore

    clock = FakeClock()
    store = SqliteJobStore(settings.database_path, clock)
    devices = [str(uuid4()), str(uuid4())]
    for device in devices:
        store.register_device(DeviceRegistration(device_id=device, agent_id=AGENT_A))
    if existing_agent:
        store.observe_agent(AgentHello.model_validate(batch(devices)))
    incoming = batch(devices)
    first_probe, second_probe = (item["probe_id"] for item in incoming["devices"])
    before = snapshot(settings)
    with sqlite3.connect(settings.database_path) as db:
        # IDs are generated UUID fixtures. The trigger proves the first insert AND device
        # update happened inside this transaction before aborting the second insert.
        db.execute(
            f"""CREATE TRIGGER abort_second_probe BEFORE INSERT ON probes
            WHEN NEW.probe_id = '{second_probe}'
            BEGIN
              SELECT CASE WHEN EXISTS(SELECT 1 FROM probes WHERE probe_id='{first_probe}')
                AND EXISTS(SELECT 1 FROM devices WHERE device_id='{devices[0]}'
                           AND current_probe='{first_probe}')
                THEN RAISE(ABORT, 'synthetic_second_after_first_write')
                ELSE RAISE(ABORT, 'synthetic_missing_first_write') END;
            END"""
        )
    clock.advance(5)
    with pytest.raises(sqlite3.IntegrityError, match="synthetic_second_after_first_write"):
        store.observe_agent(AgentHello.model_validate(incoming))
    assert snapshot(settings) == before
    # Reopen the durable store before retry: no hidden partial observations survived.
    store = SqliteJobStore(settings.database_path, clock)
    assert snapshot(settings) == before
    with sqlite3.connect(settings.database_path) as db:
        db.execute("DROP TRIGGER abort_second_probe")
    store.observe_agent(AgentHello.model_validate(incoming))
    accepted = snapshot(settings)
    clock.advance(10)
    store.observe_agent(AgentHello.model_validate(incoming))
    replayed = snapshot(settings)
    assert replayed["probes"] == accepted["probes"]
    assert replayed["devices"] == accepted["devices"]


def test_probe_mapping_assertion_rejects_fence_only_and_swapped_probes(settings):
    from swu_happyrun.core.models import AgentHello, DeviceRegistration
    from swu_happyrun.server.store import SqliteJobStore

    store = SqliteJobStore(settings.database_path, FakeClock())
    devices = [str(uuid4()), str(uuid4())]
    for device in devices:
        store.register_device(DeviceRegistration(device_id=device, agent_id=AGENT_A))
    report = batch(devices)
    with pytest.raises(AssertionError):
        assert_device_probe_mapping(settings, report)  # fence=0, current_probe=NULL
    store.observe_agent(AgentHello.model_validate(report))
    assert_device_probe_mapping(settings, report)
    with sqlite3.connect(settings.database_path) as db:
        db.execute(
            "UPDATE devices SET current_probe=? WHERE device_id=?",
            (report["devices"][1]["probe_id"], devices[0]),
        )
    with pytest.raises(AssertionError):
        assert_device_probe_mapping(settings, report)
