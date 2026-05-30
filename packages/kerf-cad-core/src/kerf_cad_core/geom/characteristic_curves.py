"""
characteristic_curves.py
========================
Characteristic curve extraction on NURBS surfaces (GK-P49).

Implements the canonical "feature curve" set as defined in differential
geometry of surfaces:

  * **Ridge curves** — loci where the larger principal curvature κ₁ is
    extremal along its principal direction (∇κ₁ · e₁ = 0).
  * **Valley curves** — loci where the smaller principal curvature κ₂ is
    extremal along its principal direction (∇κ₂ · e₂ = 0).
  * **Parabolic lines** — loci where the Gaussian curvature K = 0 (boundary
    between elliptic K>0 and hyperbolic K<0 regions).
  * **Umbilic points** — isolated points where κ₁ = κ₂ (principal directions
    degenerate).

Public API
----------
extract_characteristic_curves(surface, n_samples_u, n_samples_v)
    -> CharacteristicCurves

trace_curve_from_seed(surface, seed_uv, field_function, max_steps)
    -> Curve2D

CharacteristicCurves(ridges, valleys, parabolic, umbilic_points)
Curve2D — list of (u, v) parameter pairs

References
----------
Pottmann, H. & Wallner, J., *Computational Line Geometry*, Springer 2001 —
§11 ridge curves on parametric surfaces.

Belyaev, A., Anoshkina, E. & Belyaev, G., "Detection of surface creases on
triangle meshes", Lecture Notes in Computer Science, Springer 2005 — extended
ridge/valley criterion.

do Carmo, M.P., *Differential Geometry of Curves and Surfaces*,
Prentice-Hall 1976 — §3.3–3.4.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence, Tuple

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsSurface, surface_derivatives

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

# A 2-D parametric curve is a list of (u, v) pairs
Curve2D = List[Tuple[float, float]]

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class CharacteristicCurves:
    """Characteristic curves extracted from a NURBS surface.

    Attributes
    ----------
    ridges : list of Curve2D
        Parametric curves (u,v) tracing ridge lines — loci of extremal larger
        principal curvature κ₁ along its eigenvector.
    valleys : list of Curve2D
        Parametric curves tracing valley lines — loci of extremal smaller
        principal curvature κ₂ along its eigenvector.
    parabolic : list of Curve2D
        Parametric curves tracing parabolic lines (K = 0 contours).
    umbilic_points : list of tuple
        Isolated (u, v) parameter pairs where κ₁ ≈ κ₂.
    ok : bool
        True on successful extraction.
    reason : str
        Non-empty if ``ok`` is False.
    """

    ridges: List[Curve2D] = field(default_factory=list)
    valleys: List[Curve2D] = field(default_factory=list)
    parabolic: List[Curve2D] = field(default_factory=list)
    umbilic_points: List[Tuple[float, float]] = field(default_factory=list)
    ok: bool = True
    reason: str = ""


# ---------------------------------------------------------------------------
# Internal helpers — differential geometry at a (u, v) point
# ---------------------------------------------------------------------------

def _curvature_data(surf: NurbsSurface, u: float, v: float) -> Optional[dict]:
    """Full differential-geometry data at (u, v).  Returns None at singular pts.

    Keys
    ----
    Su, Sv, Suu, Svv, Suv   — first and second partial derivatives (3-vectors)
    n                        — unit outward normal
    E, F, G                  — first fundamental form coefficients
    e, f, g                  — second fundamental form coefficients (L,M,N)
    EGF2                     — EG − F²  (> 0 for regular points)
    K                        — Gaussian curvature
    H                        — mean curvature
    k1, k2                   — principal curvatures, k1 >= k2
    e1_u, e1_v               — (u,v)-parametric components of eigenvector for k1
    e2_u, e2_v               — (u,v)-parametric components of eigenvector for k2

    Reference: do Carmo §3.3–3.4; Piegl & Tiller §6.1.
    """
    try:
        SKL = surface_derivatives(surf, u, v, d=2)
    except Exception:
        return None

    Su  = SKL[1, 0][:3]
    Sv  = SKL[0, 1][:3]
    Suu = SKL[2, 0][:3]
    Svv = SKL[0, 2][:3]
    Suv = SKL[1, 1][:3]

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

    # Second fundamental form
    e = float(np.dot(Suu, n))
    f_coef = float(np.dot(Suv, n))
    g = float(np.dot(Svv, n))

    K = (e * g - f_coef * f_coef) / EGF2
    H = (e * G - 2.0 * f_coef * F + g * E) / (2.0 * EGF2)

    disc = max(0.0, H * H - K)
    sq = math.sqrt(disc)
    k1 = H + sq
    k2 = H - sq

    # Principal directions in parameter space via shape operator
    # The shape operator in the (Su, Sv) basis is  S = I^{-1} II
    # where I = [[E,F],[F,G]], II = [[e,f],[f,g]]
    # We solve (II - κ I) v = 0 for each eigenvalue
    # For k1: eigenvector direction in parameter space (qu, qv)
    #   (e - k1 E) qu + (f - k1 F) qv = 0
    #   a·qu + b·qv = 0  →  direction is (-b, a) or (b, -a)
    def _principal_direction(k: float) -> Tuple[float, float]:
        a = e - k * E
        b = f_coef - k * F
        c_val = f_coef - k * F   # second eq row coefficient
        d = g - k * G
        # Pick the most stable combination
        # From row 1: a*qu + b*qv = 0  → if |a| or |b| non-trivial
        if abs(b) > 1e-14 or abs(a) > 1e-14:
            # direction perpendicular to (a, b): (-b, a)
            qu = -b
            qv = a
        elif abs(c_val) > 1e-14 or abs(d) > 1e-14:
            qu = -d
            qv = c_val
        else:
            # Umbilic — degenerate; use u-direction
            qu = 1.0
            qv = 0.0
        # Normalise in metric (first fundamental form)
        norm2 = E * qu * qu + 2.0 * F * qu * qv + G * qv * qv
        if norm2 < 1e-20:
            return 0.0, 0.0
        s = math.sqrt(norm2)
        return qu / s, qv / s

    e1_u, e1_v = _principal_direction(k1)
    e2_u, e2_v = _principal_direction(k2)

    return {
        "Su": Su, "Sv": Sv,
        "Suu": Suu, "Svv": Svv, "Suv": Suv,
        "n": n,
        "E": E, "F": F, "G": G,
        "e": e, "f": f_coef, "g": g,
        "EGF2": EGF2,
        "K": K, "H": H,
        "k1": k1, "k2": k2,
        "e1_u": e1_u, "e1_v": e1_v,
        "e2_u": e2_u, "e2_v": e2_v,
    }


def _k1_grid(
    surf: NurbsSurface, us: np.ndarray, vs: np.ndarray
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Sample k1, k2, K, e1, e2 over the (us x vs) grid.

    Returns
    -------
    k1_grid, k2_grid, K_grid, e1_grid, e2_grid
        k1_grid, k2_grid, K_grid : (nu, nv) float arrays (nan at singular pts)
        e1_grid : (nu, nv, 2) array of (e1_u, e1_v) eigenvectors for κ₁
        e2_grid : (nu, nv, 2) array of (e2_u, e2_v) eigenvectors for κ₂
    """
    nu, nv = len(us), len(vs)
    k1_grid = np.full((nu, nv), float("nan"))
    k2_grid = np.full((nu, nv), float("nan"))
    K_grid  = np.full((nu, nv), float("nan"))
    e1_grid = np.full((nu, nv, 2), float("nan"))
    e2_grid = np.full((nu, nv, 2), float("nan"))

    for i, u in enumerate(us):
        for j, v in enumerate(vs):
            cd = _curvature_data(surf, u, v)
            if cd is None:
                continue
            k1_grid[i, j] = cd["k1"]
            k2_grid[i, j] = cd["k2"]
            K_grid[i, j]  = cd["K"]
            e1_grid[i, j, 0] = cd["e1_u"]
            e1_grid[i, j, 1] = cd["e1_v"]
            e2_grid[i, j, 0] = cd["e2_u"]
            e2_grid[i, j, 1] = cd["e2_v"]

    return k1_grid, k2_grid, K_grid, e1_grid, e2_grid


def _uv_bounds(surf: NurbsSurface) -> Tuple[float, float, float, float]:
    """Return (u_min, u_max, v_min, v_max) for the surface parameter domain."""
    return (
        float(surf.knots_u[0]), float(surf.knots_u[-1]),
        float(surf.knots_v[0]), float(surf.knots_v[-1]),
    )


def _clamp_uv(
    u: float, v: float,
    u_min: float, u_max: float, v_min: float, v_max: float,
) -> Tuple[float, float]:
    return (
        float(np.clip(u, u_min, u_max)),
        float(np.clip(v, v_min, v_max)),
    )


# ---------------------------------------------------------------------------
# Ridge / valley field function
# ---------------------------------------------------------------------------

def _ridge_field(
    surf: NurbsSurface, u: float, v: float
) -> Optional[Tuple[float, float]]:
    """Unit tangent of the ridge curve at (u, v) = eigenvector e₁ of κ₁.

    Returns (qu, qv) in metric-normalised parameter coordinates, or None.
    """
    cd = _curvature_data(surf, u, v)
    if cd is None:
        return None
    return cd["e1_u"], cd["e1_v"]


def _valley_field(
    surf: NurbsSurface, u: float, v: float
) -> Optional[Tuple[float, float]]:
    """Unit tangent of the valley curve at (u, v) = eigenvector e₂ of κ₂.

    Returns (qu, qv) in metric-normalised parameter coordinates, or None.
    """
    cd = _curvature_data(surf, u, v)
    if cd is None:
        return None
    return cd["e2_u"], cd["e2_v"]


# ---------------------------------------------------------------------------
# Runge-Kutta tracer
# ---------------------------------------------------------------------------

def trace_curve_from_seed(
    surface: NurbsSurface,
    seed_uv: Tuple[float, float],
    field_function: Callable[[NurbsSurface, float, float], Optional[Tuple[float, float]]],
    max_steps: int = 500,
    step_size: float = 0.02,
) -> Curve2D:
    """Trace a parametric curve by Runge-Kutta integration of a vector field.

    Generic integrator: from seed (u, v), follows the direction returned by
    ``field_function(surface, u, v)`` using a fixed-step RK4 scheme in
    parameter space.  The curve is traced in both the forward and backward
    direction and the two half-traces are joined.

    Parameters
    ----------
    surface : NurbsSurface
        The NURBS surface to trace on.
    seed_uv : (u0, v0)
        Starting parameter point.
    field_function : callable
        ``(surface, u, v) -> (qu, qv) | None``
        Returns the (metric-normalised) parameter-space tangent at (u, v),
        or None at degenerate points.
    max_steps : int
        Maximum steps per half-trace direction.  Default 500.
    step_size : float
        Fixed RK4 step size in parameter space.  Default 0.02.

    Returns
    -------
    Curve2D
        List of (u, v) pairs from backward end to forward end.

    Notes
    -----
    The eigenvector field has a sign ambiguity (direction not orientation); RK4
    is restarted at each step checking sign consistency with the previous step.
    """
    u_min, u_max, v_min, v_max = _uv_bounds(surface)

    def rk4_step(
        u: float, v: float, sign: float, h: float
    ) -> Optional[Tuple[float, float, float]]:
        """One RK4 step.  Returns (u_new, v_new, used_sign) or None."""
        def field(uu: float, vv: float, s: float) -> Optional[Tuple[float, float]]:
            res = field_function(surface, uu, vv)
            if res is None:
                return None
            return s * res[0], s * res[1]

        f0 = field(u, v, sign)
        if f0 is None:
            return None

        k1u, k1v = f0
        uh = u + 0.5 * h * k1u
        vh = v + 0.5 * h * k1v
        uh, vh = _clamp_uv(uh, vh, u_min, u_max, v_min, v_max)

        f1 = field(uh, vh, sign)
        if f1 is None:
            k2u, k2v = k1u, k1v
        else:
            k2u, k2v = f1

        uh2 = u + 0.5 * h * k2u
        vh2 = v + 0.5 * h * k2v
        uh2, vh2 = _clamp_uv(uh2, vh2, u_min, u_max, v_min, v_max)

        f2 = field(uh2, vh2, sign)
        if f2 is None:
            k3u, k3v = k2u, k2v
        else:
            k3u, k3v = f2

        uf = u + h * k3u
        vf = v + h * k3v
        uf, vf = _clamp_uv(uf, vf, u_min, u_max, v_min, v_max)

        f3 = field(uf, vf, sign)
        if f3 is None:
            k4u, k4v = k3u, k3v
        else:
            k4u, k4v = f3

        du = h * (k1u + 2 * k2u + 2 * k3u + k4u) / 6.0
        dv = h * (k1v + 2 * k2v + 2 * k3v + k4v) / 6.0

        u_new = float(np.clip(u + du, u_min, u_max))
        v_new = float(np.clip(v + dv, v_min, v_max))
        return u_new, v_new, sign

    def _trace_half(
        u0: float, v0: float, direction: float
    ) -> List[Tuple[float, float]]:
        pts: List[Tuple[float, float]] = []
        u, v = u0, v0
        sign = direction

        for _ in range(max_steps):
            pts.append((u, v))
            result = rk4_step(u, v, sign, step_size)
            if result is None:
                break
            u_new, v_new, _ = result

            # Detect boundary stalling
            if abs(u_new - u) < 1e-12 and abs(v_new - v) < 1e-12:
                break

            # Sign consistency: check if field at new point aligns with direction
            new_field = field_function(surface, u_new, v_new)
            if new_field is not None:
                dot = sign * (new_field[0] * (u_new - u) + new_field[1] * (v_new - v))
                if dot < 0:
                    sign = -sign

            u, v = u_new, v_new

        return pts

    u0, v0 = float(seed_uv[0]), float(seed_uv[1])
    forward  = _trace_half(u0, v0, +1.0)
    backward = _trace_half(u0, v0, -1.0)

    # Join: backward list is reversed (it goes away from seed in -dir),
    # skip the duplicated seed point at the start of each half
    result = list(reversed(backward[1:])) + forward
    return result


# ---------------------------------------------------------------------------
# Zero-crossing contour tracer for K = 0 (parabolic lines)
# ---------------------------------------------------------------------------

def _trace_parabolic_lines(
    surf: NurbsSurface,
    us: np.ndarray,
    vs: np.ndarray,
    K_grid: np.ndarray,
) -> List[Curve2D]:
    """Trace K = 0 contour segments from the pre-sampled K_grid.

    Uses a marching-squares approach on the (u,v) grid: for each grid cell
    where K changes sign, linearly interpolates the zero-crossing along the
    cell edges and assembles the contour.

    Returns a list of Curve2D (each a sequence of (u,v) pairs).
    """
    nu, nv = len(us), len(vs)
    segments: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []

    for i in range(nu - 1):
        for j in range(nv - 1):
            # Corners of cell (i,j): (i,j), (i+1,j), (i+1,j+1), (i,j+1)
            corners = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
            vals = [K_grid[ci, cj] for (ci, cj) in corners]
            coords = [(us[ci], vs[cj]) for (ci, cj) in corners]

            # Find sign-change edges (4 edges: 0-1, 1-2, 2-3, 3-0)
            edges = [(0, 1), (1, 2), (2, 3), (3, 0)]
            crossings: List[Tuple[float, float]] = []
            for ea, eb in edges:
                ka, kb = vals[ea], vals[eb]
                if (not math.isfinite(ka)) or (not math.isfinite(kb)):
                    continue
                if ka * kb < 0:  # sign change
                    # Linear interpolation for crossing
                    t = ka / (ka - kb)
                    ua_coord, va_coord = coords[ea]
                    ub_coord, vb_coord = coords[eb]
                    u_cross = ua_coord + t * (ub_coord - ua_coord)
                    v_cross = va_coord + t * (vb_coord - va_coord)
                    crossings.append((u_cross, v_cross))

            if len(crossings) == 2:
                segments.append((crossings[0], crossings[1]))

    if not segments:
        return []

    # Stitch segments into polylines via greedy nearest-endpoint matching
    curves: List[Curve2D] = []
    remaining = list(segments)
    tol = 1e-9

    while remaining:
        seg = remaining.pop(0)
        chain: List[Tuple[float, float]] = [seg[0], seg[1]]

        changed = True
        while changed:
            changed = False
            new_remaining = []
            for s in remaining:
                # Try attaching to chain head or tail
                head = chain[0]
                tail = chain[-1]
                d_sh = (s[0][0] - head[0]) ** 2 + (s[0][1] - head[1]) ** 2
                d_sh2 = (s[1][0] - head[0]) ** 2 + (s[1][1] - head[1]) ** 2
                d_st = (s[0][0] - tail[0]) ** 2 + (s[0][1] - tail[1]) ** 2
                d_st2 = (s[1][0] - tail[0]) ** 2 + (s[1][1] - tail[1]) ** 2
                min_d = min(d_sh, d_sh2, d_st, d_st2)

                if min_d < tol:
                    changed = True
                    if min_d == d_sh:
                        chain.insert(0, s[1])
                    elif min_d == d_sh2:
                        chain.insert(0, s[0])
                    elif min_d == d_st:
                        chain.append(s[1])
                    else:
                        chain.append(s[0])
                else:
                    new_remaining.append(s)
            remaining = new_remaining

        curves.append(chain)

    return curves


# ---------------------------------------------------------------------------
# Ridge / valley seed detection
# ---------------------------------------------------------------------------

def _ridge_sign_field(
    K1_grid: np.ndarray,
    e1_grid: np.ndarray,
    us: np.ndarray,
    vs: np.ndarray,
) -> np.ndarray:
    """Compute the ridge indicator ∇κ₁ · e₁ on the grid via finite differences.

    Returns a (nu, nv) array whose sign changes mark ridge loci.
    Ridge lines pass through zeros of this field.
    """
    nu, nv = len(us), len(vs)
    du = (us[-1] - us[0]) / max(nu - 1, 1)
    dv = (vs[-1] - vs[0]) / max(nv - 1, 1)

    # Gradient of κ₁ via central differences
    grad_u = np.full((nu, nv), float("nan"))
    grad_v = np.full((nu, nv), float("nan"))

    for i in range(nu):
        for j in range(nv):
            if i == 0:
                if math.isfinite(K1_grid[0, j]) and math.isfinite(K1_grid[1, j]):
                    grad_u[i, j] = (K1_grid[1, j] - K1_grid[0, j]) / du
            elif i == nu - 1:
                if math.isfinite(K1_grid[nu-1, j]) and math.isfinite(K1_grid[nu-2, j]):
                    grad_u[i, j] = (K1_grid[nu-1, j] - K1_grid[nu-2, j]) / du
            else:
                if (math.isfinite(K1_grid[i+1, j]) and math.isfinite(K1_grid[i-1, j])):
                    grad_u[i, j] = (K1_grid[i+1, j] - K1_grid[i-1, j]) / (2.0 * du)

            if j == 0:
                if math.isfinite(K1_grid[i, 0]) and math.isfinite(K1_grid[i, 1]):
                    grad_v[i, j] = (K1_grid[i, 1] - K1_grid[i, 0]) / dv
            elif j == nv - 1:
                if math.isfinite(K1_grid[i, nv-1]) and math.isfinite(K1_grid[i, nv-2]):
                    grad_v[i, j] = (K1_grid[i, nv-1] - K1_grid[i, nv-2]) / dv
            else:
                if (math.isfinite(K1_grid[i, j+1]) and math.isfinite(K1_grid[i, j-1])):
                    grad_v[i, j] = (K1_grid[i, j+1] - K1_grid[i, j-1]) / (2.0 * dv)

    # Ridge indicator: dot(∇κ₁, e₁)
    indicator = np.full((nu, nv), float("nan"))
    for i in range(nu):
        for j in range(nv):
            eu, ev = e1_grid[i, j, 0], e1_grid[i, j, 1]
            gu, gv = grad_u[i, j], grad_v[i, j]
            if all(math.isfinite(x) for x in [eu, ev, gu, gv]):
                indicator[i, j] = gu * eu + gv * ev

    return indicator


def _valley_sign_field(
    K2_grid: np.ndarray,
    e2_grid: np.ndarray,
    us: np.ndarray,
    vs: np.ndarray,
) -> np.ndarray:
    """Compute the valley indicator ∇κ₂ · e₂ on the grid via finite differences."""
    nu, nv = len(us), len(vs)
    du = (us[-1] - us[0]) / max(nu - 1, 1)
    dv = (vs[-1] - vs[0]) / max(nv - 1, 1)

    grad_u = np.full((nu, nv), float("nan"))
    grad_v = np.full((nu, nv), float("nan"))

    for i in range(nu):
        for j in range(nv):
            if i == 0:
                if math.isfinite(K2_grid[0, j]) and math.isfinite(K2_grid[1, j]):
                    grad_u[i, j] = (K2_grid[1, j] - K2_grid[0, j]) / du
            elif i == nu - 1:
                if math.isfinite(K2_grid[nu-1, j]) and math.isfinite(K2_grid[nu-2, j]):
                    grad_u[i, j] = (K2_grid[nu-1, j] - K2_grid[nu-2, j]) / du
            else:
                if (math.isfinite(K2_grid[i+1, j]) and math.isfinite(K2_grid[i-1, j])):
                    grad_u[i, j] = (K2_grid[i+1, j] - K2_grid[i-1, j]) / (2.0 * du)

            if j == 0:
                if math.isfinite(K2_grid[i, 0]) and math.isfinite(K2_grid[i, 1]):
                    grad_v[i, j] = (K2_grid[i, 1] - K2_grid[i, 0]) / dv
            elif j == nv - 1:
                if math.isfinite(K2_grid[i, nv-1]) and math.isfinite(K2_grid[i, nv-2]):
                    grad_v[i, j] = (K2_grid[i, nv-1] - K2_grid[i, nv-2]) / dv
            else:
                if (math.isfinite(K2_grid[i, j+1]) and math.isfinite(K2_grid[i, j-1])):
                    grad_v[i, j] = (K2_grid[i, j+1] - K2_grid[i, j-1]) / (2.0 * dv)

    indicator = np.full((nu, nv), float("nan"))
    for i in range(nu):
        for j in range(nv):
            eu, ev = e2_grid[i, j, 0], e2_grid[i, j, 1]
            gu, gv = grad_u[i, j], grad_v[i, j]
            if all(math.isfinite(x) for x in [eu, ev, gu, gv]):
                indicator[i, j] = gu * eu + gv * ev

    return indicator


def _find_sign_change_seeds(
    indicator: np.ndarray, us: np.ndarray, vs: np.ndarray, tol: float = 1e-10
) -> List[Tuple[float, float]]:
    """Find (u, v) seed points from sign-change cells in the indicator grid.

    For each grid cell where the indicator changes sign, returns the
    linearly-interpolated zero-crossing as a seed for the curve tracer.
    Deduplicates seeds within proximity ``tol``.
    """
    nu, nv = len(us), len(vs)
    seeds: List[Tuple[float, float]] = []

    for i in range(nu - 1):
        for j in range(nv - 1):
            val = indicator[i, j]
            if not math.isfinite(val):
                continue
            # Check right neighbour (i, j+1)
            val_r = indicator[i, j + 1]
            if math.isfinite(val_r) and val * val_r < 0:
                t = val / (val - val_r)
                seeds.append((us[i], vs[j] + t * (vs[j + 1] - vs[j])))
            # Check bottom neighbour (i+1, j)
            val_b = indicator[i + 1, j]
            if math.isfinite(val_b) and val * val_b < 0:
                t = val / (val - val_b)
                seeds.append((us[i] + t * (us[i + 1] - us[i]), vs[j]))

    # Deduplicate
    unique: List[Tuple[float, float]] = []
    for s in seeds:
        if all(
            abs(s[0] - q[0]) > tol or abs(s[1] - q[1]) > tol
            for q in unique
        ):
            unique.append(s)

    return unique


# ---------------------------------------------------------------------------
# Umbilic point detection
# ---------------------------------------------------------------------------

def _find_umbilic_points(
    k1_grid: np.ndarray,
    k2_grid: np.ndarray,
    us: np.ndarray,
    vs: np.ndarray,
    rel_tol: float = 0.01,
) -> List[Tuple[float, float]]:
    """Find (u, v) parameter pairs where κ₁ ≈ κ₂.

    Uses a relative tolerance: |κ₁ - κ₂| / (|κ₁| + |κ₂| + ε) < rel_tol.
    Returns the grid sample closest to the local minimum of |κ₁ - κ₂|.

    An umbilic is a point where principal directions degenerate because the
    surface is locally spherical (κ₁ = κ₂) or flat (κ₁ = κ₂ = 0).
    """
    nu, nv = len(us), len(vs)
    diff = np.full((nu, nv), float("nan"))
    for i in range(nu):
        for j in range(nv):
            k1, k2 = k1_grid[i, j], k2_grid[i, j]
            if math.isfinite(k1) and math.isfinite(k2):
                denom = abs(k1) + abs(k2) + 1e-12
                diff[i, j] = abs(k1 - k2) / denom

    umbilics: List[Tuple[float, float]] = []
    visited = set()

    for i in range(nu):
        for j in range(nv):
            if not math.isfinite(diff[i, j]):
                continue
            if diff[i, j] < rel_tol:
                # Check it's a local minimum of diff (avoids degenerate flat patches)
                neighbours = []
                for di in [-1, 0, 1]:
                    for dj in [-1, 0, 1]:
                        ni, nj = i + di, j + dj
                        if 0 <= ni < nu and 0 <= nj < nv and math.isfinite(diff[ni, nj]):
                            neighbours.append(diff[ni, nj])
                if diff[i, j] <= min(neighbours) if neighbours else True:
                    key = (i, j)
                    if key not in visited:
                        visited.add(key)
                        umbilics.append((float(us[i]), float(vs[j])))

    return umbilics


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def extract_characteristic_curves(
    surface: NurbsSurface,
    n_samples_u: int = 30,
    n_samples_v: int = 30,
) -> CharacteristicCurves:
    """Extract characteristic curves from a NURBS surface.

    Computes the canonical differential-geometry feature set:

    * **Ridge curves** — loci where the larger principal curvature κ₁ has
      zero directional derivative along its eigenvector e₁ (∇κ₁ · e₁ = 0).
      These mark topographic ridges on the curvature landscape.

    * **Valley curves** — loci where the smaller principal curvature κ₂ has
      zero directional derivative along its eigenvector e₂ (∇κ₂ · e₂ = 0).
      These mark curvature valleys.

    * **Parabolic lines** — contours of K = 0 separating elliptic (K > 0)
      from hyperbolic (K < 0) regions.  Traced by marching squares on the
      sampled Gaussian-curvature grid.

    * **Umbilic points** — isolated parameter loci where κ₁ ≈ κ₂, so the
      principal directions degenerate.  On a sphere all points are umbilic.

    Algorithm
    ---------
    1. Sample the surface curvature data on an (n_samples_u × n_samples_v)
       parameter grid.
    2. For ridges/valleys: compute the directional-derivative indicators
       (∇κ₁ · e₁ and ∇κ₂ · e₂) via finite differences on the grid.  Find
       sign-change seed points, then trace each curve via RK4 integration
       along the respective eigenvector field (Pottmann-Wallner §11).
    3. For parabolic lines: run marching squares on the K grid to produce
       contour segments and stitch them into polylines.
    4. For umbilic points: scan the grid for local minima of |κ₁ - κ₂|.

    Parameters
    ----------
    surface : NurbsSurface
        The NURBS surface to analyse.
    n_samples_u : int
        Grid resolution in U.  Default 30.  Clamped to [5, 200].
    n_samples_v : int
        Grid resolution in V.  Default 30.  Clamped to [5, 200].

    Returns
    -------
    CharacteristicCurves
        Dataclass with ``ridges``, ``valleys``, ``parabolic``, and
        ``umbilic_points``.  ``ok=False`` if the surface type is wrong.

    References
    ----------
    Pottmann & Wallner 2001 §11 (ridge curves on parametric surfaces).
    Belyaev-Anoshkina-Belyaev 2005 (ridge/valley on meshes, extended to NURBS).
    do Carmo 1976 §3.3–3.4 (shape operator, principal directions).
    """
    if not isinstance(surface, NurbsSurface):
        return CharacteristicCurves(
            ok=False, reason=f"expected NurbsSurface, got {type(surface).__name__}"
        )

    n_samples_u = int(np.clip(n_samples_u, 5, 200))
    n_samples_v = int(np.clip(n_samples_v, 5, 200))

    try:
        u_min, u_max, v_min, v_max = _uv_bounds(surface)
        us = np.linspace(u_min, u_max, n_samples_u)
        vs = np.linspace(v_min, v_max, n_samples_v)

        # 1. Sample curvature data
        k1_grid, k2_grid, K_grid, e1_grid, e2_grid = _k1_grid(surface, us, vs)

        # 2. Parabolic lines (K = 0 contours) — marching squares
        parabolic = _trace_parabolic_lines(surface, us, vs, K_grid)

        # 3. Umbilic points
        umbilic_pts = _find_umbilic_points(k1_grid, k2_grid, us, vs)

        # 4. Ridge curves (∇κ₁ · e₁ = 0)
        ridge_indicator = _ridge_sign_field(k1_grid, e1_grid, us, vs)
        ridge_seeds = _find_sign_change_seeds(ridge_indicator, us, vs)

        ridges: List[Curve2D] = []
        # Adaptive step size relative to parameter domain width
        step_u = (u_max - u_min) / n_samples_u
        step_v = (v_max - v_min) / n_samples_v
        step = min(step_u, step_v) * 0.8

        for seed in ridge_seeds:
            curve = trace_curve_from_seed(
                surface, seed, _ridge_field,
                max_steps=400, step_size=step,
            )
            if len(curve) >= 2:
                ridges.append(curve)

        # 5. Valley curves (∇κ₂ · e₂ = 0)
        valley_indicator = _valley_sign_field(k2_grid, e2_grid, us, vs)
        valley_seeds = _find_sign_change_seeds(valley_indicator, us, vs)

        valleys: List[Curve2D] = []
        for seed in valley_seeds:
            curve = trace_curve_from_seed(
                surface, seed, _valley_field,
                max_steps=400, step_size=step,
            )
            if len(curve) >= 2:
                valleys.append(curve)

        return CharacteristicCurves(
            ridges=ridges,
            valleys=valleys,
            parabolic=parabolic,
            umbilic_points=umbilic_pts,
            ok=True,
            reason="",
        )

    except Exception as exc:  # noqa: BLE001
        return CharacteristicCurves(ok=False, reason=str(exc))


# ---------------------------------------------------------------------------
# LLM tool registration (gated, mirrors surface_analysis.py pattern)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json

    import numpy as _np
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    _characteristic_curves_spec = ToolSpec(
        name="nurbs_extract_characteristic_curves",
        description=(
            "Extract characteristic curves from a NURBS surface:\n"
            "  • ridge curves  — loci of extremal larger principal curvature κ₁ "
            "along its eigenvector (∇κ₁ · e₁ = 0; Pottmann-Wallner §11)\n"
            "  • valley curves — loci of extremal smaller principal curvature κ₂\n"
            "  • parabolic lines — K = 0 contours (elliptic/hyperbolic boundary)\n"
            "  • umbilic points — κ₁ ≈ κ₂ (degenerate principal directions)\n\n"
            "Samples a UV grid, computes curvature derivatives, then traces curves "
            "by RK4 integration along the principal-direction eigenvector fields.\n\n"
            "Returns: {ok, ridges, valleys, parabolic, umbilic_points}.\n"
            "  ridges/valleys/parabolic: list of curves, each a list of [u,v] pairs.\n"
            "  umbilic_points: list of [u,v] pairs.\n"
            "Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "degree_u": {
                    "type": "integer",
                    "description": "Surface degree in U direction.",
                },
                "degree_v": {
                    "type": "integer",
                    "description": "Surface degree in V direction.",
                },
                "control_points": {
                    "type": "array",
                    "description": "Flattened nu*nv control points as [[x,y,z], ...].",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "num_u": {
                    "type": "integer",
                    "description": "Number of control points in U.",
                },
                "num_v": {
                    "type": "integer",
                    "description": "Number of control points in V.",
                },
                "n_samples_u": {
                    "type": "integer",
                    "description": "UV sampling resolution in U (default 30).",
                },
                "n_samples_v": {
                    "type": "integer",
                    "description": "UV sampling resolution in V (default 30).",
                },
            },
            "required": ["degree_u", "degree_v", "control_points", "num_u", "num_v"],
        },
    )

    def _build_surface_from_args(a: dict):
        """Build NurbsSurface from LLM tool args dict.  Returns (surface, error_str)."""
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
            cp_flat = [_np.asarray(p, dtype=float) for p in raw_cp]
            dim = cp_flat[0].size
            cp = _np.array(
                [p.tolist()[:dim] for p in cp_flat], dtype=float
            ).reshape(num_u, num_v, dim)
        except Exception as exc:
            return None, f"invalid control_points: {exc}"

        def _make_knots(n: int, deg: int) -> _np.ndarray:
            inner = max(0, n - deg - 1)
            return _np.concatenate([
                _np.zeros(deg + 1),
                _np.linspace(0.0, 1.0, inner + 2)[1:-1] if inner > 0 else _np.array([]),
                _np.ones(deg + 1),
            ])

        try:
            surface = NurbsSurface(
                degree_u=degree_u,
                degree_v=degree_v,
                control_points=cp,
                knots_u=_make_knots(num_u, degree_u),
                knots_v=_make_knots(num_v, degree_v),
            )
        except Exception as exc:
            return None, f"failed to build NurbsSurface: {exc}"

        return surface, ""

    @register(_characteristic_curves_spec)
    async def run_nurbs_extract_characteristic_curves(
        ctx: "ProjectCtx", args: bytes
    ) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        surface, err = _build_surface_from_args(a)
        if surface is None:
            return err_payload(err, "BAD_ARGS")

        nu = int(a.get("n_samples_u", 30))
        nv = int(a.get("n_samples_v", 30))

        result = extract_characteristic_curves(surface, nu, nv)
        if not result.ok:
            return err_payload(result.reason, "OP_FAILED")

        # Serialise to JSON-safe format
        payload = {
            "ok": True,
            "reason": "",
            "ridges": [list(c) for c in result.ridges],
            "valleys": [list(c) for c in result.valleys],
            "parabolic": [list(c) for c in result.parabolic],
            "umbilic_points": list(result.umbilic_points),
            "n_ridges": len(result.ridges),
            "n_valleys": len(result.valleys),
            "n_parabolic": len(result.parabolic),
            "n_umbilic": len(result.umbilic_points),
        }
        return ok_payload(payload)
