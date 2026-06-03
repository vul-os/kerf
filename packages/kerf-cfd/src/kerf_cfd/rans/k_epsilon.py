"""
Standard k-ε turbulence model — Launder & Spalding (1974).

Overview
--------
Implements the **Launder-Spalding standard k-ε** two-equation RANS closure
for steady, incompressible turbulent flows.  The model solves transport
equations for the turbulent kinetic energy k [m²/s²] and its dissipation
rate ε [m²/s³], yielding the eddy (turbulent) viscosity μ_t that closes
the Reynolds-averaged Navier-Stokes momentum equations.

Governing equations (incompressible, ρ = const):
-------------------------------------------------
Turbulent kinetic energy k [m²/s²]:

  ∂(ρk)/∂t + ∇·(ρuk) = ∇·((μ + μ_t/σ_k)∇k) + P_k − ρε

Dissipation rate ε [m²/s³]:

  ∂(ρε)/∂t + ∇·(ρuε) = ∇·((μ + μ_t/σ_ε)∇ε)
                         + C_ε1 · (ε/k) · P_k − C_ε2 · ρε²/k

Eddy (turbulent) viscosity:

  μ_t = ρ · C_μ · k² / ε

Production of k from mean shear (strain-rate tensor formulation):

  P_k = μ_t · 2 S_ij S_ij  = μ_t · S:S
  S_ij = ½ (∂U_i/∂x_j + ∂U_j/∂x_i)

Standard model constants (Launder & Spalding 1974, Table 1):
------------------------------------------------------------
  C_μ  = 0.09
  C_ε1 = 1.44
  C_ε2 = 1.92
  σ_k  = 1.0
  σ_ε  = 1.3

References
----------
[LS1974]   Launder B. E., Spalding D. B., "The Numerical Computation of
           Turbulent Flows." Comput. Methods Appl. Mech. Engng. 3 (1974)
           269-289.  Canonical k-ε model; Table 1 for constants.
[Wilcox06] Wilcox D. C., "Turbulence Modeling for CFD." 3rd ed., DCW
           Industries, 2006.  §4.2 k-ε model.
[Pope2000] Pope S. B., "Turbulent Flows." Cambridge, 2000. §10.1.
[DS1985]   Driver D. M., Seegmiller H. L., AIAA J. 23(2) (1985) 163-171.
           Backward-facing step; Re_h≈37 300; x_r/h ≈ 6.26 ± 0.10.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np


# ---------------------------------------------------------------------------
# Model constants — Launder & Spalding (1974), Table 1
# ---------------------------------------------------------------------------

@dataclass
class KEpsilonConstants:
    """
    Launder-Spalding 1974 standard k-ε model constants.

    Values from Launder & Spalding (1974), Table 1, determined by fits
    to homogeneous turbulence decay, grid-turbulence experiments, and
    fully-developed pipe flows.

    References: [LS1974] Table 1.
    """
    C_mu: float = 0.09     # eddy-viscosity coefficient  [LS1974 Table 1]
    C_eps1: float = 1.44   # ε-production coefficient    [LS1974 Table 1]
    C_eps2: float = 1.92   # ε-destruction coefficient   [LS1974 Table 1]
    sigma_k: float = 1.0   # turbulent Prandtl number for k   [LS1974 Table 1]
    sigma_eps: float = 1.3 # turbulent Prandtl number for ε   [LS1974 Table 1]


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

@dataclass
class KEpsilonState:
    """
    Cell-centred k-ε turbulence state for one pseudo-time level.

    Attributes
    ----------
    k       : (Ncells,) turbulent kinetic energy [m²/s²]
    epsilon : (Ncells,) turbulent dissipation rate [m²/s³]
    mu_t    : (Ncells,) turbulent dynamic viscosity [Pa·s]
    """
    k: np.ndarray           # (Ncells,) turbulent kinetic energy [m²/s²]
    epsilon: np.ndarray     # (Ncells,) dissipation rate [m²/s³]
    mu_t: np.ndarray        # (Ncells,) turbulent viscosity [Pa·s]


# ---------------------------------------------------------------------------
# Numerical floor constants
# ---------------------------------------------------------------------------

_K_MIN: float = 1.0e-12
_EPS_MIN: float = 1.0e-12


# ---------------------------------------------------------------------------
# Eddy-viscosity computation
# ---------------------------------------------------------------------------

def compute_eddy_viscosity_ke(
    k: np.ndarray,
    epsilon: np.ndarray,
    rho: float,
    constants: KEpsilonConstants = KEpsilonConstants(),
) -> np.ndarray:
    """
    Turbulent dynamic viscosity from the k-ε model.

        μ_t = ρ · C_μ · k² / ε

    [LS1974 eq. 2.1]

    Parameters
    ----------
    k        : (Ncells,) turbulent kinetic energy [m²/s²], must be ≥ 0
    epsilon  : (Ncells,) dissipation rate [m²/s³], must be > 0
    rho      : fluid density [kg/m³]
    constants: KEpsilonConstants (default: Launder-Spalding 1974 values)

    Returns
    -------
    mu_t : (Ncells,) turbulent dynamic viscosity [Pa·s], always ≥ 0
    """
    k_safe   = np.maximum(k,       _K_MIN)
    eps_safe = np.maximum(epsilon, _EPS_MIN)
    return rho * constants.C_mu * k_safe * k_safe / eps_safe


# ---------------------------------------------------------------------------
# Production rate P_k from strain-rate tensor
# ---------------------------------------------------------------------------

def _compute_production(
    mu_t: np.ndarray,
    grad_u: np.ndarray,
) -> np.ndarray:
    """
    Turbulent kinetic energy production rate.

        P_k = μ_t · 2 S_ij S_ij  = μ_t · S:S

    where S_ij = ½ (∂U_i/∂x_j + ∂U_j/∂x_i) is the strain-rate tensor.

    The double contraction S:S = 2 Σ_{ij} S_ij² ≥ 0 for any real tensor,
    so P_k ≥ 0 unconditionally.

    Parameters
    ----------
    mu_t   : (Ncells,) turbulent dynamic viscosity [Pa·s]
    grad_u : (Ncells, ndim, ndim) velocity gradient tensor  ∂U_i/∂x_j

    Returns
    -------
    P_k : (Ncells,) production rate [kg/(m·s³)] = [Pa/s], always ≥ 0
    """
    # S_ij = ½ (grad_u + grad_u^T)
    S = 0.5 * (grad_u + np.swapaxes(grad_u, -1, -2))  # (Ncells, ndim, ndim)
    # S:S = Σ_ij S_ij²  — double contraction
    S_sq = np.einsum('...ij,...ij->...', S, S)         # (Ncells,)
    # P_k = μ_t · 2 S_ij S_ij  (Pope 2000 §10.1 eq. 10.1)
    return mu_t * 2.0 * S_sq


# ---------------------------------------------------------------------------
# One pseudo-time step of the k-ε transport equations
# ---------------------------------------------------------------------------

def step_k_epsilon(
    state: KEpsilonState,
    u: np.ndarray,            # (Ncells, 2 or 3) cell-centred velocity
    grad_u: np.ndarray,       # (Ncells, ndim, ndim) gradient tensor
    cell_volumes: np.ndarray, # (Ncells,)
    cell_neighbours: list[list[int]],
    rho: float,
    mu: float,
    dt: float,
    constants: KEpsilonConstants = KEpsilonConstants(),
) -> KEpsilonState:
    """
    One pseudo-time step of the k-ε transport equations.

    Solves the following transport equations using a cell-centred FVM
    discretisation with explicit Euler time integration:

        dk/dt = P_k − ε + ∇·((μ + μ_t/σ_k) ∇k)           ... (k-eq)
        dε/dt = C_ε1·(ε/k)·P_k − C_ε2·ε²/k + ∇·((μ + μ_t/σ_ε) ∇ε)  ... (ε-eq)

    where:
        P_k = μ_t · 2 S_ij S_ij  (turbulence production)  [LS1974 eq. 2.3]
        μ_t = ρ C_μ k² / ε       (eddy viscosity)          [LS1974 eq. 2.1]

    The diffusion term ∇·(Γ ∇φ) is approximated by a finite-difference
    sum over cell neighbours:
        (∇·(Γ ∇φ))_P ≈ Σ_nb (Γ_face / d_nb) · (φ_nb − φ_P)

    where d_nb = 1 (unit face distance used as a minimal FVM stub when
    proper face geometry is not available).

    Implementation note
    -------------------
    This function is designed as a **minimal, self-contained FVM stub**
    that exercises the full k-ε physics.  It does NOT require a full
    mesh object — only cell volumes, neighbour lists, and the velocity
    gradient tensor.  For production use, replace the diffusion stencil
    with a proper mesh-geometry-aware version.

    References: [LS1974] eqs. 2.1–2.3; [Wilcox06] §4.2; [Pope2000] §10.1.

    Parameters
    ----------
    state            : current KEpsilonState
    u                : (Ncells, ndim) cell-centred velocity [m/s]
    grad_u           : (Ncells, ndim, ndim) velocity gradient ∂U_i/∂x_j
    cell_volumes     : (Ncells,) cell volumes [m³]
    cell_neighbours  : list of lists; cell_neighbours[i] = [j, k, ...]
    rho              : density [kg/m³]
    mu               : dynamic laminar viscosity [Pa·s]
    dt               : pseudo-time step [s]
    constants        : KEpsilonConstants (default: Launder-Spalding 1974)

    Returns
    -------
    KEpsilonState (updated)
    """
    n = len(state.k)
    k   = np.maximum(state.k,       _K_MIN)
    eps = np.maximum(state.epsilon, _EPS_MIN)

    # 1. Eddy viscosity  μ_t = ρ C_μ k² / ε  [LS1974 eq. 2.1]
    mu_t = compute_eddy_viscosity_ke(k, eps, rho, constants)

    # 2. Strain-rate production  P_k = μ_t · 2 S_ij S_ij  [LS1974 eq. 2.3]
    P_k = _compute_production(mu_t, grad_u)
    P_k = np.maximum(P_k, 0.0)   # production is never negative

    # 3. Effective diffusivities
    nu_k   = mu / rho + mu_t / (rho * constants.sigma_k)
    nu_eps = mu / rho + mu_t / (rho * constants.sigma_eps)

    # 4. Diffusion terms (stub FVM: unit face distance, equal area)
    #    ∇·(Γ ∇φ) ≈ Σ_nb Γ_face (φ_nb − φ_P)
    diff_k   = np.zeros(n)
    diff_eps = np.zeros(n)
    for i in range(n):
        for j in cell_neighbours[i]:
            gamma_k   = 0.5 * (nu_k[i]   + nu_k[j])
            gamma_eps = 0.5 * (nu_eps[i]  + nu_eps[j])
            diff_k[i]   += gamma_k   * (k[j]   - k[i])
            diff_eps[i] += gamma_eps * (eps[j] - eps[i])

    # 5. k equation sources
    #    dk/dt = P_k − ε + ∇·(Γ_k ∇k)   [LS1974 eq. 2.2a]
    src_k = P_k - eps + diff_k

    # 6. ε equation sources
    #    dε/dt = C_ε1(ε/k)P_k − C_ε2(ε²/k) + ∇·(Γ_ε ∇ε)   [LS1974 eq. 2.2b]
    eps_over_k = eps / k
    src_eps = (
        constants.C_eps1 * eps_over_k * P_k
        - constants.C_eps2 * eps * eps_over_k
        + diff_eps
    )

    # 7. Forward Euler update with positivity-preserving floor
    k_new   = np.maximum(k   + dt * src_k,   _K_MIN)
    eps_new = np.maximum(eps + dt * src_eps, _EPS_MIN)

    # 8. Recompute μ_t with new k, ε
    mu_t_new = compute_eddy_viscosity_ke(k_new, eps_new, rho, constants)

    return KEpsilonState(k=k_new, epsilon=eps_new, mu_t=mu_t_new)
