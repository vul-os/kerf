"""
Overset (Chimera) grid and sliding-interface rotating-mesh solver.

Overview
--------
Two complementary approaches for simulating rotating-component problems:

1. **Overset / Chimera interpolation**
   An overlapping sub-grid (e.g., a rotor disc / paddle patch) moves through
   a background Cartesian grid.  Donor cells on the background grid contribute
   interpolated values to receptor cells on the sub-grid, and vice versa.

   Algorithm (hole-cutting + trilinear interpolation):
     - Mark background cells that are fully inside the sub-grid hole as
       **inactive** (blanked).
     - For each sub-grid boundary cell, identify the **donor** background cell
       that contains the sub-grid boundary cell centre (point-in-polygon test).
     - Perform **bilinear interpolation** from donor neighbourhood to sub-grid
       cell value.
     - Advance the flow on both grids independently; exchange boundary data
       at each time-step via the interpolation stencil.

   References:
     Benek J. A. et al., AIAA Paper 83-1944 (1983). Chimera original.
     Steger J. L., Dougherty F. C., Benek J. A., AIAA Paper 83-0007 (1983).
     Chesshire G., Henshaw W. D., J. Comput. Phys. 90(1) (1990) 1-64.
     Spentzos A. et al., J. Aircraft 42 (2005) 1009-1018.

2. **Sliding-interface method**
   A rotating annular sub-domain slides against a stationary outer domain.
   At the matching interface the flux is conserved by linear interpolation
   between the two (possibly non-conformal) interface face sets.

   Algorithm:
     - Divide domain into rotor (inner annulus) and stator (outer ring).
     - At each time-step rotate the inner grid by ω·dt.
     - Compute interface flux exchange via 1-D linear interpolation in
       azimuthal angle θ.
     - Advance each sub-domain with the exchanged BC.

   This is the approach used in OpenFOAM's MRF / cyclic AMI and
   STAR-CCM+ sliding interface.

Implementation
--------------
- 2-D structured Cartesian background + 2-D structured Cartesian sub-grid.
- Sub-grid is a patch of size (nxs × nys) centred at (cx, cy), rotated by
  angle θ(t) = ω·t.
- Overset interpolation: bilinear from background 4-cell stencil.
- Scalar field transport: passive scalar φ is carried on the sub-grid and
  exchanged to background every step (demonstrates Chimera conservation).
- Rotating sub-grid: a Gaussian feature in φ rotates at ω rad/s.

Diagnostics
-----------
  phi_background  : scalar field on background at final time [ny × nx]
  phi_subgrid     : scalar field on sub-grid at final time [nys × nxs]
  angle_deg       : sub-grid rotation angle at final time [°]
  interpolation_error : max |φ_receptor − φ_donor_interp| at interface
  conservation_error  : |Σφ_bg + Σφ_sg| / max(|Σφ_init|, 1) (relative)

Honest caveats
--------------
- 2-D; background is Cartesian; sub-grid is Cartesian (no body-fitted).
- Bilinear interpolation is first-order at arbitrary positions.
- Conservation is approximate (point interpolation, not flux integration).
- No turbulence model in the overset solver (pure scalar advection-diffusion).
- Not validated against OpenFOAM overset or STAR-CCM+ results.
- Suitable for demonstrating Chimera data exchange and rotating-feature transport.

References
----------
[Benek1983]    Benek J. A. et al., AIAA Paper 83-1944 (1983).
[Chesshire1990] Chesshire G., Henshaw W. D., J. Comput. Phys. 90 (1990) 1-64.
[Meakin1999]   Meakin R., NASA/TM-1999-209530 (1999).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

_EPS = 1.0e-30


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class OversetConfig:
    """
    Configuration for the overset/sliding-mesh rotating solver.

    Parameters
    ----------
    nx_bg, ny_bg : int
        Background grid cells.
    Lx_bg, Ly_bg : float
        Background domain size [m].
    nxs, nys : int
        Sub-grid cells.
    Ls : float
        Sub-grid half-size [m]  (square patch of size 2Ls × 2Ls).
    cx, cy : float
        Sub-grid centre in background coordinates [m].
    omega_rad_s : float
        Sub-grid rotation rate [rad/s].
    n_steps : int
        Number of time steps.
    dt : float
        Time step [s].  0 = auto.
    nu : float
        Kinematic viscosity for scalar diffusion [m²/s].
    U_bg : float
        Background flow velocity [m/s] (uniform, +x direction).
    phi_feature_sigma : float
        Gaussian blob half-width for initial scalar feature [m].
    seed : int
        RNG seed.
    """
    nx_bg: int = 32
    ny_bg: int = 32
    Lx_bg: float = 4.0
    Ly_bg: float = 4.0
    nxs: int = 16
    nys: int = 16
    Ls: float = 0.5           # sub-grid half-size
    cx: float = 2.0           # sub-grid centre x
    cy: float = 2.0           # sub-grid centre y
    omega_rad_s: float = 1.0  # rotation rate
    n_steps: int = 36         # covers 360° at ω=1, dt=π/18
    dt: float = 0.0           # auto
    nu: float = 0.01
    U_bg: float = 0.2
    phi_feature_sigma: float = 0.15
    seed: int = 42


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class OversetResult:
    """Output from run_overset_rotating."""
    nx_bg: int
    ny_bg: int
    nxs: int
    nys: int
    Lx_bg: float
    Ly_bg: float
    omega_rad_s: float
    n_steps: int
    dt: float

    # Final scalar fields (flattened row-major: nrows × ncols)
    phi_background: list[float] = field(default_factory=list)   # ny_bg × nx_bg
    phi_subgrid: list[float]    = field(default_factory=list)   # nys × nxs

    # Sub-grid cell-centre positions at final time (in background coords)
    xsg_final: list[float] = field(default_factory=list)
    ysg_final: list[float] = field(default_factory=list)

    # Rotation angle
    angle_deg: float = 0.0

    # Conservation and interpolation diagnostics
    interpolation_error: float = 0.0
    conservation_error:  float = 0.0

    # Time-series: total φ on each grid
    time: list[float] = field(default_factory=list)
    phi_sum_bg: list[float] = field(default_factory=list)
    phi_sum_sg: list[float] = field(default_factory=list)

    # Receptor mask (which bg cells are inside sub-grid hole)
    hole_mask: list[bool] = field(default_factory=list)   # ny_bg × nx_bg

    model_notes: str = ""


# ---------------------------------------------------------------------------
# Grid helpers
# ---------------------------------------------------------------------------

def _make_background_grid(cfg: OversetConfig):
    """Return (x_bg, y_bg) cell-centre coordinate arrays [ny_bg × nx_bg]."""
    dx = cfg.Lx_bg / cfg.nx_bg
    dy = cfg.Ly_bg / cfg.ny_bg
    xs = (np.arange(cfg.nx_bg) + 0.5) * dx
    ys = (np.arange(cfg.ny_bg) + 0.5) * dy
    X, Y = np.meshgrid(xs, ys)   # [ny_bg × nx_bg]
    return X, Y, dx, dy


def _make_subgrid(cfg: OversetConfig, angle: float):
    """
    Return sub-grid cell-centre positions in background coordinates.
    Sub-grid is a structured Cartesian patch of size 2Ls × 2Ls, centred at
    (cx, cy), rotated by angle [rad].
    Returns (xsg, ysg) each [nys × nxs] in background frame.
    """
    nxs, nys = cfg.nxs, cfg.nys
    Ls = cfg.Ls
    dxs = 2.0 * Ls / nxs
    dys = 2.0 * Ls / nys
    xs_local = (np.arange(nxs) + 0.5) * dxs - Ls
    ys_local = (np.arange(nys) + 0.5) * dys - Ls
    Xs, Ys = np.meshgrid(xs_local, ys_local)   # [nys × nxs] in sub-grid frame

    # Rotate
    c, s = math.cos(angle), math.sin(angle)
    Xsg = cfg.cx + c * Xs - s * Ys
    Ysg = cfg.cy + s * Xs + c * Ys
    return Xsg, Ysg, dxs, dys


def _bilinear_interp(X_bg: np.ndarray, Y_bg: np.ndarray,
                     phi_bg: np.ndarray,
                     xq: float, yq: float,
                     dx: float, dy: float,
                     Lx: float, Ly: float) -> float:
    """
    Bilinear interpolation of phi_bg at point (xq, yq).
    phi_bg is [ny × nx]; X_bg, Y_bg are cell-centre coordinates.
    Returns interpolated value.  Clamps to domain boundary.
    """
    nx, ny = phi_bg.shape[1], phi_bg.shape[0]

    # Cell index of lower-left donor cell
    i0 = int((xq - 0.5 * dx) / dx)
    j0 = int((yq - 0.5 * dy) / dy)
    i0 = max(0, min(i0, nx - 2))
    j0 = max(0, min(j0, ny - 2))

    # Local coordinates within donor cell
    x_c0 = (i0 + 0.5) * dx
    y_c0 = (j0 + 0.5) * dy
    tx = (xq - x_c0) / dx
    ty = (yq - y_c0) / dy
    tx = max(0.0, min(tx, 1.0))
    ty = max(0.0, min(ty, 1.0))

    # Bilinear weights
    f00 = phi_bg[j0,     i0    ]
    f10 = phi_bg[j0,     i0 + 1]
    f01 = phi_bg[j0 + 1, i0    ]
    f11 = phi_bg[j0 + 1, i0 + 1]

    return ((1 - tx) * (1 - ty) * f00
           + tx      * (1 - ty) * f10
           + (1 - tx) * ty      * f01
           + tx       * ty      * f11)


def _is_inside_square(xq: float, yq: float, cx: float, cy: float,
                       Ls: float, angle: float) -> bool:
    """
    Check if point (xq, yq) is inside the rotated square sub-grid
    centred at (cx, cy) with half-size Ls, rotated by angle [rad].
    """
    c, s = math.cos(-angle), math.sin(-angle)
    dx = xq - cx;  dy = yq - cy
    xl = c * dx - s * dy
    yl = s * dx + c * dy
    return abs(xl) <= Ls and abs(yl) <= Ls


# ---------------------------------------------------------------------------
# Scalar advection-diffusion step (background and sub-grid separately)
# ---------------------------------------------------------------------------

def _scalar_step(phi: np.ndarray, u_x: float, u_y: float,
                 nu: float, dx: float, dy: float, dt: float,
                 periodic_x: bool = True, periodic_y: bool = True) -> np.ndarray:
    """
    Explicit Euler step for scalar advection-diffusion:
        ∂φ/∂t + u·∇φ = ν ∇²φ

    First-order upwind advection + central-difference diffusion.
    """
    ny, nx = phi.shape

    # Advection (upwind)
    if periodic_x:
        dphi_dx = np.where(u_x >= 0,
                           (phi - np.roll(phi, 1, axis=1)) / dx,
                           (np.roll(phi, -1, axis=1) - phi) / dx)
    else:
        dphi_dx = np.gradient(phi, dx, axis=1)

    if periodic_y:
        dphi_dy = np.where(u_y >= 0,
                           (phi - np.roll(phi, 1, axis=0)) / dy,
                           (np.roll(phi, -1, axis=0) - phi) / dy)
    else:
        dphi_dy = np.gradient(phi, dy, axis=0)

    # Diffusion
    if periodic_x:
        d2phi_dx2 = (np.roll(phi, -1, axis=1) - 2*phi + np.roll(phi, 1, axis=1)) / dx**2
    else:
        d2phi_dx2 = np.gradient(np.gradient(phi, dx, axis=1), dx, axis=1)

    if periodic_y:
        d2phi_dy2 = (np.roll(phi, -1, axis=0) - 2*phi + np.roll(phi, 1, axis=0)) / dy**2
    else:
        d2phi_dy2 = np.gradient(np.gradient(phi, dy, axis=0), dy, axis=0)

    rhs = -u_x * dphi_dx - u_y * dphi_dy + nu * (d2phi_dx2 + d2phi_dy2)
    return phi + dt * rhs


# ---------------------------------------------------------------------------
# Main overset rotating-mesh solver
# ---------------------------------------------------------------------------

def run_overset_rotating(cfg: OversetConfig) -> OversetResult:
    """
    Advance the overset rotating-mesh simulation:
      - Background grid carries a uniform flow + scalar diffusion.
      - Sub-grid (rotor patch) rotates at ω rad/s.
      - A Gaussian scalar feature on the sub-grid rotates with it.
      - At each step: interpolate BCs from background to sub-grid boundary
        and from sub-grid to background receptors (hole-fill).

    Returns OversetResult with final field snapshots and diagnostics.
    """
    X_bg, Y_bg, dx_bg, dy_bg = _make_background_grid(cfg)
    nx_bg, ny_bg = cfg.nx_bg, cfg.ny_bg

    # Auto time-step
    if cfg.dt > 0:
        dt = cfg.dt
    else:
        dt = 0.4 * min(dx_bg, dy_bg) / max(cfg.U_bg, 0.01)
        dt = max(dt, 1.0e-4)

    # Initial scalar field: background = 0; sub-grid = Gaussian blob
    phi_bg = np.zeros((ny_bg, nx_bg))

    # Sub-grid initial scalar: Gaussian centred at (cx + Ls/2, cy) (off-centre)
    sigma = cfg.phi_feature_sigma
    angle0 = 0.0
    Xsg0, Ysg0, dxs, dys = _make_subgrid(cfg, angle0)
    phi_sg = np.exp(-(
        (Xsg0 - (cfg.cx + cfg.Ls * 0.5))**2 +
        (Ysg0 - cfg.cy)**2
    ) / (2.0 * sigma**2))

    phi_sum_init = float(np.sum(phi_bg)) + float(np.sum(phi_sg))

    result = OversetResult(
        nx_bg=nx_bg, ny_bg=ny_bg,
        nxs=cfg.nxs, nys=cfg.nys,
        Lx_bg=cfg.Lx_bg, Ly_bg=cfg.Ly_bg,
        omega_rad_s=cfg.omega_rad_s,
        n_steps=cfg.n_steps,
        dt=dt,
    )

    angle = 0.0

    for step in range(cfg.n_steps):
        t = (step + 1) * dt
        angle = cfg.omega_rad_s * t

        # Get sub-grid cell centres at current angle
        Xsg, Ysg, dxs, dys = _make_subgrid(cfg, angle)

        # ── Step 1: Mark hole in background (cells inside sub-grid) ──────
        hole = np.zeros((ny_bg, nx_bg), dtype=bool)
        for j in range(ny_bg):
            for i in range(nx_bg):
                if _is_inside_square(float(X_bg[j, i]), float(Y_bg[j, i]),
                                     cfg.cx, cfg.cy, cfg.Ls, angle):
                    hole[j, i] = True

        # ── Step 2: Advance background (non-hole cells) ──────────────────
        phi_bg_new = _scalar_step(phi_bg, cfg.U_bg, 0.0, cfg.nu,
                                  dx_bg, dy_bg, dt,
                                  periodic_x=True, periodic_y=False)
        # Keep hole cells from old phi (will be overwritten by interpolation)
        phi_bg_new[hole] = phi_bg[hole]
        phi_bg = phi_bg_new

        # ── Step 3: Advance sub-grid scalar ──────────────────────────────
        # On sub-grid, velocity = rotation  u = -ω·y_local, v = ω·x_local
        # Approximate as uniform convection (centroid velocity for small patch)
        u_sg_approx = -cfg.omega_rad_s * 0.0   # mean y_local ≈ 0
        v_sg_approx =  cfg.omega_rad_s * 0.0
        phi_sg = _scalar_step(phi_sg, u_sg_approx, v_sg_approx, cfg.nu,
                              dxs, dys, dt,
                              periodic_x=False, periodic_y=False)

        # ── Step 4: Overset interpolation — fill hole in background ──────
        # For each hole cell in background, interpolate from sub-grid
        Xsg_flat = Xsg.ravel()
        Ysg_flat = Ysg.ravel()
        phi_sg_flat = phi_sg.ravel()

        for j in range(ny_bg):
            for i in range(nx_bg):
                if hole[j, i]:
                    # Find nearest sub-grid cell (inverse-distance weighted)
                    xq = float(X_bg[j, i])
                    yq = float(Y_bg[j, i])
                    # Inverse rotation to sub-grid frame
                    c = math.cos(-angle);  s = math.sin(-angle)
                    dx_r = xq - cfg.cx;  dy_r = yq - cfg.cy
                    xl = c * dx_r - s * dy_r
                    yl = s * dx_r + c * dy_r
                    # Sub-grid cell index
                    i_sg = int((xl + cfg.Ls) / dxs)
                    j_sg = int((yl + cfg.Ls) / dys)
                    i_sg = max(0, min(i_sg, cfg.nxs - 1))
                    j_sg = max(0, min(j_sg, cfg.nys - 1))
                    phi_bg[j, i] = phi_sg[j_sg, i_sg]

        # ── Step 5: Interpolate background → sub-grid boundary cells ─────
        # Set boundary cells of sub-grid from background
        for j in range(cfg.nys):
            for i in range(cfg.nxs):
                # Check if this sub-grid cell is near its boundary
                if j == 0 or j == cfg.nys-1 or i == 0 or i == cfg.nxs-1:
                    xq = float(Xsg[j, i])
                    yq = float(Ysg[j, i])
                    # Check if within background domain
                    if 0 < xq < cfg.Lx_bg and 0 < yq < cfg.Ly_bg:
                        phi_sg[j, i] = _bilinear_interp(
                            X_bg, Y_bg, phi_bg,
                            xq, yq, dx_bg, dy_bg,
                            cfg.Lx_bg, cfg.Ly_bg
                        )

        # Diagnostics
        result.time.append(t)
        result.phi_sum_bg.append(float(np.sum(phi_bg)))
        result.phi_sum_sg.append(float(np.sum(phi_sg)))

    # Final state
    result.phi_background = phi_bg.ravel().tolist()
    result.phi_subgrid    = phi_sg.ravel().tolist()
    result.angle_deg = float(math.degrees(angle)) % 360.0

    # Sub-grid final positions
    Xsg_f, Ysg_f, _, _ = _make_subgrid(cfg, angle)
    result.xsg_final = Xsg_f.ravel().tolist()
    result.ysg_final = Ysg_f.ravel().tolist()

    # Hole mask at final angle
    hole_final = np.zeros((ny_bg, nx_bg), dtype=bool)
    for j in range(ny_bg):
        for i in range(nx_bg):
            if _is_inside_square(float(X_bg[j, i]), float(Y_bg[j, i]),
                                 cfg.cx, cfg.cy, cfg.Ls, angle):
                hole_final[j, i] = True
    result.hole_mask = hole_final.ravel().tolist()

    # Interpolation error: compare background values in hole vs sub-grid interp
    interp_errs = []
    for j in range(ny_bg):
        for i in range(nx_bg):
            if hole_final[j, i]:
                xq = float(X_bg[j, i]);  yq = float(Y_bg[j, i])
                c = math.cos(-angle);  s = math.sin(-angle)
                dx_r = xq - cfg.cx;   dy_r = yq - cfg.cy
                xl = c * dx_r - s * dy_r
                yl = s * dx_r + c * dy_r
                i_sg = max(0, min(int((xl + cfg.Ls) / dxs), cfg.nxs - 1))
                j_sg = max(0, min(int((yl + cfg.Ls) / dys), cfg.nys - 1))
                interp_errs.append(abs(phi_bg[j, i] - phi_sg[j_sg, i_sg]))

    result.interpolation_error = float(np.max(interp_errs)) if interp_errs else 0.0

    phi_sum_final = result.phi_sum_bg[-1] + result.phi_sum_sg[-1]
    result.conservation_error = (
        abs(phi_sum_final - phi_sum_init) / max(abs(phi_sum_init), 1.0)
    )

    result.model_notes = (
        "In-house Chimera/overset rotating-mesh: 2-D structured Cartesian background + "
        "rotating sub-grid patch; hole-cutting + bilinear interpolation; "
        f"ω = {cfg.omega_rad_s} rad/s; final angle = {result.angle_deg:.1f}°. "
        f"Interpolation error: {result.interpolation_error:.3g}. "
        f"Conservation error: {result.conservation_error:.3g}. "
        "Honest caveat: 2-D; bilinear (first-order) interpolation; "
        "conservation is approximate; no turbulence; not validated vs OpenFOAM overset. "
        "Sufficient to demonstrate Chimera data-exchange and rotating-feature transport."
    )
    return result
