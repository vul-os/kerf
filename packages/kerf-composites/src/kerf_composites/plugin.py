"""
kerf-composites plugin entry-point.

Registers:
  - LLM tools: layup_analysis, composites_drape, composites_interlaminar,
               composites_thermal, composites_failure_depth,
               composites_optimize_layup, composites_failure_check,
               composites_weight_cost, composites_failure_envelope,
               composites_afp_pathplan
"""

from __future__ import annotations

from fastapi import FastAPI


async def register(app: FastAPI, ctx):
    """Plugin entry-point — called by the kerf-core plugin loader at startup."""

    from kerf_composites.tools import (
        layup_analysis_spec, run_layup_analysis,
        composites_drape_spec, run_composites_drape,
        composites_interlaminar_spec, run_composites_interlaminar,
        composites_thermal_spec, run_composites_thermal,
        composites_failure_depth_spec, run_composites_failure_depth,
        composites_optimize_layup_spec, run_composites_optimize_layup,
        composites_failure_check_spec, run_composites_failure_check,
        composites_weight_cost_spec, run_composites_weight_cost,
        composites_failure_envelope_spec, run_composites_failure_envelope,
        composites_afp_pathplan_spec, run_composites_afp_pathplan,
    )
    ctx.tools.register("layup_analysis", layup_analysis_spec, run_layup_analysis)
    ctx.tools.register("composites_drape", composites_drape_spec, run_composites_drape)
    ctx.tools.register("composites_interlaminar",
                       composites_interlaminar_spec, run_composites_interlaminar)
    ctx.tools.register("composites_thermal",
                       composites_thermal_spec, run_composites_thermal)
    ctx.tools.register("composites_failure_depth",
                       composites_failure_depth_spec, run_composites_failure_depth)
    ctx.tools.register("composites_optimize_layup",
                       composites_optimize_layup_spec, run_composites_optimize_layup)
    ctx.tools.register("composites_failure_check",
                       composites_failure_check_spec, run_composites_failure_check)
    ctx.tools.register("composites_weight_cost",
                       composites_weight_cost_spec, run_composites_weight_cost)
    ctx.tools.register("composites_failure_envelope",
                       composites_failure_envelope_spec, run_composites_failure_envelope)
    ctx.tools.register("composites_afp_pathplan",
                       composites_afp_pathplan_spec, run_composites_afp_pathplan)

    provides = [
        "composites.layup",
        "composites.clt",
        "composites.failure",
        "composites.drape",
        "composites.interlaminar",
        "composites.thermal",
        "composites.failure_depth",
        "composites.layup_optimizer",
        "composites.weight_cost",
        "composites.failure_envelope",
        "composites.afp_pathplan",
    ]

    try:
        from kerf_core.plugin import PluginManifest
        return PluginManifest(
            name="composites",
            version="0.1.0",
            provides=provides,
            depends=[],
        )
    except ImportError:
        return {
            "name": "composites",
            "version": "0.1.0",
            "provides": provides,
            "depends": [],
        }
