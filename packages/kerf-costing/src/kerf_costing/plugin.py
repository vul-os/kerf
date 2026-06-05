"""
kerf-costing plugin entry-point.

Registers:
  bim_quantity_schedule     — BIM material take-off schedule (quantity only)
  bim_material_cost_rollup  — BIM material take-off with direct cost rollup

No heavy optional dependencies — kerf-costing is pure Python.
"""
from __future__ import annotations

from fastapi import FastAPI


async def register(app: FastAPI, ctx):
    """Plugin entry-point — called by the kerf-core plugin loader at startup."""

    from kerf_costing.tools import (
        bim_quantity_schedule_spec, run_bim_quantity_schedule,
        bim_material_cost_rollup_spec, run_bim_material_cost_rollup,
    )

    ctx.tools.register(
        "bim_quantity_schedule",
        bim_quantity_schedule_spec,
        run_bim_quantity_schedule,
    )
    ctx.tools.register(
        "bim_material_cost_rollup",
        bim_material_cost_rollup_spec,
        run_bim_material_cost_rollup,
    )

    try:
        from kerf_core.plugin import PluginManifest
        return PluginManifest(
            name="costing",
            version="0.1.0",
            provides=[
                "costing.bim_quantity_schedule",
                "costing.bim_material_cost_rollup",
            ],
            depends=[],
        )
    except ImportError:
        return {
            "name": "costing",
            "version": "0.1.0",
            "provides": [
                "costing.bim_quantity_schedule",
                "costing.bim_material_cost_rollup",
            ],
            "depends": [],
        }
