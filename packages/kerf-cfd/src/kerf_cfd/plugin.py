"""
kerf-cfd plugin entry-point.

Registers:
  - LLM tools: cfd_run, cfd_select_turbulence_model, cfd_pick_solver (via cfd_llm_tools)
  - LLM tool:  cfd_rans_solve  (SIMPLE RANS — run cavity/channel case)
"""

from __future__ import annotations

from fastapi import FastAPI


async def register(app: FastAPI, ctx):
    """Plugin entry-point — called by the kerf-core plugin loader at startup."""

    # Existing tools from cfd_llm_tools (self-registering via @register decorator)
    import kerf_cfd.cfd_llm_tools  # noqa: F401 — triggers @register decorators

    # New: cfd_rans_solve
    from kerf_cfd.rans_tool import cfd_rans_solve_spec, run_cfd_rans_solve
    ctx.tools.register("cfd_rans_solve", cfd_rans_solve_spec, run_cfd_rans_solve)

    provides = [
        "cfd.simple_rans",
        "cfd.turbulence_model",
        "cfd.solver_selection",
        "cfd.heat_transfer",
        "cfd.k_omega_sst",
    ]

    try:
        from kerf_core.plugin import PluginManifest
        return PluginManifest(
            name="cfd",
            version="0.1.0",
            provides=provides,
            depends=[],
        )
    except ImportError:
        return {
            "name": "cfd",
            "version": "0.1.0",
            "provides": provides,
            "depends": [],
        }
