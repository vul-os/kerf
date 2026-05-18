"""
kerf-microfluidics plugin entry-point.

Registers:
  - FastAPI router  POST /microfluidics/*
  - LLM tools       microfluidics_channel, microfluidics_network,
                    microfluidics_mems, microfluidics_mixer
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI


# ---------------------------------------------------------------------------
# Minimal router (HTTP surface — tools are the primary interface)
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/microfluidics", tags=["microfluidics"])


@router.get("/health")
async def health():
    return {"status": "ok", "plugin": "microfluidics"}


# ---------------------------------------------------------------------------
# Plugin entry-point
# ---------------------------------------------------------------------------

async def register(app: FastAPI, ctx):
    """Plugin entry-point — called by the kerf-core plugin loader at startup."""

    app.include_router(router)

    from kerf_microfluidics.tools import (
        microfluidics_channel_spec,
        run_microfluidics_channel,
        microfluidics_network_spec,
        run_microfluidics_network,
        microfluidics_mems_spec,
        run_microfluidics_mems,
        microfluidics_mixer_spec,
        run_microfluidics_mixer,
    )

    ctx.tools.register(
        "microfluidics_channel",
        microfluidics_channel_spec,
        run_microfluidics_channel,
    )
    ctx.tools.register(
        "microfluidics_network",
        microfluidics_network_spec,
        run_microfluidics_network,
    )
    ctx.tools.register(
        "microfluidics_mems",
        microfluidics_mems_spec,
        run_microfluidics_mems,
    )
    ctx.tools.register(
        "microfluidics_mixer",
        microfluidics_mixer_spec,
        run_microfluidics_mixer,
    )

    provides = [
        "microfluidics.channels",
        "microfluidics.networks",
        "microfluidics.mixers",
        "microfluidics.mems",
    ]

    try:
        from kerf_core.plugin import PluginManifest
        return PluginManifest(
            name="microfluidics",
            version="0.1.0",
            provides=provides,
            depends=["cad-core"],
        )
    except ImportError:
        return {
            "name": "microfluidics",
            "version": "0.1.0",
            "provides": provides,
            "depends": ["cad-core"],
        }
