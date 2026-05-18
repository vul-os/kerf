"""
kerf-interior plugin registration.

Wires the interior LLM tools into a Kerf plugin app.  All heavy deps
(fastapi, kerf_core, kerf_chat) are optional — the plugin returns a
manifest dict when the runtime is absent.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


async def register(app: "FastAPI", ctx):
    """Entry point called by the Kerf plugin loader at startup."""

    provides: list[str] = []
    _register_tools(ctx, provides)

    try:
        from kerf_core.plugin import PluginManifest  # type: ignore
        return PluginManifest(
            name="interior",
            version="0.1.0",
            provides=provides,
            depends=[],
        )
    except ImportError:
        return {
            "name": "interior",
            "version": "0.1.0",
            "provides": provides,
            "depends": [],
        }


def _register_tools(ctx, provides: list) -> None:
    """Register all interior LLM tools into ctx.tools."""
    try:
        from kerf_interior.tools import TOOLS
        for name, spec, handler in TOOLS:
            ctx.tools.register(name, spec, handler)
        provides.extend([
            "interior.clearance-check",
            "interior.make-furniture",
            "interior.room-layout",
        ])
    except Exception as exc:
        logger.warning("kerf-interior: failed to load tools: %s", exc)

    provides.append("interior.ada-audit")
    provides.append("interior.space-planning")
    provides.append("interior.ffe")
