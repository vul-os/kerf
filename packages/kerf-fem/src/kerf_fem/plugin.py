"""
kerf-fem plugin entry-point.

Registers:
  - FastAPI router  POST /run-fem
  - LLM tools       fem_run, fem_job_status  (via ctx.tools.register)
  - LLM tools       fem_acoustics, fem_electrostatics, fem_magnetostatics,
                    cfd_navier_stokes_steady, cfd_potential_cylinder,
                    fem_propagate_uncertainty,
                    fem_solid_static, fem_modal_beam, fem_linear_static_beam
                    (via import-triggered self-registration)
  - background worker for fem_jobs table     (via ctx.workers.register)

Heavy deps (dolfinx, slepc4py) are optional — the plugin still loads
with a reduced `provides` list when they are absent.
"""

from __future__ import annotations

import logging
import shutil

logger = logging.getLogger(__name__)

from fastapi import FastAPI

# ── dependency gates ──────────────────────────────────────────────────────────

_DOLFINX_AVAILABLE = False
try:
    import dolfinx  # noqa: F401
    _DOLFINX_AVAILABLE = True
except ImportError:
    pass

_SLEPC_AVAILABLE = False
try:
    from slepc4py import SLEPc  # noqa: F401
    _SLEPC_AVAILABLE = True
except ImportError:
    pass

_CALCULIX_AVAILABLE = shutil.which("ccx") is not None


# ── register ──────────────────────────────────────────────────────────────────

async def register(app: FastAPI, ctx):
    """Plugin entry-point — called by the kerf-core plugin loader at startup."""

    from kerf_fem.routes import router
    app.include_router(router)

    # Register LLM tools
    from kerf_fem.tools import (
        fem_run_spec, run_fem_run,
        fem_job_status_spec, run_fem_job_status,
        fem_nonlinear_bar_spec, run_fem_nonlinear_bar,
        fem_truss_plastic_spec, run_fem_truss_plastic,
        fem_buckling_linear_spec, run_fem_buckling_linear,
        fem_harmonic_response_spec, run_fem_harmonic_response,
        fem_random_vibration_psd_spec, run_fem_random_vibration_psd,
        fem_explicit_dynamics_spec,
    )
    from kerf_fem.explicit_dynamics import run_fem_explicit_dynamics
    ctx.tools.register("fem_run", fem_run_spec, run_fem_run)
    ctx.tools.register("fem_job_status", fem_job_status_spec, run_fem_job_status)
    ctx.tools.register("fem_nonlinear_bar", fem_nonlinear_bar_spec, run_fem_nonlinear_bar)
    ctx.tools.register("fem_truss_plastic", fem_truss_plastic_spec, run_fem_truss_plastic)
    ctx.tools.register("fem_buckling_linear", fem_buckling_linear_spec, run_fem_buckling_linear)
    ctx.tools.register("fem_harmonic_response", fem_harmonic_response_spec, run_fem_harmonic_response)
    ctx.tools.register("fem_random_vibration_psd", fem_random_vibration_psd_spec, run_fem_random_vibration_psd)
    ctx.tools.register("fem_explicit_dynamics", fem_explicit_dynamics_spec, run_fem_explicit_dynamics)  # kerf-fem: explicit transient dynamics
    from kerf_fem.nonlinear import _fem_nonlinear_spec, run_fem_nonlinear; ctx.tools.register("fem_nonlinear", _fem_nonlinear_spec, run_fem_nonlinear)
    from kerf_fem.nonlinear_static import _fem_nonlinear_static_spec, run_fem_nonlinear_static; ctx.tools.register("fem_nonlinear_static", _fem_nonlinear_static_spec, run_fem_nonlinear_static)  # kerf-fem: 3-D NL static, TL, J2 plasticity, arc-length
    from kerf_fem.fatigue_fem import _fem_fatigue_spec, run_fem_fatigue; ctx.tools.register("fem_fatigue", _fem_fatigue_spec, run_fem_fatigue)  # kerf-fem: fatigue & durability
    from kerf_fem.fatigue_fem import _fem_sn_curve_spec, run_fem_sn_curve; ctx.tools.register("fem_sn_curve", _fem_sn_curve_spec, run_fem_sn_curve)  # kerf-fem: S-N / Wöhler curve data
    from kerf_fem.fatigue_fem import _fem_haigh_diagram_spec, run_fem_haigh_diagram; ctx.tools.register("fem_haigh_diagram", _fem_haigh_diagram_spec, run_fem_haigh_diagram)  # kerf-fem: Haigh modified-Goodman diagram
    from kerf_fem.harmonic import _fem_frf_sweep_spec, run_fem_frf_sweep; ctx.tools.register("fem_frf_sweep", _fem_frf_sweep_spec, run_fem_frf_sweep)  # kerf-fem: direct FRF sweep from modal properties
    from kerf_fem.plate import _fem_plate_static_spec, run_fem_plate_static_solve; ctx.tools.register("fem_plate_static_solve", _fem_plate_static_spec, run_fem_plate_static_solve)  # kerf-fem: MITC4 plate/shell
    import kerf_fem.em_highfreq  # kerf-fem: high-frequency EM (waveguide, S-params, FDTD) — self-registers fem_em_highfreq tool on import
    import kerf_fem.acoustics_fem  # kerf-fem: acoustics FEM (cavity modes, BEM radiation) — self-registers fem_acoustics
    import kerf_fem.em_field  # kerf-fem: electrostatics + magnetostatics — self-registers fem_electrostatics, fem_magnetostatics
    import kerf_fem.cfd_navier_stokes  # kerf-fem: 2-D projection NS solver — self-registers cfd_navier_stokes_steady
    import kerf_fem.cfd_potential  # kerf-fem: potential-flow cylinder — self-registers cfd_potential_cylinder
    from kerf_fem.coupled_variation import fem_propagate_uncertainty_spec, run_fem_propagate_uncertainty; ctx.tools.register("fem_propagate_uncertainty", fem_propagate_uncertainty_spec, run_fem_propagate_uncertainty)  # kerf-fem: probabilistic FEA (LHS + Karhunen-Loève)
    # Solid FEM / modal beam / linear static beam — close backend-only gaps
    try:
        import kerf_fem.solid_fem_tools as _sft
        for _name, _spec, _handler in _sft.TOOLS:
            ctx.tools.register(_name, _spec, _handler)
        provides.append("fem.solid-tet-hex")
        provides.append("fem.modal-beam")
        provides.append("fem.linear-static-beam")
    except Exception as exc:
        logger.warning("kerf-fem: solid_fem_tools failed to load: %s", exc)
    # Wave 12E: material plasticity (J2 / Drucker-Prager / Mohr-Coulomb / Hill anisotropic)
    try:
        import kerf_fem.plasticity.plasticity_tools as _pl
        for name, spec, handler in _pl.TOOLS:
            ctx.tools.register(name, spec, handler)
        provides.append("fem.plasticity-j2")
        provides.append("fem.plasticity-drucker-prager")
        provides.append("fem.plasticity-mohr-coulomb")
        provides.append("fem.plasticity-hill")
    except Exception as exc:
        logger.warning("kerf-fem: plasticity tools failed to load: %s", exc)
    # Wave 12E: thermal-structural coupled + composite laminate (CLT) + failure criteria
    try:
        import kerf_fem.multiphysics.multiphysics_tools as _mp
        for name, spec, handler in _mp.TOOLS:
            ctx.tools.register(name, spec, handler)
        provides.append("fem.thermo-elastic")
    except Exception as exc:
        logger.warning("kerf-fem: multiphysics tools failed to load: %s", exc)
    try:
        import kerf_fem.composites.composite_tools as _co
        for name, spec, handler in _co.TOOLS:
            ctx.tools.register(name, spec, handler)
        provides.append("fem.composite-clt")
        provides.append("fem.composite-failure")
    except Exception as exc:
        logger.warning("kerf-fem: composite tools failed to load: %s", exc)
    # Wave 12E: contact mechanics + fracture
    try:
        import kerf_fem.contact.contact_tools as _ct
        for name, spec, handler in _ct.TOOLS:
            ctx.tools.register(name, spec, handler)
        provides.append("fem.contact-hertzian")
        provides.append("fem.contact-penalty")
    except Exception as exc:
        logger.warning("kerf-fem: contact tools failed to load: %s", exc)
    try:
        import kerf_fem.fracture.fracture_tools as _ft
        for name, spec, handler in _ft.TOOLS:
            ctx.tools.register(name, spec, handler)
        provides.append("fem.fracture-j-integral")
        provides.append("fem.fracture-stress-intensity")
        provides.append("fem.fracture-cohesive-zone")
    except Exception as exc:
        logger.warning("kerf-fem: fracture tools failed to load: %s", exc)
    # FEM-gaps: Paris-law crack growth + Erdogan-Sih kink angle
    try:
        import kerf_fem.fracture.crack_growth_tools as _cgt
        for name, spec, handler in _cgt.TOOLS:
            ctx.tools.register(name, spec, handler)
        provides.append("fem.fracture-paris-law")
        provides.append("fem.fracture-mixed-mode-kink")
    except Exception as exc:
        logger.warning("kerf-fem: crack_growth_tools failed to load: %s", exc)
    # FEM-gaps: hyperelastic materials (Neo-Hookean, Mooney-Rivlin, Ogden)
    try:
        import kerf_fem.hyperelastic.hyperelastic_tools as _ht
        for name, spec, handler in _ht.TOOLS:
            ctx.tools.register(name, spec, handler)
        provides.append("fem.hyperelastic-neo-hookean")
        provides.append("fem.hyperelastic-mooney-rivlin")
        provides.append("fem.hyperelastic-ogden")
    except Exception as exc:
        logger.warning("kerf-fem: hyperelastic tools failed to load: %s", exc)

    # Register background worker
    from kerf_fem.worker import FEMWorker
    fem_worker = FEMWorker(
        pool=ctx.pool,
        storage_getter=lambda: ctx.storage,
        pyworker_url=getattr(ctx.config, "pyworker_url", "http://localhost:8090"),
    )

    async def _fem_factory():
        return fem_worker

    ctx.workers.register("fem", _fem_factory)

    # Build `provides` list based on available deps
    # fem.nonlinear is pure-Python — always available
    provides = [
        "fem.nonlinear", "fem.electromagnetics",
        "fem.acoustics", "fem.electrostatics", "fem.magnetostatics",
        "fem.cfd-navier-stokes", "fem.cfd-potential",
        "fem.buckling", "fem.harmonic-response", "fem.random-vibration",
        "fem.probabilistic",  # LHS + Karhunen-Loève uncertainty propagation
        "fem.fatigue-sn", "fem.fatigue-haigh", "fem.frf-sweep",
    ]
    if _DOLFINX_AVAILABLE:
        provides.append("fem.linear-static")
        provides.append("fem.thermal")
        if _SLEPC_AVAILABLE:
            provides.append("fem.modal")
    if _CALCULIX_AVAILABLE:
        if "fem.linear-static" not in provides:
            provides.append("fem.linear-static")
        if "fem.modal" not in provides:
            provides.append("fem.modal")

    # Return manifest as a plain dict (PluginManifest from kerf_core when available)
    try:
        from kerf_core.plugin import PluginManifest
        return PluginManifest(
            name="fem",
            version="0.1.0",
            provides=provides,
            depends=["cad-core"],
        )
    except ImportError:
        return {
            "name": "fem",
            "version": "0.1.0",
            "provides": provides,
            "depends": ["cad-core"],
        }
