"""
kerf-marine plugin entry-point.

Registers:
  - LLM tools: marine_hydrostatics, marine_box_barge, marine_stability_gz,
               marine_seakeeping_rao, marine_seakeeping_stats,
               marine_scantlings (ISO 12215-5), marine_vpp, holtrop_mennen_resistance
"""

from __future__ import annotations

from fastapi import FastAPI


async def register(app: FastAPI, ctx):
    """Plugin entry-point — called by the kerf-core plugin loader at startup."""

    from kerf_marine.tools import (
        marine_hydrostatics_spec, run_marine_hydrostatics,
        marine_box_barge_spec, run_marine_box_barge,
        marine_stability_gz_spec, run_marine_stability_gz,
        marine_scantlings_spec, run_marine_scantlings,
        marine_vpp_spec, run_marine_vpp,
        marine_seakeeping_rao_spec, run_marine_seakeeping_rao,
        marine_seakeeping_stats_spec, run_marine_seakeeping_stats,
    )
    from kerf_marine.holtrop_mennen import (
        holtrop_mennen_spec, run_holtrop_mennen,
    )
    from kerf_marine.hull_fairness import (
        marine_hull_fairness_audit_spec, run_marine_hull_fairness_audit,
        marine_fair_hull_spec, run_marine_fair_hull,
    )
    ctx.tools.register(
        "marine_hydrostatics",
        marine_hydrostatics_spec,
        run_marine_hydrostatics,
    )
    ctx.tools.register(
        "marine_box_barge",
        marine_box_barge_spec,
        run_marine_box_barge,
    )
    ctx.tools.register(
        "marine_stability_gz",
        marine_stability_gz_spec,
        run_marine_stability_gz,
    )
    ctx.tools.register(
        "holtrop_mennen_resistance",
        holtrop_mennen_spec,
        run_holtrop_mennen,
    )
    ctx.tools.register(
        "marine_scantlings",
        marine_scantlings_spec,
        run_marine_scantlings,
    )
    ctx.tools.register(
        "marine_vpp",
        marine_vpp_spec,
        run_marine_vpp,
    )
    ctx.tools.register(
        "marine_seakeeping_rao",
        marine_seakeeping_rao_spec,
        run_marine_seakeeping_rao,
    )
    ctx.tools.register(
        "marine_seakeeping_stats",
        marine_seakeeping_stats_spec,
        run_marine_seakeeping_stats,
    )
    ctx.tools.register(
        "marine_hull_fairness_audit",
        marine_hull_fairness_audit_spec,
        run_marine_hull_fairness_audit,
    )
    ctx.tools.register(
        "marine_fair_hull",
        marine_fair_hull_spec,
        run_marine_fair_hull,
    )

    try:
        from kerf_core.plugin import PluginManifest
        return PluginManifest(
            name="marine",
            version="0.1.0",
            provides=["marine.hydrostatics", "marine.stability", "marine.sections",
                      "marine.resistance", "marine.scantlings", "marine.vpp",
                      "marine.seakeeping", "marine.hull_fairness"],
            depends=[],
        )
    except ImportError:
        return {
            "name": "marine",
            "version": "0.1.0",
            "provides": ["marine.hydrostatics", "marine.stability", "marine.sections",
                         "marine.resistance", "marine.scantlings", "marine.vpp",
                         "marine.seakeeping", "marine.hull_fairness"],
            "depends": [],
        }
