"""kerf-mold plugin entry point.

Registers:
  - LLM tools: mold_check_moldability, mold_generate_parting_surface,
               mold_draft_angle_per_face  (via @register decorator in tools.py)
  - LLM tool:  mold_cooling_analysis  (Dittus-Boelter cooling circuit)
"""
from __future__ import annotations

from fastapi import FastAPI


async def register(app: FastAPI, ctx):
    """Plugin entry-point — called by the kerf-core plugin loader at startup."""
    # Trigger self-registering @register decorators for existing mold tools
    try:
        import kerf_mold.tools  # noqa: F401
    except ImportError:
        pass

    # Register new cooling analysis tool via ctx
    from kerf_mold.cooling_tool import mold_cooling_analysis_spec, run_mold_cooling_analysis
    ctx.tools.register(
        "mold_cooling_analysis",
        mold_cooling_analysis_spec,
        run_mold_cooling_analysis,
    )

    provides = [
        "mold.moldability",
        "mold.parting_surface",
        "mold.draft_angle",
        "mold.cooling_analysis",
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
