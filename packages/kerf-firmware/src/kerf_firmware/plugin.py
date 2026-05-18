"""
kerf-firmware plugin registration.

Wires the firmware build/monitor routes and LLM tools into a Kerf plugin app.
The capability `firmware.build` is only advertised when PlatformIO Core CLI is
available on PATH (probed at startup). The HTTP routes are always mounted —
they return descriptive errors when PlatformIO is absent so the frontend can
show a helpful install prompt.
"""
from __future__ import annotations

import logging
import shutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


def _pio_available() -> bool:
    """Return True if PlatformIO Core CLI is on PATH."""
    return (
        shutil.which("pio") is not None
        or shutil.which("platformio") is not None
    )


async def register(app: "FastAPI", ctx):
    """Entry point called by the Kerf plugin loader."""
    # ── HTTP routes ──────────────────────────────────────────────────────────
    from kerf_firmware.routes import router as firmware_router
    app.include_router(firmware_router, tags=["firmware"])

    # ── LLM tools ────────────────────────────────────────────────────────────
    provides: list[str] = []
    _register_tools(ctx, provides)

    # Advertise firmware.build only when PlatformIO is actually present.
    if _pio_available():
        if "firmware.build" not in provides:
            provides.append("firmware.build")
        logger.info("kerf-firmware: PlatformIO found — firmware.build available")
    else:
        logger.warning(
            "kerf-firmware: PlatformIO Core CLI not found on PATH — "
            "install it to enable firmware builds. "
            "pip install platformio  |  brew install platformio"
        )

    try:
        from kerf_core.plugin import PluginManifest  # type: ignore
    except ImportError:
        return {
            "name": "firmware",
            "version": "0.1.0",
            "provides": provides,
            "depends": [],
        }

    return PluginManifest(
        name="firmware",
        version="0.1.0",
        provides=provides,
        depends=[],
    )


def _register_tools(ctx, provides: list) -> None:
    """Register all firmware LLM tools into ctx.tools."""
    try:
        from kerf_firmware.tools.build_firmware import (
            build_firmware_tool,
            build_firmware_spec,
        )
        ctx.tools.register("build_firmware", build_firmware_spec, build_firmware_tool)
        provides.append("firmware.build")
    except Exception as exc:
        logger.warning("kerf-firmware: failed to load build_firmware tool: %s", exc)
