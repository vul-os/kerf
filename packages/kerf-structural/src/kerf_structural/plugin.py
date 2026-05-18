"""
kerf-structural plugin entry-point.

Registers:
  - LLM tools:  structural_rc_beam, structural_steel_beam,
                structural_rebar, structural_loads
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

    try:
        from kerf_core.plugin import PluginManifest
        return PluginManifest(
            name="structural",
            version="0.1.0",
            provides=[
                "structural.rc-beam",
                "structural.steel-beam",
                "structural.rebar-detailing",
                "structural.load-combinations",
            ],
            depends=[],
        )
    except ImportError:
        return {
            "name": "structural",
            "version": "0.1.0",
            "provides": [
                "structural.rc-beam",
                "structural.steel-beam",
                "structural.rebar-detailing",
                "structural.load-combinations",
            ],
            "depends": [],
        }
