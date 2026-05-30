"""
kerf-landscape plugin entry-point.

Registers LLM tools for grading, drainage, planting, hardscape, and irrigation.
No background workers or FastAPI routes are needed — all landscape
computations are synchronous pure-Python.
"""

from __future__ import annotations

from fastapi import FastAPI


async def register(app: FastAPI, ctx):
    """Plugin entry-point — called by the kerf-core plugin loader at startup."""

    from kerf_landscape.tools import (
        landscape_contours_spec, run_landscape_contours,
        landscape_cut_fill_spec, run_landscape_cut_fill,
        landscape_runoff_spec, run_landscape_runoff,
        landscape_plants_spec, run_landscape_plants,
        landscape_paver_spec, run_landscape_paver_pattern,
        landscape_wall_spec, run_landscape_retaining_wall,
        # irrigation schedule (coverage sweep 2026-05-25 — was in tools.py but unregistered)
        landscape_irrigation_spec, run_landscape_irrigation,
        # plant species catalog with USDA zones + Dirr data
        landscape_lookup_plant_spec, run_landscape_lookup_plant,
        landscape_filter_plants_spec, run_landscape_filter_plants,
    )

    ctx.tools.register("landscape_contours", landscape_contours_spec, run_landscape_contours)
    ctx.tools.register("landscape_cut_fill", landscape_cut_fill_spec, run_landscape_cut_fill)
    ctx.tools.register("landscape_runoff", landscape_runoff_spec, run_landscape_runoff)
    ctx.tools.register("landscape_plants", landscape_plants_spec, run_landscape_plants)
    ctx.tools.register("landscape_paver_pattern", landscape_paver_spec, run_landscape_paver_pattern)
    ctx.tools.register("landscape_retaining_wall", landscape_wall_spec, run_landscape_retaining_wall)
    ctx.tools.register(
        "landscape_irrigation_schedule",
        landscape_irrigation_spec,
        run_landscape_irrigation,
    )
    ctx.tools.register(
        "landscape_lookup_plant",
        landscape_lookup_plant_spec,
        run_landscape_lookup_plant,
    )
    ctx.tools.register(
        "landscape_filter_plants",
        landscape_filter_plants_spec,
        run_landscape_filter_plants,
    )

    provides = [
        "landscape.grading",
        "landscape.drainage",
        "landscape.planting",
        "landscape.hardscape",
        "landscape.irrigation",
        "landscape.plant_catalog",
    ]

    try:
        from kerf_core.plugin import PluginManifest
        return PluginManifest(
            name="landscape",
            version="0.1.0",
            provides=provides,
            depends=[],
        )
    except ImportError:
        return {
            "name": "landscape",
            "version": "0.1.0",
            "provides": provides,
            "depends": [],
        }
