"""Optional real Chromium / loopback console acceptance.

Run from a source checkout or against an installed distribution:
  python scripts/check_console_browser.py --output-dir browser-evidence
Requires the optional browser-test dependencies and `playwright install chromium`.
Only disposable synthetic identities, simulation jobs and a temporary SQLite DB
are used. No devices, external services, user accounts or persistent credentials.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import socket
import tempfile
import threading
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import uvicorn
from playwright.async_api import async_playwright, expect

from swu_happyrun.core.models import DeviceRegistration, JobSpec, ScheduleSpec
from swu_happyrun.server.app import create_app
from swu_happyrun.server.settings import ServerSettings

TOKEN = "synthetic-console-acceptance-only"
AGENT_ID = str(UUID(int=1))
DEVICE_ID = str(UUID(int=5))
SPEC = {
    "protocol_version": 1,
    "mode": "simulation",
    "expected_app_version": None,
    "profile_id": str(UUID(int=3)),
    "profile_revision": "a" * 64,
    "route_id": str(UUID(int=4)),
    "route_revision": "b" * 64,
    "device_id": DEVICE_ID,
    "not_before": "2026-10-19T00:00:00Z",
    "deadline": "2026-10-19T01:00:00Z",
}


class FixedClock:
    def utcnow(self):
        return datetime(2026, 10, 19, tzinfo=UTC)

    def monotonic(self):
        return time.monotonic()


class Suite:
    def __init__(self, browser, origin, output):
        self.browser, self.origin, self.output = browser, origin, output
        self.results = []
        self.context = None
        self.page = None
        self.requests = []
        self.logs = []
        self.errors = []

    async def fresh(self, *, connect=True, width=1440):
        if self.context:
            await self.context.close()
        self.context = await self.browser.new_context(viewport={"width": width, "height": 900})
        self.page = await self.context.new_page()
        self.requests, self.logs, self.errors = [], [], []
        self.page.on("request", lambda r: self.requests.append(r))
        self.page.on("console", lambda m: self.logs.append(m.text))
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        await self.page.goto(self.origin + "/console/")
        if connect:
            await self.connect()
        return self.page

    async def connect(self):
        await self.page.locator("#token").fill(TOKEN)
        await self.page.locator("#connect-form button").click()
        await expect(self.page.locator("#workspace")).to_be_visible()
        await expect(self.page.locator("#jobs-list .job-row").first).to_be_visible()
        await expect(self.page.locator("#schedules-list .schedule-row")).to_be_visible()

    async def imported(self):
        p = self.page
        await p.locator(".create-panel summary").click()
        await p.locator("#import-job").set_input_files(
            {
                "name": "synthetic-jobspec.json",
                "mimeType": "application/json",
                "buffer": json.dumps(SPEC).encode(),
            }
        )
        await expect(p.locator('#job-form [name="profile_id"]')).to_have_value(SPEC["profile_id"])
        await expect(p.locator('#job-form [name="not_before"]')).to_have_value("2026-10-19T08:00")

    async def check(self, name, action):
        try:
            await action()
            assert not self.errors, self.errors
            assert all(r.url.startswith(self.origin + "/") for r in self.requests)
            assert all(TOKEN not in line for line in self.logs)
            self.results.append({"name": name, "status": "passed"})
            print("PASS " + name, flush=True)
        except Exception as exc:
            self.results.append(
                {"name": name, "status": "failed", "error": str(exc).replace(TOKEN, "[redacted]")}
            )
            print("FAIL " + name + ": " + str(exc).replace(TOKEN, "[redacted]"), flush=True)
            if self.page:
                await self.page.screenshot(
                    path=str(self.output / ("failure-" + str(len(self.results)) + ".png"))
                )

    async def overflow(self):
        assert await self.page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
            "Horizontal page overflow"
        )

    async def screenshot(self, name):
        path = self.output / name
        await self.page.screenshot(path=str(path), full_page=False)
        if os.environ.get("HAPPYRUN_EMIT_QA_SCREENSHOTS") == "1":
            data = path.read_bytes()
            # A bounded viewport contains only synthetic data and never an entered token.
            if len(data) > 700_000:
                raise AssertionError("Screenshot exceeds evidence output limit")
            print(f"HAPPYRUN_SCREENSHOT_BEGIN {name} sha256={hashlib.sha256(data).hexdigest()}")
            encoded = base64.b64encode(data).decode()
            for start in range(0, len(encoded), 120):
                print(encoded[start : start + 120])
            print(f"HAPPYRUN_SCREENSHOT_END {name}", flush=True)

    async def auth_and_layout(self):
        p = await self.fresh(connect=False)
        await p.keyboard.press("Tab")
        assert await p.evaluate("document.activeElement.classList.contains('skip')")
        await p.locator("#token").fill("synthetic-invalid")
        await p.locator("#connect-form button").click()
        await expect(p.locator("#notice")).to_contain_text("令牌")
        await expect(p.locator("#workspace")).to_be_hidden()
        await self.connect()
        await expect(p.locator("#token")).to_have_value("")
        assert await p.evaluate("localStorage.length + sessionStorage.length") == 0
        assert TOKEN not in p.url and all(TOKEN not in line for line in self.logs)
        assert all(r.url.startswith(self.origin + "/") for r in self.requests), (
            "Third-party network request"
        )
        await self.overflow()
        await self.screenshot("desktop-1440.png")
        for width in (375, 390):
            await p.set_viewport_size({"width": width, "height": 844})
            await self.overflow()
            if width == 390:
                await self.screenshot("mobile-390.png")
        await p.locator("#logout").click()
        await expect(p.locator("#workspace")).to_be_hidden()
        await expect(p.locator("#token")).to_have_value("")
        assert await p.locator("#jobs-list").inner_text() == ""
        await expect(p.locator("#import-job")).to_be_enabled()
        await p.reload()
        await expect(p.locator("#workspace")).to_be_hidden()

    async def pagination_lookup(self):
        p = await self.fresh()
        await expect(p.locator(".job-row")).to_have_count(25)
        await p.locator("#load-more").click()
        await expect(p.locator(".job-row")).to_have_count(50)
        await p.locator("#load-more").click()
        await expect(p.locator(".job-row")).to_have_count(55)
        await expect(p.locator("#load-more")).to_be_hidden()
        ids = await p.locator(".job-row .uuid").all_text_contents()
        assert len(set(ids)) == 55
        await p.locator("#lookup-id").fill(ids[-1])
        await p.locator("#job-lookup button").click()
        await expect(p.locator("#job-detail")).to_contain_text(ids[-1])
        await p.locator("#lookup-id").fill(str(UUID(int=999)))
        await p.locator("#job-lookup button").click()
        await expect(p.locator("#notice")).to_contain_text("未找到")

    async def validation_creation(self):
        p = await self.fresh()
        await p.locator(".create-panel summary").click()
        await p.locator("#import-job").set_input_files(
            {"name": "bad.json", "mimeType": "application/json", "buffer": b"{bad"}
        )
        await expect(p.locator("#notice")).to_contain_text("无法解析 JSON")
        bad = dict(SPEC, profile_revision="not-a-digest")
        await p.locator("#import-job").set_input_files(
            {
                "name": "bad-revision.json",
                "mimeType": "application/json",
                "buffer": json.dumps(bad).encode(),
            }
        )
        await expect(p.locator("#notice")).to_contain_text("64 位小写")
        for invalid_time in ("2026-02-30T00:00:00Z", "2026-10-19T00:00:00.123Z"):
            bad_time = dict(SPEC, not_before=invalid_time)
            await p.locator("#import-job").set_input_files(
                {
                    "name": "bad-time.json",
                    "mimeType": "application/json",
                    "buffer": json.dumps(bad_time).encode(),
                }
            )
            await expect(p.locator("#notice")).to_have_class("notice error")
            await expect(p.locator('#job-form [name="profile_id"]')).to_have_value("")
        await p.locator(".create-panel summary").click()
        await self.imported()
        posts = []
        gate = asyncio.Event()

        async def slow_post(route):
            if route.request.method == "POST":
                posts.append(route.request)
                await gate.wait()
            await route.continue_()

        await p.route("**/api/v1/jobs", slow_post)
        await p.locator("#create-job").dblclick()
        await expect(p.locator("#create-job")).to_be_disabled()
        # The browser's second pointer click must not submit another request.
        gate.set()
        await expect(p.locator("#job-detail")).to_be_visible()
        assert len(posts) == 1, "Double submit created more than one request"
        assert posts[0].post_data_json["mode"] == "simulation"
        await expect(p.locator("#creation-state")).to_contain_text("任务已创建")

    async def ambiguous_retry(self, fault="network"):
        p = await self.fresh()
        await self.imported()
        seen, persisted_ids = [], []
        retry_started, retry_release = asyncio.Event(), asyncio.Event()

        async def lose_response(route):
            if route.request.method != "POST":
                await route.continue_()
                return
            seen.append((route.request.headers.get("idempotency-key"), route.request.post_data))
            response = await route.fetch()
            persisted_ids.append((await response.json())["job_id"])
            if len(seen) == 1:
                # The real API persisted intent before the transport corrupts its response.
                if fault == "malformed":
                    await route.fulfill(status=201, json={})
                elif fault == "server_error":
                    await route.fulfill(status=500, json={"error": {"code": "unknown"}})
                else:
                    await route.abort("failed")
            else:
                retry_started.set()
                await retry_release.wait()
                await route.fulfill(response=response)

        await p.route("**/api/v1/jobs", lose_response)
        await p.locator("#create-job").click()
        await expect(p.locator("#create-job")).to_have_text("用同一请求重试")
        await expect(p.locator("#job-fields")).to_be_disabled()
        await expect(p.locator("#import-job")).to_be_disabled()
        await p.locator("#create-job").click()
        await asyncio.wait_for(retry_started.wait(), 10)
        await expect(p.locator("#reset-creation")).to_be_disabled()
        await p.locator("#reset-creation").click(force=True)
        await expect(p.locator("#confirm-dialog")).to_be_hidden()
        await expect(p.locator("#job-fields")).to_be_disabled()
        retry_release.set()
        await expect(p.locator("#creation-state")).to_contain_text("任务已创建")
        assert len(seen) == 2 and seen[0] == seen[1] and seen[0][0]
        assert len(set(persisted_ids)) == 1, "Retry created a different task"
        await expect(p.locator("#job-detail")).to_contain_text(persisted_ids[0])

    async def rejected_creation_edit(self):
        p = await self.fresh()
        await self.imported()
        seen = []

        async def reject_first(route):
            if route.request.method != "POST":
                await route.continue_()
                return
            seen.append((route.request.headers.get("idempotency-key"), route.request.post_data))
            if len(seen) == 1:
                await route.fulfill(status=422, json={"error": {"code": "invalid_input"}})
            else:
                await route.continue_()

        await p.route("**/api/v1/jobs", reject_first)
        await p.locator("#create-job").click()
        await expect(p.locator("#notice")).to_contain_text("输入不符合协议")
        await expect(p.locator("#job-fields")).to_be_enabled()
        await expect(p.locator("#import-job")).to_be_enabled()
        await p.locator('#job-form [name="profile_revision"]').fill("c" * 64)
        await p.locator("#create-job").click()
        await expect(p.locator("#creation-state")).to_contain_text("任务已创建")
        assert len(seen) == 2 and seen[0][0] != seen[1][0] and seen[0][1] != seen[1][1]

    async def cancel_dialog(self):
        p = await self.fresh()
        await p.locator(".job-row button").first.click()
        await p.locator("#cancel-job").click()
        await expect(p.locator("#confirm-dialog")).to_be_visible()
        await expect(p.locator("#confirm-back")).to_be_focused()
        await p.keyboard.press("Escape")
        await expect(p.locator("#confirm-dialog")).to_be_hidden()
        assert not [r for r in self.requests if r.method == "POST" and r.url.endswith("/cancel")]
        await p.locator("#cancel-job").click()
        await p.locator("#confirm-accept").click()
        await expect(p.locator("#job-detail .chip")).to_have_text("已取消")
        assert (
            len([r for r in self.requests if r.method == "POST" and r.url.endswith("/cancel")]) == 1
        )

    async def devices_schedules(self):
        p = await self.fresh()
        await expect(p.locator("#devices-list")).to_contain_text("能力未知")
        await p.locator("#devices details summary").click()
        await p.locator('#device-form [name="device_id"]').fill(str(UUID(int=50)))
        await p.locator('#device-form [name="agent_id"]').fill(AGENT_ID)
        await p.locator("#device-form button").click()
        await p.locator("#confirm-accept").click()
        await expect(p.locator("#devices-list")).to_contain_text(str(UUID(int=50)))
        for label, result in (("启用日程", "已启用"), ("暂停日程", "已暂停")):
            await p.locator("#schedules-list").get_by_role("button", name=label).click()
            await p.locator("#confirm-accept").click()
            await expect(p.locator("#schedules-list .chip")).to_have_text(result)

    async def resume_conflict_xss(self):
        p = await self.fresh()
        response = await self.context.request.get(
            self.origin + "/api/v1/jobs?limit=1", headers={"Authorization": "Bearer " + TOKEN}
        )
        job = (await response.json())["items"][0]
        job.update(
            state="needs_attention",
            resume_phase="preflight",
            reason_code='<img src=x onerror="window.happyrun_xss=1">',
            revision=8,
            desired_state="run",
        )
        path = "**/api/v1/jobs/" + job["job_id"]
        await p.route(path, lambda route: route.fulfill(json=job))
        await p.locator("#lookup-id").fill(job["job_id"])
        await p.locator("#job-lookup button").click()
        await expect(p.locator("#job-detail")).to_contain_text(job["reason_code"])
        assert await p.locator("#job-detail img").count() == 0
        assert await p.evaluate("window.happyrun_xss === undefined")
        sent = []

        async def conflict(route):
            sent.append(route.request.post_data_json)
            await route.fulfill(status=409, json={"error": {"code": "revision_conflict"}})

        await p.route(path + "/resume", conflict)
        await p.locator("#resume-job").click()
        await p.locator("#confirm-accept").click()
        await expect(p.locator("#notice")).to_contain_text("状态或版本冲突")
        assert sent == [{"expected_revision": 8, "action": "verify_only"}]

    async def stale_401(self):
        p = await self.fresh()
        started, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def delayed_jobs(route):
            response = await route.fetch()
            started.set()
            await release.wait()
            try:
                await route.fulfill(response=response)
            except Exception:
                pass  # Logout aborts the old transport, which is an expected result.
            finally:
                finished.set()

        await p.route("**/api/v1/jobs?*", delayed_jobs)
        await p.route(
            "**/api/v1/devices",
            lambda route: route.fulfill(status=401, json={"error": {"code": "unauthorized"}}),
        )
        await p.locator("#refresh-jobs").click()
        await asyncio.wait_for(started.wait(), 10)
        await p.locator("#refresh-devices").click()
        await expect(p.locator("#workspace")).to_be_hidden()
        release.set()
        await asyncio.wait_for(finished.wait(), 10)
        await expect(p.locator("#notice")).to_contain_text("私有内容已清除")
        await expect(p.locator("#jobs-list")).to_be_empty()
        await expect(p.locator("#devices-list")).to_be_empty()
        await expect(p.locator("#token")).to_have_value("")
        assert await p.evaluate("localStorage.length + sessionStorage.length") == 0

    async def loading_empty_error_offline(self):
        p = await self.fresh()
        started, release = asyncio.Event(), asyncio.Event()

        async def delayed_empty(route):
            started.set()
            await release.wait()
            await route.fulfill(json={"items": [], "next_cursor": None})

        await p.route("**/api/v1/jobs?*", delayed_empty)
        await p.locator("#refresh-jobs").click()
        await asyncio.wait_for(started.wait(), 10)
        await expect(p.locator("#jobs-list")).to_contain_text("正在加载")
        release.set()
        await expect(p.locator("#jobs-list")).to_contain_text("还没有任务")
        await p.unroute("**/api/v1/jobs?*", delayed_empty)
        await p.route(
            "**/api/v1/jobs?*",
            lambda route: route.fulfill(status=503, json={"error": {"code": "unavailable"}}),
        )
        await p.locator("#refresh-jobs").click()
        await expect(p.locator("#jobs-list")).to_contain_text("任务加载失败")
        await expect(p.locator("#notice")).to_contain_text("暂时不可用")
        await self.context.set_offline(True)
        await expect(p.locator("#notice")).to_contain_text("离线")
        await self.context.set_offline(False)

    async def run(self):
        for name, action in [
            ("auth, token hygiene, keyboard, desktop/mobile layout, logout", self.auth_and_layout),
            ("55-job pagination and UUID lookup", self.pagination_lookup),
            (
                "JSON validation, import, simulation creation, duplicate click",
                self.validation_creation,
            ),
            (
                "persisted request / lost response retries exact same idempotency key",
                self.ambiguous_retry,
            ),
            (
                "persisted intent / malformed 201 keeps key and body",
                lambda: self.ambiguous_retry("malformed"),
            ),
            (
                "persisted intent / unknown 500 keeps key and body",
                lambda: self.ambiguous_retry("server_error"),
            ),
            ("known 422 unlocks editable form and new submission", self.rejected_creation_edit),
            ("cancel confirmation focus, Escape, successful cancellation", self.cancel_dialog),
            ("synthetic device registration and schedule enable/disable", self.devices_schedules),
            (
                "XSS remains text and resume revision conflict has no retry",
                self.resume_conflict_xss,
            ),
            ("401 clears private state and stale response cannot restore it", self.stale_401),
            ("loading, empty, error and offline states", self.loading_empty_error_offline),
        ]:
            await self.check(name, action)
        if self.context:
            await self.context.close()
        return self.results


async def exercise(origin, output):
    async with async_playwright() as playwright:
        options = {"headless": True}
        if os.environ.get("HAPPYRUN_CHROMIUM_EXECUTABLE"):
            options["executable_path"] = os.environ["HAPPYRUN_CHROMIUM_EXECUTABLE"]
        browser = await playwright.chromium.launch(**options)
        print("Chromium " + browser.version, flush=True)
        try:
            return await Suite(browser, origin, output).run()
        finally:
            await browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("browser-evidence"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="happyrun-browser-") as tmp:
        app = create_app(
            ServerSettings(
                database_path=Path(tmp) / "qa.sqlite3",
                admin_token=TOKEN,
                agent_tokens={AGENT_ID: "synthetic-agent-only"},
            ),
            clock=FixedClock(),
        )
        app.state.store.register_device(DeviceRegistration(device_id=DEVICE_ID, agent_id=AGENT_ID))
        for index in range(55):
            app.state.store.create(
                JobSpec.model_validate_json(json.dumps(SPEC)), f"synthetic-seed-{index}"
            )
        app.state.scheduler.create(
            ScheduleSpec.model_validate_json(
                json.dumps(
                    {
                        "schedule_id": str(UUID(int=20)),
                        "job_template": SPEC,
                        "timezone": "Asia/Shanghai",
                        "local_time": "20:00",
                        "weekdays": [1, 2, 3, 4, 5],
                        "enabled": False,
                    }
                )
            )
        )
        # Bind once and pass the socket into Uvicorn; no choose-then-bind port race.
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level="warning"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        origin = f"http://127.0.0.1:{port}"
        try:
            for _ in range(100):
                if server.started:
                    break
                time.sleep(0.05)
            assert server.started, "Temporary API did not start"
            with urllib.request.urlopen(origin + "/api/v1/health", timeout=5) as response:
                assert response.status == 200
            results = asyncio.run(exercise(origin, args.output_dir))
            (args.output_dir / "results.json").write_text(
                json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            failures = sum(result["status"] != "passed" for result in results)
            print(
                f"BROWSER_RESULT {len(results) - failures} passed / {failures} failed", flush=True
            )
            return 1 if failures else 0
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            sock.close()
            assert not thread.is_alive(), "Temporary server failed to stop"


if __name__ == "__main__":
    raise SystemExit(main())
