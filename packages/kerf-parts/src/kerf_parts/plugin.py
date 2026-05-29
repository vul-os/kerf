"""kerf-parts plugin registration.

Wires the parts-library LLM tools (currently ``substitute_component``) into a
Kerf plugin. The package's main contribution at runtime is the tool surface;
the fetch/seed pipeline is a contributor-facing CLI concern and is not exposed
as plugin routes.
"""
from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)

_TOOL_MODULES = [
    "kerf_parts.tools",
]


async def register(app: "FastAPI", ctx):
    """Entry point called by the Kerf plugin loader."""

    provides: list[str] = []
    _register_tools(ctx, provides)

    provides += [
        "parts.substitute_component",
    ]

    try:
        from kerf_core.plugin import PluginManifest  # type: ignore
    except ImportError:
        return {
            "name": "kerf-parts",
            "version": "0.1.0",
            "provides": provides,
            "depends": [],
        }

    return PluginManifest(
        name="kerf-parts",
        version="0.1.0",
        provides=provides,
        depends=[],
    )


def _register_tools(ctx, provides: list) -> None:
    """Register all kerf-parts LLM tools into ctx.tools."""
    for module_path in _TOOL_MODULES:
        try:
            mod = importlib.import_module(module_path)
            if hasattr(mod, "TOOLS"):
                for name, spec, handler in mod.TOOLS:
                    ctx.tools.register(name, spec, handler)
                    provides.append(f"tool.{name}")
        except Exception as exc:
            logger.warning(
                "kerf-parts: failed to load %s: %s", module_path, exc
            )
