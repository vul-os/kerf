"""
kerf-wiring plugin registration.

Wires the WireViz routes and LLM tools into a Kerf plugin app.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


async def register(app: "FastAPI", ctx):
    """Entry point called by the Kerf plugin loader."""
    # ── HTTP routes ──────────────────────────────────────────────────────────
    from kerf_wiring.routes import router as wiring_router
    app.include_router(wiring_router, tags=["wiring"])

    # ── LLM tools ────────────────────────────────────────────────────────────
    provides = []
    _register_tools(ctx, provides)

    # wiring.svg is always declared — the route is unconditional (graceful
    # degradation when WireViz isn't installed).
    if "wiring.svg" not in provides:
        provides.append("wiring.svg")

    try:
        from kerf_core.plugin import PluginManifest  # type: ignore
    except ImportError:
        return {
            "name": "wiring",
            "version": "0.1.0",
            "provides": provides,
            "depends": [],
        }

    return PluginManifest(
        name="wiring",
        version="0.1.0",
        provides=provides,
        depends=[],
    )


def _register_tools(ctx, provides: list) -> None:
    """Register all wiring LLM tools into ctx.tools."""
    try:
        from kerf_wiring.tools.run_wireviz import run_wireviz_spec, run_wireviz
        ctx.tools.register("run_wireviz", run_wireviz_spec, run_wireviz)
        provides.append("wiring.svg")
    except Exception as exc:
        logger.warning("kerf-wiring: failed to load run_wireviz tool: %s", exc)

    try:
        from kerf_wiring.tools.route_harness_3d import (
            route_harness_3d_spec,
            route_harness_3d,
        )
        ctx.tools.register("route_harness_3d", route_harness_3d_spec, route_harness_3d)
        provides.append("wiring.harness3d")
    except Exception as exc:
        logger.warning("kerf-wiring: failed to load route_harness_3d tool: %s", exc)
