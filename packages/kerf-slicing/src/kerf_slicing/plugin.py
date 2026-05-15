"""
kerf-slicing plugin registration.

Wires the CuraEngine slicing routes and LLM tools into a Kerf plugin app.
The capability `slicing.fdm` is only advertised when CuraEngine is available
on PATH (probed at startup). The HTTP route is always mounted — it returns a
descriptive error if CuraEngine is absent, so the frontend can show a helpful
install prompt rather than a 500.
"""
from __future__ import annotations

import logging
import shutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


def _cura_available() -> bool:
    """Return True if CuraEngine is on PATH."""
    return shutil.which("CuraEngine") is not None or shutil.which("curaengine") is not None


async def register(app: "FastAPI", ctx):
    """Entry point called by the Kerf plugin loader."""
    # ── HTTP routes ──────────────────────────────────────────────────────────
    from kerf_slicing.routes import router as slicing_router
    app.include_router(slicing_router, tags=["slicing"])

    # ── LLM tools ────────────────────────────────────────────────────────────
    provides = []
    _register_tools(ctx, provides)

    # Advertise slicing.fdm only when CuraEngine is actually present.
    if _cura_available():
        if "slicing.fdm" not in provides:
            provides.append("slicing.fdm")
        logger.info("kerf-slicing: CuraEngine found — slicing.fdm available")
    else:
        logger.warning(
            "kerf-slicing: CuraEngine not found on PATH — "
            "install it to enable 3D-print slicing. "
            "Ubuntu/Debian: apt-get install cura-engine | "
            "macOS: brew install curaengine"
        )

    try:
        from kerf_core.plugin import PluginManifest  # type: ignore
    except ImportError:
        return {
            "name": "slicing",
            "version": "0.1.0",
            "provides": provides,
            "depends": [],
        }

    return PluginManifest(
        name="slicing",
        version="0.1.0",
        provides=provides,
        depends=[],
    )


def _register_tools(ctx, provides: list) -> None:
    """Register all slicing LLM tools into ctx.tools."""
    try:
        from kerf_slicing.tools.run_print_slice import (
            run_print_slice,
            run_print_slice_spec,
        )
        ctx.tools.register("run_print_slice", run_print_slice_spec, run_print_slice)
        provides.append("slicing.fdm")
    except Exception as exc:
        logger.warning("kerf-slicing: failed to load run_print_slice tool: %s", exc)
