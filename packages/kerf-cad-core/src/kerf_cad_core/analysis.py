"""
kerf_cad_core.analysis — public AnalysisType enum for Kerf FEM/CAE.

Enumerates every simulation discipline advertised by the Kerf FEM engine.
Each member carries:

  ``requires`` — set of capability strings that must be present in the
                 active solver configuration before this analysis can run.

The enum is JSON-serialisable via ``.value`` (the string key) and can be
round-tripped with ``AnalysisType(value)``.

Existing values (added before 2026-05-17):
  linear_static, modal, thermal_steady, thermal_transient, buckling

New values wired in this commit (T-100b/c/d/h):
  nonlinear, explicit, acoustics_fem, em_field, em_highfreq, fatigue_fem

Author: imranparuk
"""

from __future__ import annotations

from enum import Enum
from typing import FrozenSet


class AnalysisType(str, Enum):
    """
    Enumeration of FEM / CAE analysis disciplines.

    Each member is a ``str`` subclass whose ``.value`` is the canonical
    JSON/serialisation key.  Members can therefore be compared to plain
    strings and serialised without special handling:

        >>> AnalysisType.linear_static == "linear_static"
        True
        >>> AnalysisType("modal") is AnalysisType.modal
        True

    The ``requires`` property returns a frozenset of capability tags that
    the active solver must expose before the analysis can be dispatched.
    """

    # ------------------------------------------------------------------
    # Pre-existing values — DO NOT change values; byte-exact stability.
    # ------------------------------------------------------------------

    linear_static = "linear_static"
    """Linear static structural analysis.

    Solves [K]{u} = {F} under the assumptions of small displacements,
    linear elastic material, and static loading.

    requires: ``{"linear_solver"}``
    """

    modal = "modal"
    """Natural frequency / modal analysis.

    Solves the generalised eigenvalue problem [K]{φ} = ω² [M]{φ} to
    extract natural frequencies and mode shapes.

    requires: ``{"linear_solver", "eigensolver"}``
    """

    thermal_steady = "thermal_steady"
    """Steady-state thermal analysis.

    Solves the steady heat-conduction equation ∇·(k ∇T) + Q = 0 for the
    temperature field under prescribed thermal boundary conditions.

    requires: ``{"thermal_solver"}``
    """

    thermal_transient = "thermal_transient"
    """Transient thermal analysis.

    Solves ρ c_p ∂T/∂t = ∇·(k ∇T) + Q for time-varying temperature fields
    using an implicit time-integration scheme.

    requires: ``{"thermal_solver", "time_integration"}``
    """

    buckling = "buckling"
    """Linear (Euler) buckling analysis.

    Solves the eigenvalue problem ([K] + λ [K_σ]){φ} = {0} to find the
    lowest buckling load multiplier λ and the associated buckling mode.

    requires: ``{"linear_solver", "eigensolver"}``
    """

    # ------------------------------------------------------------------
    # New values — T-100b, T-100c, T-100d, T-100h
    # ------------------------------------------------------------------

    nonlinear = "nonlinear"
    """Geometrically and/or materially nonlinear static analysis (T-100b).

    Handles large displacements / rotations (geometric nonlinearity) and
    nonlinear material behaviour (plasticity, hyperelasticity, creep) via
    an incremental Newton-Raphson load-stepping scheme with consistent
    tangent stiffness.

    Typical use cases: post-buckling response, rubber components, metal
    forming, contact under large deformation.

    requires: ``{"nonlinear_solver", "material_nonlinear"}``
    """

    explicit = "explicit"
    """Explicit dynamic / crash analysis (T-100c).

    Integrates the equations of motion forward in time using a central-
    difference explicit scheme (no global solve per step).  Suitable for
    short-duration events where implicit convergence is impractical: high-
    rate impact, crash, blast, metal stamping, and drop tests.

    The stable time increment is governed by the Courant–Friedrichs–Lewy
    (CFL) condition:  Δt ≤ L_min / c_wave.

    requires: ``{"explicit_integrator", "contact_explicit"}``
    """

    acoustics_fem = "acoustics_fem"
    """Structural-acoustic / vibroacoustics FEM analysis (T-100c).

    Couples structural vibration with acoustic pressure fields in fluid
    cavities.  Solves the Helmholtz equation ∇²p + k² p = 0 (frequency
    domain) or the full coupled structural-acoustic system for noise,
    vibration, and harshness (NVH) applications.

    requires: ``{"acoustic_solver", "fluid_structure_coupling"}``
    """

    em_field = "em_field"
    """Low-frequency electromagnetic field analysis (T-100c).

    Solves quasi-static Maxwell equations (magnetostatics, eddy-current,
    time-harmonic magnetic) using a vector-potential FEM formulation.
    Covers motors, transformers, magnetic shielding, and induction heating.

    requires: ``{"em_solver_lowfreq", "vector_potential"}``
    """

    em_highfreq = "em_highfreq"
    """High-frequency electromagnetic / microwave analysis (T-100c).

    Full-wave FEM solution of the vector Helmholtz equation for
    waveguides, antennae, radar cross-section, and microwave component
    design.  Supports absorbing boundary conditions and perfectly matched
    layers (PML).

    requires: ``{"em_solver_fullwave", "pml_boundary"}``
    """

    fatigue_fem = "fatigue_fem"
    """FEM-driven fatigue life prediction (T-100d).

    Post-processes stress/strain results from a linear-static or nonlinear
    analysis to compute fatigue damage and life using:
      - S-N (Basquin) stress-life curves (ASTM, BS7608 corpus)
      - ε-N (Coffin-Manson) strain-life
      - Rainflow cycle counting per ASTM E1049
      - Palmgren-Miner cumulative damage

    requires: ``{"linear_solver", "fatigue_postprocessor"}``
    """

    # ------------------------------------------------------------------
    # Capability descriptor
    # ------------------------------------------------------------------

    @property
    def requires(self) -> FrozenSet[str]:
        """Return the frozenset of capability tags required by this analysis."""
        return _REQUIRES[self]


# Capability map — separated to keep the enum body readable.
_REQUIRES: dict[AnalysisType, FrozenSet[str]] = {
    AnalysisType.linear_static:     frozenset({"linear_solver"}),
    AnalysisType.modal:             frozenset({"linear_solver", "eigensolver"}),
    AnalysisType.thermal_steady:    frozenset({"thermal_solver"}),
    AnalysisType.thermal_transient: frozenset({"thermal_solver", "time_integration"}),
    AnalysisType.buckling:          frozenset({"linear_solver", "eigensolver"}),
    AnalysisType.nonlinear:         frozenset({"nonlinear_solver", "material_nonlinear"}),
    AnalysisType.explicit:          frozenset({"explicit_integrator", "contact_explicit"}),
    AnalysisType.acoustics_fem:     frozenset({"acoustic_solver", "fluid_structure_coupling"}),
    AnalysisType.em_field:          frozenset({"em_solver_lowfreq", "vector_potential"}),
    AnalysisType.em_highfreq:       frozenset({"em_solver_fullwave", "pml_boundary"}),
    AnalysisType.fatigue_fem:       frozenset({"linear_solver", "fatigue_postprocessor"}),
}

__all__ = ["AnalysisType"]
