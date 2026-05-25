"""
kerf-structural plugin entry-point.

Registers:
  - LLM tools:  structural_rc_beam, structural_steel_beam,
                structural_rebar, structural_loads,
                aisc_compression, aisc_flexure, aisc_combined,
                aisc_member_check
"""

from __future__ import annotations

from fastapi import FastAPI


async def register(app: FastAPI, ctx):
    """Plugin entry-point — called by the kerf-core plugin loader at startup."""

    from kerf_structural.tools import (
        rc_beam_spec, run_rc_beam,
        steel_beam_spec, run_steel_beam,
        rebar_spec, run_rebar,
        loads_spec, run_loads,
    )

    ctx.tools.register("structural_rc_beam",   rc_beam_spec,   run_rc_beam)
    ctx.tools.register("structural_steel_beam", steel_beam_spec, run_steel_beam)
    ctx.tools.register("structural_rebar",      rebar_spec,     run_rebar)
    ctx.tools.register("structural_loads",      loads_spec,     run_loads)

    # AISC 360-22 Chapters E / F / H full member checks (were in aisc_member.py
    # but never registered in the plugin — coverage sweep 2026-05-25).
    from kerf_structural.aisc_member import (
        aisc_compression_spec, run_aisc_compression,
        aisc_flexure_spec, run_aisc_flexure,
        aisc_combined_spec, run_aisc_combined,
        aisc_member_check_spec, run_aisc_member_check,
    )
    ctx.tools.register("aisc_compression",  aisc_compression_spec,  run_aisc_compression)
    ctx.tools.register("aisc_flexure",      aisc_flexure_spec,      run_aisc_flexure)
    ctx.tools.register("aisc_combined",     aisc_combined_spec,     run_aisc_combined)
    ctx.tools.register("aisc_member_check", aisc_member_check_spec, run_aisc_member_check)

    provides = [
        "structural.rc-beam",
        "structural.steel-beam",
        "structural.rebar-detailing",
        "structural.load-combinations",
        "structural.aisc-compression",
        "structural.aisc-flexure",
        "structural.aisc-combined",
        "structural.aisc-member-check",
    ]

    try:
        from kerf_core.plugin import PluginManifest
        return PluginManifest(
            name="structural",
            version="0.1.0",
            provides=provides,
            depends=[],
        )
    except ImportError:
        return {
            "name": "structural",
            "version": "0.1.0",
            "provides": provides,
            "depends": [],
        }
