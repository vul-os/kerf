"""
kerf-cfd plugin entry-point.

Registers:
  - LLM tools: cfd_run, cfd_select_turbulence_model, cfd_pick_solver (via cfd_llm_tools)
  - LLM tool:  cfd_rans_solve         (SIMPLE RANS — run cavity/channel case)
  - LLM tool:  cfd_rans_keps_solve    (k-ε RANS — channel + BFS validation)
  - LLM tool:  cfd_rans_solve  (SIMPLE RANS — run cavity/channel case)
  - LLM tools: cfd_openfoam_export, cfd_openfoam_import  (T-101-C OpenFOAM bridge)
  - LLM tool:  cfd_mesh_unstructured  (3-D unstructured mesh generation)
"""

from __future__ import annotations

from fastapi import FastAPI


async def register(app: FastAPI, ctx):
    """Plugin entry-point — called by the kerf-core plugin loader at startup."""

    # Existing tools from cfd_llm_tools (self-registering via @register decorator)
    import kerf_cfd.cfd_llm_tools  # noqa: F401 — triggers @register decorators

    # cfd_rans_solve (SIMPLE staggered-grid solver)
    from kerf_cfd.rans_tool import cfd_rans_solve_spec, run_cfd_rans_solve
    ctx.tools.register("cfd_rans_solve", cfd_rans_solve_spec, run_cfd_rans_solve)

    # cfd_rans_keps_solve — standard k-ε turbulence model (Launder-Spalding 1974)
    from kerf_cfd.rans_keps import cfd_rans_keps_spec, run_cfd_rans_keps_solve
    ctx.tools.register("cfd_rans_keps_solve", cfd_rans_keps_spec, run_cfd_rans_keps_solve)
    # T-101-C: OpenFOAM bridge — case generator + result parser
    import kerf_cfd.openfoam_llm_tools  # noqa: F401 — triggers @register decorators
    # New: cfd_mesh_unstructured (3-D Delaunay tet mesh + Voronoi dual)
    from kerf_cfd.mesh_unstructured_tool import (
        cfd_mesh_unstructured_spec,
        run_cfd_mesh_unstructured,
    )
    ctx.tools.register(
        "cfd_mesh_unstructured",
        cfd_mesh_unstructured_spec,
        run_cfd_mesh_unstructured,
    )

    provides = [
        "cfd.simple_rans",
        "cfd.turbulence_model",
        "cfd.solver_selection",
        "cfd.heat_transfer",
        "cfd.k_omega_sst",
        "cfd.k_epsilon_rans",
        "cfd.openfoam_bridge",
        "cfd.mesh_unstructured_3d",
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
