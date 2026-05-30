"""
curvature_gradient.py
=====================
Curvature-gradient field computation on NURBS surfaces.

For each surface point, compute ∇K = (∂K/∂u, ∂K/∂v) in the tangent plane:
  - Magnitude |∇K| and direction angle (from u-tangent) in the tangent plane.
  - Ridge-line and valley-line tracing: integral curves where κ₁ = κ₂ (ridges)
    or sign-change contours of K.
  - Field visualisation grid for rendering.

Mathematical basis
------------------
Gaussian curvature K = (eg − f²) / (EG − F²) where E, F, G are first-
fundamental-form coefficients and e, f, g are second-fundamental-form
coefficients.  The parameter gradient (∂K/∂u, ∂K/∂v) is computed by central
finite differences of the analytic curvature values at neighbouring (u, v)
points.  This preserves the full accuracy of the analytic curvature kernel
(exact rational NURBS derivatives) while only differentiating the scalar
output — i.e. the standard "differentiate the analytic scalar" pattern used
in Pottmann-Wallner 2001 §11 ridge extraction.

The 3-D gradient vector lives in the tangent plane:
    ∇K₃D = (∂K/∂u) · Ŝᵤ + (∂K/∂v) · Ŝᵥ
where Ŝᵤ = Sᵤ / |Sᵤ| and Ŝᵥ = Sᵥ / |Sᵥ| are the (non-unit) parameter
partial derivatives.  The direction angle θ is the angle of ∇K₃D relative to
the Sᵤ tangent direction in the tangent plane.

Ridge / valley lines
--------------------
A *ridge line* is a curve along which the larger principal curvature κ₁ is a
local maximum in its principal direction (i.e. ∂κ₁/∂t = 0 in the κ₁ direction).
Equivalently, ridges occur where (∇κ₁) · e₁ = 0 (Pottmann-Wallner §11 eq. 11.6).

For practical CAD inspection we use a simplified but effective criterion:
  - On a parameter-space grid, sample κ₁ at each point.
  - A ridge cell is one where the sign of (∇κ₁ · ê₁) changes across an edge
    (zero-crossing contour of the directed κ₁ gradient along the principal
    direction e₁).
  - Each sign-crossing edge yields a midpoint that is a ridge-point candidate.
  - Ridge polylines are assembled by nearest-neighbour chaining.

The K_threshold parameters control which cells are considered:
  - compute_ridge_lines:  include cells where K ≥ K_threshold (synclastic
    / convex ridges, e.g. outer equator of a torus).
  - compute_valley_lines: include cells where K ≤ K_threshold (anticlastic
    / concave valleys).

References
----------
do Carmo, M.P., "Differential Geometry of Curves and Surfaces",
    Prentice-Hall 1976 — §5 (intrinsic vs extrinsic derivatives).
Pottmann, H. and Wallner, J., "Computational Line Geometry",
    Springer 2001 — §11 (curvature lines, ridges and valleys).
Piegl & Tiller, "The NURBS Book", 2nd ed., Springer 1997 — §6.1
    (surface derivatives, rational-correct).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsSurface, surface_derivatives

# ---------------------------------------------------------------------------
# Internal helpers — re-use the exact analytic curvature kernel from
# surface_analysis without creating a hard module dependency at import time.
# We duplicate only what we need (< 50 lines) to keep this module self-contained.
# ---------------------------------------------------------------------------

def _analytic_curvature_data(surf: NurbsSurface, u: float, v: float) -> Optional[dict]:
    """Full differential-geometry data at a single (u, v) point.

    Returns a dict with K, H, k1, k2, Su, Sv, n or None when degenerate.
    Uses exact analytic derivatives (Piegl & Tiller Alg. A3.6 / A4.4).
    """
    try:
        SKL = surface_derivatives(surf, u, v, d=2)
    except Exception:
        return None

    Su  = SKL[1, 0][:3].astype(float)
    Sv  = SKL[0, 1][:3].astype(float)
    Suu = SKL[2, 0][:3].astype(float)
    Svv = SKL[0, 2][:3].astype(float)
    Suv = SKL[1, 1][:3].astype(float)

    cross = np.cross(Su, Sv)
    mag = float(np.linalg.norm(cross))
    if mag < 1e-14:
        return None

    n = cross / mag

    E = float(np.dot(Su, Su))
    F = float(np.dot(Su, Sv))
    G = float(np.dot(Sv, Sv))
    EGF2 = E * G - F * F
    if EGF2 < 1e-20:
        return None

    e = float(np.dot(Suu, n))
    f = float(np.dot(Suv, n))
    g = float(np.dot(Svv, n))

    K = (e * g - f * f) / EGF2
    H = (e * G - 2.0 * f * F + g * E) / (2.0 * EGF2)

    disc = max(0.0, H * H - K)
    sq = math.sqrt(disc)
    k1 = H + sq
    k2 = H - sq

    return {
        "Su": Su, "Sv": Sv, "n": n,
        "E": E, "F": F, "G": G,
        "e": e, "f": f, "g": g,
        "EGF2": EGF2,
        "K": K, "H": H,
        "k1": k1, "k2": k2,
    }


def _uv_domain(surf: NurbsSurface) -> Tuple[float, float, float, float]:
    """Return (u_min, u_max, v_min, v_max) for the surface."""
    return (
        float(surf.knots_u[0]),
        float(surf.knots_u[-1]),
        float(surf.knots_v[0]),
        float(surf.knots_v[-1]),
    )


def _fd_step(surf: NurbsSurface, u: float, v: float) -> Tuple[float, float]:
    """Finite-difference step sizes in u and v.

    Scales to 1e-4 of the parameter-domain extent, clamped so the step stays
    inside the domain.  Uses relative stepping so that wide-domain surfaces
    (e.g. 0..2π) and unit-domain surfaces both get numerically appropriate steps.
    """
    u_min, u_max, v_min, v_max = _uv_domain(surf)
    u_span = max(u_max - u_min, 1e-12)
    v_span = max(v_max - v_min, 1e-12)
    h_u = u_span * 1e-4
    h_v = v_span * 1e-4
    # Clamp so that u ± h stays strictly inside the domain
    h_u = min(h_u, (u - u_min) * 0.5, (u_max - u) * 0.5)
    h_v = min(h_v, (v - v_min) * 0.5, (v_max - v) * 0.5)
    # If clamping reduces to zero (at boundary), use one-sided step
    if h_u < 1e-14:
        h_u = u_span * 1e-5
    if h_v < 1e-14:
        h_v = v_span * 1e-5
    return h_u, h_v


# ---------------------------------------------------------------------------
# Public data classes
# ---------------------------------------------------------------------------

@dataclass
class CurvatureGradientResult:
    """Result of compute_curvature_gradient at a single (u, v) point.

    Attributes
    ----------
    magnitude : float
        |∇K| — the Euclidean magnitude of the curvature gradient in the
        tangent plane (units: 1/length³ for a surface in world units).
    direction_angle : float
        Angle of ∇K from the u-tangent direction Sᵤ, in radians [-π, π].
        Zero = gradient points in the +u direction.
    gradient_vector_3d : list[float]
        The 3-D gradient vector ∇K₃D = (∂K/∂u) · Sᵤ_hat + (∂K/∂v) · Sᵥ_hat
        in world space.  Lives in the tangent plane.
    K : float
        Gaussian curvature at (u, v).
    dK_du : float
        Partial derivative ∂K/∂u (central finite difference).
    dK_dv : float
        Partial derivative ∂K/∂v (central finite difference).
    """
    magnitude: float
    direction_angle: float
    gradient_vector_3d: List[float]
    K: float
    dK_du: float
    dK_dv: float


@dataclass
class RidgeLine:
    """A ridge or valley polyline on a NURBS surface.

    Attributes
    ----------
    points : list of [u, v, x, y, z]
        Each element is a 5-tuple: parameter values (u, v) + world position.
    K_values : list of float
        Gaussian curvature at each point.
    is_ridge : bool
        True for ridge lines (κ₁ local maximum); False for valley lines.
    """
    points: List[List[float]]
    K_values: List[float]
    is_ridge: bool = True


# ---------------------------------------------------------------------------
# Core single-point function
# ---------------------------------------------------------------------------

def compute_curvature_gradient(
    surface: NurbsSurface,
    u: float,
    v: float,
) -> CurvatureGradientResult:
    """Compute the curvature gradient ∇K at surface point (u, v).

    Uses a 5-point central finite-difference stencil on the analytic Gaussian
    curvature K(u, v) computed via exact surface_derivatives (Piegl & Tiller
    Alg. A3.6 / A4.4).  The scalar gradient (∂K/∂u, ∂K/∂v) is projected into
    the 3-D tangent plane to obtain the world-space gradient vector.

    Parameters
    ----------
    surface : NurbsSurface
    u, v    : float — surface parameter values (must be in the domain)

    Returns
    -------
    CurvatureGradientResult
        magnitude      |∇K| in the tangent plane
        direction_angle  angle from Sᵤ direction (radians, [-π, π])
        gradient_vector_3d  3-D world-space gradient vector
        K              Gaussian curvature at (u, v)
        dK_du          ∂K/∂u
        dK_dv          ∂K/∂v

    Raises
    ------
    ValueError
        If (u, v) is outside the domain or the surface is degenerate there.

    References
    ----------
    do Carmo §5; Pottmann-Wallner §11.
    """
    u = float(u)
    v = float(v)
    u_min, u_max, v_min, v_max = _uv_domain(surface)
    if not (u_min <= u <= u_max and v_min <= v <= v_max):
        raise ValueError(
            f"(u={u}, v={v}) outside surface domain "
            f"[{u_min}, {u_max}] × [{v_min}, {v_max}]"
        )

    h_u, h_v = _fd_step(surface, u, v)

    # --- Evaluate K at the 4 neighbours for central differences ---
    def _K(uu: float, vv: float) -> float:
        cd = _analytic_curvature_data(surface, uu, vv)
        return cd["K"] if cd is not None else float("nan")

    K0 = _K(u, v)
    K_up   = _K(u + h_u, v)
    K_down = _K(u - h_u, v)
    K_right = _K(u, v + h_v)
    K_left  = _K(u, v - h_v)

    # Central difference (fall back to one-sided if a neighbour is degenerate)
    if math.isfinite(K_up) and math.isfinite(K_down):
        dK_du = (K_up - K_down) / (2.0 * h_u)
    elif math.isfinite(K_up):
        dK_du = (K_up - K0) / h_u
    elif math.isfinite(K_down):
        dK_du = (K0 - K_down) / h_u
    else:
        dK_du = 0.0

    if math.isfinite(K_right) and math.isfinite(K_left):
        dK_dv = (K_right - K_left) / (2.0 * h_v)
    elif math.isfinite(K_right):
        dK_dv = (K_right - K0) / h_v
    elif math.isfinite(K_left):
        dK_dv = (K0 - K_left) / h_v
    else:
        dK_dv = 0.0

    # --- Project into 3-D tangent plane ---
    cd0 = _analytic_curvature_data(surface, u, v)
    if cd0 is None:
        # Degenerate point — return zero gradient
        return CurvatureGradientResult(
            magnitude=0.0,
            direction_angle=0.0,
            gradient_vector_3d=[0.0, 0.0, 0.0],
            K=K0 if math.isfinite(K0) else 0.0,
            dK_du=dK_du,
            dK_dv=dK_dv,
        )

    Su = cd0["Su"]  # first partial (not unit)
    Sv = cd0["Sv"]

    # Metric normalisation: project using the actual tangent vectors
    # so that the 3-D gradient has proper magnitude (not parameter-space magnitude).
    # ∇K₃D = (∂K/∂u) * Ŝᵤ + (∂K/∂v) * Ŝᵥ
    # where Ŝᵤ = Sᵤ / |Sᵤ|, Ŝᵥ = Sᵥ / |Sᵥ|  (parameter derivative tangents).
    Su_norm = float(np.linalg.norm(Su))
    Sv_norm = float(np.linalg.norm(Sv))
    Su_hat = Su / Su_norm if Su_norm > 1e-14 else np.zeros(3)
    Sv_hat = Sv / Sv_norm if Sv_norm > 1e-14 else np.zeros(3)

    grad_3d = dK_du * Su_hat + dK_dv * Sv_hat
    magnitude = float(np.linalg.norm(grad_3d))

    # Direction angle in the tangent plane (angle from Su_hat)
    if magnitude < 1e-30:
        direction_angle = 0.0
    else:
        # Project grad_3d onto Su_hat and onto Sv_hat components
        # (using tangent frame from the metric: correct for non-orthogonal params)
        cos_a = float(np.dot(grad_3d, Su_hat)) / magnitude
        sin_a = float(np.dot(grad_3d, Sv_hat)) / magnitude
        cos_a = float(np.clip(cos_a, -1.0, 1.0))
        direction_angle = math.atan2(sin_a, cos_a)

    return CurvatureGradientResult(
        magnitude=magnitude,
        direction_angle=direction_angle,
        gradient_vector_3d=grad_3d.tolist(),
        K=K0 if math.isfinite(K0) else 0.0,
        dK_du=dK_du,
        dK_dv=dK_dv,
    )


# ---------------------------------------------------------------------------
# Ridge and valley line extraction
# ---------------------------------------------------------------------------

def _principal_direction_e1(cd: dict) -> np.ndarray:
    """Principal direction e₁ (for κ₁, the larger principal curvature).

    Uses the shape-operator eigendecomposition in the (Sᵤ, Sᵥ) tangent frame.
    The shape operator (Weingarten map) matrix in the parameter basis is:
        [L, M]     where L = eG−fF, M = fE−eF  (first column = shape op · Sᵤ)
        [M, N]                N = gE−fF         (second column = shape op · Sᵥ)
    divided by EGF2 = EG − F².

    The eigenvector for κ₁ in the parameter frame (αᵤ, αᵥ) satisfies:
        (A − κ₁ I) [αᵤ; αᵥ] = 0
    The world-space direction is αᵤ · Sᵤ + αᵥ · Sᵥ (normalised).

    Reference: do Carmo §3.3; Piegl & Tiller §6.1.
    """
    E, F, G = cd["E"], cd["F"], cd["G"]
    e, f, g = cd["e"], cd["f"], cd["g"]
    EGF2 = cd["EGF2"]
    Su, Sv = cd["Su"], cd["Sv"]
    k1 = cd["k1"]

    # Shape operator in metric basis: A = I⁻¹ · II  (in parameter frame)
    # I = [[E, F], [F, G]],  II = [[e, f], [f, g]]
    # A = I⁻¹ · II
    # I⁻¹ = (1/EGF2) * [[G, -F], [-F, E]]
    # A = (1/EGF2) * [[eG-fF, fE-eF], [fG-gF, gE-fF]]  ... standard result
    a11 = (e * G - f * F) / EGF2
    a12 = (f * E - e * F) / EGF2
    a21 = (f * G - g * F) / EGF2
    a22 = (g * E - f * F) / EGF2

    # Null-space of (A - k1*I): solve for eigenvector [au, av]
    # Row 1: (a11 - k1)*au + a12*av = 0
    # Row 2: a21*au + (a22 - k1)*av = 0
    r1u = a11 - k1
    r1v = a12
    r2u = a21
    r2v = a22 - k1

    # Pick the larger-norm row
    if abs(r1u) + abs(r1v) >= abs(r2u) + abs(r2v):
        au, av = -r1v, r1u
    else:
        au, av = -r2v, r2u

    e1_param_norm = math.sqrt(au * au + av * av)
    if e1_param_norm < 1e-14:
        # Umbilical point: k1 = k2, any direction is principal
        Su_nrm = float(np.linalg.norm(Su))
        return Su / Su_nrm if Su_nrm > 1e-14 else np.array([1.0, 0.0, 0.0])

    # World-space direction
    e1 = (au * Su + av * Sv)
    nrm = float(np.linalg.norm(e1))
    if nrm < 1e-14:
        Su_nrm = float(np.linalg.norm(Su))
        return Su / Su_nrm if Su_nrm > 1e-14 else np.array([1.0, 0.0, 0.0])
    return e1 / nrm


def compute_ridge_lines(
    surface: NurbsSurface,
    n_samples_u: int = 20,
    n_samples_v: int = 20,
    K_threshold: float = 0.5,
) -> List[RidgeLine]:
    """Trace ridge lines on a NURBS surface.

    Ridge lines are contours where the gradient of κ₁ (the larger principal
    curvature), projected along the κ₁ principal direction e₁, changes sign.
    This is the Pottmann-Wallner (§11) ridge criterion:
        ridge = { p : (∇κ₁ · e₁)(p) = 0 }

    Parameters
    ----------
    surface    : NurbsSurface
    n_samples_u, n_samples_v : int — parameter grid density.
    K_threshold : float — only consider grid cells where K ≥ K_threshold.
        Positive threshold keeps convex (synclastic) regions.

    Returns
    -------
    list[RidgeLine]
        Each RidgeLine is a polyline with (u, v, x, y, z) nodes.
    """
    return _extract_feature_lines(
        surface, n_samples_u, n_samples_v,
        K_threshold=K_threshold, is_ridge=True
    )


def compute_valley_lines(
    surface: NurbsSurface,
    n_samples_u: int = 20,
    n_samples_v: int = 20,
    K_threshold: float = -0.5,
) -> List[RidgeLine]:
    """Trace valley lines on a NURBS surface.

    Valley lines satisfy the same criterion as ridge lines but for κ₂ (the
    smaller / more negative principal curvature):
        valley = { p : (∇κ₂ · e₂)(p) = 0 }

    Parameters
    ----------
    surface    : NurbsSurface
    n_samples_u, n_samples_v : int — grid density.
    K_threshold : float — only consider cells where K ≤ K_threshold.
        Negative threshold keeps concave (anticlastic) regions.

    Returns
    -------
    list[RidgeLine]
        Each RidgeLine has is_ridge=False.
    """
    return _extract_feature_lines(
        surface, n_samples_u, n_samples_v,
        K_threshold=K_threshold, is_ridge=False
    )


def _extract_feature_lines(
    surface: NurbsSurface,
    n_u: int,
    n_v: int,
    K_threshold: float,
    is_ridge: bool,
) -> List[RidgeLine]:
    """Shared implementation for ridge and valley extraction.

    Algorithm
    ---------
    1. Sample the surface on an n_u × n_v parameter grid.
    2. At each sample compute κ₁ (ridge) or κ₂ (valley) and the principal
       direction e₁ (or e₂).
    3. Compute the ridge function r(i, j) = ∇κ₁ · e₁ via finite differences
       of κ₁ across the grid.  For valleys use κ₂.
    4. Find sign changes of r across grid edges (marching-squares style): the
       zero-crossing midpoint is a candidate ridge point.
    5. Chain points into polylines by nearest-neighbour search.
    """
    n_u = max(4, int(n_u))
    n_v = max(4, int(n_v))

    u_min, u_max, v_min, v_max = _uv_domain(surface)
    us = np.linspace(u_min, u_max, n_u)
    vs = np.linspace(v_min, v_max, n_v)

    # Step 1+2: Evaluate curvature data on the grid
    K_grid  = np.full((n_u, n_v), float("nan"))
    k_feat  = np.full((n_u, n_v), float("nan"))  # κ₁ or κ₂
    e1_grid = np.empty((n_u, n_v, 3))             # principal direction
    pts_3d  = np.empty((n_u, n_v, 3))             # world positions

    for i, u in enumerate(us):
        for j, v in enumerate(vs):
            cd = _analytic_curvature_data(surface, u, v)
            if cd is None:
                continue
            K_grid[i, j] = cd["K"]
            if is_ridge:
                k_feat[i, j]  = cd["k1"]
                e1_grid[i, j] = _principal_direction_e1(cd)
            else:
                k_feat[i, j]  = cd["k2"]
                # e₂ is perpendicular to e₁ in the tangent plane
                e1 = _principal_direction_e1(cd)
                n_hat = cd["n"]
                e2 = np.cross(n_hat, e1)
                e2_nrm = float(np.linalg.norm(e2))
                e1_grid[i, j] = e2 / e2_nrm if e2_nrm > 1e-14 else e1

            try:
                from kerf_cad_core.geom.nurbs import surface_evaluate
                pt = surface_evaluate(surface, u, v)
            except Exception:
                # Fallback: evaluate using surface_derivatives
                SKL = surface_derivatives(surface, u, v, d=0)
                pt = SKL[0, 0][:3]
            pts_3d[i, j] = pt[:3]

    # Step 3: Compute ridge function r = ∇(k_feat) · e1 on the grid
    # Using central finite differences of k_feat
    r_grid = np.full((n_u, n_v), float("nan"))
    for i in range(n_u):
        for j in range(n_v):
            if not math.isfinite(k_feat[i, j]):
                continue
            if not (math.isfinite(K_grid[i, j])):
                continue
            # K threshold filter
            if is_ridge and K_grid[i, j] < K_threshold:
                continue
            if not is_ridge and K_grid[i, j] > K_threshold:
                continue

            # Finite differences of k_feat in (u, v)
            # Central diff where neighbours exist, forward/backward at boundaries.
            if 0 < i < n_u - 1 and math.isfinite(k_feat[i + 1, j]) and math.isfinite(k_feat[i - 1, j]):
                du = us[i + 1] - us[i - 1]
                dkdu = (k_feat[i + 1, j] - k_feat[i - 1, j]) / du if abs(du) > 1e-15 else 0.0
            elif i < n_u - 1 and math.isfinite(k_feat[i + 1, j]):
                du = us[i + 1] - us[i]
                dkdu = (k_feat[i + 1, j] - k_feat[i, j]) / du if abs(du) > 1e-15 else 0.0
            elif i > 0 and math.isfinite(k_feat[i - 1, j]):
                du = us[i] - us[i - 1]
                dkdu = (k_feat[i, j] - k_feat[i - 1, j]) / du if abs(du) > 1e-15 else 0.0
            else:
                dkdu = 0.0

            if 0 < j < n_v - 1 and math.isfinite(k_feat[i, j + 1]) and math.isfinite(k_feat[i, j - 1]):
                dv = vs[j + 1] - vs[j - 1]
                dkdv = (k_feat[i, j + 1] - k_feat[i, j - 1]) / dv if abs(dv) > 1e-15 else 0.0
            elif j < n_v - 1 and math.isfinite(k_feat[i, j + 1]):
                dv = vs[j + 1] - vs[j]
                dkdv = (k_feat[i, j + 1] - k_feat[i, j]) / dv if abs(dv) > 1e-15 else 0.0
            elif j > 0 and math.isfinite(k_feat[i, j - 1]):
                dv = vs[j] - vs[j - 1]
                dkdv = (k_feat[i, j] - k_feat[i, j - 1]) / dv if abs(dv) > 1e-15 else 0.0
            else:
                dkdv = 0.0

            # Project gradient into e1 direction (parameter space dot product)
            # We do this in world space: ∇K₃D · e1_world
            Su = np.array([1.0, 0.0, 0.0])  # placeholder
            cd_ij = _analytic_curvature_data(surface, float(us[i]), float(vs[j]))
            if cd_ij is None:
                continue
            Su_vec = cd_ij["Su"]
            Sv_vec = cd_ij["Sv"]
            Su_nrm = float(np.linalg.norm(Su_vec))
            Sv_nrm = float(np.linalg.norm(Sv_vec))
            Su_hat = Su_vec / Su_nrm if Su_nrm > 1e-14 else np.zeros(3)
            Sv_hat = Sv_vec / Sv_nrm if Sv_nrm > 1e-14 else np.zeros(3)
            grad_3d = dkdu * Su_hat + dkdv * Sv_hat
            e1_hat = e1_grid[i, j]
            r_grid[i, j] = float(np.dot(grad_3d, e1_hat))

    # Step 4: Find sign changes across horizontal and vertical grid edges
    candidate_pts: List[Tuple[float, float, np.ndarray, float]] = []  # (u, v, xyz, K)

    for i in range(n_u - 1):
        for j in range(n_v):
            r0 = r_grid[i, j]
            r1 = r_grid[i + 1, j]
            if not (math.isfinite(r0) and math.isfinite(r1)):
                continue
            if r0 * r1 < 0.0:
                # Linear interpolation to find zero crossing
                alpha = abs(r0) / (abs(r0) + abs(r1))
                u_c = float(us[i] + alpha * (us[i + 1] - us[i]))
                v_c = float(vs[j])
                K_c_vals = [K_grid[i, j], K_grid[i + 1, j]]
                K_c = float(np.nanmean(K_c_vals))
                # World position
                xyz_a = pts_3d[i, j]
                xyz_b = pts_3d[i + 1, j]
                if np.all(np.isfinite(xyz_a)) and np.all(np.isfinite(xyz_b)):
                    xyz_c = xyz_a + alpha * (xyz_b - xyz_a)
                    candidate_pts.append((u_c, v_c, xyz_c, K_c))

    for i in range(n_u):
        for j in range(n_v - 1):
            r0 = r_grid[i, j]
            r1 = r_grid[i, j + 1]
            if not (math.isfinite(r0) and math.isfinite(r1)):
                continue
            if r0 * r1 < 0.0:
                alpha = abs(r0) / (abs(r0) + abs(r1))
                u_c = float(us[i])
                v_c = float(vs[j] + alpha * (vs[j + 1] - vs[j]))
                K_c = float(np.nanmean([K_grid[i, j], K_grid[i, j + 1]]))
                xyz_a = pts_3d[i, j]
                xyz_b = pts_3d[i, j + 1]
                if np.all(np.isfinite(xyz_a)) and np.all(np.isfinite(xyz_b)):
                    xyz_c = xyz_a + alpha * (xyz_b - xyz_a)
                    candidate_pts.append((u_c, v_c, xyz_c, K_c))

    if not candidate_pts:
        return []

    # Step 5: Chain candidates into polylines by nearest-neighbour in 3-D
    lines = _chain_into_polylines(candidate_pts, is_ridge=is_ridge)
    return lines


def _chain_into_polylines(
    pts: List[Tuple[float, float, np.ndarray, float]],
    is_ridge: bool,
    dist_threshold: float = 1.0,
) -> List[RidgeLine]:
    """Chain unordered 3-D points into polylines by nearest-neighbour.

    Points are chained greedily: start at the first unvisited point, find its
    nearest unvisited neighbour within dist_threshold, continue until no
    neighbour is within threshold.  dist_threshold is applied to Euclidean
    distance in 3-D.

    For uniform coverage, dist_threshold defaults to 1.0 which is appropriate
    for unit-scale surfaces.  For larger surfaces, this scales with actual
    inter-point spacing.
    """
    if not pts:
        return []

    positions = np.array([p[2] for p in pts], dtype=float)  # (N, 3)
    n = len(pts)

    # Estimate a reasonable chaining distance from the data spread
    if n >= 2:
        # Use the median nearest-neighbour distance as the threshold
        from_first = np.linalg.norm(positions - positions[0], axis=1)
        from_first_sorted = np.sort(from_first[from_first > 1e-12])
        if len(from_first_sorted) > 0:
            median_spread = float(from_first_sorted[min(len(from_first_sorted) - 1, n // 2)])
            # Allow chaining across about 1/4 of the spread between samples
            dist_threshold = max(dist_threshold, median_spread * 2.0)

    used = [False] * n
    polylines: List[RidgeLine] = []

    for start in range(n):
        if used[start]:
            continue
        chain_u: List[float] = []
        chain_v: List[float] = []
        chain_xyz: List[List[float]] = []
        chain_K: List[float] = []

        cur = start
        while True:
            used[cur] = True
            u_c, v_c, xyz_c, K_c = pts[cur]
            chain_u.append(u_c)
            chain_v.append(v_c)
            chain_xyz.append(xyz_c.tolist())
            chain_K.append(K_c)

            # Find nearest unvisited neighbour
            best_dist = float("inf")
            best_idx = -1
            cur_pos = positions[cur]
            for k in range(n):
                if used[k]:
                    continue
                d = float(np.linalg.norm(positions[k] - cur_pos))
                if d < best_dist:
                    best_dist = d
                    best_idx = k

            if best_idx < 0 or best_dist > dist_threshold:
                break
            cur = best_idx

        if len(chain_u) >= 1:
            # Build point list as [u, v, x, y, z] tuples
            points_out = [
                [chain_u[k], chain_v[k]] + chain_xyz[k]
                for k in range(len(chain_u))
            ]
            polylines.append(RidgeLine(
                points=points_out,
                K_values=chain_K,
                is_ridge=is_ridge,
            ))

    return polylines


# ---------------------------------------------------------------------------
# Field visualisation grid
# ---------------------------------------------------------------------------

def curvature_gradient_field_visualization(
    surface: NurbsSurface,
    n_samples: int = 15,
) -> dict:
    """Sample the curvature-gradient field on a UV grid for visualisation.

    Returns a dict suitable for JSON serialisation that a frontend / viewport
    renderer can consume to draw ∇K arrows on the surface.

    Parameters
    ----------
    surface   : NurbsSurface
    n_samples : int — grid resolution in both U and V (clamped to [3, 60]).

    Returns
    -------
    dict
        ok (bool), reason (str on failure),
        grid (list of dicts, one per sample):
            u, v            parameter values
            x, y, z         world position
            magnitude       |∇K|
            direction_angle angle of ∇K from Sᵤ (radians)
            gradient_3d     [gx, gy, gz] world-space gradient vector
            K               Gaussian curvature
            dK_du, dK_dv    parameter-space partial derivatives
        K_min, K_max      Gaussian curvature range
        grad_mag_max      maximum |∇K| in the grid
        n_samples         actual grid size (n × n)
    """
    try:
        if not isinstance(surface, NurbsSurface):
            return {"ok": False, "reason": f"expected NurbsSurface, got {type(surface).__name__}"}

        n = max(3, min(int(n_samples), 60))
        u_min, u_max, v_min, v_max = _uv_domain(surface)
        us = np.linspace(u_min, u_max, n)
        vs = np.linspace(v_min, v_max, n)

        grid_out = []
        K_vals = []
        mag_vals = []

        try:
            from kerf_cad_core.geom.nurbs import surface_evaluate
        except ImportError:
            surface_evaluate = None

        for u in us:
            for v in vs:
                try:
                    res = compute_curvature_gradient(surface, float(u), float(v))
                except Exception:
                    continue

                # World position
                if surface_evaluate is not None:
                    try:
                        pt = surface_evaluate(surface, float(u), float(v))[:3]
                    except Exception:
                        pt = [0.0, 0.0, 0.0]
                else:
                    try:
                        SKL = surface_derivatives(surface, float(u), float(v), d=0)
                        pt = SKL[0, 0][:3].tolist()
                    except Exception:
                        pt = [0.0, 0.0, 0.0]

                entry = {
                    "u": float(u),
                    "v": float(v),
                    "x": float(pt[0]),
                    "y": float(pt[1]),
                    "z": float(pt[2]),
                    "magnitude": res.magnitude,
                    "direction_angle": res.direction_angle,
                    "gradient_3d": res.gradient_vector_3d,
                    "K": res.K,
                    "dK_du": res.dK_du,
                    "dK_dv": res.dK_dv,
                }
                grid_out.append(entry)
                K_vals.append(res.K)
                mag_vals.append(res.magnitude)

        if not grid_out:
            return {"ok": False, "reason": "no valid samples on the surface"}

        return {
            "ok": True,
            "reason": "",
            "grid": grid_out,
            "K_min": float(min(K_vals)),
            "K_max": float(max(K_vals)),
            "grad_mag_max": float(max(mag_vals)) if mag_vals else 0.0,
            "n_samples": n,
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


# ---------------------------------------------------------------------------
# LLM tool registration
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    def _build_surface_from_args(a: dict):
        """Build NurbsSurface from tool args dict. Returns (surface, error_str)."""
        from kerf_cad_core.geom.nurbs import NurbsSurface as _NS

        degree_u = a.get("degree_u")
        degree_v = a.get("degree_v")
        raw_cp = a.get("control_points", [])
        num_u = a.get("num_u")
        num_v = a.get("num_v")

        if any(x is None for x in [degree_u, degree_v, num_u, num_v]) or not raw_cp:
            return None, "degree_u, degree_v, control_points, num_u, num_v are required"

        try:
            degree_u = int(degree_u)
            degree_v = int(degree_v)
            num_u = int(num_u)
            num_v = int(num_v)
        except (TypeError, ValueError) as exc:
            return None, f"degree/num must be integers: {exc}"

        if degree_u < 1 or degree_v < 1:
            return None, "degree_u and degree_v must be >= 1"
        if num_u < 2 or num_v < 2:
            return None, "num_u and num_v must be >= 2"
        if len(raw_cp) != num_u * num_v:
            return None, f"control_points length {len(raw_cp)} != num_u*num_v={num_u * num_v}"

        try:
            cp_flat = [np.asarray(p, dtype=float) for p in raw_cp]
            dim = cp_flat[0].size
            cp = np.array([p.tolist()[:dim] for p in cp_flat], dtype=float).reshape(num_u, num_v, dim)
        except Exception as exc:
            return None, f"invalid control_points: {exc}"

        def _make_knots(n: int, deg: int) -> np.ndarray:
            inner = max(0, n - deg - 1)
            return np.concatenate([
                np.zeros(deg + 1),
                np.linspace(0.0, 1.0, inner + 2)[1:-1] if inner > 0 else np.array([]),
                np.ones(deg + 1),
            ])

        try:
            surface = _NS(
                degree_u=degree_u, degree_v=degree_v,
                control_points=cp,
                knots_u=_make_knots(num_u, degree_u),
                knots_v=_make_knots(num_v, degree_v),
            )
        except Exception as exc:
            return None, f"failed to build NurbsSurface: {exc}"

        return surface, ""

    # ------------------------------------------------------------------
    # nurbs_curvature_gradient_field
    # ------------------------------------------------------------------

    _curvature_gradient_field_spec = ToolSpec(
        name="nurbs_curvature_gradient_field",
        description=(
            "Compute the Gaussian curvature gradient field ∇K on a NURBS surface. "
            "For each sample point on a UV grid, returns |∇K| (magnitude), ∂K/∂u, ∂K/∂v, "
            "the 3-D world-space gradient vector in the tangent plane, and the direction angle "
            "from the u-tangent. Used for class-A surface inspection (ridge/valley detection), "
            "CAM toolpath optimisation, and mesh refinement.\n\n"
            "Returns: {ok, grid (list of {u,v,x,y,z,magnitude,direction_angle,gradient_3d,"
            "K,dK_du,dK_dv}), K_min, K_max, grad_mag_max, n_samples}. Never raises.\n\n"
            "Reference: do Carmo §5; Pottmann-Wallner 2001 §11."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "degree_u": {"type": "integer", "description": "Surface degree in U."},
                "degree_v": {"type": "integer", "description": "Surface degree in V."},
                "control_points": {
                    "type": "array",
                    "description": "Flattened nu*nv control points [[x,y,z], ...].",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "num_u": {"type": "integer", "description": "Number of control points in U."},
                "num_v": {"type": "integer", "description": "Number of control points in V."},
                "n_samples": {
                    "type": "integer",
                    "description": "Grid resolution (default 15, max 60).",
                },
            },
            "required": ["degree_u", "degree_v", "control_points", "num_u", "num_v"],
        },
    )

    @register(_curvature_gradient_field_spec)
    async def run_nurbs_curvature_gradient_field(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        surface, err = _build_surface_from_args(a)
        if surface is None:
            return err_payload(err, "BAD_ARGS")

        n_samples = int(a.get("n_samples", 15))
        result = curvature_gradient_field_visualization(surface, n_samples)
        if not result["ok"]:
            return err_payload(result["reason"], "OP_FAILED")
        return ok_payload(result)
