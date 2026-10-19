"""Opt-in real Chromium tests: python tests/console/test_console_browser.py."""

import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

ROOT = Path(__file__).resolve().parents[2] / "src/swu_happyrun/server/web"


def main():
    from playwright.sync_api import sync_playwright

    assert (ROOT / "index.html").exists(), "Console entrypoint missing"
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(ROOT))
    )
    Thread(target=server.serve_forever, daemon=True).start()
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 375, "height": 812})

        def api(route):
            path = route.request.url.split("/api/v1/")[-1]
            payload = (
                []
                if path in ("devices", "schedules")
                else {"items": [], "next_cursor": None}
                if path.startswith("jobs?")
                else {"status": "ok", "protocol_version": 1}
            )
            route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

        page.route("**/api/v1/**", api)
        page.goto(f"http://127.0.0.1:{server.server_port}/")
        page.locator("#token").fill("test-admin-token")
        page.locator("#connect-form button").click()
        page.locator("#workspace").wait_for(state="visible")
        assert page.locator("#token").input_value() == ""
        assert page.evaluate("localStorage.length + sessionStorage.length") == 0
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.locator("#logout").click()
        assert page.locator("#workspace").is_hidden()
        assert page.locator("#jobs-list").inner_text() == ""
        browser.close()
    server.shutdown()
    print("PASS: real Chromium connect, secret clearing, logout, 375px overflow")


if __name__ == "__main__":
    main()
