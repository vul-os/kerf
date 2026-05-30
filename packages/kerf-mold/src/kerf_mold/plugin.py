"""kerf-mold plugin entry point.

Registers:
  - LLM tools: mold_check_moldability, mold_generate_parting_surface,
               mold_draft_angle_per_face  (via @register decorator in tools.py)
  - LLM tool:  mold_cooling_analysis  (Dittus-Boelter cooling circuit)
  - LLM tool:  brep_construct_parting_surface  (Yu-Fan 2003 §6 parting surface)
  - LLM tools: mold_plan_ejector_pins, mold_pin_conflicts
               (Yu-Fan 2003 §10 + SPI/ANSI B151.1 ejector pin layout)
  - LLM tool:  mold_verify_cooling_channels
               (Menges 2001 §6.5 cooling-channel conflict detection)
"""
from __future__ import annotations

from fastapi import FastAPI


async def register(app: FastAPI, ctx):
    """Plugin entry-point — called by the kerf-core plugin loader at startup."""
    # Register mold check / parting / draft tools explicitly via ctx
    from kerf_mold.tools import (
        _CHECK_SPEC, run_mold_check_moldability,
        _PARTING_SPEC, run_mold_generate_parting_surface,
        _DRAFT_SPEC, run_mold_draft_angle_per_face,
        _CONSTRUCT_PARTING_SPEC, run_brep_construct_parting_surface,
    )
    ctx.tools.register("mold_check_moldability",
                       _CHECK_SPEC, run_mold_check_moldability)
    ctx.tools.register("mold_generate_parting_surface",
                       _PARTING_SPEC, run_mold_generate_parting_surface)
    ctx.tools.register("mold_draft_angle_per_face",
                       _DRAFT_SPEC, run_mold_draft_angle_per_face)
    ctx.tools.register("brep_construct_parting_surface",
                       _CONSTRUCT_PARTING_SPEC, run_brep_construct_parting_surface)

    # Register cooling analysis tool
    from kerf_mold.cooling_tool import mold_cooling_analysis_spec, run_mold_cooling_analysis
    ctx.tools.register(
        "mold_cooling_analysis",
        mold_cooling_analysis_spec,
        run_mold_cooling_analysis,
    )

    # Register ejector pin layout tools
    from kerf_mold.ejector_pin_tool import (
        _PLAN_SPEC, run_mold_plan_ejector_pins,
        _CONFLICT_SPEC, run_mold_pin_conflicts,
    )
    ctx.tools.register(
        "mold_plan_ejector_pins",
        _PLAN_SPEC,
        run_mold_plan_ejector_pins,
    )
    ctx.tools.register(
        "mold_pin_conflicts",
        _CONFLICT_SPEC,
        run_mold_pin_conflicts,
    )
    # Register cooling-channel conflict verification tool
    from kerf_mold.cooling_channel_conflict_tool import (
        _VERIFY_SPEC, run_mold_verify_cooling_channels,
    )
    ctx.tools.register(
        "mold_verify_cooling_channels",
        _VERIFY_SPEC,
        run_mold_verify_cooling_channels,
    )

    provides = [
        "mold.moldability",
        "mold.parting_surface",
        "mold.parting_surface_construction",
        "mold.draft_angle",
        "mold.cooling_analysis",
        "mold.ejector_pin_layout",
        "mold.cooling_channel_conflict",
    ]

    try:
        from kerf_core.plugin import PluginManifest
        return PluginManifest(
            name="mold",
            version="0.1.0",
            provides=provides,
            depends=[],
        )
    except ImportError:
        return {
            "name": "mold",
            "version": "0.1.0",
            "provides": provides,
            "depends": [],
        }
