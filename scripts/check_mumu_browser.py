"""Real Chromium panel QA with intercepted synthetic MuMu receipts; no device operations."""

import argparse
import json
import socket
import tempfile
import threading
import time
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import uvicorn
from playwright.sync_api import expect, sync_playwright

from swu_happyrun.desktop.app import create_desktop_app
from swu_happyrun.desktop.workspace import Workspace


class NoDeviceController:
    """Replace the production constructor even though every MuMu request is intercepted."""

    def close(self):
        pass

    def __getattr__(self, name):
        raise AssertionError(f"Browser QA must not call a MuMu controller: {name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    counts = Counter()
    errors = []
    cases = []
    # Explicit synthetic browser fixture: these are not campus coordinates or a real route.
    route_profile = {
        "route_id": "00000000-0000-4000-8000-000000000000",
        "revision": "a" * 64,
        "input_crs": "WGS84",
        "source_ref": "synthetic-browser-fixture-only",
        "points": [
            {"latitude": 0.0, "longitude": 0.0},
            {"latitude": 0.0002, "longitude": 0.0004},
            {"latitude": 0.0005, "longitude": 0.0003},
            {"latitude": 0.0001, "longitude": 0.00005},
        ],
    }
    state = {
        "state": "disconnected",
        "error_code": None,
        "instances": [
            {"index": "5", "name": "浏览器测试实例", "running": True, "android_version": "15"}
        ],
        "instance_index": None,
        "host_version": "6.8.4.0",
        "android_api": 35,
        "device_verified": False,
        "record_verified": False,
        "route": None,
        "progress": None,
        "sample": None,
        "writes": 0,
        "max_error_m": None,
        "stop_confirmed": False,
        "observation_state": None,
    }
    unauthorized_once = True
    fail_start = False

    def intercept(request_route):
        nonlocal unauthorized_once
        request = request_route.request
        operation = request.url.split("/mumu", 1)[1]
        if request.method == "GET":
            if unauthorized_once:
                unauthorized_once = False
                request_route.fulfill(status=401, json={"error": {"code": "session_required"}})
            else:
                request_route.fulfill(json=state)
            return
        counts[operation] += 1
        body = request.post_data_json
        if operation == "/connect":
            assert body == {"instance_index": "5"}
            state.update(state="connecting", instance_index="5")
        elif operation == "/route":
            assert body["route"] == route_profile
            state.update(route=body["route"], device_verified=False)
        elif operation == "/calibrate":
            state.update(state="calibrating")
        elif operation == "/start":
            assert body == {"speed_mps": 2, "maximum_duration_seconds": 120}
            if fail_start:
                request_route.fulfill(status=503, json={"error": {"code": "device_locked"}})
                return
            state.update(state="running", stop_confirmed=False)
        elif operation == "/pause":
            state.update(state="paused")
        elif operation == "/resume":
            state.update(state="running")
        elif operation == "/stop":
            state.update(state="stopping", stop_confirmed=False)
        else:
            raise AssertionError(f"Unexpected MuMu operation: {operation}")
        request_route.fulfill(status=202, json={"status": "accepted", "state": state["state"]})

    def no_overflow(page):
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")

    with tempfile.TemporaryDirectory(prefix="happyrun-mumu-browser-") as temp:
        workspace = Workspace.open(Path(temp) / "workspace")
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        with patch("swu_happyrun.desktop.app.TrajectoryController", NoDeviceController):
            app = create_desktop_app(workspace, port=port)
        assert isinstance(app.state.mumu_controller, NoDeviceController)
        server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level="error"))
        thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page(viewport={"width": 1440, "height": 1100})
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.route("**/api/v1/desktop/mumu**", intercept)
                page.goto(f"http://127.0.0.1:{port}/desktop/#" + app.state.desktop_nonce)
                expect(page.locator("#connection")).to_have_text("本机已连接")
                expect(page.locator("#mumu-state")).to_have_text("尚未连接")
                expect(page.locator("#mumu-notice")).to_be_hidden()
                expect(page.locator("#mumu-connect")).to_be_enabled()
                expect(page.locator("#mumu-start")).to_be_disabled()
                assert "#" not in page.url
                cases.append("real_session_bootstrap_and_silent_initial_401")
                page.locator("#mumu-connect").click()
                expect(page.locator("#mumu-state")).to_have_text("正在连接")
                state.update(state="connected", observation_state="observing")
                expect(page.locator("#mumu-state")).to_have_text("实例已连接")
                page.locator("#mumu-route-file").set_input_files(
                    {
                        "name": "synthetic-browser-fixture.json",
                        "mimeType": "application/json",
                        "buffer": json.dumps(route_profile).encode(),
                    }
                )
                expect(page.locator("#mumu-route-info")).to_contain_text("4 个路点")
                expect(page.locator("#mumu-calibrate")).to_be_enabled()
                assert page.locator(".mumu-route-line").get_attribute("points")
                cases.append("instance_selection_private_file_import_and_local_svg")
                page.locator("#mumu-calibrate").click()
                expect(page.locator("#mumu-state")).to_have_text("正在校准")
                expect(page.locator("#mumu-start")).to_be_disabled()
                expect(page.locator("#mumu-stop")).to_be_enabled()
                page.wait_for_timeout(5500)
                expect(page.locator("#mumu-notice")).to_be_hidden()
                assert counts["/calibrate"] == 1
                cases.append("async_calibration_beyond_request_timeout_without_retry")
                state.update(
                    state="ready",
                    device_verified=True,
                    max_error_m=0.8,
                    sample={"latitude": 0.0, "longitude": 0.0, "accuracy": 2.0},
                )
                expect(page.locator("#mumu-start")).to_be_enabled()
                expect(page.locator("#mumu-observation")).to_have_text("正在观察")
                page.locator("#mumu-start").dblclick(force=True)
                expect(page.locator("#mumu-state")).to_have_text("轨迹运行中")
                assert counts["/start"] == 1
                state.update(
                    writes=8,
                    progress={
                        "distance_m": 24.0,
                        "total_distance_m": 120.0,
                        "progress": 0.2,
                        "elapsed_seconds": 12,
                        "speed_mps": 2,
                    },
                    sample={"latitude": 0.0002, "longitude": 0.0004, "accuracy": 2.0},
                )
                expect(page.locator("#mumu-distance")).to_have_text("24.0 / 120.0 m")
                expect(page.locator("#mumu-progress")).to_have_attribute("value", "0.2")
                expect(page.locator(".mumu-readback-marker")).to_have_attribute(
                    "visibility", "visible"
                )
                no_overflow(page)
                page.screenshot(path=str(args.output / "mumu-desktop-running.png"), full_page=True)
                cases.append("double_click_single_start_and_actual_readback_progress")
                page.locator("#mumu-pause").click()
                expect(page.locator("#mumu-state")).to_have_text("已暂停")
                page.locator("#mumu-resume").click()
                expect(page.locator("#mumu-state")).to_have_text("轨迹运行中")
                cases.append("explicit_pause_and_resume")
                state.update(state="needs_attention", error_code="location_write_uncertain")
                expect(page.locator("#mumu-state")).to_have_text("需要处理")
                expect(page.locator("#mumu-detail")).to_contain_text("关闭选定 MuMu")
                expect(page.locator("#mumu-stop")).to_be_enabled()
                assert counts["/start"] == 1
                page.set_viewport_size({"width": 390, "height": 844})
                no_overflow(page)
                page.screenshot(path=str(args.output / "mumu-mobile-attention.png"), full_page=True)
                cases.append("attention_recovery_and_390_mobile_without_overflow")
                page.locator("#mumu-stop").click()
                expect(page.locator("#mumu-state")).to_have_text("等待停止确认")
                state.update(state="stopped", stop_confirmed=False, error_code=None)
                expect(page.locator("#mumu-state")).to_have_text("停止待确认")
                expect(page.locator("#mumu-route-file")).to_be_disabled()
                state.update(stop_confirmed=True)
                expect(page.locator("#mumu-state")).to_have_text("已确认停止")
                expect(page.locator("#mumu-start")).to_be_disabled()
                cases.append("stopping_requires_explicit_stop_confirmed_receipt")
                state.update(
                    route={**route_profile, "input_crs": "GCJ02"},
                    state="ready",
                    stop_confirmed=False,
                )
                expect(page.locator("#mumu-map-note")).to_have_text("坐标基准不同，读回单独显示")
                expect(page.locator(".mumu-readback-marker")).to_have_attribute(
                    "visibility", "hidden"
                )
                fail_start = True
                page.locator("#mumu-start").click()
                expect(page.locator("#mumu-notice")).to_contain_text("device_locked")
                expect(page.locator("#mumu-start")).to_be_disabled()
                expect(page.locator("#mumu-stop")).to_be_enabled()
                page.wait_for_timeout(1500)
                assert counts["/start"] == 2
                cases.append("crs_separation_and_unknown_start_error_without_retry")
                expect(page.locator("#start")).to_be_enabled(timeout=15000)
                page.locator("#start").click()
                expect(page.locator("#job-state")).to_have_text("模拟完成", timeout=30000)
                expect(page.locator(".history-row")).to_have_count(1)
                cases.append("existing_simulation_remains_functional")
                assert not errors, errors
                browser.close()
        finally:
            server.should_exit = True
            thread.join(12)
            sock.close()
            assert not thread.is_alive()
            assert not app.state.desktop_worker.thread.is_alive()
        report = {
            "status": "passed",
            "cases": cases,
            "mutation_counts": dict(counts),
            "browser": "Chromium",
            "desktop_viewport": [1440, 1100],
            "mobile_viewport": [390, 844],
            "javascript_errors": errors,
            "mumu_api": "intercepted_synthetic_receipts_only",
            "production_controller_instantiated": False,
            "device_verified": False,
            "record_verified": False,
            "server_and_worker_stopped": True,
        }
        (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report))


if __name__ == "__main__":
    main()
