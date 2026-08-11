"""Kerf desktop launcher — one process, one binary, no sidecar.

Boots ``kerf_core.app:create_app`` on uvicorn in a background daemon thread,
bound to an OS-assigned free port on 127.0.0.1 (never a hardcoded port),
waits for ``/health`` to answer, then opens a native OS webview window
(pywebview: WebView2 on Windows, WebKit on macOS/Linux — not a bundled
Chromium) pointed at that URL. When the window closes, the server is asked
to shut down and the launcher waits for it to actually stop before exiting.

Usage::

    kerf-desktop
    python -m kerf_desktop
"""
from __future__ import annotations

import logging
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger("kerf_desktop")

_HEALTH_TIMEOUT_S = 60.0
_HEALTH_POLL_INTERVAL_S = 0.15
_SHUTDOWN_JOIN_TIMEOUT_S = 10.0


def _free_port() -> int:
    """Bind to :0 on localhost and read back the OS-assigned free port.

    Never hardcode a port: two desktop instances (or anything else already
    listening) must not collide.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _resolve_frontend_dist() -> Path | None:
    """Locate the built frontend directory and return it, or None if absent.

    Frozen (PyInstaller one-file): the binary unpacks its ``--add-data``
    payload into a temp dir exposed at runtime as ``sys._MEIPASS``; the spec
    (packages/kerf-desktop/kerf-desktop.spec) places the built frontend there
    under ``web_dist/``.

    Unfrozen (running `kerf-desktop` from an installed/editable environment,
    e.g. to exercise this wiring without a full PyInstaller build): fall back
    to ``<repo>/web/dist`` relative to this source file, if it has been
    built (`npm run build` in web/).

    Returns None if neither is found; the caller sets KERF_FRONTEND_DIST
    only when a real directory exists, so kerf_core.app._mount_frontend's
    existing "skip if missing" behavior applies rather than pointing it at a
    directory that doesn't exist.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = Path(meipass) / "web_dist"
        if candidate.is_dir() and (candidate / "index.html").exists():
            return candidate
        logger.warning("kerf_desktop_frontend_missing_in_bundle path=%s", candidate)
        return None

    # Dev fallback: packages/kerf-desktop/src/kerf_desktop/main.py -> repo root
    # is four parents up (kerf_desktop -> src -> kerf-desktop -> packages -> root).
    dev_dist = Path(__file__).resolve().parents[4] / "web" / "dist"
    if dev_dist.is_dir() and (dev_dist / "index.html").exists():
        return dev_dist
    return None


def _wait_for_health(url: str, timeout_s: float = _HEALTH_TIMEOUT_S) -> None:
    """Poll ``url`` until it answers 200, or raise a clear error on timeout."""
    deadline = time.monotonic() + timeout_s
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:  # noqa: S310 (localhost only)
                if resp.status == 200:
                    return
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            last_error = exc
        time.sleep(_HEALTH_POLL_INTERVAL_S)
    raise RuntimeError(
        f"Kerf server did not answer {url} within {timeout_s:.0f}s — it "
        "never became healthy. It may have crashed on startup; check the "
        "logs above for a traceback." + (f" Last connection error: {last_error}" if last_error else "")
    )


def _run_server(server) -> None:
    try:
        server.run()
    except Exception:
        logger.exception("kerf_desktop_server_crashed")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    # Fail the boot if any plugin fails to register, rather than opening a
    # window onto a dead API. This shipped broken once: excluding pygit2 from
    # the frozen build made kerf-api's registration raise, so every /api route
    # vanished and the SPA fallback answered {"detail": "Not Found"} — while
    # the launcher reported a clean start and cheerfully opened the window.
    # A desktop user cannot read plugin logs; a hard failure with a real error
    # is far kinder than a UI where nothing works.
    os.environ.setdefault("KERF_STRICT_PLUGINS", "true")

    dist = _resolve_frontend_dist()
    if dist is not None:
        os.environ["KERF_FRONTEND_DIST"] = str(dist)
        logger.info("kerf_desktop_frontend_dist path=%s", dist)
    else:
        logger.warning(
            "kerf_desktop_no_frontend_dist — the API will run but no UI will be served; "
            "build web/dist (npm run build) or check the PyInstaller spec's --add-data."
        )

    # Zero-dependency by design: no DATABASE_URL means kerf_core.db.config
    # falls back to embedded SQLite at ~/.kerf/kerf.db (WAL, foreign keys
    # on). No Postgres server is required to run this binary.

    host = "127.0.0.1"
    port = _free_port()
    base_url = f"http://{host}:{port}"

    import uvicorn

    from kerf_core.app import create_app
    from kerf_core.bind import set_bind_host

    # Record the bind address before serving. The terminal and first-run setup
    # both refuse on a network-reachable bind and assume the worst when nobody
    # has said — so without this the desktop app, which is the most
    # loopback-only deployment there is, would be refused both.
    set_bind_host(host)

    config = uvicorn.Config(
        create_app,
        host=host,
        port=port,
        factory=True,
        log_level="info",
    )
    server = uvicorn.Server(config)

    server_thread = threading.Thread(
        target=_run_server, args=(server,), name="kerf-uvicorn", daemon=True
    )
    server_thread.start()

    try:
        _wait_for_health(f"{base_url}/health")
    except RuntimeError:
        server.should_exit = True
        server_thread.join(timeout=_SHUTDOWN_JOIN_TIMEOUT_S)
        raise

    logger.info("kerf_desktop_server_ready url=%s", base_url)

    import webview

    window = webview.create_window("Kerf", base_url)

    def _on_closed() -> None:
        logger.info("kerf_desktop_window_closed shutting_down_server")
        server.should_exit = True

    window.events.closed += _on_closed

    try:
        webview.start()
    finally:
        server.should_exit = True
        server_thread.join(timeout=_SHUTDOWN_JOIN_TIMEOUT_S)
        if server_thread.is_alive():
            logger.warning("kerf_desktop_server_did_not_stop_cleanly")


if __name__ == "__main__":
    main()
