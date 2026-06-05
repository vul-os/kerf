"""
kerf-entertainment plugin entry-point.

Registers:
  - LLM tools:  lighting_plot_patch, lighting_dmx_check,
                rigging_load_analysis
"""

from __future__ import annotations

from fastapi import FastAPI


async def register(app: FastAPI, ctx):
    """Plugin entry-point — called by the kerf-core plugin loader at startup."""

    from kerf_entertainment.tools import (
        lighting_plot_patch_spec, run_lighting_plot_patch,
        lighting_dmx_check_spec, run_lighting_dmx_check,
        rigging_load_analysis_spec, run_rigging_load_analysis,
    )

    ctx.tools.register("lighting_plot_patch",   lighting_plot_patch_spec,   run_lighting_plot_patch)
    ctx.tools.register("lighting_dmx_check",    lighting_dmx_check_spec,    run_lighting_dmx_check)
    ctx.tools.register("rigging_load_analysis", rigging_load_analysis_spec, run_rigging_load_analysis)

    provides = [
        "entertainment.lighting-plot",
        "entertainment.dmx-patch",
        "entertainment.rigging-load",
        "entertainment.bridle-tension",
    ]

    try:
        from kerf_core.plugin import PluginManifest
        return PluginManifest(
            name="entertainment",
            version="0.1.0",
            provides=provides,
            depends=[],
        )
    except ImportError:
        return {
            "name": "entertainment",
            "version": "0.1.0",
            "provides": provides,
            "depends": [],
        }
