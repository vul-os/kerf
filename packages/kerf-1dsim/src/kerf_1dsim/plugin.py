"""
kerf-1dsim plugin entry-point.

Registers:
  - LLM tools: sim1d_run, sim1d_parse  (via ctx.tools.register)

No heavy optional dependencies — the plugin loads everywhere.
"""

from __future__ import annotations

from fastapi import FastAPI


async def register(app: FastAPI, ctx):
    """Plugin entry-point — called by the kerf-core plugin loader at startup."""

    from kerf_1dsim.tools import (
        sim1d_run_spec, run_sim1d_run,
        sim1d_parse_spec, run_sim1d_parse,
        sim_import_spice_spec, run_sim_import_spice,
        sim_dc_analysis_spec, run_sim_dc_analysis,
    )
    ctx.tools.register("sim1d_run", sim1d_run_spec, run_sim1d_run)
    ctx.tools.register("sim1d_parse", sim1d_parse_spec, run_sim1d_parse)
    ctx.tools.register("sim_import_spice", sim_import_spice_spec, run_sim_import_spice)
    ctx.tools.register("sim_dc_analysis", sim_dc_analysis_spec, run_sim_dc_analysis)

    try:
        from kerf_core.plugin import PluginManifest
        return PluginManifest(
            name="sim1d",
            version="0.1.0",
            provides=["sim1d.dae", "sim1d.modelica-parser", "sim1d.spice-import"],
            depends=[],
        )
    except ImportError:
        return {
            "name": "sim1d",
            "version": "0.1.0",
            "provides": ["sim1d.dae", "sim1d.modelica-parser", "sim1d.spice-import"],
            "depends": [],
        }
