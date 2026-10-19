"""Public, credential-free console shell with a fixed packaged-asset allowlist."""

from importlib.resources import files

from fastapi import APIRouter
from fastapi.responses import RedirectResponse, Response

router = APIRouter()

SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
        "img-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; "
        "frame-ancestors 'none'"
    ),
}


def _asset(name: str, media_type: str) -> Response:
    content = files("swu_happyrun.server").joinpath("web", name).read_bytes()
    return Response(content=content, media_type=media_type)


@router.get("/")
def root():
    return RedirectResponse("/console/", status_code=307)


@router.get("/console/")
def console():
    return _asset("index.html", "text/html")


@router.get("/console/app.js")
def script():
    return _asset("app.js", "text/javascript")


@router.get("/console/styles.css")
def stylesheet():
    return _asset("styles.css", "text/css")


def browser_url(host: str, port: int) -> str:
    """Do not turn a wildcard/public listener into a browser navigation target."""
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Opening a browser requires an explicit loopback host")
    if not 1 <= port <= 65535:
        raise ValueError("Invalid browser target port")
    authority = "[::1]" if host == "::1" else host
    return f"http://{authority}:{port}/console/"


def run_with_browser(app, *, host: str, port: int) -> None:
    import logging
    import webbrowser
    from threading import Thread

    import uvicorn

    url = browser_url(host, port)

    def open_console():
        try:
            opened = webbrowser.open(url)
        except Exception:
            # Browser availability cannot bring down a healthy control plane.
            opened = False
        if not opened:
            logging.getLogger("uvicorn.error").warning(
                "Browser could not be opened; open the local console URL manually"
            )

    class ConsoleServer(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets=sockets)
            if self.started:
                # A platform browser launcher may never return. It is a convenience
                # action, not server work: do not await it or join it on shutdown.
                Thread(target=open_console, name="happyrun-browser", daemon=True).start()

    ConsoleServer(
        uvicorn.Config(app, host=host, port=port, access_log=False, log_level="info")
    ).run()
