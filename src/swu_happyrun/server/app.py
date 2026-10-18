"""FastAPI factory with redacted, protocol-shaped errors."""

from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from swu_happyrun.core.clock import Clock, SystemClock
from swu_happyrun.server.auth import Authenticator
from swu_happyrun.server.errors import ApiError
from swu_happyrun.server.routes import agents, jobs
from swu_happyrun.server.settings import ServerSettings
from swu_happyrun.server.store import SqliteJobStore


def create_app(settings: ServerSettings, *, clock: Clock | None = None) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.clock = clock if clock is not None else SystemClock()
    app.state.auth = Authenticator(settings)
    app.state.store = SqliteJobStore(settings.database_path, app.state.clock)

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

    app.include_router(jobs.router, prefix="/api/v1")
    app.include_router(agents.router, prefix="/api/v1")
    return app
