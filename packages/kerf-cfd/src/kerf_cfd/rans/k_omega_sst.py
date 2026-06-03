"""
k-ω SST turbulence model — Menter (1994).

Overview
--------
The Shear-Stress Transport (SST) k-ω model blends the Wilcox k-ω model near
solid walls (where it is well-behaved) with the standard k-ε model transformed
to k-ω form in the freestream (where k-ω is sensitive to freestream boundary
conditions).  The blending is achieved via the function F1.

Governing equations (incompressible, ρ = const):
-------------------------------------------------
Turbulent kinetic energy k [m²/s²]:

  ∂(ρk)/∂t = P_k − β* ρ k ω + ∇·((μ + μ_t σ_k) ∇k)

Specific dissipation ω [1/s]:

  ∂(ρω)/∂t = α ρ/μ_t · P_k − β ρ ω²
              + ∇·((μ + μ_t σ_ω) ∇ω)
              + 2 ρ (1-F1) σ_ω2 (1/ω) ∇k · ∇ω

Eddy (turbulent) viscosity (SST limiter):

  μ_t = ρ a1 k / max(a1 ω, S F2)

where S = √(2 S_ij S_ij) is the strain-rate magnitude.

Closure constants (Menter 1994, Table 1):
------------------------------------------
Set 1 (inner, k-ω near wall):   σ_k1=0.85, σ_ω1=0.5,   β1=0.075
Set 2 (outer, k-ε freestream):  σ_k2=1.0,  σ_ω2=0.856, β2=0.0828
Common:  β* = 0.09,  a1 = 0.31,  κ = 0.41

Blending:
  F1 = tanh(arg1⁴),
  arg1 = min(max(√k / (β* ω d), 500 ν/(d² ω)), 4 σ_ω2 k / (CD_kω d²))
  CD_kω = max(2 ρ σ_ω2 (1/ω) ∂k·∂ω, 1e-10)

  F2 = tanh(arg2²)
  arg2 = max(2√k / (β* ω d), 500 ν / (d² ω))

References
----------
[Menter1994] Menter F. R., "Two-Equation Eddy-Viscosity Turbulence Models for
             Engineering Applications." AIAA J. 32(8) (1994) 1598-1605.
             Canonical SST model; blending functions F1, F2; Table 1.
[Menter2003] Menter F. R. et al., NASA/TM-2003-212144.
[Wilcox06]   Wilcox D. C., "Turbulence Modeling for CFD." 3rd ed., 2006.
[Pope2000]   Pope S. B., "Turbulent Flows." Cambridge, 2000.  §7.2.
[DS1985]     Driver D. M., Seegmiller H. L., AIAA J. 23(2) (1985) 163-171.
             Backward-facing step; Re_h≈37 300; x_r/h ≈ 6.26.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


# ---------------------------------------------------------------------------
# Model constants — Menter (1994), Table 1
# ---------------------------------------------------------------------------

@dataclass
class KOmegaSSTConstants:
    """
    Menter 1994 k-ω SST model constants.  Two sets (inner k-ω, outer k-ε)
    blended via F1 wall-distance function.

    References: [Menter1994] Table 1; [Menter2003] Table 1.
    """
    # Inner (k-ω near wall)
    sigma_k1: float = 0.85     # turbulent Prandtl for k (inner)   [Menter1994]
    sigma_w1: float = 0.5      # turbulent Prandtl for ω (inner)   [Menter1994]
    beta1:    float = 0.075    # ω-destruction coefficient (inner)  [Menter1994]
    # Outer (k-ε freestream)
    sigma_k2: float = 1.0      # turbulent Prandtl for k (outer)   [Menter1994]
    sigma_w2: float = 0.856    # turbulent Prandtl for ω (outer)   [Menter1994]
    beta2:    float = 0.0828   # ω-destruction coefficient (outer)  [Menter1994]
    # Common constants
    beta_star: float = 0.09    # k-equation dissipation coeff       [Menter1994]
    a1:        float = 0.31    # SST νt limiter                    [Menter1994 eq. 2]
    kappa:     float = 0.41    # von-Kármán constant               [Pope2000 §7.1]


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

@dataclass
class KOmegaSSTState:
    """
    Cell-centred k-ω SST turbulence state for one pseudo-time level.

    Attributes
    ----------
    k      : (Ncells,) turbulent kinetic energy [m²/s²]
    omega  : (Ncells,) specific dissipation rate [1/s]
    mu_t   : (Ncells,) turbulent dynamic viscosity [Pa·s]
    F1     : (Ncells,) blending function (1=near wall, 0=freestream)
    """
    k: np.ndarray
    omega: np.ndarray     # specific dissipation rate [1/s]
    mu_t: np.ndarray
    F1: np.ndarray        # blending function (1=near wall, 0=freestream)


# ---------------------------------------------------------------------------
# Numerical floor constants
# ---------------------------------------------------------------------------

_K_MIN:   float = 1.0e-12
_OMG_MIN: float = 1.0e-12


# ---------------------------------------------------------------------------
# Blending functions
# ---------------------------------------------------------------------------

def _compute_F1_scalar(
    k: float,
    omega: float,
    d: float,
    nu: float,
    grad_k_dot_grad_omega: float,
    c: KOmegaSSTConstants,
) -> float:
    """
    SST blending function F1 at a single cell.

        F1 = tanh(arg1⁴)
        arg1 = min(max(√k / (β* ω d), 500 ν / (d² ω)),
                   4 σ_ω2 k / (CD_kω d²))

    F1 → 1 near walls (k-ω activated), F1 → 0 in freestream (k-ε form).

    References: [Menter1994] eqs. 12-14; [Menter2003] eq. 12-14.
    """
    omega = max(omega, _OMG_MIN)
    k     = max(k,     _K_MIN)
    d     = max(d,     1.0e-15)
    sqrt_k = math.sqrt(k)

    # Cross-diffusion term  CD_kω = max(2 ρ σ_ω2 / ω · ∇k·∇ω, 1e-10)
    cross = 2.0 * c.sigma_w2 * grad_k_dot_grad_omega / omega
    CD_kw = max(cross, 1.0e-10)

    arg1_a = sqrt_k / (c.beta_star * omega * d)
    arg1_b = 500.0 * nu / (d * d * omega)
    arg1_c = 4.0 * c.sigma_w2 * k / (CD_kw * d * d)

    arg1 = min(max(arg1_a, arg1_b), arg1_c)
    return math.tanh(arg1 ** 4)


def _compute_F2_scalar(
    k: float,
    omega: float,
    d: float,
    nu: float,
    c: KOmegaSSTConstants,
) -> float:
    """
    SST blending function F2 at a single cell.

        F2 = tanh(arg2²)
        arg2 = max(2√k / (β* ω d), 500 ν / (d² ω))

    F2 → 1 inside the boundary layer, F2 → 0 outside.
    Used in the SST νt limiter (reduces νt in high-strain regions).

    References: [Menter1994] eq. 15; [Menter2003] eq. 15.
    """
    omega = max(omega, _OMG_MIN)
    k     = max(k,     _K_MIN)
    d     = max(d,     1.0e-15)
    sqrt_k = math.sqrt(k)

    arg2_a = 2.0 * sqrt_k / (c.beta_star * omega * d)
    arg2_b = 500.0 * nu / (d * d * omega)
    arg2   = max(arg2_a, arg2_b)
    return math.tanh(arg2 * arg2)


# ---------------------------------------------------------------------------
# Eddy-viscosity computation (SST form)
# ---------------------------------------------------------------------------

def compute_eddy_viscosity_sst(
    k: np.ndarray,
    omega: np.ndarray,
    strain_rate_mag: np.ndarray,
    F2: np.ndarray,
    rho: float,
    a1: float,
) -> np.ndarray:
    """
    SST turbulent dynamic viscosity.

        μ_t = ρ · a1 · k / max(a1 · ω, S · F2)

    where S = √(2 S_ij S_ij) is the local strain-rate magnitude.

    In the outer layer (F2 → 0 or S small):
        μ_t → ρ k / ω   (standard k-ε/k-ω form)

    In regions of high strain (F2 · S > a1 · ω):
        μ_t < ρ k / ω   (Bradshaw's assumption: τ = ρ a1 k limits νt)

    References: [Menter1994] eq. 2; [Menter2003] eq. 1.

    Parameters
    ----------
    k              : (Ncells,) turbulent kinetic energy [m²/s²]
    omega          : (Ncells,) specific dissipation rate [1/s]
    strain_rate_mag: (Ncells,) |S| = √(2 S_ij S_ij) [1/s]
    F2             : (Ncells,) SST blending function (near-wall = 1)
    rho            : fluid density [kg/m³]
    a1             : SST νt limiter constant (default 0.31)

    Returns
    -------
    mu_t : (Ncells,) turbulent dynamic viscosity [Pa·s], always ≥ 0
    """
    k_safe   = np.maximum(k,     _K_MIN)
    om_safe  = np.maximum(omega, _OMG_MIN)
    denom    = np.maximum(a1 * om_safe, strain_rate_mag * F2)
    return rho * a1 * k_safe / np.maximum(denom, _OMG_MIN)


# ---------------------------------------------------------------------------
# One pseudo-time step of the k-ω SST transport equations
# ---------------------------------------------------------------------------

def step_k_omega_sst(
    state: KOmegaSSTState,
    u: np.ndarray,              # (Ncells, ndim) cell-centred velocity
    grad_u: np.ndarray,         # (Ncells, ndim, ndim) gradient tensor
    wall_distance: np.ndarray,  # (Ncells,) distance to nearest wall [m]
    cell_volumes: np.ndarray,   # (Ncells,)
    cell_neighbours: list[list[int]],
    rho: float,
    mu: float,
    dt: float,
    constants: KOmegaSSTConstants = KOmegaSSTConstants(),
) -> KOmegaSSTState:
    """
    One pseudo-time step of k-ω SST transport equations.

    Implements Menter (1994) k-ω SST model:
        dk/dt = P_k − β* k ω + ∇·((ν + ν_t σ_k) ∇k)
        dω/dt = α S² − β ω² + ∇·((ν + ν_t σ_ω) ∇ω) + CD_cross

    where α, β, σ_k, σ_ω are blended via F1.

    Blending of constants (Menter 1994 eq. 17):
        φ = F1 · φ_1 + (1 − F1) · φ_2

    The cross-diffusion term (outer layer only):
        CD_cross = 2 (1-F1) σ_ω2 / ω · ∇k·∇ω

    References: [Menter1994] eqs. 1-17; [Menter2003].

    Parameters
    ----------
    state          : KOmegaSSTState — current turbulence state
    u              : (Ncells, ndim) cell-centred velocity [m/s]
    grad_u         : (Ncells, ndim, ndim) velocity gradient ∂U_i/∂x_j
    wall_distance  : (Ncells,) wall-normal distance [m]
    cell_volumes   : (Ncells,) cell volumes [m³]
    cell_neighbours: cell_neighbours[i] = [j, k, ...] neighbour indices
    rho            : density [kg/m³]
    mu             : dynamic laminar viscosity [Pa·s]
    dt             : pseudo-time step [s]
    constants      : KOmegaSSTConstants (default: Menter 1994)

    Returns
    -------
    KOmegaSSTState (updated)
    """
    c = constants
    n = len(state.k)
    k     = np.maximum(state.k,     _K_MIN)
    omega = np.maximum(state.omega, _OMG_MIN)
    nu    = mu / rho   # kinematic viscosity

    # 1. Strain-rate tensor and magnitude
    #    S_ij = ½ (∂U_i/∂x_j + ∂U_j/∂x_i)
    S_tensor = 0.5 * (grad_u + np.swapaxes(grad_u, -1, -2))  # (n, ndim, ndim)
    S_sq     = np.einsum('...ij,...ij->...', S_tensor, S_tensor)  # (n,)
    S_mag    = np.sqrt(np.maximum(2.0 * S_sq, 0.0))              # |S| = √(2 S_ij S_ij)

    # 2. Estimate ∇k · ∇ω (stub: assume zero gradient between neighbours means
    #    we approximate via cell-centre differences)
    #    For the blending function we use the FVM-neighbour approximation.
    grad_k_dot_grad_omega = np.zeros(n)
    for i in range(n):
        for j in cell_neighbours[i]:
            dk   = k[j]     - k[i]
            dom  = omega[j] - omega[i]
            grad_k_dot_grad_omega[i] += dk * dom  # |face|/d_nb = 1 (unit stub)

    # 3. Blending functions F1, F2 at each cell
    #    F1 → 1 near wall (k-ω), F1 → 0 freestream (k-ε)  [Menter1994 eq. 12-14]
    F1 = np.array([
        _compute_F1_scalar(
            k[i], omega[i], wall_distance[i], nu,
            grad_k_dot_grad_omega[i], c,
        )
        for i in range(n)
    ])
    F2 = np.array([
        _compute_F2_scalar(k[i], omega[i], wall_distance[i], nu, c)
        for i in range(n)
    ])

    # 4. Blended constants  φ = F1·φ1 + (1-F1)·φ2  [Menter1994 eq. 17]
    alpha    = F1 * (5.0 / 9.0)        + (1.0 - F1) * 0.44
    beta     = F1 * c.beta1            + (1.0 - F1) * c.beta2
    sigma_k  = F1 * c.sigma_k1        + (1.0 - F1) * c.sigma_k2
    sigma_w  = F1 * c.sigma_w1        + (1.0 - F1) * c.sigma_w2

    # 5. Turbulent viscosity (SST limiter)  [Menter1994 eq. 2]
    mu_t = compute_eddy_viscosity_sst(k, omega, S_mag, F2, rho, c.a1)

    # 6. Production  P_k = μ_t · 2 S_ij S_ij  [Menter1994 eq. 3]
    P_k = np.maximum(mu_t * 2.0 * S_sq, 0.0)

    # 7. Effective diffusivities (kinematic)
    nu_k = nu + mu_t / (rho * sigma_k)
    nu_w = nu + mu_t / (rho * sigma_w)

    # 8. Diffusion terms (unit-distance stub FVM)
    diff_k = np.zeros(n)
    diff_w = np.zeros(n)
    for i in range(n):
        for j in cell_neighbours[i]:
            g_k = 0.5 * (nu_k[i] + nu_k[j])
            g_w = 0.5 * (nu_w[i] + nu_w[j])
            diff_k[i] += g_k * (k[j]     - k[i])
            diff_w[i] += g_w * (omega[j] - omega[i])

    # 9. Cross-diffusion term (outer layer, 1-F1 factor)
    #    CD_cross_i = 2(1-F1) σ_ω2 / ω · ∇k·∇ω  [Menter1994 eq. 7]
    CD_cross = 2.0 * (1.0 - F1) * c.sigma_w2 / np.maximum(omega, _OMG_MIN) * grad_k_dot_grad_omega

    # 10. k equation sources
    #     dk/dt = P_k/ρ − β* k ω + diff_k  [Menter1994 eq. 1]
    src_k = P_k / rho - c.beta_star * k * omega + diff_k

    # 11. ω equation sources
    #     dω/dt = α S² − β ω² + diff_w + CD_cross  [Menter1994 eq. 2]
    src_w = alpha * S_mag ** 2 - beta * omega ** 2 + diff_w + CD_cross

    # 12. Forward Euler update
    k_new   = np.maximum(k     + dt * src_k, _K_MIN)
    om_new  = np.maximum(omega + dt * src_w, _OMG_MIN)

    # 13. Recompute μ_t with updated values
    mu_t_new = compute_eddy_viscosity_sst(k_new, om_new, S_mag, F2, rho, c.a1)

    return KOmegaSSTState(k=k_new, omega=om_new, mu_t=mu_t_new, F1=F1)
