"""Ordinary-user loopback launch with one-time, fragment-only browser bootstrap."""

import os
from pathlib import Path
from threading import Thread


def run(*, root=None, port=8765, open_browser=True):
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("desktop_port_invalid")
    import uvicorn

    from swu_happyrun.desktop.app import create_desktop_app
    from swu_happyrun.desktop.workspace import Workspace

    if root is None:
        if os.name == "nt":
            from swu_happyrun.drivers.mumu.enrollment import _local_app_data

            root = _local_app_data() / "HappyRunDesktop"
        else:
            root = Path.home() / ".happyrun-desktop"
    workspace = Workspace.open(root)
    app = create_desktop_app(workspace, port=port)

    def show():
        import webbrowser

        try:
            # The one-time nonce is never an ADMIN token. The page erases it from
            # history before any request. No URL/nonce is printed or access-logged.
            webbrowser.open(f"http://127.0.0.1:{port}/desktop/#" + app.state.desktop_nonce)
        except Exception:
            pass  # The service remains available if the browser cannot launch.

    class DesktopServer(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets=sockets)
            if self.started and open_browser:
                Thread(target=show, name="happyrun-desktop-browser", daemon=True).start()

    print(f"HappyRun local workstation: http://127.0.0.1:{port}/desktop/", flush=True)
    print(
        "Local simulation and calibrated MuMu tool. Ctrl+C requests a controlled stop.", flush=True
    )
    DesktopServer(
        uvicorn.Config(app, host="127.0.0.1", port=port, access_log=False, log_level="warning")
    ).run()
    return 0
