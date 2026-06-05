"""
kerf-cfd plugin entry-point.

Registers:
  - LLM tools: cfd_run, cfd_select_turbulence_model, cfd_pick_solver (via cfd_llm_tools)
  - LLM tool:  cfd_rans_solve         (SIMPLE RANS — run cavity/channel case)
  - LLM tool:  cfd_rans_keps_solve    (k-ε RANS — channel + BFS validation)
  - LLM tool:  cfd_rans_solve  (SIMPLE RANS — run cavity/channel case)
  - LLM tools: cfd_openfoam_export, cfd_openfoam_import  (T-101-C OpenFOAM bridge)
  - LLM tool:  cfd_mesh_unstructured  (3-D unstructured mesh generation)
  - LLM tool:  cfd_combustion_ebu     (Magnussen-Hjertager EBU non-premixed combustion)
  - LLM tool:  cfd_reacting_flow_multispecies  (N-species finite-rate Arrhenius chemistry,
                                                 1-D plug-flow reactor, Westbrook-Dryer 1981)
  - LLM tool:  cfd_lagrangian_track   (Lagrangian particle tracking, Schiller-Naumann drag)
  - LLM tool:  cfd_fsi_displace_mesh  (ALE dynamic mesh, Laplacian smoothing, GCL)
  - LLM tool:  cfd_snappy_hex_mesh   (Cartesian + snap hex mesher, Aftosmis 1998)
  - LLM tool:  cfd_wind_load         (ASCE 7-22 building wind pressures + drag)
  - LLM tool:  cfd_vortex_shedding   (Bearman 1984 St vortex shedding frequency)
  - LLM tool:  cfd_compressible_shock (Roe 1981 + Rankine-Hugoniot normal shock)
  - LLM tool:  cfd_conjugate_ht       (Dirichlet-Neumann CHT coupling, Quarteroni-Valli 1999)
  - LLM tool:  cfd_vof_mixture        (VOF mixture density, Hirt-Nichols 1981)
  - LLM tool:  cfd_marine_resistance  (Holtrop-Mennen 1982 ship resistance)
  - LLM tool:  cfd_marine_wave_spectrum (JONSWAP/P-M wave spectrum, Hasselmann 1973)
  - LLM tool:  cfd_marine_wave_force  (Froude-Krylov + diffraction, Faltinsen 1990)
  - LLM tool:  cfd_postprocess_results (field stats, y⁺, postProcessing summary)
  - LLM tool:  cfd_extract_residuals   (parse simpleFoam/pimpleFoam log residuals)
  - LLM tool:  cfd_probe_field         (probe scalar/vector fields at N points)
  - LLM tool:  cfd_flow_setup          (internal/external flow BC + solver config)
  - LLM tool:  plasma_discharge_simulate  (1-D DC glow-discharge drift-diffusion solver;
                                            Townsend ionisation + Poisson self-consistent field;
                                            Paschen breakdown curve; Hagelaar & Pitchford 2005)

# Wave 9C: OpenFOAM combustion + Lagrangian + FSI
# Wave 10C: snappyHexMesh-style mesher + wind engineering
# Wave 12B: CFD advanced physics (compressible/conjugate-HT/multiphase/marine)
# Wave parity: postprocessing + flow setup + isentropic/oblique shock + VOF surface tension
# Multi-species reacting flow: general finite-rate chemistry + 1-D plug-flow reactor
# Wave plasma: 1-D drift-diffusion glow-discharge (ionisation transport, COMSOL compare flip)
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
    # T-101-C: OpenFOAM bridge — case generator + result parser + export adapter
    import kerf_cfd.openfoam_llm_tools  # noqa: F401 — triggers @register decorators (cfd_openfoam_export, cfd_openfoam_import, cfd_export_openfoam)
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

    # Multi-species finite-rate reacting flow (COMSOL compare: Chemical / reacting flow → yes)
    import kerf_cfd.combustion.multispecies_tool  # noqa: F401 — registers cfd_reacting_flow_multispecies

    # Wave 9C: OpenFOAM combustion + Lagrangian + FSI
    import kerf_cfd.cfd_advanced_tools  # noqa: F401 — triggers @register decorators

    # Wave 10C: snappyHexMesh-style mesher + wind engineering
    import kerf_cfd.cfd_advanced_tools_v2  # noqa: F401 — triggers @register decorators

    # Wave 12B: CFD advanced physics (compressible/conjugate-HT/multiphase/marine)
    import kerf_cfd.cfd_advanced_v3_tools  # noqa: F401 — triggers @register decorators

    # Wave parity: postprocessing + flow setup tools
    import kerf_cfd.cfd_postprocessing_tool  # noqa: F401 — triggers @register decorators

    # Wave plasma: 1-D drift-diffusion glow-discharge solver (Townsend + Poisson)
    from kerf_cfd.plasma.plasma_tool import (
        plasma_discharge_simulate_spec,
        run_plasma_discharge_simulate,
    )
    ctx.tools.register(
        "plasma_discharge_simulate",
        plasma_discharge_simulate_spec,
        run_plasma_discharge_simulate,
    )

    # Wave 12B: Landscape + Quote-to-delivery + MicroFlo
    # IES MicroFlo-style room airflow: preview-grade RANS + Fanger 1972 PMV/PPD
    # References: Fanger (1972); ASHRAE 55-2020; ASHRAE 62.1-2022;
    #             Launder-Spalding 1974 k-ε (reused from kerf_cfd.rans.k_epsilon)
    try:
        import kerf_cfd.internal_airflow.microflo  # noqa: F401
    except Exception:
        pass  # internal_airflow optional — fail silently

    provides = [
        "cfd.simple_rans",
        "cfd.turbulence_model",
        "cfd.solver_selection",
        "cfd.heat_transfer",
        "cfd.k_omega_sst",
        "cfd.k_epsilon_rans",
        "cfd.openfoam_bridge",
        "cfd.mesh_unstructured_3d",
        "cfd.combustion_ebu",
        "cfd.multispecies_reacting_flow",
        "cfd.lagrangian_particles",
        "cfd.fsi_dynamic_mesh",
        "cfd.snappy_hex_mesh",
        "cfd.wind_engineering",
        "cfd.compressible_flow",
        "cfd.conjugate_heat_transfer",
        "cfd.vof_multiphase",
        "cfd.marine_hydrodynamics",
        "cfd.internal_airflow_microflo",
        "cfd.postprocessing",
        "cfd.flow_setup",
        "cfd.isentropic_relations",
        "cfd.oblique_shock",
        "cfd.prandtl_meyer",
        "cfd.vof_surface_tension",
        "plasma.drift_diffusion",
        "plasma.glow_discharge",
        "plasma.paschen_curve",
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
