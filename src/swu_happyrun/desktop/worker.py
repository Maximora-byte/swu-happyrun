"""One cooperative fake agent using the unchanged HTTP control plane."""

import signal
from threading import Thread

from swu_happyrun.agent.client import ControlClient
from swu_happyrun.agent.journal import RunJournal
from swu_happyrun.agent.lifecycle import Shutdown, ShutdownRequested, idle_liveness
from swu_happyrun.agent.runner import AgentRunner
from swu_happyrun.core.clock import SystemClock
from swu_happyrun.core.models import AgentHello
from swu_happyrun.core.profiles import LocalProfileStore
from swu_happyrun.drivers.fake import FakeDriver


class DesktopWorker:
    def __init__(self, workspace, port, token):
        self.workspace, self.port, self._token = workspace, port, token
        self.shutdown = Shutdown()
        self.status = "starting"
        self.thread = Thread(target=self._run, name="happyrun-local-agent", daemon=True)

    def _run(self):
        workspace = self.workspace
        driver = FakeDriver(
            workspace.device_id,
            LocalProfileStore(workspace.root / "profiles"),
            app_version="test-1",
            state_path=workspace.root / "fake-state.json",
            route_speed_mps=2.0,
        )
        try:
            with (
                ControlClient(f"http://127.0.0.1:{self.port}", self._token) as client,
                RunJournal(workspace.root / "agent.sqlite") as journal,
            ):
                runner = AgentRunner(
                    client,
                    driver,
                    journal,
                    SystemClock(),
                    device_id=workspace.device_id,
                    run_seconds=120,
                    sleep=self.shutdown.wait,
                    shutdown=self.shutdown,
                )
                while True:
                    self.shutdown.check()
                    hello = AgentHello(
                        protocol_version=1, agent_id=workspace.agent_id, devices=[driver.inspect()]
                    )
                    idle_liveness(lambda hello=hello: client.hello(hello), self.shutdown)
                    runner.hello = hello
                    self.status = "ready"
                    runner.run_once()
                    self.shutdown.wait(0.5)
        except ShutdownRequested:
            self.status = "stopped"
        except Exception:
            self.status = "needs_attention"  # Never expose exception text or auto-restart.

    def start(self):
        self.thread.start()

    def close(self):
        self.shutdown.request(signal.SIGTERM)
        self.thread.join(timeout=6)
        if self.thread.is_alive():
            self.status = "stop_unconfirmed"
