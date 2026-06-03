"""
nurbs_derivative.py — NURBS Analytic Surface Derivatives
=========================================================
Piegl & Tiller, "The NURBS Book" 2nd ed. (Springer 1997) §3.3

Public API
----------
``surface_derivatives(surf, u, v, d)``
    Returns all mixed partial derivatives of total order ≤ d at (u, v) as a
    dict keyed by ``(k, l)`` where ``k + l ≤ d``.

``surface_derivative_single(surf, u, v, k, l)``
    Single specific derivative ∂^(k+l) S / ∂u^k ∂v^l.

``fundamental_forms(surf, u, v)``
    First + second fundamental forms, mean curvature H, Gaussian curvature K,
    and principal curvatures (k1, k2).

Implementation notes
--------------------
All computation delegates to the canonical
``kerf_cad_core.geom.nurbs.surface_derivatives`` (array form), which
implements:

  * P&T Algorithm A2.3 — DersBasisFuns (basis function derivatives)
  * P&T Algorithm A3.6 — SurfaceDerivsAlg1/2 (B-spline tensor-product
    derivative table in homogeneous space)
  * P&T Algorithm A4.4 — Rational quotient-rule (Leibniz recursion)

This module provides the dict-keyed wrapper, convenience helpers, and the
differential-geometry layer (do Carmo §3.2).

References
----------
* Piegl & Tiller. *The NURBS Book*, 2nd ed., Springer 1997.
  §2.5 A2.3 (DersBasisFuns), §3.3 A3.6 (SurfaceDerivsAlg2),
  §4.4 A4.4 (SurfPointByCornerCut / rational quotient rule).
* do Carmo, M.P. *Differential Geometry of Curves and Surfaces*, §3.2.
"""

from __future__ import annotations

import math
from typing import Dict, Sequence, Tuple

import numpy as np

from kerf_cad_core.geom.nurbs import (
    NurbsSurface,
    # Array-form surface derivative table (shape (d+1, d+1, dim)).
    # Implements P&T A3.6 + A4.4 (rational quotient rule).
    surface_derivatives as _surface_derivatives_array,
    surface_evaluate as _surface_evaluate,
)


# ---------------------------------------------------------------------------
# Pascal-triangle binomial coefficients (no scipy dependency)
# ---------------------------------------------------------------------------

def _build_pascal(n: int) -> np.ndarray:
    """Return a (n+1, n+1) Pascal triangle: entry [i,j] = C(i, j).

    Used internally; built once per call, cheap for d ≤ 10.
    """
    C = np.zeros((n + 1, n + 1), dtype=float)
    for i in range(n + 1):
        C[i, 0] = 1.0
        for j in range(1, i + 1):
            C[i, j] = C[i - 1, j - 1] + C[i - 1, j]
    return C


# ---------------------------------------------------------------------------
# Core: dict-keyed surface derivative table
# ---------------------------------------------------------------------------


def surface_derivatives(
    surf: NurbsSurface,
    u: float,
    v: float,
    d: int,
) -> Dict[Tuple[int, int], np.ndarray]:
    """All surface derivatives of total order ≤ d at (u, v).

    Key:   (k, l)  where k = u-differentiation order, l = v-order, k+l ≤ d.
    Value: 3-vector  ∂^(k+l) S / ∂u^k ∂v^l.

    Implementation
    --------------
    1. Delegate to the array-form ``_surface_derivatives_array(surf, u, v, d)``
       which returns SKL[k, l] of shape (d+1, d+1, dim) using:

         * P&T A2.3 — DersBasisFuns for each knot direction.
         * P&T A3.6 — B-spline tensor-product derivative table
           (homogeneous coordinates: control points weighted as Pw = w·P).
         * P&T A4.4 — Leibniz rational quotient-rule recovery:

             S^(k,l) = (A^(k,l)
                        − Σ_{j=1}^{l} C(l,j)·w^(0,j)·S^(k,l-j)
                        − Σ_{i=1}^{k} C(k,i)·w^(i,0)·S^(k-i,l)
                        − Σ_{i=1}^{k} C(k,i)·Σ_{j=1}^{l} C(l,j)·w^(i,j)·S^(k-i,l-j)
                       ) / w^(0,0)

    2. Slice the array into a ``{(k, l): vec}`` dict for all k+l ≤ d.

    Parameters
    ----------
    surf : NurbsSurface
        The NURBS surface to differentiate.
    u, v : float
        Parameter values within the surface's knot domain.
    d : int
        Maximum total derivative order (≥ 0).

    Returns
    -------
    dict[(k, l), np.ndarray]
        All partial derivatives of total order k + l ≤ d.
        (0, 0) gives the surface position S(u, v).
    """
    if d < 0:
        raise ValueError("derivative order d must be >= 0")

    # Clamp to domain.
    u, v = _clamp_uv(surf, float(u), float(v))

    # Delegate to the array-form implementation (P&T A3.6 + A4.4).
    SKL = _surface_derivatives_array(surf, u, v, d)  # shape (d+1, d+1, 3)

    result: Dict[Tuple[int, int], np.ndarray] = {}
    for k in range(d + 1):
        for l in range(d + 1 - k):
            result[(k, l)] = SKL[k, l, :3].copy()

    return result


def surface_derivative_single(
    surf: NurbsSurface,
    u: float,
    v: float,
    k: int,
    l: int,
) -> np.ndarray:
    """Single specific derivative ∂^(k+l) S / ∂u^k ∂v^l at (u, v).

    Parameters
    ----------
    surf : NurbsSurface
    u, v : float  — parameter values
    k    : int    — u-differentiation order (≥ 0)
    l    : int    — v-differentiation order (≥ 0)

    Returns
    -------
    np.ndarray, shape (3,)
    """
    if k < 0 or l < 0:
        raise ValueError("derivative orders k, l must be >= 0")
    d = k + l
    derivs = surface_derivatives(surf, u, v, d)
    return derivs[(k, l)]


# ---------------------------------------------------------------------------
# Fundamental forms and curvature (do Carmo §3.2)
# ---------------------------------------------------------------------------


def fundamental_forms(surf: NurbsSurface, u: float, v: float) -> dict:
    """First and second fundamental forms of the surface at (u, v).

    Computes the second-order derivative table (P&T A3.6 / A4.4) and uses
    it to build the classical differential-geometry quantities
    (do Carmo, §3.2; Mortenson §6.5).

    Formulae
    --------
    Let S_u = ∂S/∂u, S_v = ∂S/∂v, S_uu = ∂²S/∂u², etc.
    Unit normal: n̂ = (S_u × S_v) / |S_u × S_v|.

    First fundamental form coefficients:
        E = S_u · S_u,   F = S_u · S_v,   G = S_v · S_v.

    Second fundamental form coefficients:
        L = S_uu · n̂,   M = S_uv · n̂,   N = S_vv · n̂.

    Gaussian curvature (Brioschi / shape-operator):
        K = (L·N − M²) / (E·G − F²).

    Mean curvature:
        H = (E·N − 2·F·M + G·L) / (2·(E·G − F²)).

    Principal curvatures (roots of the characteristic polynomial of the
    shape operator):
        k1, k2 = H ± sqrt(H² − K).

    Parameters
    ----------
    surf : NurbsSurface
    u, v : float — parameter values

    Returns
    -------
    dict with keys:
        'E', 'F', 'G'       — first fundamental form coefficients (float)
        'L', 'M', 'N'       — second fundamental form coefficients (float)
        'normal'            — unit surface normal np.ndarray(3,)
        'mean_curvature'    — H (float; NaN at degenerate points)
        'gaussian_curvature'— K (float; NaN at degenerate points)
        'principal_curvatures' — (k1, k2) tuple of floats (NaN at degen.)
    """
    u, v = _clamp_uv(surf, float(u), float(v))

    # Second-order derivative table (P&T A3.6 + A4.4).
    SKL = _surface_derivatives_array(surf, u, v, d=2)
    su  = SKL[1, 0, :3]
    sv  = SKL[0, 1, :3]
    suu = SKL[2, 0, :3]
    suv = SKL[1, 1, :3]
    svv = SKL[0, 2, :3]

    # First fundamental form.
    E = float(np.dot(su, su))
    F = float(np.dot(su, sv))
    G = float(np.dot(sv, sv))
    denom = E * G - F * F

    # Unit normal.
    cross = np.cross(su, sv)
    cross_mag = float(np.linalg.norm(cross))
    is_degen = cross_mag < 1e-12
    n_hat = cross / cross_mag if not is_degen else np.array([0.0, 0.0, 1.0])

    # Second fundamental form.
    L = float(np.dot(suu, n_hat))
    M = float(np.dot(suv, n_hat))
    N = float(np.dot(svv, n_hat))

    # Curvatures.
    if is_degen or abs(denom) < 1e-30:
        K = float("nan")
        H = float("nan")
        k1 = float("nan")
        k2 = float("nan")
    else:
        K = (L * N - M * M) / denom
        H = (E * N - 2.0 * F * M + G * L) / (2.0 * denom)
        # Principal curvatures: roots of κ² − 2H·κ + K = 0.
        disc = H * H - K
        disc = max(disc, 0.0)   # guard against tiny negative rounding noise
        sq = math.sqrt(disc)
        k1 = H + sq
        k2 = H - sq

    return {
        "E": E,
        "F": F,
        "G": G,
        "L": L,
        "M": M,
        "N": N,
        "normal": n_hat,
        "mean_curvature": H,
        "gaussian_curvature": K,
        "principal_curvatures": (k1, k2),
    }


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


def _clamp_uv(surf: NurbsSurface, u: float, v: float) -> Tuple[float, float]:
    """Clamp (u, v) to the surface's valid knot domain."""
    pu, pv = surf.degree_u, surf.degree_v
    u_min = float(surf.knots_u[pu])
    u_max = float(surf.knots_u[-pu - 1])
    v_min = float(surf.knots_v[pv])
    v_max = float(surf.knots_v[-pv - 1])
    return max(u_min, min(u_max, u)), max(v_min, min(v_max, v))
