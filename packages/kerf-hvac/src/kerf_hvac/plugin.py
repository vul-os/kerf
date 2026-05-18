"""plugin.py — kerf-hvac plugin registration.

Wires the HVAC LLM tools into a Kerf plugin app.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


async def register(app: "FastAPI", ctx):
    """Entry point called by the Kerf plugin loader."""
    provides: list[str] = []
    _register_tools(ctx, provides)

    try:
        from kerf_core.plugin import PluginManifest  # type: ignore
    except ImportError:
        return {
            "name": "hvac",
            "version": "0.1.0",
            "provides": provides,
            "depends": [],
        }

    return PluginManifest(
        name="hvac",
        version="0.1.0",
        provides=provides,
        depends=[],
    )


def _register_tools(ctx, provides: list) -> None:
    """Register all HVAC LLM tools into ctx.tools."""
    try:
        from kerf_hvac.tools import TOOLS
        for name, spec, handler in TOOLS:
            ctx.tools.register(name, spec, handler)
            provides.append(name)
    except Exception as exc:
        logger.warning("kerf-hvac: failed to load tools: %s", exc)

    # Always declare core capabilities
    for cap in [
        "hvac.size_duct",
        "hvac.pressure_drop",
        "hvac.fitting_loss",
        "hvac.flat_pattern",
    ]:
        if cap not in provides:
            provides.append(cap)
