"""
Conjugate Heat Transfer — Dirichlet-Neumann domain-decomposition coupling.

Implements coupled fluid-solid temperature computation for conjugate heat
transfer problems where a solid domain (conduction) and fluid domain
(convection) share an interface.

HONEST FLAG: Design-exploration accuracy only.  Not validated against
commercial CHT solvers (ANSYS Fluent, Star-CCM+).  Production solvers use
tighter monolithic or partitioned coupling with under-relaxation controls,
turbulent heat transfer models (y⁺-based wall functions), and higher-order
spatial discretisation.

References
----------
Quarteroni, A., Valli, A. (1999). "Domain Decomposition Methods for Partial
  Differential Equations." Oxford University Press.  §7 — Dirichlet-Neumann
  alternating iterations.
Patankar, S.V. (1980). "Numerical Heat Transfer and Fluid Flow."
  Hemisphere Publishing, New York.  §3 — heat conduction FVM.
Giles, M.B. (1997). "Stability analysis of numerical interface conditions in
  fluid-structure thermal analysis." IJNME 40, 2263–2282.

# Wave 12B: CFD advanced physics (compressible/conjugate-HT/multiphase/marine)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


# ---------------------------------------------------------------------------
# Interface descriptor
# ---------------------------------------------------------------------------

@dataclass
class FluidSolidInterface:
    """
    Describes the shared interface between a fluid and a solid domain.

    Parameters
    ----------
    fluid_cell_ids : indices into the fluid temperature array for cells
                     adjacent to the interface
    solid_cell_ids : corresponding indices into the solid temperature array
    face_pairs     : list of (fluid_face_idx, solid_face_idx) for each
                     shared interface face
    face_areas     : (Nfaces,) area of each interface face [m²].
                     If None, all areas assumed to be 1.0 m².
    """
    fluid_cell_ids: list[int]
    solid_cell_ids: list[int]
    face_pairs: list[tuple[int, int]]
    face_areas: np.ndarray | None = None

    def __post_init__(self):
        n = len(self.face_pairs)
        if self.face_areas is None:
            self.face_areas = np.ones(n)
        else:
            self.face_areas = np.asarray(self.face_areas, dtype=float)
        assert len(self.fluid_cell_ids) == n, "fluid_cell_ids length must match face_pairs"
        assert len(self.solid_cell_ids) == n, "solid_cell_ids length must match face_pairs"


# ---------------------------------------------------------------------------
# Heat flux primitive
# ---------------------------------------------------------------------------

def heat_flux_at_interface(T_fluid_face: float, T_solid_face: float, h: float) -> float:
    """
    Convective heat flux from fluid to solid at one interface face.

    q = h · (T_fluid - T_solid)   [W/m²]

    where h is the convection heat transfer coefficient [W/(m²·K)].

    References
    ----------
    Patankar (1980) §3.3 — boundary heat flux condition.
    Newton's law of cooling.
    """
    return h * (T_fluid_face - T_solid_face)


# ---------------------------------------------------------------------------
# Simplified domain solvers
# ---------------------------------------------------------------------------

def _solve_fluid_domain(
    T_fluid: np.ndarray,
    T_interface_dirichlet: np.ndarray,
    fluid_cell_ids: list[int],
    alpha_relax: float,
) -> np.ndarray:
    """
    Update fluid temperature field with Dirichlet BC at interface.

    Simplified approach: interface cells are relaxed toward the prescribed
    Dirichlet temperature T_interface_dirichlet.  Interior cells remain
    unchanged (operator splitting — in a full solver, these would be updated
    by the convective/diffusive transport equations).

    Patankar (1980) §4 — finite-volume energy equation.
    """
    T_new = T_fluid.copy()
    for k, cell_id in enumerate(fluid_cell_ids):
        T_new[cell_id] = (
            (1.0 - alpha_relax) * T_fluid[cell_id]
            + alpha_relax * T_interface_dirichlet[k]
        )
    return T_new


def _solve_solid_domain(
    T_solid: np.ndarray,
    q_neumann: np.ndarray,
    T_fluid_iface: np.ndarray,
    solid_cell_ids: list[int],
    face_areas: np.ndarray,
    solid_k: float,
    fluid_h: float,
    alpha_relax: float,
) -> np.ndarray:
    """
    Update solid temperature field with Neumann (Robin) BC at interface.

    The solid boundary cell temperature is driven toward the equilibrium value
    imposed by the incoming heat flux:

        T_eq = T_fluid - q / h

    This is the Dirichlet equivalent derived from Newton's law q = h·(T_f - T_s),
    rearranged to T_s = T_f - q/h.  Under-relaxation prevents divergence.

    Patankar (1980) §3 — conduction with boundary heat flux.
    Quarteroni-Valli (1999) §7 — Dirichlet-Neumann alternating iterations.
    """
    T_new = T_solid.copy()
    for k_idx, cell_id in enumerate(solid_cell_ids):
        q = q_neumann[k_idx]
        T_f = T_fluid_iface[k_idx]
        # Equivalent solid interface temperature from Newton's law: T_s = T_f - q/h
        h_guard = max(abs(fluid_h), 1e-12) * (1.0 if fluid_h >= 0 else -1.0)
        T_eq = T_f - q / h_guard
        T_new[cell_id] = (1.0 - alpha_relax) * T_solid[cell_id] + alpha_relax * T_eq
    return T_new


# ---------------------------------------------------------------------------
# Main coupling solver
# ---------------------------------------------------------------------------

def couple_fluid_solid_temperature(
    fluid_T: np.ndarray,
    solid_T: np.ndarray,
    interface: FluidSolidInterface,
    fluid_h: float,
    solid_k: float,
    n_iter: int = 20,
    relaxation: float = 0.5,
    tol: float = 1e-6,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Coupled fluid-solid temperature field via Dirichlet-Neumann iterations.

    Algorithm (Quarteroni-Valli 1999 §7):
    ─────────────────────────────────────
    1. Extract interface temperatures from both sides.
    2. Compute convective heat flux q = h·(T_f - T_s).
    3. Solve fluid domain with T_solid as Dirichlet BC at interface.
    4. Solve solid domain with q as Neumann BC at interface.
    5. Check interface temperature residual; relax and iterate.

    Parameters
    ----------
    fluid_T     : (N_fluid,) fluid temperature array [K]
    solid_T     : (N_solid,) solid temperature array [K]
    interface   : FluidSolidInterface descriptor
    fluid_h     : convection coefficient [W/(m²·K)]
    solid_k     : solid thermal conductivity [W/(m·K)]
    n_iter      : maximum coupling iterations
    relaxation  : under-relaxation factor (0 < ω ≤ 1)
    tol         : convergence criterion on interface ΔT [K]

    Returns
    -------
    (fluid_T_coupled, solid_T_coupled) after convergence or n_iter steps.

    References
    ----------
    Quarteroni & Valli (1999) §7.2 — Dirichlet-Neumann algorithm convergence.
    Giles (1997) — stability criterion ω < 2k/(h·Δx + 2k).
    """
    fluid_T = np.asarray(fluid_T, dtype=float).copy()
    solid_T = np.asarray(solid_T, dtype=float).copy()

    fids = interface.fluid_cell_ids
    sids = interface.solid_cell_ids
    areas = interface.face_areas

    for _it in range(n_iter):
        # Current interface temperatures
        T_f_iface = fluid_T[fids]
        T_s_iface = solid_T[sids]

        # Heat flux: q = h·(T_fluid - T_solid) [W/m²]
        q_iface = np.array([
            heat_flux_at_interface(float(T_f_iface[k]), float(T_s_iface[k]), fluid_h)
            for k in range(len(fids))
        ])

        # Solid sees fluid surface as Dirichlet (temperature continuity at interface)
        # T_dirichlet for fluid = T_solid (Neumann side imposes T_fluid continuity)
        # Dirichlet: fluid receives T_solid at its boundary cells
        fluid_T = _solve_fluid_domain(fluid_T, T_s_iface, fids, relaxation)

        # Neumann: solid receives heat flux from fluid (with fluid T_iface for Robin BC)
        solid_T = _solve_solid_domain(
            solid_T, q_iface, T_f_iface, sids, areas, solid_k, fluid_h, relaxation
        )

        # Convergence check: max interface temperature residual
        T_f_new = fluid_T[fids]
        T_s_new = solid_T[sids]
        residual = np.max(np.abs(T_f_new - T_s_new))
        if residual < tol:
            break

    return fluid_T, solid_T
