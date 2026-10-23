"""Loopback desktop surface; independent of public ADMIN/AGENT bearer APIs."""

import asyncio
import secrets
from contextlib import asynccontextmanager
from importlib.resources import files
from threading import Lock

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from swu_happyrun.core.models import DeviceRegistration, JobSpec, ResumeRequest, RouteProfile
from swu_happyrun.desktop.mumu import TrajectoryController
from swu_happyrun.desktop.worker import DesktopWorker
from swu_happyrun.server.app import create_app
from swu_happyrun.server.errors import ApiError
from swu_happyrun.server.settings import ServerSettings

PREFIX = "/api/v1/desktop"
COOKIE = "happyrun_desktop"


class Bootstrap(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    nonce: str


class MuMuConnect(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    instance_index: str = Field(pattern=r"^[0-9]{1,8}$")


class MuMuRoute(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    route: RouteProfile


class MuMuStart(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    speed_mps: float = Field(ge=0.3, le=8, allow_inf_nan=False)
    maximum_duration_seconds: float = Field(ge=5, le=1800, allow_inf_nan=False)


def create_desktop_app(workspace, *, port):
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("desktop_port_invalid")
    agent_token = secrets.token_urlsafe(32)
    app = create_app(
        ServerSettings(
            database_path=workspace.root / "server.sqlite",
            admin_token=secrets.token_urlsafe(32),
            agent_tokens={workspace.agent_id: agent_token},
            bind_host="127.0.0.1",
            port=port,
        )
    )
    registration = DeviceRegistration(device_id=workspace.device_id, agent_id=workspace.agent_id)
    existing = app.state.store.list_devices()
    if registration.model_dump(mode="json") not in existing:
        app.state.store.register_device(registration)
    app.state.desktop_nonce = secrets.token_urlsafe(32)
    session = secrets.token_urlsafe(32)
    bootstrap_lock = Lock()
    bootstrap_consumed = False
    origin = f"http://127.0.0.1:{port}"
    worker = DesktopWorker(workspace, port, agent_token)
    mumu = TrajectoryController()
    app.state.desktop_worker = worker
    app.state.mumu_controller = mumu
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app):
        async with original_lifespan(app):
            worker.start()
            try:
                yield
            finally:
                await asyncio.to_thread(mumu.close)
                await asyncio.to_thread(worker.close)

    app.router.lifespan_context = lifespan

    def authorize(request, *, bootstrap=False):
        if request.headers.get("host") != f"127.0.0.1:{port}":
            raise ApiError(403, "local_origin_required", "Local session required")
        if request.method != "GET" and request.headers.get("origin") != origin:
            raise ApiError(403, "local_origin_required", "Local session required")
        value = request.cookies.get(COOKIE, "")
        if not bootstrap and not secrets.compare_digest(value.encode(), session.encode()):
            raise ApiError(401, "local_session_required", "Open this workstation from the launcher")

    def own_job(job_id):
        job = app.state.store.get(job_id)
        if job is None or job.spec.device_id != workspace.device_id:
            raise ApiError(404, "not_found", "Resource not found")
        return job

    def asset(name, media_type):
        return Response(
            files("swu_happyrun.desktop").joinpath("web", name).read_bytes(), media_type=media_type
        )

    @app.get("/desktop/")
    def index():
        return asset("index.html", "text/html")

    @app.get("/desktop/app.js")
    def script():
        return asset("app.js", "text/javascript")

    @app.get("/desktop/styles.css")
    def style():
        return asset("styles.css", "text/css")

    @app.get("/desktop/mumu.js")
    def mumu_script():
        return asset("mumu.js", "text/javascript")

    @app.post(PREFIX + "/session")
    def bootstrap(body: Bootstrap, request: Request):
        nonlocal bootstrap_consumed
        authorize(request, bootstrap=True)
        with bootstrap_lock:
            if bootstrap_consumed or not secrets.compare_digest(
                body.nonce.encode(), app.state.desktop_nonce.encode()
            ):
                raise ApiError(401, "bootstrap_expired", "Reopen from the local launcher")
            bootstrap_consumed = True
        response = JSONResponse({"status": "connected"})
        response.set_cookie(COOKIE, session, httponly=True, samesite="strict", path=PREFIX)
        return response

    @app.get(PREFIX + "/workspace")
    def status(request: Request):
        authorize(request)
        with app.state.store.connection() as database:
            database.execute("SELECT 1").fetchone()
        jobs, _ = app.state.store.list_jobs(100, None)
        ticker = getattr(app.state, "ticker", None)
        return {
            "mode": "simulation",
            "record_verified": False,
            "device_verified": False,
            "worker_status": worker.status,
            "worker_alive": worker.thread.is_alive(),
            "service_ready": bool(ticker and ticker.is_alive() and app.state.scheduler_healthy),
            "job_template": workspace.job_spec().model_dump(mode="json"),
            "jobs": [job for job in jobs if job.spec.device_id == workspace.device_id],
            "native_execution": "enrollment_execution_not_ready",
        }

    @app.post(PREFIX + "/jobs")
    def create(spec: JobSpec, request: Request):
        authorize(request)
        expected = workspace.job_spec()
        for field in (
            "mode",
            "device_id",
            "profile_id",
            "profile_revision",
            "route_id",
            "route_revision",
            "expected_app_version",
        ):
            if getattr(spec, field) != getattr(expected, field):
                raise ApiError(422, "desktop_simulation_only", "Use the local simulation template")
        job, created = app.state.store.create(spec, request.headers.get("idempotency-key", ""))
        return JSONResponse(job.model_dump(mode="json"), status_code=201 if created else 200)

    @app.post(PREFIX + "/jobs/{job_id}/cancel")
    def cancel(job_id: str, request: Request):
        authorize(request)
        own_job(job_id)
        return app.state.store.cancel(job_id)

    @app.post(PREFIX + "/jobs/{job_id}/stop")
    def recover_stop(job_id: str, body: ResumeRequest, request: Request):
        authorize(request)
        own_job(job_id)
        if body.action != "stop_only":
            raise ApiError(
                422, "stop_only_required", "Only an explicit controlled stop is available"
            )
        return app.state.store.resume(job_id, body.expected_revision, body.action)

    @app.get(PREFIX + "/mumu")
    def mumu_status(request: Request):
        authorize(request)
        return mumu.snapshot()

    def mumu_submit(action, request, **values):
        authorize(request)
        try:
            mumu.submit(action, **values)
        except ValueError as error:
            code = str(error)
            allowed = {
                "invalid_mumu_state",
                "mumu_busy",
                "controller_closed",
                "route_required",
                "route_revision_mismatch",
                "route_too_large",
                "calibration_points_too_close",
                "invalid_route_duration",
                "invalid_route_speed",
            }
            raise ApiError(
                409,
                code if code in allowed else "route_invalid",
                "Refresh the local MuMu state before another action",
            ) from None
        return JSONResponse({"state": mumu.snapshot()["state"]}, status_code=202)

    @app.post(PREFIX + "/mumu/connect")
    def mumu_connect(body: MuMuConnect, request: Request):
        return mumu_submit("connect", request, instance_index=body.instance_index)

    @app.post(PREFIX + "/mumu/route")
    def mumu_route(body: MuMuRoute, request: Request):
        return mumu_submit("route", request, route=body.route)

    @app.post(PREFIX + "/mumu/calibrate")
    def mumu_calibrate(request: Request):
        return mumu_submit("calibrate", request)

    @app.post(PREFIX + "/mumu/start")
    def mumu_start(body: MuMuStart, request: Request):
        return mumu_submit("start", request, **body.model_dump())

    @app.post(PREFIX + "/mumu/{action}")
    def mumu_action(action: str, request: Request):
        if action not in {"pause", "resume", "stop"}:
            raise ApiError(404, "not_found", "Resource not found")
        return mumu_submit(action, request)

    return app
