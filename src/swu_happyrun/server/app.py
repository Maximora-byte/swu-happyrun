"""FastAPI factory with redacted, protocol-shaped errors."""

import asyncio
from contextlib import asynccontextmanager
from threading import Event, Thread
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from swu_happyrun.core.clock import Clock, SystemClock
from swu_happyrun.server.auth import Authenticator
from swu_happyrun.server.errors import ApiError
from swu_happyrun.server.routes import agents, jobs, leases, schedules
from swu_happyrun.server.scheduler import Scheduler
from swu_happyrun.server.settings import ServerSettings
from swu_happyrun.server.store import SqliteJobStore


def create_app(settings: ServerSettings, *, clock: Clock | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        stop = Event()

        def tick_loop():
            while not stop.is_set():
                try:
                    app.state.scheduler.tick()
                    app.state.scheduler_healthy = True
                except Exception:
                    # Keep retrying transient storage failures; never log data or credentials.
                    app.state.scheduler_healthy = False
                stop.wait(1.0)

        app.state.ticker = Thread(target=tick_loop, name="happyrun-scheduler", daemon=True)
        app.state.ticker.start()
        try:
            yield
        finally:
            stop.set()
            await asyncio.to_thread(app.state.ticker.join)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.clock = clock if clock is not None else SystemClock()
    app.state.auth = Authenticator(settings)
    app.state.store = SqliteJobStore(settings.database_path, app.state.clock)

    app.state.scheduler = Scheduler(app.state.store, app.state.clock)
    app.state.scheduler_healthy = True

    def error_response(status: int, code: str, message: str, retryable: bool = False):
        return JSONResponse(
            status_code=status,
            content={
                "error": {"code": code, "message": message, "retryable": retryable},
                "request_id": str(uuid4()),
            },
            headers={"WWW-Authenticate": "Bearer"} if status == 401 else None,
        )

    @app.middleware("http")
    async def safe_failures(request: Request, call_next):
        try:
            return await call_next(request)
        except Exception:
            # Do not forward exception details to ASGI's logging layer.
            return error_response(500, "internal_error", "Internal server error")

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        return error_response(exc.status, exc.code, exc.message, exc.retryable)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return error_response(422, "invalid_input", "Request does not match the protocol")

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return error_response(exc.status_code, "http_error", "Request not supported")

    @app.get("/api/v1/health")
    def health():
        return {"status": "ok", "protocol_version": 1}

    @app.get("/api/v1/ready")
    def ready():
        ticker = getattr(app.state, "ticker", None)
        if not app.state.scheduler_healthy or ticker is None or not ticker.is_alive():
            raise ApiError(503, "not_ready", "Service temporarily unavailable", True)
        with app.state.store.connection() as db:
            db.execute("SELECT 1").fetchone()
        return {"status": "ready", "protocol_version": 1}

    app.include_router(jobs.router, prefix="/api/v1")
    app.include_router(agents.router, prefix="/api/v1")
    app.include_router(leases.router, prefix="/api/v1")
    app.include_router(schedules.router, prefix="/api/v1")
    return app
