"""
Volume of Fluid (VOF) Multiphase Method.

Implements the VOF method for tracking the free interface between two
immiscible fluids (e.g. water/air).  The phase fraction α ∈ [0, 1] per
cell indicates the volume fraction of phase 1 (default: water).

  α = 1  →  pure phase 1 (water)
  α = 0  →  pure phase 2 (air)
  0 < α < 1  →  interface cell

Key algorithms:
  1. Upwind advection of α with interface compression (MULES — Multidimensional
     Universal Limiter with Explicit Solution, as in OpenFOAM).
  2. PLIC (Piecewise Linear Interface Calculation) for sub-cell interface
     reconstruction from the Youngs (1982) finite-difference gradient estimate.
  3. CFL-limited sub-stepping to maintain stability.

HONEST FLAG: Design-exploration accuracy only.  Production VOF uses OpenFOAM
interFoam, Star-CCM+ or Ansys Fluent with adaptive mesh refinement near the
interface and surface-tension modelling (CSF, Brackbill 1992).

References
----------
Hirt, C.W., Nichols, B.D. (1981). "Volume of fluid (VOF) method for the
  dynamics of free boundaries." J. Comput. Phys. 39(1), 201–225.
Youngs, D.L. (1982). "Time-dependent multi-material flow with large fluid
  distortion." Num. Meth. Fluid Dyn., Academic Press, pp. 273–285.
Weller, H.G. (2008). "A new approach to VOF-based interface capturing
  methods for incompressible and compressible flow." OpenFOAM Tech. Rep.
Rider, W.J., Kothe, D.B. (1998). "Reconstructing volume tracking."
  J. Comput. Phys. 141, 112–152.

# Wave 12B: CFD advanced physics (compressible/conjugate-HT/multiphase/marine)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# VofState
# ---------------------------------------------------------------------------

@dataclass
class VofState:
    """
    Volume-of-Fluid state — α ∈ [0, 1] per cell tracks phase fraction.

    Parameters
    ----------
    alpha      : (Ncells,)  volume fraction of phase 1 [dimensionless, 0–1]
    velocity   : (Ncells, ndim)  shared velocity field [m/s]
    rho_phase1 : density of phase 1 [kg/m³]  (default: water 1000)
    rho_phase2 : density of phase 2 [kg/m³]  (default: air 1.225)
    mu_phase1  : dynamic viscosity phase 1 [Pa·s]
    mu_phase2  : dynamic viscosity phase 2 [Pa·s]

    References
    ----------
    Hirt & Nichols (1981) §2 — VOF function definition.
    """
    alpha: np.ndarray              # (Ncells,)
    velocity: np.ndarray           # (Ncells, ndim)
    rho_phase1: float = 1000.0     # water [kg/m³]
    rho_phase2: float = 1.225      # air   [kg/m³]
    mu_phase1: float = 1.0e-3      # water [Pa·s]
    mu_phase2: float = 1.8e-5      # air   [Pa·s]

    def __post_init__(self):
        self.alpha = np.asarray(self.alpha, dtype=float)
        self.velocity = np.asarray(self.velocity, dtype=float)
        if self.velocity.ndim == 1:
            self.velocity = self.velocity[:, None]
        # Clip to [0, 1] for robustness
        self.alpha = np.clip(self.alpha, 0.0, 1.0)


# ---------------------------------------------------------------------------
# Mixture properties
# ---------------------------------------------------------------------------

def mixture_density(state: VofState) -> np.ndarray:
    """
    Mixture density by linear interpolation of phase densities.

    ρ_mix = α·ρ₁ + (1-α)·ρ₂

    Standard VOF mixture model — volume-weighted average.
    Hirt & Nichols (1981) Eq. 1.
    """
    return state.alpha * state.rho_phase1 + (1.0 - state.alpha) * state.rho_phase2


def mixture_viscosity(state: VofState) -> np.ndarray:
    """
    Mixture dynamic viscosity (arithmetic mean — VOF standard).

    μ_mix = α·μ₁ + (1-α)·μ₂
    """
    return state.alpha * state.mu_phase1 + (1.0 - state.alpha) * state.mu_phase2


# ---------------------------------------------------------------------------
# Interface reconstruction — PLIC (Youngs 1982)
# ---------------------------------------------------------------------------

def interface_reconstruction_plic(
    state: VofState,
    neighbours: list[list[int]],
) -> dict[int, np.ndarray]:
    """
    PLIC — Piecewise Linear Interface Calculation.

    Computes a unit normal for each interface cell using finite-difference
    estimates of ∇α (Youngs 1982 finite-difference stencil).

    For an interface cell (0 < α < 1), the interface is represented as a
    plane:  n̂ · x = d  within the cell.

    Parameters
    ----------
    state      : VofState with current α field
    neighbours : for each cell i, list of neighbour cell indices

    Returns
    -------
    normals : dict mapping cell_index → unit normal vector (ndim,)
              Only interface cells (0 < α < 1) are included.

    References
    ----------
    Youngs (1982) — finite-difference estimate of ∇α, pp. 273–285.
    Rider & Kothe (1998) §3.2 — Youngs' gradient stencil.
    """
    alpha = state.alpha
    normals: dict[int, np.ndarray] = {}
    ncells = len(alpha)

    for i in range(ncells):
        if alpha[i] <= 0.0 or alpha[i] >= 1.0:
            continue  # not an interface cell

        nbrs = neighbours[i] if i < len(neighbours) else []
        if not nbrs:
            # Isolated cell — normal undefined; use placeholder
            normals[i] = np.zeros(state.velocity.shape[1])
            continue

        # Youngs gradient: ∇α ≈ (α_j - α_i) / (j - i) summed over neighbours
        grad = np.zeros(state.velocity.shape[1])
        ndim = state.velocity.shape[1]
        for j in nbrs:
            if j < ncells:
                # Approximate unit cell spacing between i and j
                d_alpha = alpha[j] - alpha[i]
                # Direction approximation: unit vector in each dimension
                # (for structured-like usage; general unstructured requires cell centroid geometry)
                direction = np.zeros(ndim)
                if ndim >= 1:
                    direction[0] = float(j - i)  # signed index offset as proxy
                mag = np.linalg.norm(direction)
                if mag > 0:
                    direction /= mag
                grad += d_alpha * direction

        grad_mag = np.linalg.norm(grad)
        if grad_mag > 1e-14:
            normals[i] = -grad / grad_mag   # normal points from phase1→phase2
        else:
            normals[i] = np.zeros(ndim)

    return normals


# ---------------------------------------------------------------------------
# VOF advection step
# ---------------------------------------------------------------------------

def _cfl_number(state: VofState, face_areas: np.ndarray, neighbours: list[tuple[int, int]], dt: float) -> float:
    """Estimate maximum CFL number over all faces."""
    cfl_max = 0.0
    ndim = state.velocity.shape[1]
    for i_face, (iL, iR) in enumerate(neighbours):
        A = face_areas[i_face]
        u_face = 0.5 * (state.velocity[iL] + state.velocity[iR])
        u_n = np.linalg.norm(u_face) * A  # approximate |u_n|·A
        # CFL ~ |u|·dt/Δx; use face area as proxy for 1/Δx in 2-D/3-D
        cfl_max = max(cfl_max, u_n * dt)
    return cfl_max


def step_vof(
    state: VofState,
    face_areas: np.ndarray,
    face_normals: np.ndarray,
    neighbours: list[tuple[int, int]],
    dt: float,
    courant_max: float = 0.5,
) -> VofState:
    """
    Advance the VOF α field by one time step via upwind advection with
    interface compression.

    Algorithm (Hirt-Nichols 1981 + Weller MULES compressive term):
    ──────────────────────────────────────────────────────────────
    1. Sub-step dt into n sub-steps so that CFL ≤ courant_max.
    2. For each sub-step:
       a. Compute face-centre α via donor-cell (upwind) interpolation.
       b. Add interface-compression flux: C_α · |U_face| · ∇α ·  n̂ · α(1-α)
          to keep interface sharp (Weller 2008).
       c. Advance α via FVM divergence theorem:
          α^{n+1}_i = α^n_i - (dt_sub/V_i) · Σ_faces (α_f · U_f · A_f)
    3. Clip result to [0, 1] to handle floating-point drift.

    Parameters
    ----------
    state        : current VofState
    face_areas   : (Nfaces,) face areas [m²]
    face_normals : (Nfaces, ndim) area-weighted face normal vectors
    neighbours   : list of (left_cell, right_cell) index pairs
    dt           : time step [s]
    courant_max  : maximum Courant number per sub-step (default 0.5)

    Returns
    -------
    Updated VofState with new α field (velocity unchanged).

    References
    ----------
    Hirt & Nichols (1981) §3 — donor-cell advection algorithm.
    Weller (2008) — MULES compressive flux for interface sharpening.
    """
    face_areas = np.asarray(face_areas, dtype=float)
    face_normals = np.asarray(face_normals, dtype=float)

    ncells = len(state.alpha)
    cell_volumes = np.ones(ncells)   # unit volumes if not provided; caller should scale

    # Estimate sub-steps needed
    alpha = state.alpha.copy()
    u_vel = state.velocity

    # Estimate CFL from velocity and face sizes
    u_max = np.max(np.linalg.norm(u_vel, axis=1)) if len(u_vel) > 0 else 0.0
    A_min = np.min(face_areas) if len(face_areas) > 0 else 1.0
    # Rough CFL estimate: dt * u_max / (V/A) ~ dt * u_max * A_min
    cfl_est = dt * u_max * A_min
    n_sub = max(1, int(np.ceil(cfl_est / courant_max + 1e-10)))
    dt_sub = dt / n_sub

    for _sub in range(n_sub):
        d_alpha = np.zeros(ncells)

        for i_face, (iL, iR) in enumerate(neighbours):
            A = face_areas[i_face]
            n_vec = face_normals[i_face]
            n_hat = n_vec / (np.linalg.norm(n_vec) + 1e-14)

            # Face velocity (average of two cell centres)
            u_face = 0.5 * (u_vel[iL] + u_vel[iR])
            u_n = float(np.dot(u_face, n_hat)) * A   # volume flux through face

            # Upwind α on face
            if u_n >= 0.0:
                alpha_f = alpha[iL]   # left cell is upwind
            else:
                alpha_f = alpha[iR]   # right cell is upwind

            # Interface compression (Weller MULES): add c_alpha * |u_n| * α(1-α)
            # c_alpha tunable; typical value 1.0
            c_alpha = 1.0
            alpha_bar = 0.5 * (alpha[iL] + alpha[iR])
            compress = c_alpha * abs(u_n) * alpha_bar * (1.0 - alpha_bar)
            # Sign: compress flows toward lower-α side to sharpen interface
            if alpha[iL] > alpha[iR]:
                compress_sign = 1.0
            else:
                compress_sign = -1.0

            flux = (alpha_f * u_n + compress_sign * compress) * dt_sub

            d_alpha[iL] -= flux / cell_volumes[iL]
            d_alpha[iR] += flux / cell_volumes[iR]

        alpha = np.clip(alpha + d_alpha, 0.0, 1.0)

    return VofState(
        alpha=alpha,
        velocity=state.velocity,
        rho_phase1=state.rho_phase1,
        rho_phase2=state.rho_phase2,
        mu_phase1=state.mu_phase1,
        mu_phase2=state.mu_phase2,
    )


# ---------------------------------------------------------------------------
# Surface tension — Continuum Surface Force (CSF) model
# ---------------------------------------------------------------------------

def interface_curvature_2d(
    alpha: np.ndarray,
    cell_centres: np.ndarray,
) -> np.ndarray:
    """
    Estimate interface curvature κ from α gradients (2-D Cartesian grid).

    Uses the Brackbill (1992) Continuum Surface Force (CSF) approach:
      n̂ = ∇α / |∇α|                       (interface normal)
      κ  = −∇·n̂                           (mean curvature)

    Gradient computed by finite-difference stencil on the sorted cell centres.

    Parameters
    ----------
    alpha        : (Ncells,) volume fraction [0, 1]
    cell_centres : (Ncells, 2) cell centroid coordinates [m]

    Returns
    -------
    kappa : (Ncells,) interface curvature [1/m].
            Non-interface cells (α ≈ 0 or α ≈ 1) return 0.

    References
    ----------
    Brackbill, J.U., Kothe, D.B., Zemach, C. (1992). "A continuum method for
    modeling surface tension." J. Comput. Phys. 100(2), 335–354.
    """
    alpha = np.asarray(alpha, dtype=float)
    centres = np.asarray(cell_centres, dtype=float)
    ncells = len(alpha)
    kappa = np.zeros(ncells)

    if centres.ndim != 2 or centres.shape[1] < 2:
        return kappa

    # Identify interface cells: 0.01 < α < 0.99
    intf = (alpha > 0.01) & (alpha < 0.99)

    # For each interface cell estimate ∇α by nearest-4 neighbours
    for i in range(ncells):
        if not intf[i]:
            continue
        xi, yi = centres[i, 0], centres[i, 1]
        dists = np.sqrt((centres[:, 0] - xi) ** 2 + (centres[:, 1] - yi) ** 2)
        dists[i] = 1e20  # exclude self
        nn_idx = np.argsort(dists)[:6]   # up to 6 neighbours

        if len(nn_idx) < 2:
            continue

        # Weighted least-squares gradient ∇α
        dx = centres[nn_idx, 0] - xi
        dy = centres[nn_idx, 1] - yi
        da = alpha[nn_idx] - alpha[i]
        w = 1.0 / (dists[nn_idx] + 1e-12)

        # WLS normal equations:  [A^T W A] g = A^T W b
        A = np.column_stack([dx, dy])
        W = np.diag(w)
        AtWA = A.T @ W @ A
        AtWb = A.T @ (W @ da)
        try:
            grad = np.linalg.solve(AtWA, AtWb)
        except np.linalg.LinAlgError:
            continue

        # Curvature κ ≈ -∇·(∇α / |∇α|) — approximate as -div(n̂) on stencil
        # For scalar field, κ ≈ (∂²α/∂x² + ∂²α/∂y²) / |∇α|³ (Brackbill 1992)
        grad_mag = np.linalg.norm(grad)
        if grad_mag < 1e-10:
            continue

        # Second derivatives from WLS (include x², y², xy terms)
        A2 = np.column_stack([dx, dy, 0.5 * dx ** 2, 0.5 * dy ** 2, dx * dy])
        AtWA2 = A2.T @ W @ A2
        AtWb2 = A2.T @ (W @ da)
        try:
            coeffs = np.linalg.lstsq(AtWA2, AtWb2, rcond=None)[0]
            d2alpha_dx2 = coeffs[2]
            d2alpha_dy2 = coeffs[3]
        except Exception:
            d2alpha_dx2 = 0.0
            d2alpha_dy2 = 0.0

        # κ = −(d²α/dx² + d²α/dy²) / |∇α|  (Brackbill 1992 Eq. 14)
        kappa[i] = -(d2alpha_dx2 + d2alpha_dy2) / (grad_mag + 1e-12)

    return kappa


def surface_tension_pressure_jump(
    kappa: np.ndarray,
    sigma_N_per_m: float = 0.072,
) -> np.ndarray:
    """
    Young-Laplace pressure jump across the interface.

    Δp = σ · κ   (Young-Laplace equation, 2-D: one principal curvature)
    Δp = 2σ · κ  (3-D sphere: two equal principal curvatures)

    This function returns the 2-D form (one curvature).  Multiply by 2 for
    a spherical drop/bubble.

    Parameters
    ----------
    kappa          : (Ncells,) interface curvature [1/m]
    sigma_N_per_m  : surface tension coefficient [N/m]
                     default 0.072 N/m (water-air at 20°C)

    Returns
    -------
    dp_surface_tension : (Ncells,) pressure jump [Pa]

    References
    ----------
    Young, T. (1805). Phil. Trans. R. Soc. 95, 65–87.
    Laplace, P.S. (1806). Mécanique Céleste, Supplement.
    Brackbill (1992) §2 — CSF pressure jump.
    """
    return sigma_N_per_m * np.asarray(kappa, dtype=float)


def weber_number(
    rho: float,
    U: float,
    L: float,
    sigma: float,
) -> float:
    """
    Weber number We = ρ U² L / σ.

    Ratio of inertial to surface tension forces.
    We < 1 → surface tension dominant (droplet stable).
    We > 1 → inertia dominant (breakup possible).

    Parameters
    ----------
    rho   : fluid density [kg/m³]
    U     : characteristic velocity [m/s]
    L     : characteristic length (drop diameter, jet diameter) [m]
    sigma : surface tension [N/m]

    Returns
    -------
    We : Weber number (dimensionless)

    References
    ----------
    Weber, C. (1931). Z. Angew. Math. Mech. 11(2) — breakup of liquid jets.
    Ashgriz, N. (2011). "Handbook of Atomization and Sprays." Springer. §2.
    """
    return rho * U ** 2 * L / max(sigma, 1e-20)


def ohnesorge_number(
    mu: float,
    rho: float,
    L: float,
    sigma: float,
) -> float:
    """
    Ohnesorge number Oh = μ / √(ρ L σ).

    Compares viscous to inertial-capillary forces.
    Oh << 1 → inviscid breakup regime.
    Oh >> 1 → viscous dripping regime.

    References
    ----------
    Ohnesorge, W. (1936). Z. Angew. Math. Mech. 16, 355–358.
    """
    denom = math.sqrt(max(rho * L * sigma, 1e-30))
    return mu / denom
