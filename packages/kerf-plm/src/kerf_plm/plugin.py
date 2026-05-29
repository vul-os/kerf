"""
kerf-plm plugin entry-point.

Registers:
  - LLM tool  plm_configure  (via ctx.tools.register)
"""

from __future__ import annotations

from fastapi import FastAPI


async def register(app: FastAPI, ctx):
    """Plugin entry-point — called by the kerf-core plugin loader at startup."""

    from kerf_plm.tools import plm_configure_spec, run_plm_configure
    ctx.tools.register("plm_configure", plm_configure_spec, run_plm_configure)

    try:
        from kerf_core.plugin import PluginManifest
        return PluginManifest(
            name="plm",
            version="0.1.0",
            provides=["plm.configurator", "plm.effectivity-bom"],
            depends=[],
        )
    except ImportError:
        return {
            "name": "plm",
            "version": "0.1.0",
            "provides": ["plm.configurator", "plm.effectivity-bom"],
            "depends": [],
        }
