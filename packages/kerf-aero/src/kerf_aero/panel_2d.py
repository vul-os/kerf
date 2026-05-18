"""2-D Linear-Vortex Panel Method (XFOIL class).

Implements the two-dimensional vortex panel method with a linearly varying
vortex sheet strength per panel and an explicit Kutta condition at the
trailing edge.  This formulation produces results comparable to XFOIL for
thin-to-moderately-thick airfoils at moderate angles of attack.

Theory
------
The airfoil surface is approximated by N straight panels.  Over each panel j
the vortex sheet strength γ varies linearly between the nodal values γⱼ and
γⱼ₊₁.  The influence of panel j on the normal velocity at control point i is

    V_n(i,j) = A(i,j)*γⱼ + B(i,j)*γⱼ₊₁

where A and B are the analytic influence coefficients derived below.

The no-penetration boundary condition (zero normal velocity on the surface)
gives N equations:

    Σⱼ [A(i,j)*γⱼ + B(i,j)*γⱼ₊₁] = −V∞·nᵢ   for i = 1..N

The Kutta condition supplies the (N+1)-th equation:  γ₀ + γ_N = 0

(γ at the trailing edge from both the upper and lower surface panels must be
zero so the velocity is finite at the trailing edge.)

Analytic influence coefficients (Katz & Plotkin §11.1 / Drela panel notes)
---------------------------------------------------------------------------
For a panel from node 1=(x1,y1) to node 2=(x2,y2) with length l, and a
control point P transformed to panel-local coordinates (xp, yp):

    d_theta = atan2(yp, xp−l) − atan2(yp, xp)
    log_r2_r1 = ln(r2/r1)  where r1²=xp²+yp², r2²=(xp−l)²+yp²

Induced velocity in panel-LOCAL frame (u=tangential, v=normal):

    u1 = (1/2π)·[(1−xp/l)·d_theta − (yp/l)·log_r2_r1]
    u2 = (1/2π)·[(xp/l)  ·d_theta + (yp/l)·log_r2_r1]
    v1 = (1/2π)·[(1−xp/l)·log_r2_r1 − 1 + (yp/l)·d_theta]
    v2 = (1/2π)·[(xp/l)  ·log_r2_r1 + 1 − (yp/l)·d_theta]

These are analytically verified against numerical integration.

The normal velocity at control point i from panel j (with nodal strengths γⱼ,
γⱼ₊₁) is then obtained by rotating (u,v) to the global frame and projecting
onto the control-point outward normal.

Reference
---------
Katz, J. and Plotkin, A. (2001). *Low-Speed Aerodynamics* (2nd ed.),
Cambridge University Press.  §§ 11.1–11.2.

Drela, M. (1989). "XFOIL: An Analysis and Design System for Low Reynolds
Number Airfoils."
"""

from __future__ import annotations

import math
from typing import Union

import numpy as np
from numpy.typing import NDArray


# ---------------------------------------------------------------------------
# Coordinate utilities
# ---------------------------------------------------------------------------

def _normalise_coords(coords: NDArray) -> NDArray:
    """Return coordinates as a closed CCW loop (open: last ≠ first).

    Accepts Selig format (upper TE→LE→lower TE) or any (x,y) ordering.
    Returns coordinates going upper-surface TE → LE → lower surface → TE
    (counter-clockwise when viewed with x right, y up).
    """
    coords = np.asarray(coords, dtype=float)

    # Remove exact duplicate last point if present
    if np.allclose(coords[0], coords[-1], atol=1e-10):
        coords = coords[:-1]

    # Ensure CCW orientation via signed area (shoelace)
    x, y = coords[:, 0], coords[:, 1]
    signed_area = 0.5 * np.sum(x[:-1] * y[1:] - x[1:] * y[:-1])
    signed_area += 0.5 * (x[-1] * y[0] - x[0] * y[-1])

    if signed_area < 0:
        coords = coords[::-1]

    return coords


# ---------------------------------------------------------------------------
# Panel geometry
# ---------------------------------------------------------------------------

def _panel_geometry(nodes: NDArray) -> tuple:
    """Compute panel midpoints, tangent/normal vectors, lengths, angles.

    Parameters
    ----------
    nodes : NDArray, shape (N+1, 2)
        Panel corner coordinates.  Panel i runs from nodes[i] to nodes[i+1].

    Returns
    -------
    xm, ym : NDArray (N,)  — panel midpoints (control points)
    tx, ty : NDArray (N,)  — panel tangent unit vectors
    nx, ny : NDArray (N,)  — panel outward normal unit vectors
    ds     : NDArray (N,)  — panel lengths
    theta  : NDArray (N,)  — panel inclination angles (rad from x-axis)
    """
    x1, y1 = nodes[:-1, 0], nodes[:-1, 1]
    x2, y2 = nodes[1:, 0],  nodes[1:, 1]

    dx = x2 - x1
    dy = y2 - y1
    ds = np.sqrt(dx**2 + dy**2)

    tx = dx / ds
    ty = dy / ds

    # Outward normal: for CCW ordering, rotate tangent by -90° (clockwise):
    # n = (ty, -tx)
    nx =  ty
    ny = -tx

    theta = np.arctan2(dy, dx)
    xm = 0.5 * (x1 + x2)
    ym = 0.5 * (y1 + y2)

    return xm, ym, tx, ty, nx, ny, ds, theta


# ---------------------------------------------------------------------------
# Analytic influence coefficients for a linear-strength vortex panel
# ---------------------------------------------------------------------------

def _linear_vortex_influence(
    xp: float, yp: float, l: float
) -> tuple[float, float, float, float]:
    """Analytic velocity influence at panel-local (xp, yp) from a linear-
    strength vortex panel of length l spanning from (0,0) to (l,0).

    The vortex strength varies as  γ(s) = γ₁·(1−s/l) + γ₂·(s/l).

    Returns
    -------
    (u1, u2, v1, v2) : float
        Induced velocity components in panel-local frame:
        * u1, u2 : tangential (x) components for basis γ₁=1 and γ₂=1 resp.
        * v1, v2 : normal    (y) components for basis γ₁=1 and γ₂=1 resp.

    Formulas (analytically derived and numerically verified):

        u1 = (1/2π)·[(1−xp/l)·Δθ − (yp/l)·log(r2/r1)]
        u2 = (1/2π)·[(xp/l)  ·Δθ + (yp/l)·log(r2/r1)]
        v1 = (1/2π)·[(1−xp/l)·log(r2/r1) − 1 + (yp/l)·Δθ]
        v2 = (1/2π)·[(xp/l)  ·log(r2/r1) + 1 − (yp/l)·Δθ]

    where:
        Δθ       = atan2(yp, xp−l) − atan2(yp, xp)
        log(r2/r1) = 0.5·ln[(xp−l)²+yp²) / (xp²+yp²)]
    """
    EPS = 1e-14
    r1_sq = xp**2 + yp**2
    r2_sq = (xp - l)**2 + yp**2

    # Avoid log of zero (control point at panel node)
    r1_sq_safe = max(r1_sq, EPS)
    r2_sq_safe = max(r2_sq, EPS)
    log_r2_r1 = 0.5 * math.log(r2_sq_safe / r1_sq_safe)

    # Angle subtended by the panel as seen from the control point
    # Regularise: if yp is essentially zero, the control point is on the panel
    # (self-influence). We shift slightly to avoid atan2 ambiguity.
    if abs(yp) < EPS:
        yp_reg = EPS
    else:
        yp_reg = yp
    d_theta = math.atan2(yp_reg, xp - l) - math.atan2(yp_reg, xp)

    inv_2pi = 1.0 / (2.0 * math.pi)

    u1 = inv_2pi * ((1.0 - xp / l) * d_theta - (yp / l) * log_r2_r1)
    u2 = inv_2pi * ((xp / l) * d_theta       + (yp / l) * log_r2_r1)
    v1 = inv_2pi * ((1.0 - xp / l) * log_r2_r1 - 1.0 + (yp / l) * d_theta)
    v2 = inv_2pi * ((xp / l) * log_r2_r1       + 1.0 - (yp / l) * d_theta)

    return u1, u2, v1, v2


def _panel_normal_influence(
    xm_i: float, ym_i: float, nx_i: float, ny_i: float,
    x1_j: float, y1_j: float, x2_j: float, y2_j: float,
) -> tuple[float, float]:
    """Normal-velocity influence at control point i from panel j.

    Returns (a, b) such that the induced normal velocity is a*γⱼ + b*γⱼ₊₁.
    """
    dx = x2_j - x1_j
    dy = y2_j - y1_j
    l = math.sqrt(dx**2 + dy**2)
    if l < 1e-15:
        return 0.0, 0.0

    cos_t = dx / l
    sin_t = dy / l

    # Transform control point to panel-j local coordinates
    xp = (xm_i - x1_j) * cos_t + (ym_i - y1_j) * sin_t
    yp = -(xm_i - x1_j) * sin_t + (ym_i - y1_j) * cos_t

    # Local-frame influence coefficients
    u1, u2, v1, v2 = _linear_vortex_influence(xp, yp, l)

    # Rotate back to global frame:
    # (u_global, v_global) = R * (u_local, v_local)
    # where R = [[cos_t, -sin_t], [sin_t, cos_t]]
    U1 = u1 * cos_t - v1 * sin_t
    V1 = u1 * sin_t + v1 * cos_t

    U2 = u2 * cos_t - v2 * sin_t
    V2 = u2 * sin_t + v2 * cos_t

    # Project onto control-point outward normal (nx_i, ny_i)
    a = U1 * nx_i + V1 * ny_i
    b = U2 * nx_i + V2 * ny_i

    return a, b


def _panel_tangential_influence(
    xm_i: float, ym_i: float, tx_i: float, ty_i: float,
    x1_j: float, y1_j: float, x2_j: float, y2_j: float,
) -> tuple[float, float]:
    """Tangential-velocity influence at control point i from panel j.

    Returns (a, b) such that the tangential velocity contribution is a*γⱼ + b*γⱼ₊₁.
    """
    dx = x2_j - x1_j
    dy = y2_j - y1_j
    l = math.sqrt(dx**2 + dy**2)
    if l < 1e-15:
        return 0.0, 0.0

    cos_t = dx / l
    sin_t = dy / l

    xp = (xm_i - x1_j) * cos_t + (ym_i - y1_j) * sin_t
    yp = -(xm_i - x1_j) * sin_t + (ym_i - y1_j) * cos_t

    u1, u2, v1, v2 = _linear_vortex_influence(xp, yp, l)

    # Rotate back to global frame
    U1 = u1 * cos_t - v1 * sin_t
    V1 = u1 * sin_t + v1 * cos_t
    U2 = u2 * cos_t - v2 * sin_t
    V2 = u2 * sin_t + v2 * cos_t

    # Project onto control-point tangential direction
    a = U1 * tx_i + V1 * ty_i
    b = U2 * tx_i + V2 * ty_i

    return a, b


# ---------------------------------------------------------------------------
# NACA 4-digit coordinate generator (self-contained, no import from airfoils/)
# ---------------------------------------------------------------------------

def _naca4_coords(profile: str, n_pts: int = 200) -> NDArray:
    """Generate NACA 4-digit airfoil coordinates in Selig format."""
    m = int(profile[0]) / 100.0
    p = int(profile[1]) / 10.0
    t = int(profile[2:]) / 100.0

    beta = np.linspace(0, math.pi, n_pts)
    x = 0.5 * (1.0 - np.cos(beta))

    # NACA 4-digit thickness distribution (finite TE)
    a = (0.2969, -0.1260, -0.3516, 0.2843, -0.1015)
    yt = (t / 0.2) * (
        a[0] * np.sqrt(x + 1e-30) + a[1] * x + a[2] * x**2
        + a[3] * x**3 + a[4] * x**4
    )

    # Camber line
    yc = np.zeros_like(x)
    dyc = np.zeros_like(x)
    if m > 0.0 and p > 0.0:
        fore = x <= p
        aft = ~fore
        yc[fore] = (m / p**2) * (2 * p * x[fore] - x[fore]**2)
        yc[aft]  = (m / (1 - p)**2) * ((1 - 2*p) + 2*p*x[aft] - x[aft]**2)
        dyc[fore] = (2*m / p**2) * (p - x[fore])
        dyc[aft]  = (2*m / (1-p)**2) * (p - x[aft])

    th = np.arctan(dyc)
    xu = x - yt * np.sin(th)
    yu = yc + yt * np.cos(th)
    xl = x + yt * np.sin(th)
    yl = yc - yt * np.cos(th)

    # Selig ordering: upper TE→LE then lower LE→TE
    upper = np.column_stack([xu[::-1], yu[::-1]])
    lower = np.column_stack([xl[1:], yl[1:]])
    return np.vstack([upper, lower])


# ---------------------------------------------------------------------------
# Main solver
# ---------------------------------------------------------------------------

def panel_solve(
    coords: Union[NDArray, str],
    alpha_deg: float,
    n_panels: int = 160,
) -> dict:
    """Solve 2D linear-vortex panel flow over an airfoil.

    Parameters
    ----------
    coords : array-like (M, 2) or str
        Airfoil surface coordinates in Selig format, *or* a 4-digit NACA
        designator string (e.g. ``"0012"``).  Chord normalised to 1.
    alpha_deg : float
        Freestream angle of attack (degrees).
    n_panels : int
        Number of panels.  Must be even.  Default 160.

    Returns
    -------
    dict with keys:
        CL  : float — lift coefficient
        Cp  : NDArray (n_panels,) — pressure coefficient at panel midpoints
    """
    # -- Coordinate input -------------------------------------------------
    if isinstance(coords, str):
        raw = _naca4_coords(coords, n_pts=max(n_panels + 40, 240))
    else:
        raw = np.asarray(coords, dtype=float)

    # -- Normalise to CCW closed loop -------------------------------------
    raw = _normalise_coords(raw)

    # -- Resample to n_panels+1 nodes (uniform arc-length) ---------------
    N = n_panels
    dists = np.sqrt(np.sum(np.diff(raw, axis=0)**2, axis=1))
    arc = np.concatenate([[0.0], np.cumsum(dists)])
    arc_total = arc[-1]
    arc_norm = arc / arc_total

    s_new = np.linspace(0.0, 1.0, N + 1)
    nodes_x = np.interp(s_new, arc_norm, raw[:, 0])
    nodes_y = np.interp(s_new, arc_norm, raw[:, 1])
    nodes = np.column_stack([nodes_x, nodes_y])

    # -- Panel geometry --------------------------------------------------
    xm, ym, tx, ty, nx, ny, ds, theta = _panel_geometry(nodes)

    # -- Freestream ------------------------------------------------------
    alpha_rad = math.radians(alpha_deg)
    V_inf_x = math.cos(alpha_rad)
    V_inf_y = math.sin(alpha_rad)

    # -- Build linear system: (N+1) × (N+1) ------------------------------
    # Unknowns: γ₀, γ₁, ..., γ_N  (N+1 nodal vortex strengths)
    # Equations:
    #   i = 0..N-1 : no-penetration at control point i
    #   i = N      : Kutta condition  γ₀ + γ_N = 0

    M = N + 1
    A = np.zeros((M, M))
    rhs = np.zeros(M)

    for i in range(N):
        # Freestream normal velocity component (negative = into the surface)
        rhs[i] = -(V_inf_x * nx[i] + V_inf_y * ny[i])

        for j in range(N):
            a_ij, b_ij = _panel_normal_influence(
                xm[i], ym[i], nx[i], ny[i],
                nodes[j, 0], nodes[j, 1], nodes[j+1, 0], nodes[j+1, 1],
            )
            # γⱼ coefficient
            A[i, j]   += a_ij
            # γⱼ₊₁ coefficient
            A[i, j+1] += b_ij

    # Kutta condition: γ₀ + γ_N = 0
    A[N, 0] = 1.0
    A[N, N] = 1.0
    rhs[N] = 0.0

    # -- Solve -----------------------------------------------------------
    gamma_nodes = np.linalg.solve(A, rhs)

    # -- Lift (Kutta-Joukowski) -------------------------------------------
    # Γ_total = ∫ γ ds ≈ Σ 0.5*(γⱼ+γⱼ₊₁)*dsⱼ
    # CL = 2·Γ / (V_inf · c),  with V_inf=1, c=1  →  CL = 2·Γ
    gamma_avg = 0.5 * (gamma_nodes[:-1] + gamma_nodes[1:])
    Gamma_total = np.sum(gamma_avg * ds)
    CL = 2.0 * Gamma_total

    # -- Pressure coefficient --------------------------------------------
    # Cp = 1 - (Vt / V_inf)²,  Vt = tangential velocity at panel midpoints.
    # Vt = freestream tangential + Σⱼ (tangential influence from panel j)
    Vt = np.empty(N)
    for i in range(N):
        # Freestream tangential component
        Vt_i = V_inf_x * tx[i] + V_inf_y * ty[i]

        for j in range(N):
            a_t, b_t = _panel_tangential_influence(
                xm[i], ym[i], tx[i], ty[i],
                nodes[j, 0], nodes[j, 1], nodes[j+1, 0], nodes[j+1, 1],
            )
            Vt_i += a_t * gamma_nodes[j] + b_t * gamma_nodes[j+1]

        Vt[i] = Vt_i

    Cp = 1.0 - Vt**2  # V_inf = 1

    return {
        "CL": float(CL),
        "Cp": Cp,
    }
