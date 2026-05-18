"""Vortex-Lattice Method (VLM) for subsonic lifting-surface aerodynamics.

Implements the classic horseshoe-vortex VLM following Katz & Plotkin,
"Low-Speed Aerodynamics", 2nd ed., §13.  Each panel carries one horseshoe
vortex whose bound segment lies at the panel 1/4-chord line; downwash
boundary conditions are enforced at collocation points at 3/4-chord.

Sign convention and geometry
-----------------------------
* x – streamwise (aft positive)
* y – spanwise (starboard positive)
* z – upward

A horseshoe vortex of circulation Γ consists of:
  1. A finite bound segment at x = x_LE + c/4  (1/4-chord)
  2. Two semi-infinite trailing vortex filaments extending in the +x direction
     from each tip of the bound segment.

Downwash is computed via the Biot-Savart law.  The influence of a vortex
filament from point A to point B on field point P is

    w = (Γ / 4π) * (cosφ₁ + cosφ₂) / d

with the standard sign rules embedded below.

Reference
---------
Katz, J. and Plotkin, A. (2001). *Low-Speed Aerodynamics* (2nd ed.).
Cambridge University Press.  §§ 10.4, 13.1–13.4.
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np
from numpy.typing import NDArray


# ---------------------------------------------------------------------------
# Biot-Savart helpers
# ---------------------------------------------------------------------------

def _biot_savart_finite(
    r1: NDArray, r2: NDArray, rp: NDArray
) -> NDArray:
    """Velocity induced at *rp* by a finite vortex segment from *r1* to *r2*,
    unit circulation (Γ=1).

    Returns the 3-component velocity vector.

    Uses the formulation from Katz & Plotkin eq. 2.72 / §10.4:

        V = (Γ/4π) * (r1×r2) / |r1×r2|² * (r1_hat − r2_hat) · (r1/|r1| − r2/|r2|)

    but written in the cleaner cross-product form to avoid singularities.
    """
    v1 = rp - r1   # vector from segment start to field point
    v2 = rp - r2   # vector from segment end   to field point

    v1xv2 = np.cross(v1, v2)
    mag_v1xv2_sq = np.dot(v1xv2, v1xv2)

    # If the field point is on (or extremely close to) the vortex filament,
    # the induced velocity is zero by definition.
    if mag_v1xv2_sq < 1e-30:
        return np.zeros(3)

    mag_v1 = np.linalg.norm(v1)
    mag_v2 = np.linalg.norm(v2)

    if mag_v1 < 1e-15 or mag_v2 < 1e-15:
        return np.zeros(3)

    r0 = r2 - r1  # segment direction vector
    factor = (np.dot(r0, v1) / mag_v1 - np.dot(r0, v2) / mag_v2) / (
        4.0 * math.pi * mag_v1xv2_sq
    )

    return factor * v1xv2


def _biot_savart_semi_infinite(
    r_start: NDArray, direction: NDArray, rp: NDArray
) -> NDArray:
    """Velocity induced at *rp* by a semi-infinite vortex filament starting at
    *r_start* and extending in *direction* (unit vector), unit circulation.

    Uses the half-infinite specialisation of the Biot-Savart law (Katz &
    Plotkin §2.10):

        V = (Γ/4π) * (d × r) / (|d × r|² * (1 + cos θ) / |r| )

    where r is from r_start to rp and cos θ = d̂·r̂.

    A cleaner form avoids the explicit cos θ:

        V = (Γ/4π) * (d × rp_shifted) / (|d × rp_shifted|²) * (1 + d̂ · r̂)
    """
    r = rp - r_start
    d = direction / np.linalg.norm(direction)  # unit along trailing vortex

    dxr = np.cross(d, r)
    mag_dxr_sq = np.dot(dxr, dxr)

    if mag_dxr_sq < 1e-30:
        return np.zeros(3)

    mag_r = np.linalg.norm(r)
    if mag_r < 1e-15:
        return np.zeros(3)

    cos_theta = np.dot(d, r) / mag_r
    factor = (1.0 + cos_theta) / (4.0 * math.pi * mag_dxr_sq)

    return factor * dxr


# ---------------------------------------------------------------------------
# Mesh generation
# ---------------------------------------------------------------------------

def _build_wing_mesh(
    span: float,
    root_chord: float,
    tip_chord: float,
    sweep_deg: float,
    twist_deg: float,
    m_chord: int,
    n_span: int,
) -> tuple[NDArray, NDArray, NDArray, NDArray]:
    """Build panel geometry for a (possibly tapered, swept, twisted) wing.

    The wing is defined from y = -b/2 to y = +b/2 (full-span symmetric).

    Returns
    -------
    bound_A, bound_B : NDArray, shape (N, 3)
        Port and starboard ends of each bound vortex (1/4-chord line).
    colloc : NDArray, shape (N, 3)
        Collocation points (3/4-chord, midspan of each panel).
    normal : NDArray, shape (N, 3)
        Unit normal vectors at each collocation point (approximately z-hat
        for flat wing, rotated by local twist).
    """
    sweep_rad = math.radians(sweep_deg)
    twist_rad = math.radians(twist_deg)  # washout: positive = LE-down at tip

    # Spanwise stations: equal-cosine spacing for better tip accuracy.
    # We use cosine spacing on one semi-span then mirror.
    # Full span: y from -b/2 to +b/2.
    b = span
    beta_sp = np.linspace(0.0, math.pi, n_span + 1)  # n_span+1 edges
    # Half-span values 0..1 mapped to cosine
    eta = 0.5 * (1.0 - np.cos(beta_sp))  # 0 … 1 (one semi-span)
    y_edges = np.concatenate([-(b / 2) * eta[::-1][:-1], (b / 2) * eta])

    # Now we have n_span*2 + 1 edges... but we want n_span panels.
    # Use uniform spacing to keep things simple and predictable.
    y_edges = np.linspace(-b / 2, b / 2, n_span + 1)

    panels = []
    for j in range(n_span):
        y_left = y_edges[j]
        y_right = y_edges[j + 1]
        y_mid = 0.5 * (y_left + y_right)

        for i in range(m_chord):
            # Local chord at left/right edges (linear taper)
            eta_l = (y_left + b / 2) / b   # 0 at root, 1 at tip
            eta_r = (y_right + b / 2) / b
            c_left = root_chord + (tip_chord - root_chord) * eta_l
            c_right = root_chord + (tip_chord - root_chord) * eta_r
            c_mid = root_chord + (tip_chord - root_chord) * ((y_mid + b / 2) / b)

            # Leading edge x-position (sweep from root LE)
            x_le_left = abs(y_left + b / 2) * math.tan(sweep_rad)
            x_le_right = abs(y_right + b / 2) * math.tan(sweep_rad)
            x_le_mid = abs(y_mid + b / 2) * math.tan(sweep_rad)

            # Chordwise panel edges (fraction of chord)
            xi_left = i / m_chord
            xi_right = (i + 1) / m_chord

            # 1/4-chord bound vortex: x = x_le + (xi_left + (xi_right - xi_left)/4) * c
            xi_bound = xi_left + (xi_right - xi_left) * 0.25
            x_A = x_le_left + xi_bound * c_left
            x_B = x_le_right + xi_bound * c_right

            # Local twist angle (linear from root to tip)
            twist_left = twist_rad * (y_left + b / 2) / b
            twist_right = twist_rad * (y_right + b / 2) / b
            twist_mid = twist_rad * (y_mid + b / 2) / b

            # z-positions due to twist (dihedral = 0 here)
            z_A = 0.0
            z_B = 0.0

            A = np.array([x_A, y_left, z_A])
            B = np.array([x_B, y_right, z_B])

            # Collocation point at 3/4-chord, midspan of panel
            xi_colloc = xi_left + (xi_right - xi_left) * 0.75
            x_cp = x_le_mid + xi_colloc * c_mid
            colloc_pt = np.array([x_cp, y_mid, 0.0])

            # Normal vector: account for twist.
            # For a flat wing with no camber: normal = [sin(twist), 0, cos(twist)]
            # pointing upward from the surface.
            n = np.array([-math.sin(twist_mid), 0.0, math.cos(twist_mid)])

            panels.append((A, B, colloc_pt, n))

    N = len(panels)
    bound_A = np.array([p[0] for p in panels])
    bound_B = np.array([p[1] for p in panels])
    colloc = np.array([p[2] for p in panels])
    normals = np.array([p[3] for p in panels])

    return bound_A, bound_B, colloc, normals


# ---------------------------------------------------------------------------
# AIC matrix
# ---------------------------------------------------------------------------

def _horseshoe_velocity(
    A: NDArray, B: NDArray, rp: NDArray, v_inf_dir: NDArray
) -> NDArray:
    """Velocity induced at *rp* by a horseshoe vortex of unit circulation.

    The horseshoe consists of:
      - Bound segment A → B
      - Semi-infinite trailing leg from A in the -v_inf_dir direction
        (i.e., extending upstream from the bound vortex TE sense ... actually
        the trailing vortices go downstream, in the +x direction = +v_inf_dir).

    For a horseshoe in the standard orientation (bound at 1/4-chord, trailing
    legs going downstream):
      - Left trailing: semi-inf from A in +x direction
      - Right trailing: semi-inf from B in +x direction
      Sign: the right leg has +Γ sense, the left leg has -Γ sense relative to
      the bound segment.

    Using the right-hand rule with positive Γ defined as circulation producing
    upwash inside (between the legs):
      - Bound vortex A→B contributes w_AB
      - Left trailing from A → +∞: contributes with one sign
      - Right trailing from B → +∞: contributes with opposite sign
    """
    trail = v_inf_dir / np.linalg.norm(v_inf_dir)  # unit downstream direction

    # Bound vortex contribution (A → B)
    w_bound = _biot_savart_finite(A, B, rp)

    # Trailing vortex from A: extends from A to +infinity downstream.
    # This vortex has circulation in the -Γ sense (left leg of horseshoe):
    # the horseshoe circulation Γ goes: +∞ → A → B → +∞ (right hand rule).
    # So left trailing (ending at A) effectively means semi-inf from A to -∞
    # i.e. a vortex from -∞ to A.  For the horseshoe we want:
    #   - segment from -∞ to A (entering): same as semi-inf from A pointing upstream = -trail
    #   Actually, standard formulation: trailing vortex from A going to +x infinity.
    #   The bound+trailing forms a closed loop at infinity.
    #   Contribution from left trailing (A to +∞ in +x): negative sense for CW when viewed from above.
    w_trail_A = _biot_savart_semi_infinite(A, trail, rp)
    # Right trailing (B to +∞ in +x): positive sense
    w_trail_B = _biot_savart_semi_infinite(B, trail, rp)

    # The horseshoe vortex: bound A→B plus trailing A→+∞ and B→+∞.
    # In the standard derivation: the right hand rule gives the total as
    #   w = w_bound + w_trail_B - w_trail_A
    # (the left trailing vortex travels in the opposite rotational sense).
    return w_bound + w_trail_B - w_trail_A


def _build_aic(
    bound_A: NDArray,
    bound_B: NDArray,
    colloc: NDArray,
    normals: NDArray,
    v_inf_dir: NDArray,
) -> NDArray:
    """Build the aerodynamic influence coefficient matrix.

    AIC[i, j] = normal component of velocity at collocation point i
                induced by horseshoe vortex j with unit circulation.
    """
    N = len(colloc)
    AIC = np.zeros((N, N))

    for j in range(N):
        A = bound_A[j]
        B = bound_B[j]
        for i in range(N):
            vel = _horseshoe_velocity(A, B, colloc[i], v_inf_dir)
            AIC[i, j] = np.dot(vel, normals[i])

    return AIC


# ---------------------------------------------------------------------------
# Main solver
# ---------------------------------------------------------------------------

def vlm_wing(
    span: float,
    root_chord: float,
    tip_chord: Optional[float] = None,
    sweep_deg: float = 0.0,
    twist_deg: float = 0.0,
    alpha_deg: float = 5.0,
    m_chord: int = 4,
    n_span: int = 10,
    v_inf: float = 1.0,
) -> dict:
    """Compute steady aerodynamic coefficients of a finite wing using VLM.

    Parameters
    ----------
    span : float
        Full wing span *b*.
    root_chord : float
        Root chord length.
    tip_chord : float, optional
        Tip chord length.  Defaults to *root_chord* (rectangular wing).
    sweep_deg : float
        Leading-edge sweep angle in degrees (positive swept back).
    twist_deg : float
        Geometric twist (washout) in degrees.  Positive = leading edge down
        at tip (washes out).
    alpha_deg : float
        Angle of attack in degrees.
    m_chord : int
        Number of chordwise panels.
    n_span : int
        Number of spanwise panels.
    v_inf : float
        Freestream speed (m/s).  Aerodynamic coefficients are dimensionless so
        this only matters for the Γ magnitudes, not CL/CDi.

    Returns
    -------
    dict with keys:
        CL  : float – lift coefficient
        CDi : float – induced drag coefficient
        Cm  : float – pitching moment coefficient (about LE, x_ref=0)
        gamma : np.ndarray, shape (n_span * m_chord,) – panel circulations
    """
    if tip_chord is None:
        tip_chord = root_chord

    alpha_rad = math.radians(alpha_deg)

    # Freestream direction (in the x-z plane, angle alpha from x-axis)
    v_inf_dir = np.array([math.cos(alpha_rad), 0.0, math.sin(alpha_rad)])

    # Build mesh
    bound_A, bound_B, colloc, normals = _build_wing_mesh(
        span, root_chord, tip_chord, sweep_deg, twist_deg, m_chord, n_span
    )

    N = len(colloc)

    # Build AIC (trailing vortices go in pure x direction, not along v_inf,
    # as is standard for linearised VLM — wake aligned with x-axis)
    wake_dir = np.array([1.0, 0.0, 0.0])
    AIC = _build_aic(bound_A, bound_B, colloc, normals, wake_dir)

    # Right-hand side: enforce no-penetration boundary condition.
    # The normal velocity of the freestream must be cancelled by the
    # vortex-induced downwash at each collocation point.
    # rhs[i] = -V_inf · n_i
    rhs = -v_inf * np.dot(v_inf_dir.reshape(1, 3), normals.T).flatten()

    # Solve the linear system for panel circulations
    gamma = np.linalg.solve(AIC, rhs)

    # Reference geometry
    # Mean chord
    c_mean = 0.5 * (root_chord + tip_chord)
    S_ref = span * c_mean  # reference area

    # Lift force per panel (Kutta-Joukowski): dL = ρ * V_inf * Γ * Δy
    # For CL we use: CL = L / (0.5 * ρ * V² * S)
    # Since ρ and V cancel in CL, we normalise by 0.5 * V_inf² * S_ref.
    dy = np.abs(bound_B[:, 1] - bound_A[:, 1])
    dL = v_inf * gamma * dy  # per-panel lift (per unit density)

    # Note: This gives the spanwise component only; for small alpha the
    # approximation L_total ≈ sum(dL) * cos(alpha) is used.
    L_total = np.sum(dL) * math.cos(alpha_rad)

    CL = L_total / (0.5 * v_inf**2 * S_ref)

    # Induced drag (Trefftz plane): CDi = -sum(Γ_i * w_i * Δy_i) / (0.5*V²*S)
    # w_i = downwash at collocation point = sum_j(AIC[i,j]*Γ_j) + V_inf*sin(α) (the full normal-vel)
    # For CDi via the near-field formula:
    # D_i = ρ * sum(Γ_i * (-w_i) * Δy_i) where w_i is the induced downwash
    induced_w = AIC @ gamma   # This is the downwash (in terms of normal component)
    # The actual induced downwash velocity component is the normal-velocity induced:
    # We approximate CDi using the near-field formula:
    Di_panels = -gamma * induced_w * dy  # per-panel induced drag (Γ * w_induced * Δy)
    Di_total = np.sum(Di_panels)
    CDi = Di_total / (0.5 * v_inf**2 * S_ref)

    # Pitching moment about x=0 (leading edge), positive nose-up
    # Cm = -sum(dL_i * x_cp_i) / (0.5 * V² * S * c_mean)
    x_cp = colloc[:, 0]
    Cm = -np.sum(dL * x_cp * math.cos(alpha_rad)) / (
        0.5 * v_inf**2 * S_ref * c_mean
    )

    return {
        "CL": float(CL),
        "CDi": float(CDi),
        "Cm": float(Cm),
        "gamma": gamma,
    }
