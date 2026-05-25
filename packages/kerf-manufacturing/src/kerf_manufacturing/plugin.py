"""
kerf-manufacturing plugin entry-point.

Registers:
  - LLM tools: manufacturing_moldflow (Hele-Shaw injection-moulding fill simulation)
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def register(app=None, ctx=None):
    """Plugin entry-point — called by the kerf-core plugin loader at startup."""

    provides: list[str] = []

    try:
        from kerf_manufacturing.tools import TOOLS
        if ctx is not None:
            for tool_name, tool_spec, tool_handler in TOOLS:
                ctx.tools.register(tool_name, tool_spec, tool_handler)
        provides.append("manufacturing.moldflow")
    except Exception as exc:
        logger.warning("kerf-manufacturing: failed to load tools: %s", exc)

    try:
        from kerf_core.plugin import PluginManifest  # type: ignore
        return PluginManifest(
            name="manufacturing",
            version="0.1.0",
            provides=provides,
            depends=[],
        )
    except ImportError:
        return {
            "name": "manufacturing",
            "version": "0.1.0",
            "provides": provides,
            "depends": [],
        }
