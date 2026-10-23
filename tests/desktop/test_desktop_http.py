import contextlib
import socket
import threading
import time
from uuid import uuid4

import httpx
import uvicorn

from swu_happyrun.desktop.app import create_desktop_app
from swu_happyrun.desktop.workspace import Workspace


@contextlib.contextmanager
def serve(workspace):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    app = create_desktop_app(workspace, port=port)
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=5
        ) as client:
            client.headers["Origin"] = str(client.base_url).rstrip("/")
            response = client.post(
                "/api/v1/desktop/session", json={"nonce": app.state.desktop_nonce}
            )
            assert response.status_code == 200
            yield client
    finally:
        server.should_exit = True
        thread.join(12)
        sock.close()
        assert not thread.is_alive()
        assert not app.state.desktop_worker.thread.is_alive()


def wait_for(client, predicate, *, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        response = client.get("/api/v1/desktop/workspace")
        assert response.status_code == 200
        state = response.json()
        if predicate(state):
            return state
        time.sleep(0.1)
    raise AssertionError("desktop HTTP state deadline expired")


def create(client):
    state = wait_for(client, lambda state: state["worker_status"] == "ready")
    response = client.post(
        "/api/v1/desktop/jobs",
        json=state["job_template"],
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 201
    return response.json()["job_id"]


def test_real_http_completes_cancels_and_preserves_jobs_after_restart(tmp_path):
    workspace = Workspace.open(tmp_path / "desktop")
    with serve(workspace) as client:
        first = create(client)
        state = wait_for(
            client,
            lambda state: any(
                job["job_id"] == first and job["state"] == "completed" for job in state["jobs"]
            ),
        )
        assert state["record_verified"] is False
        second = create(client)
        wait_for(
            client,
            lambda state: any(
                job["job_id"] == second and job["state"] == "running" for job in state["jobs"]
            ),
        )
        cancelled = client.post(f"/api/v1/desktop/jobs/{second}/cancel", json={})
        assert cancelled.status_code == 200
        assert cancelled.json()["state"] == "cancelling"
        wait_for(
            client,
            lambda state: any(
                job["job_id"] == second and job["state"] == "cancelled" for job in state["jobs"]
            ),
        )
    with serve(Workspace.open(workspace.root)) as client:
        state = client.get("/api/v1/desktop/workspace").json()
        assert {job["job_id"]: job["state"] for job in state["jobs"]} == {
            first: "completed",
            second: "cancelled",
        }
