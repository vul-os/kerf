"""
kerf-render plugin registration.

Wires the Blender Cycles render route and LLM tools into a Kerf plugin.
"""
from __future__ import annotations

import logging
import shutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


async def register(app: "FastAPI", ctx):
    """Entry point called by the Kerf plugin loader."""

    # ── HTTP routes ──────────────────────────────────────────────────────
    from kerf_render.routes import router as render_router
    app.include_router(render_router, tags=["render"])

    # ── LLM tools ────────────────────────────────────────────────────────
    provides = []
    _register_tools(ctx, provides)

    # Gate on blender binary availability
    blender_available = shutil.which("blender") is not None
    if blender_available:
        provides.append("render.image")
        logger.info("kerf-render: blender found on PATH")
    else:
        logger.info("kerf-render: blender not on PATH; render.image unavailable at startup")
        # Still declare the route — it will return a clear error at runtime
        provides.append("render.image")

    try:
        from kerf_core.plugin import PluginManifest  # type: ignore
    except ImportError:
        return {
            "name": "render",
            "version": "0.1.0",
            "provides": provides,
            "depends": ["cad-core"],
        }

    return PluginManifest(
        name="render",
        version="0.1.0",
        provides=provides,
        depends=["cad-core"],
    )


_TOOL_MODULES = [
    "kerf_render.tools",
    "kerf_render.pathtrace_tools",
    "kerf_render.archviz_tools",
]


def _register_tools(ctx, provides: list) -> None:
    """Register render LLM tools into ctx.tools."""
    import importlib
    for mod_name in _TOOL_MODULES:
        try:
            mod = importlib.import_module(mod_name)
            if hasattr(mod, "TOOLS"):
                for name, spec, handler in mod.TOOLS:
                    ctx.tools.register(name, spec, handler)
        except Exception as exc:
            logger.warning("kerf-render: failed to load tools from %s: %s",
                           mod_name, exc)
    provides.append("render.pathtrace")
    provides.append("render.archviz")
