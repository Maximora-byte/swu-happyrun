import asyncio
from threading import Event
from unittest.mock import Mock

import pytest

from swu_happyrun.cli import main


def test_server_open_browser_rejects_nonloopback_before_start(tmp_path, monkeypatch):
    import uvicorn

    run = Mock()
    monkeypatch.setattr(uvicorn, "run", run)
    monkeypatch.setenv("HAPPYRUN_ADMIN_TOKEN", "test-admin")
    monkeypatch.setenv("HAPPYRUN_AGENT_TOKENS", "{}")
    assert (
        main(
            [
                "server",
                "--host",
                "0.0.0.0",
                "--open-browser",
                "--database",
                str(tmp_path / "db.sqlite"),
            ]
        )
        == 2
    )
    run.assert_not_called()
    assert not (tmp_path / "db.sqlite").exists()


def test_open_browser_cli_dispatches_without_opening_real_browser(tmp_path, monkeypatch):
    from swu_happyrun.server import web

    run = Mock()
    monkeypatch.setattr(web, "run_with_browser", run, raising=False)
    monkeypatch.setenv("HAPPYRUN_ADMIN_TOKEN", "test-admin")
    monkeypatch.setenv("HAPPYRUN_AGENT_TOKENS", "{}")
    assert main(["server", "--open-browser", "--database", str(tmp_path / "db.sqlite")]) == 0
    assert run.call_args.kwargs == {"host": "127.0.0.1", "port": 8080}


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1", "http://127.0.0.1:8080/console/"),
        ("::1", "http://[::1]:8080/console/"),
    ],
)
def test_loopback_browser_url(host, expected):
    from swu_happyrun.server import web

    assert web.browser_url(host, 8080) == expected


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.2", "example.com"])
def test_browser_url_rejects_remote_targets(host):
    from swu_happyrun.server import web

    with pytest.raises(ValueError):
        web.browser_url(host, 8080)


@pytest.mark.parametrize("started", [True, False])
def test_browser_opens_only_after_successful_server_start(monkeypatch, started):
    import webbrowser

    import uvicorn

    from swu_happyrun.server import web

    calls = []
    opened = Event()

    async def startup(self, sockets=None):
        calls.append("startup")
        self.started = started

    def run(self):
        asyncio.run(self.startup())

    monkeypatch.setattr(uvicorn.Server, "startup", startup)
    monkeypatch.setattr(uvicorn.Server, "run", run)

    def open_browser(url):
        calls.append(url)
        opened.set()
        return True

    monkeypatch.setattr(webbrowser, "open", open_browser)
    web.run_with_browser(object(), host="127.0.0.1", port=8080)
    if started:
        assert opened.wait(5)
    assert calls == (["startup", "http://127.0.0.1:8080/console/"] if started else ["startup"])


def test_browser_failure_does_not_stop_server(monkeypatch):
    import webbrowser

    import uvicorn

    from swu_happyrun.server import web

    async def startup(self, sockets=None):
        self.started = True

    def run(self):
        asyncio.run(self.startup())
        assert self.started

    attempted = Event()

    def fail(url):
        attempted.set()
        raise webbrowser.Error("private environment detail")

    monkeypatch.setattr(uvicorn.Server, "startup", startup)
    monkeypatch.setattr(uvicorn.Server, "run", run)
    monkeypatch.setattr(webbrowser, "open", fail)
    web.run_with_browser(object(), host="localhost", port=8080)
    assert attempted.wait(5)


def test_failed_bind_never_opens_browser(monkeypatch):
    import webbrowser

    import uvicorn

    from swu_happyrun.server import web

    async def startup(self, sockets=None):
        raise SystemExit(1)

    monkeypatch.setattr(uvicorn.Server, "startup", startup)
    monkeypatch.setattr(uvicorn.Server, "run", lambda self: asyncio.run(self.startup()))
    browser = Mock()
    monkeypatch.setattr(webbrowser, "open", browser)
    with pytest.raises(SystemExit):
        web.run_with_browser(object(), host="localhost", port=8080)
    browser.assert_not_called()


def test_default_server_does_not_launch_browser(tmp_path, monkeypatch):
    import uvicorn

    from swu_happyrun.server import web

    ordinary = Mock()
    browser = Mock()
    monkeypatch.setattr(uvicorn, "run", ordinary)
    monkeypatch.setattr(web, "run_with_browser", browser)
    monkeypatch.setenv("HAPPYRUN_ADMIN_TOKEN", "test-admin")
    monkeypatch.setenv("HAPPYRUN_AGENT_TOKENS", "{}")
    assert main(["server", "--database", str(tmp_path / "db.sqlite")]) == 0
    ordinary.assert_called_once()
    assert ordinary.call_args.kwargs["host"] == "127.0.0.1"
    browser.assert_not_called()


def test_blocked_browser_does_not_delay_live_server_shutdown(app, monkeypatch):
    import threading
    import webbrowser

    import httpx
    import uvicorn

    from swu_happyrun.server import web

    opener_entered = threading.Event()
    release_opener = threading.Event()
    opener_finished = threading.Event()
    captured = []
    failures = []
    original_run = uvicorn.Server.run

    def capture_server(self):
        # Use an OS-assigned loopback port; only the fake opener sees the CLI URL.
        self.config.port = 0
        captured.append(self)
        original_run(self)

    def blocked_opener(url):
        opener_entered.set()
        try:
            release_opener.wait()
            return True
        finally:
            opener_finished.set()

    def serve():
        try:
            web.run_with_browser(app, host="127.0.0.1", port=8080)
        except BaseException as exc:
            failures.append(exc)

    monkeypatch.setattr(uvicorn.Server, "run", capture_server)
    monkeypatch.setattr(webbrowser, "open", blocked_opener)
    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        assert opener_entered.wait(5), "Browser was not launched after binding"
        server = captured[0]
        port = server.servers[0].sockets[0].getsockname()[1]
        response = httpx.get(f"http://127.0.0.1:{port}/api/v1/health", timeout=3, trust_env=False)
        assert response.status_code == 200
        server.should_exit = True
        thread.join(3)
        assert not thread.is_alive(), "Blocked browser prevented normal server shutdown"
        assert not opener_finished.is_set()
        assert not failures
    finally:
        if captured:
            captured[0].should_exit = True
        release_opener.set()
        thread.join(5)
        assert opener_finished.wait(5)
