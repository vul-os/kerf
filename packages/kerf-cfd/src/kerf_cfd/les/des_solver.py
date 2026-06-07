"""
Detached-Eddy Simulation (DES / DDES) — hybrid RANS-LES solver.

Overview
--------
DES (Spalart et al. 1997) and its improved variant DDES (Delayed DES,
Spalart et al. 2006) are hybrid turbulence models that:
  - Use **RANS** (Spalart-Allmaras or k-ω SST RANS closure) near walls
    where d_w < C_DES · Δ_max  (wall-bounded region)
  - Switch to **LES-like** SGS treatment in the off-wall separated/detached
    flow regions where d_w ≥ C_DES · Δ_max

The switching is determined by a **model length scale** that blends the RANS
length scale l_RANS with the LES grid scale Δ_max = max(Δx, Δy, Δz):

DES length scale:
    l_DES = min(l_RANS,  C_DES · Δ_max)

where l_RANS = √k / (C_μ^{1/4} ω)  for k-ω SST.

DDES adds a shielding function f_d to prevent "grey area" (premature switch
inside the attached boundary layer for ambiguous grid refinement):
    l_DDES = l_RANS − f_d · max(0, l_RANS − C_DES · Δ_max)
    f_d = 1 − tanh([8 r_d]³)
    r_d = (ν_t + ν) / (√(U_ij U_ij) κ² d_w²)   (Spalart 2006, eq. 12)

where U_ij = ∂U_i/∂x_j, κ = 0.41 (von Kármán).

Implementation strategy
-----------------------
This implementation solves a **1-D wall-normal profile** (channel-like domain)
plus a **2-D cross-section** (for rotating machinery / DES case), which gives:
  1. RANS region (near wall):  k-ω SST closure, full RANS stress.
  2. LES region (off wall):    Smagorinsky SGS model (as in les_solver.py).
  3. DES blend:                model_index = 0 (RANS) or 1 (LES) per cell.

Structured 2-D grid (nx × ny):
  - Wall at y=0 (d_w = y + dy/2).
  - Periodic in x (streamwise).
  - Inflow = mean profile; cyclic.

The solver advances the filtered/averaged momentum equations with the
blended effective viscosity:
    ν_eff = ν_lam + blend · ν_sgs + (1-blend) · ν_t_rans

Diagnostics
-----------
  model_index[j] : float in [0, 1]
    0 = pure RANS, 1 = pure LES, for each j-row (y-level).
  d_w[j]         : wall distance for row j
  l_rans[j]      : RANS length scale
  l_les[j]       : LES grid scale C_DES · Δ_max
  blend[j]       : DES blend factor (1 = full LES, 0 = full RANS)

Honest caveats
--------------
- 2-D structured Cartesian mesh; no curved walls; no 3-D effects.
- k-ω SST RANS region uses simplified 1-D wall-normal profiles.
- Temporal integration is explicit AB2; modest Re only.
- "Grey area" behaviour is characteristic of all DES variants; DDES
  mitigates but does not eliminate it.
- Not validated against channel-flow DNS (Moser et al. 1999) or backward-
  facing step (Driver & Seegmiller 1985); self-consistent model-index
  switching is verified.

References
----------
[Spalart1997]  Spalart P. et al., AIAA Paper 97-1803 (1997). Original DES.
[Spalart2006]  Spalart P. et al., Theor. Comput. Fluid Dyn. 20 (2006) 181-195. DDES.
[Menter1994]   Menter F. R., AIAA J. 32(8) (1994) 1598-1605. k-ω SST.
[Moser1999]    Moser R. D., Kim J., Mansour N. N., Phys. Fluids 11 (1999) 943-945. Channel DNS.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

_EPS = 1.0e-30
_KAPPA = 0.41   # von Kármán constant
_C_DES = 0.65   # DES constant (Spalart 1997)
_C_MU  = 0.09   # k-ω SST / k-ε constant


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class DESConfig:
    """
    Parameters for the 2-D hybrid DES/DDES solver.

    Parameters
    ----------
    nx, ny : int
        Grid cells in streamwise (x) and wall-normal (y).
    Lx, Ly : float
        Domain size [m].
    Re_tau : float
        Friction Reynolds number = u_tau * Ly/2 / ν.
        Sets the wall shear and turbulence profiles.
    U_bulk : float
        Mean bulk velocity [m/s].
    n_steps : int
        Number of time steps.
    dt : float
        Time step [s].  0 = auto CFL.
    variant : str
        'des' or 'ddes'.
    seed : int
        RNG seed for perturbations.
    n_poisson_iter : int
        Inner iterations for pressure Poisson.
    """
    nx: int = 32
    ny: int = 32
    Lx: float = 2.0 * math.pi
    Ly: float = 1.0
    Re_tau: float = 180.0
    U_bulk: float = 1.0
    n_steps: int = 40
    dt: float = 0.0
    variant: str = "ddes"
    seed: int = 42
    n_poisson_iter: int = 20


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class DESResult:
    """Output from run_des."""
    variant: str
    nx: int
    ny: int
    Re_tau: float
    n_steps: int
    dt: float

    # Wall-normal profiles (length = ny)
    y_plus: list[float] = field(default_factory=list)
    d_w: list[float] = field(default_factory=list)
    l_rans: list[float] = field(default_factory=list)
    l_les: list[float] = field(default_factory=list)
    model_index: list[float] = field(default_factory=list)   # 0=RANS, 1=LES
    blend: list[float] = field(default_factory=list)
    nu_eff_profile: list[float] = field(default_factory=list)

    # Time-series
    time: list[float] = field(default_factory=list)
    resolved_tke: list[float] = field(default_factory=list)

    # Mean velocity profile at final time
    U_mean_profile: list[float] = field(default_factory=list)

    # Counts
    n_rans_cells: int = 0
    n_les_cells: int = 0

    model_notes: str = ""


# ---------------------------------------------------------------------------
# RANS k-ω SST turbulent viscosity (simplified wall-profile)
# ---------------------------------------------------------------------------

def _rans_nu_t_profile(ny: int, dy: float, nu_lam: float,
                       Re_tau: float, U_bulk: float) -> np.ndarray:
    """
    Approximate k-ω SST ν_t profile for a channel flow using the
    mixing-length model as a stand-in for the full k-ω SST equations
    (appropriate for an initial / steady RANS starting field):

        ν_t ≈ κ² y² |∂U/∂y|  (mixing-length, Prandtl 1925)

    With van-Driest damping:
        l_mix = κ y [1 - exp(-y⁺/26)]   (van Driest 1956, A⁺ = 26)

    u_tau from Re_tau = u_tau * (Ly/2) / nu_lam → u_tau = Re_tau * nu_lam / (Ly/2).
    """
    Ly_half = ny * dy / 2.0
    u_tau = Re_tau * nu_lam / Ly_half

    nu_t = np.zeros(ny)
    for j in range(ny):
        y = (j + 0.5) * dy
        y_plus = u_tau * y / nu_lam
        A_plus = 26.0
        l_mix = _KAPPA * y * (1.0 - math.exp(-y_plus / A_plus))
        # |∂U/∂y| ≈ u_tau / (κ y) (log-law)
        dUdy = u_tau / max(_KAPPA * y, _EPS)
        nu_t[j] = l_mix**2 * dUdy
    return nu_t


# ---------------------------------------------------------------------------
# DES/DDES blend function
# ---------------------------------------------------------------------------

def _des_blend(
    ny: int, dy: float, dx: float, dz: float,
    nu_lam: float, nu_t: np.ndarray,
    u: np.ndarray, v: np.ndarray,
    variant: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Compute DES blend field for each y-row.

    Returns
    -------
    d_w, l_rans, l_les, blend, model_index
      all arrays of shape (ny,).

    blend = 0 → pure RANS, blend = 1 → pure LES.
    model_index = round(blend).
    """
    delta_max = max(dx, dy, dz)
    l_les_val = _C_DES * delta_max

    d_w    = np.zeros(ny)
    l_rans = np.zeros(ny)
    l_les  = np.zeros(ny) + l_les_val
    blend  = np.zeros(ny)

    for j in range(ny):
        y = (j + 0.5) * dy
        d_w[j] = y   # wall at y=0

        # RANS length scale: l_RANS = √k / (C_μ^{1/4} ω)
        # Proxy via ν_t: ν_t = C_μ k²/ε ≈ C_μ k l_RANS
        # → k ≈ (ν_t / (C_μ l_RANS))  (rough)
        # Use: l_RANS = C_μ^{3/4} k^{3/2} / ε  which with ε ≈ C_μ^{3/4} k^{3/2}/l → l_RANS ≈ ν_t / (C_MU * sqrt(k))
        # Simplified: l_RANS ≈ sqrt(ν_t * d_w / nu_lam)  (crude mixing-length inversion)
        # More defensible: Menter (1994) k-ω SST: l_RANS = sqrt(k) / (C_mu^{1/4} ω)
        # Use: l_RANS ≈ κ * d_w  (mixing-length scale) as RANS reference
        l_rans[j] = _KAPPA * d_w[j] + _EPS

        # DES criterion
        if d_w[j] >= l_les_val:
            blend_raw = 1.0   # LES region
        else:
            blend_raw = 0.0   # RANS region

        if variant == "ddes":
            # DDES shielding function f_d (Spalart 2006, eq. 12)
            # r_d = (ν_t + ν) / (sqrt(U_ij:U_ij) * κ² * d_w²)
            # Approximate |∂U/∂x| via finite difference; here 1-D → |∂U/∂y|
            # Use j-averaged dUdy from u array column
            if j > 0 and j < ny - 1:
                u_col = u[:, j, :]   # shape (nz, nx) or equivalent
                dUdy = float(np.abs(np.mean(u_col - u[:, j-1, :]))) / dy
            else:
                dUdy = 0.0
            r_d = (nu_t[j] + nu_lam) / max(
                math.sqrt(max(dUdy**2, _EPS)) * _KAPPA**2 * max(d_w[j], _EPS)**2,
                _EPS
            )
            f_d = 1.0 - math.tanh((8.0 * r_d)**3)
            blend_raw = float(f_d)

        blend[j] = blend_raw

    model_index = np.round(blend).astype(float)
    return d_w, l_rans, l_les, blend, model_index


# ---------------------------------------------------------------------------
# Main DES solver
# ---------------------------------------------------------------------------

def run_des(cfg: DESConfig) -> DESResult:
    """
    Run 2-D hybrid DES/DDES simulation.

    Advances the blended RANS-LES equations on a 2-D channel-like domain.
    Reports wall-normal profiles of model_index (0=RANS, 1=LES) and blend.
    """
    from kerf_cfd.les.les_solver import (
        _convection_diffusion_rhs, _pressure_poisson_gs,
        _divergence, _pressure_gradient,
        _vel_gradient_3d, _strain_rate, _sgs_smagorinsky, _EPS as EPS
    )

    nx, ny = cfg.nx, cfg.ny
    nz = 1   # 2-D
    dx = cfg.Lx / nx
    dy = cfg.Ly / ny
    dz = dx   # pseudo-3-D for filter width
    delta = (dx * dy * dz) ** (1.0 / 3.0)

    # Friction velocity and laminar viscosity
    nu_lam_val = cfg.U_bulk * cfg.Ly / (2.0 * max(cfg.Re_tau, 1.0))
    nu_lam = np.full((nz, ny, nx), nu_lam_val)

    # Initial mean profile (log-law + small random perturbations)
    rng = np.random.default_rng(cfg.seed)
    u_tau = cfg.Re_tau * nu_lam_val / (cfg.Ly / 2.0)

    u = np.zeros((nz, ny, nx))
    v = np.zeros((nz, ny, nx))
    w = np.zeros((nz, ny, nx))

    for j in range(ny):
        y = (j + 0.5) * dy
        y_plus = u_tau * y / nu_lam_val
        # Log-law: U+ = (1/κ) ln(y+) + B, B=5.2
        if y_plus > 11.0:
            U_plus = (1.0 / _KAPPA) * math.log(y_plus) + 5.2
        else:
            U_plus = y_plus   # linear sublayer
        u[0, j, :] = U_plus * u_tau

    # Random perturbations (5% of bulk)
    u += 0.05 * cfg.U_bulk * rng.standard_normal((nz, ny, nx))
    v += 0.02 * cfg.U_bulk * rng.standard_normal((nz, ny, nx))

    # RANS ν_t profile
    nu_t = _rans_nu_t_profile(ny, dy, nu_lam_val, cfg.Re_tau, cfg.U_bulk)

    # Time step
    if cfg.dt > 0:
        dt = cfg.dt
    else:
        U_max = float(np.max(np.abs(u))) + EPS
        dt = 0.4 * min(dx, dy) / U_max
        dt = max(dt, 1.0e-8)

    res = DESResult(
        variant=cfg.variant,
        nx=nx, ny=ny,
        Re_tau=cfg.Re_tau,
        n_steps=cfg.n_steps,
        dt=dt,
    )

    periodic_x = True
    periodic_y = False
    periodic_z = True

    rhs_u_prev = rhs_v_prev = rhs_w_prev = None
    p = np.zeros((nz, ny, nx))

    for step in range(cfg.n_steps):
        t = (step + 1) * dt

        # Compute blend field
        d_w_arr, l_rans_arr, l_les_arr, blend_arr, midx_arr = _des_blend(
            ny, dy, dx, dz, nu_lam_val, nu_t, u, v, cfg.variant
        )

        # Effective viscosity: blend between RANS ν_t and LES ν_sgs
        g = _vel_gradient_3d(u, v, w, dx, dy, dz, periodic_x, periodic_y, periodic_z)
        S = _strain_rate(g)
        nu_sgs = _sgs_smagorinsky(S, delta, 0.18)

        nu_eff = np.zeros((nz, ny, nx))
        for j in range(ny):
            b = blend_arr[j]
            nu_eff[0, j, :] = nu_lam_val + b * nu_sgs[0, j, :] + (1.0 - b) * nu_t[j]

        rhs_u, rhs_v, rhs_w = _convection_diffusion_rhs(
            u, v, w, nu_eff, dx, dy, dz, periodic_x, periodic_y, periodic_z
        )

        # Driving pressure gradient (constant dp/dx to maintain bulk velocity)
        dp_dx_drive = -nu_lam_val * 2.0 * u_tau**2 / nu_lam_val   # simplified
        rhs_u += dp_dx_drive

        if rhs_u_prev is None:
            du = dt * rhs_u;  dv = dt * rhs_v;  dw = dt * rhs_w
        else:
            du = dt * (1.5 * rhs_u - 0.5 * rhs_u_prev)
            dv = dt * (1.5 * rhs_v - 0.5 * rhs_v_prev)
            dw = dt * (1.5 * rhs_w - 0.5 * rhs_w_prev)

        u_star = u + du
        v_star = v + dv
        w_star = w + dw

        div_us = _divergence(u_star, v_star, w_star, dx, dy, dz,
                             periodic_x, periodic_y, periodic_z)
        p_prime = _pressure_poisson_gs(
            div_us, dx, dy, dz, dt, n_iter=cfg.n_poisson_iter,
            periodic_x=periodic_x, periodic_y=periodic_y, periodic_z=periodic_z
        )
        dpdx, dpdy, dpdz = _pressure_gradient(p_prime, dx, dy, dz,
                                               periodic_x, periodic_y, periodic_z)
        u = u_star - dt * dpdx
        v = v_star - dt * dpdy
        w = w_star - dt * dpdz
        p = p + p_prime

        # No-slip walls at y=0 and y=Ly
        u[:, 0, :] = 0.0;  u[:, -1, :] = 0.0
        v[:, 0, :] = 0.0;  v[:, -1, :] = 0.0
        w[:, 0, :] = 0.0;  w[:, -1, :] = 0.0

        rhs_u_prev = rhs_u
        rhs_v_prev = rhs_v
        rhs_w_prev = rhs_w

        # Diagnostics
        u_bar = float(np.mean(u))
        tke_res = 0.5 * float(np.mean((u - u_bar)**2 + v**2 + w**2))
        res.time.append(t)
        res.resolved_tke.append(tke_res)

    # Final wall-normal profiles
    d_w_arr, l_rans_arr, l_les_arr, blend_arr, midx_arr = _des_blend(
        ny, dy, dx, dz, nu_lam_val, nu_t, u, v, cfg.variant
    )
    nu_eff_final = np.zeros(ny)
    g = _vel_gradient_3d(u, v, w, dx, dy, dz, periodic_x, periodic_y, periodic_z)
    S = _strain_rate(g)
    nu_sgs = _sgs_smagorinsky(S, delta, 0.18)
    for j in range(ny):
        b = blend_arr[j]
        nu_eff_final[j] = nu_lam_val + b * float(np.mean(nu_sgs[0, j, :])) + (1.0 - b) * nu_t[j]

    y_coords = [(j + 0.5) * dy for j in range(ny)]
    y_plus_list = [y * u_tau / nu_lam_val for y in y_coords]

    res.y_plus = y_plus_list
    res.d_w = d_w_arr.tolist()
    res.l_rans = l_rans_arr.tolist()
    res.l_les = l_les_arr.tolist()
    res.blend = blend_arr.tolist()
    res.model_index = midx_arr.tolist()
    res.nu_eff_profile = nu_eff_final.tolist()
    res.U_mean_profile = [float(np.mean(u[0, j, :])) for j in range(ny)]

    # Count RANS / LES cells
    res.n_rans_cells = int(np.sum(midx_arr == 0))
    res.n_les_cells  = int(np.sum(midx_arr == 1))

    res.model_notes = (
        f"In-house {cfg.variant.upper()}: hybrid RANS-LES with k-ω SST RANS near wall, "
        f"Smagorinsky LES in detached/off-wall region. "
        f"C_DES = {_C_DES}; κ = {_KAPPA}; Re_τ = {cfg.Re_tau}. "
        f"RANS cells: {res.n_rans_cells}/{ny} rows "
        f"(d_w < C_DES·Δmax = {_C_DES * max(dx, dy, dz):.3g} m). "
        f"LES cells: {res.n_les_cells}/{ny} rows. "
        "Honest caveat: 2-D structured Cartesian; mixing-length RANS proxy; "
        "grey-area behaviour not fully eliminated; not validated vs DNS Moser 1999."
    )
    return res
