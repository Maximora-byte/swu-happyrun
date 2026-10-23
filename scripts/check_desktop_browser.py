"""Real Chromium acceptance of the loopback desktop product, using synthetic data."""

import argparse
import json
import socket
import tempfile
import threading
import time
from pathlib import Path

import uvicorn
from playwright.sync_api import expect, sync_playwright

from swu_happyrun.desktop.app import create_desktop_app
from swu_happyrun.desktop.workspace import Workspace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="happyrun-desktop-browser-") as temp:
        workspace = Workspace.open(Path(temp) / "workspace")
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        app = create_desktop_app(workspace, port=port)
        server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level="error"))
        thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
        thread.start()
        results = []
        try:
            deadline = time.monotonic() + 10
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page(viewport={"width": 1440, "height": 1100})
                errors = []
                page.on("pageerror", lambda error: errors.append(type(error).__name__))
                page.goto(f"http://127.0.0.1:{port}/desktop/#" + app.state.desktop_nonce)
                expect(page.locator("#connection")).to_have_text("本机已连接")
                assert "#" not in page.url
                expect(page.locator("#start")).to_be_enabled(timeout=15000)
                page.screenshot(path=str(args.output / "desktop-ready.png"), full_page=True)
                results.append("bootstrap_and_worker_ready")
                page.locator("#start").dblclick()
                expect(page.locator("#job-state")).to_have_text("模拟完成", timeout=30000)
                expect(page.locator(".history-row")).to_have_count(1)
                page.screenshot(path=str(args.output / "desktop-completed.png"), full_page=True)
                results.append("double_click_one_job_completed")
                page.reload()
                expect(page.locator("#connection")).to_have_text("本机已连接")
                expect(page.locator("#job-state")).to_have_text("模拟完成")
                results.append("refresh_preserves_session_and_history")
                page.locator("#start").click()
                expect(page.locator("#job-state")).to_have_text("执行中", timeout=15000)
                page.locator("#cancel").click()
                expect(page.locator("#job-state")).to_have_text("已取消", timeout=15000)
                expect(page.locator(".history-row")).to_have_count(2)
                results.append("running_cancel_requires_acknowledgment")
                page.set_viewport_size({"width": 390, "height": 844})
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.screenshot(path=str(args.output / "desktop-mobile.png"), full_page=True)
                assert not errors, "browser JavaScript errors"
                results.append("mobile_layout_no_overflow_or_script_errors")
                browser.close()
        finally:
            server.should_exit = True
            thread.join(12)
            sock.close()
            assert not thread.is_alive()
            assert not app.state.desktop_worker.thread.is_alive()
        report = {
            "status": "passed",
            "cases": results,
            "record_verified": False,
            "device_verified": False,
            "server_and_worker_stopped": True,
        }
        (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report))


if __name__ == "__main__":
    main()
