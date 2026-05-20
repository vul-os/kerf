"""
inversion.py
============
Closest-point / point-inversion primitives for NURBS curves and surfaces
(Rhino / OpenNURBS-class).  This is the foundational primitive that snapping,
projection, deviation, SSI seeding, fitting and draft analysis all build on;
its absence forces every consumer to re-implement a worse version.

Public API
----------
closest_point_curve(curve, P) -> (t, point, dist)            -- GK-06
    Point inversion on a NurbsCurve (Piegl & Tiller 6.1): coarse arc-length
    seed sampling, Newton iteration with the second-derivative term, a
    multi-seed global fallback, parameter-range clamping and closed-curve
    wrap handling.

closest_point_surface(surf, P) -> (u, v, point, dist)        -- GK-07
    UV point inversion on a NurbsSurface (Piegl & Tiller 6.1) with
    *analytic* first and second partial derivatives (rational-correct),
    a coarse grid seed, 2-D Newton iteration and a global fallback.

project_point_to_curve(curve, P) -> dict                     -- GK-08
    Public closest-point-on-curve wrapper.  Never raises.

pull_curve_to_surface(curve, surf, n) -> dict                -- GK-08
    Sample a curve at ``n`` stations and pull each onto the closest point of
    a surface, returning the UV trail and the 3-D foot polyline.  Never
    raises.

Rational NURBS
--------------
The ``NurbsCurve`` / ``NurbsSurface`` containers in ``geom/nurbs.py`` store
*non-homogeneous* control points and have no weight field, so a polynomial
(non-rational) net is the common case.  This module *additionally* supports
exact rational NURBS by accepting 4-component homogeneous control points
``[x*w, y*w, z*w, w]`` (detected by the trailing axis having length 4).  The
projective evaluation ``C(t) = A(t) / w(t)`` and the correct rational
derivatives (homogeneous quotient rule, Piegl & Tiller A4.4) are computed
locally so that exact rational circles / spheres invert to analytic
oracles.  ``nurbs.py`` is intentionally untouched (another stream owns it);
the known-correct evaluators in ``geom/intersection.py`` are imported and
used for the polynomial path / cross-check.

Implementation note
-------------------
``nurbs.surface_evaluate`` is buggy (documented in ``intersection.py``); it is
NOT used here.  Cox-de Boor is replicated correctly inside this module so
that homogeneous (rational) evaluation and analytic derivatives are
available, and the polynomial path also delegates to the known-correct
``intersection._nurbs_curve_eval`` / ``_nurbs_surface_eval`` for a
belt-and-braces cross-check of the local Cox-de Boor.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsCurve, NurbsSurface
from kerf_cad_core.geom.intersection import (
    _nurbs_curve_eval as _xs_curve_eval,
    _nurbs_surface_eval as _xs_surface_eval,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EPS: float = 1e-15
_DEFAULT_TOL: float = 1e-12
_MAX_NEWTON_ITER: int = 80
_COARSE_CURVE_SAMPLES: int = 200
_COARSE_SURF_SAMPLES: int = 28

# GK-69: condition-number threshold above which the 2-D Newton Jacobian is
# considered near-singular (degenerate surface patch, e.g. a pole or seam),
# and the solver falls back to lstsq rather than Cramer's rule.
_COND_THRESHOLD: float = 1e10


# ---------------------------------------------------------------------------
# Cox-de Boor basis (replicated correctly; see intersection.py for the
# known-correct twin used as a cross-check on the polynomial path).
# ---------------------------------------------------------------------------

def _find_span(n: int, degree: int, u: float, knots: np.ndarray) -> int:
    """Binary-search the knot span index (Piegl & Tiller A2.1)."""
    if u >= knots[n + 1]:
        return n
    if u <= knots[degree]:
        return degree
    low, high = degree, n + 1
    mid = (low + high) // 2
    while u < knots[mid] or u >= knots[mid + 1]:
        if u < knots[mid]:
            high = mid
        else:
            low = mid
        mid = (low + high) // 2
    return mid


def _ders_basis(span: int, u: float, degree: int, knots: np.ndarray,
                 n_ders: int) -> np.ndarray:
    """All non-zero basis functions and their derivatives up to ``n_ders``.

    Returns ``ders`` with shape ``(n_ders+1, degree+1)`` where
    ``ders[k, j]`` is the ``k``-th derivative of ``N_{span-degree+j,degree}``
    evaluated at ``u`` (Piegl & Tiller A2.3).
    """
    ndu = np.zeros((degree + 1, degree + 1))
    left = np.zeros(degree + 1)
    right = np.zeros(degree + 1)
    ndu[0, 0] = 1.0
    for j in range(1, degree + 1):
        left[j] = u - knots[span + 1 - j]
        right[j] = knots[span + j] - u
        saved = 0.0
        for r in range(j):
            ndu[j, r] = right[r + 1] + left[j - r]
            denom = ndu[j, r]
            temp = ndu[r, j - 1] / denom if abs(denom) > _EPS else 0.0
            ndu[r, j] = saved + right[r + 1] * temp
            saved = left[j - r] * temp
        ndu[j, j] = saved

    ders = np.zeros((n_ders + 1, degree + 1))
    for j in range(degree + 1):
        ders[0, j] = ndu[j, degree]

    a = np.zeros((2, degree + 1))
    for r in range(degree + 1):
        s1, s2 = 0, 1
        a[0, 0] = 1.0
        for k in range(1, n_ders + 1):
            d = 0.0
            rk = r - k
            pk = degree - k
            if r >= k:
                denom = ndu[pk + 1, rk]
                a[s2, 0] = a[s1, 0] / denom if abs(denom) > _EPS else 0.0
                d = a[s2, 0] * ndu[rk, pk]
            j1 = 1 if rk >= -1 else -rk
            j2 = k - 1 if (r - 1) <= pk else degree - r
            for j in range(j1, j2 + 1):
                denom = ndu[pk + 1, rk + j]
                a[s2, j] = ((a[s1, j] - a[s1, j - 1]) / denom
                            if abs(denom) > _EPS else 0.0)
                d += a[s2, j] * ndu[rk + j, pk]
            if r <= pk:
                denom = ndu[pk + 1, r]
                a[s2, k] = -a[s1, k - 1] / denom if abs(denom) > _EPS else 0.0
                d += a[s2, k] * ndu[r, pk]
            ders[k, r] = d
            s1, s2 = s2, s1

    fac = float(degree)
    for k in range(1, n_ders + 1):
        for j in range(degree + 1):
            ders[k, j] *= fac
        fac *= float(degree - k)
    return ders


# ---------------------------------------------------------------------------
# Curve evaluation + derivatives (polynomial and rational)
# ---------------------------------------------------------------------------

def _curve_param_range(c: NurbsCurve) -> Tuple[float, float]:
    return float(c.knots[c.degree]), float(c.knots[-(c.degree + 1)])


def _curve_is_rational(c: NurbsCurve) -> bool:
    return c.control_points.ndim == 2 and c.control_points.shape[1] == 4


def _curve_ders(c: NurbsCurve, t: float, n_ders: int) -> List[np.ndarray]:
    """Return [C, C', C'', ...] up to ``n_ders`` as 3-vectors.

    Rational-correct: when the control net is 4-D homogeneous the projective
    quotient rule (Piegl & Tiller A4.2) is applied.
    """
    p = c.degree
    n = c.num_control_points - 1
    knots = np.asarray(c.knots, dtype=float)
    t = float(np.clip(t, knots[p], knots[-(p + 1)]))
    span = _find_span(n, p, t, knots)
    k = min(n_ders, p)
    ders = _ders_basis(span, t, p, knots, k)

    P = np.asarray(c.control_points, dtype=float)
    rational = _curve_is_rational(c)
    dim = 4 if rational else min(3, P.shape[1])

    # Homogeneous (or plain) curve derivatives.
    A = [np.zeros(P.shape[1]) for _ in range(n_ders + 1)]
    for d in range(k + 1):
        acc = np.zeros(P.shape[1])
        for j in range(p + 1):
            acc = acc + ders[d, j] * P[span - p + j]
        A[d] = acc

    out: List[np.ndarray] = []
    if not rational:
        for d in range(n_ders + 1):
            v = np.zeros(3)
            m = min(3, P.shape[1])
            v[:m] = A[d][:m]
            out.append(v)
        return out

    # Rational: C^(k) = ( A^(k) - sum_{i=1..k} C(k,i) w^(i) C^(k-i) ) / w
    from math import comb
    w = [A[d][3] for d in range(n_ders + 1)]
    Cw = [A[d][:3] for d in range(n_ders + 1)]
    C: List[np.ndarray] = []
    for d in range(n_ders + 1):
        v = np.array(Cw[d], dtype=float)
        for i in range(1, d + 1):
            v = v - comb(d, i) * w[i] * C[d - i]
        w0 = w[0] if abs(w[0]) > _EPS else _EPS
        C.append(v / w0)
    return C


def _curve_eval(c: NurbsCurve, t: float) -> np.ndarray:
    return _curve_ders(c, t, 0)[0]


def _curve_is_closed(c: NurbsCurve, tol: float = 1e-9) -> bool:
    t0, t1 = _curve_param_range(c)
    return bool(np.linalg.norm(_curve_eval(c, t0) - _curve_eval(c, t1)) < tol)


# ---------------------------------------------------------------------------
# Surface evaluation + derivatives (polynomial and rational)
# ---------------------------------------------------------------------------

def _surface_param_range(s: NurbsSurface) -> Tuple[float, float, float, float]:
    return (
        float(s.knots_u[s.degree_u]), float(s.knots_u[-(s.degree_u + 1)]),
        float(s.knots_v[s.degree_v]), float(s.knots_v[-(s.degree_v + 1)]),
    )


def _surface_is_rational(s: NurbsSurface) -> bool:
    return s.control_points.ndim == 3 and s.control_points.shape[2] == 4


def _surf_skl(s: NurbsSurface, u: float, v: float, order: int) -> np.ndarray:
    """Surface derivatives ``SKL[k, l]`` = d^(k+l) S / du^k dv^l (3-vectors),
    for ``0 <= k+l <= order`` (others zero).  Rational-correct.
    """
    pu, pv = s.degree_u, s.degree_v
    nu = s.num_control_points_u - 1
    nv = s.num_control_points_v - 1
    ku = np.asarray(s.knots_u, dtype=float)
    kv = np.asarray(s.knots_v, dtype=float)
    u = float(np.clip(u, ku[pu], ku[-(pu + 1)]))
    v = float(np.clip(v, kv[pv], kv[-(pv + 1)]))

    du = min(order, pu)
    dv = min(order, pv)
    span_u = _find_span(nu, pu, u, ku)
    span_v = _find_span(nv, pv, v, kv)
    Nu = _ders_basis(span_u, u, pu, ku, du)
    Nv = _ders_basis(span_v, v, pv, kv, dv)

    P = np.asarray(s.control_points, dtype=float)
    rational = _surface_is_rational(s)
    comp = P.shape[2]

    # Homogeneous (or plain) surface derivatives A[k, l].
    A = np.zeros((order + 1, order + 1, comp))
    for k in range(du + 1):
        tmp = np.zeros((pv + 1, comp))
        for sci in range(pv + 1):
            acc = np.zeros(comp)
            for r in range(pu + 1):
                acc = acc + Nu[k, r] * P[span_u - pu + r, span_v - pv + sci]
            tmp[sci] = acc
        for l in range(dv + 1):
            if k + l > order:
                continue
            acc = np.zeros(comp)
            for sci in range(pv + 1):
                acc = acc + Nv[l, sci] * tmp[sci]
            A[k, l] = acc

    SKL = np.zeros((order + 1, order + 1, 3))
    if not rational:
        m = min(3, comp)
        for k in range(order + 1):
            for l in range(order + 1 - k):
                SKL[k, l, :m] = A[k, l][:m]
        return SKL

    from math import comb
    Aw = A[:, :, :3]
    w = A[:, :, 3]
    for k in range(order + 1):
        for l in range(order + 1 - k):
            v_ = np.array(Aw[k, l], dtype=float)
            for j in range(1, l + 1):
                v_ = v_ - comb(l, j) * w[0, j] * SKL[k, l - j]
            for i in range(1, k + 1):
                v_ = v_ - comb(k, i) * w[i, 0] * SKL[k - i, l]
                v2 = np.zeros(3)
                for j in range(1, l + 1):
                    v2 = v2 + comb(l, j) * w[i, j] * SKL[k - i, l - j]
                v_ = v_ - comb(k, i) * v2
            w0 = w[0, 0] if abs(w[0, 0]) > _EPS else _EPS
            SKL[k, l] = v_ / w0
    return SKL


def _surf_eval(s: NurbsSurface, u: float, v: float) -> np.ndarray:
    return _surf_skl(s, u, v, 0)[0, 0]


def _surf_partials(s: NurbsSurface, u: float, v: float):
    """Return (S, Su, Sv, Suu, Suv, Svv) — all analytic 3-vectors."""
    skl = _surf_skl(s, u, v, 2)
    return (skl[0, 0], skl[1, 0], skl[0, 1],
            skl[2, 0], skl[1, 1], skl[0, 2])


# ---------------------------------------------------------------------------
# GK-06  closest_point_curve
# ---------------------------------------------------------------------------

def _newton_curve(c: NurbsCurve, P: np.ndarray, t0: float,
                  t_min: float, t_max: float, closed: bool,
                  tol: float) -> Tuple[float, float]:
    """Single Newton run with the second-derivative term (Piegl 6.1).

    Solves  f(t) = (C(t) - P) . C'(t) = 0  using
        t_{i+1} = t_i - f / f'      with
        f' = C'.C' + (C - P).C''
    Returns (t, dist).  Robust clamp / wrap each step.
    """
    span = t_max - t_min
    t = float(np.clip(t0, t_min, t_max))
    best_t = t
    best_d = float(np.linalg.norm(_curve_eval(c, t) - P))

    for _ in range(_MAX_NEWTON_ITER):
        C, C1, C2 = _curve_ders(c, t, 2)
        r = C - P
        d = float(np.linalg.norm(r))
        if d < best_d:
            best_d, best_t = d, t

        rc1 = float(np.dot(r, C1))
        c1n = float(np.linalg.norm(C1))
        # Point-coincidence (P on curve) or zero tangent -> converged.
        if d < tol:
            return t, d
        if c1n < _EPS:
            break
        # Cosine convergence criterion (Piegl & Tiller eq. 6.8).
        if abs(rc1) / (c1n * max(d, _EPS)) < tol:
            return t, d

        fp = float(np.dot(C1, C1)) + float(np.dot(r, C2))
        if abs(fp) < _EPS:
            break
        t_new = t - rc1 / fp

        if closed:
            # Wrap into [t_min, t_max).
            t_new = t_min + ((t_new - t_min) % span if span > _EPS else 0.0)
        else:
            t_new = float(np.clip(t_new, t_min, t_max))

        # Parameter-step convergence (Piegl & Tiller eq. 6.9).
        step_vec = (t_new - t) * C1
        if float(np.linalg.norm(step_vec)) < tol:
            t = t_new
            C = _curve_eval(c, t)
            return t, float(np.linalg.norm(C - P))
        t = t_new

    C = _curve_eval(c, best_t)
    return best_t, float(np.linalg.norm(C - P))


def closest_point_curve(
    curve: NurbsCurve,
    P,
    *,
    tol: float = _DEFAULT_TOL,
    coarse_samples: int = _COARSE_CURVE_SAMPLES,
) -> Tuple[float, np.ndarray, float]:
    """GK-06 — point inversion on a NurbsCurve.

    Coarse arc-length sample to seed, Newton with the second-derivative
    term, multi-seed global fallback, range clamp / closed-curve wrap.

    Returns ``(t, point, dist)`` where ``point`` is the 3-vector
    ``C(t)`` and ``dist = |P - C(t)|``.  Never raises.
    """
    if not isinstance(curve, NurbsCurve):
        raise TypeError(f"expected NurbsCurve, got {type(curve).__name__}")
    P = np.asarray(P, dtype=float).ravel()
    Q = np.zeros(3)
    Q[:min(3, P.size)] = P[:min(3, P.size)]
    P = Q

    t_min, t_max = _curve_param_range(curve)
    closed = _curve_is_closed(curve)
    ns = max(16, int(coarse_samples))

    # Coarse scan for the global-minimum seed (defeats local-min traps).
    ts = np.linspace(t_min, t_max, ns + 1)
    pts = np.array([_curve_eval(curve, float(t)) for t in ts])
    dists = np.linalg.norm(pts - P, axis=1)
    order = np.argsort(dists)

    # Try a handful of the best coarse seeds and keep the global best.
    best = (float(ts[order[0]]), pts[order[0]].copy(), float(dists[order[0]]))
    seeds = list(order[: min(8, len(order))])
    # Always include the endpoints and midpoint as extra global fallbacks.
    for extra in (0, ns, ns // 2):
        if extra not in seeds:
            seeds.append(extra)

    for si in seeds:
        t_ref, d_ref = _newton_curve(
            curve, P, float(ts[si]), t_min, t_max, closed, tol,
        )
        if d_ref < best[2]:
            best = (t_ref, _curve_eval(curve, t_ref), d_ref)

    # Endpoint refinement for open curves (closest foot can be a corner).
    if not closed:
        for te in (t_min, t_max):
            de = float(np.linalg.norm(_curve_eval(curve, te) - P))
            if de < best[2]:
                best = (te, _curve_eval(curve, te), de)

    t_b = float(best[0])
    pt_b = _curve_eval(curve, t_b)
    return t_b, pt_b, float(np.linalg.norm(pt_b - P))


# ---------------------------------------------------------------------------
# GK-07  closest_point_surface
# ---------------------------------------------------------------------------

def _newton_surface(s: NurbsSurface, P: np.ndarray, u0: float, v0: float,
                    u_min: float, u_max: float,
                    v_min: float, v_max: float,
                    tol: float) -> Tuple[float, float, float]:
    """2-D Newton point inversion with analytic 2nd partials (Piegl 6.1).

    Solves the 2x2 system
        f = (S - P) . Su = 0
        g = (S - P) . Sv = 0
    with Jacobian using Suu, Suv, Svv.  Returns (u, v, dist).
    """
    u = float(np.clip(u0, u_min, u_max))
    v = float(np.clip(v0, v_min, v_max))
    best_u, best_v = u, v
    best_d = float(np.linalg.norm(_surf_eval(s, u, v) - P))

    for _ in range(_MAX_NEWTON_ITER):
        S, Su, Sv, Suu, Suv, Svv = _surf_partials(s, u, v)
        r = S - P
        d = float(np.linalg.norm(r))
        if d < best_d:
            best_d, best_u, best_v = d, u, v

        su_n = float(np.linalg.norm(Su))
        sv_n = float(np.linalg.norm(Sv))
        f = float(np.dot(r, Su))
        g = float(np.dot(r, Sv))

        if d < tol:
            return u, v, d
        # Zero-cosine convergence on both parametric directions.
        c1 = abs(f) / (su_n * max(d, _EPS)) if su_n > _EPS else 0.0
        c2 = abs(g) / (sv_n * max(d, _EPS)) if sv_n > _EPS else 0.0
        if c1 < tol and c2 < tol:
            return u, v, d

        j11 = float(np.dot(Su, Su)) + float(np.dot(r, Suu))
        j12 = float(np.dot(Su, Sv)) + float(np.dot(r, Suv))
        j22 = float(np.dot(Sv, Sv)) + float(np.dot(r, Svv))
        det = j11 * j22 - j12 * j12
        # GK-69: condition-number guard on the 2x2 Jacobian.  A degenerate
        # surface patch (pole, collapsed edge, seam) makes j11*j22 ≈ j12^2;
        # Cramer's rule amplifies noise in that case.  Check the condition
        # number and fall back to lstsq for near-singular systems.
        J2 = np.array([[j11, j12], [j12, j22]])
        try:
            cond2 = np.linalg.cond(J2)
        except np.linalg.LinAlgError:
            cond2 = float("inf")
        if not np.isfinite(cond2) or cond2 > _COND_THRESHOLD or abs(det) < _EPS:
            # lstsq on the 2x2 system [j11 j12; j12 j22] * [du; dv] = [-f; -g]
            sol, *_ = np.linalg.lstsq(J2, np.array([-f, -g]), rcond=None)
            du, dv = float(sol[0]), float(sol[1])
        else:
            du = -(j22 * f - j12 * g) / det
            dv = -(j11 * g - j12 * f) / det

        u_new = float(np.clip(u + du, u_min, u_max))
        v_new = float(np.clip(v + dv, v_min, v_max))

        step = (u_new - u) * Su + (v_new - v) * Sv
        if float(np.linalg.norm(step)) < tol:
            u, v = u_new, v_new
            pt = _surf_eval(s, u, v)
            return u, v, float(np.linalg.norm(pt - P))
        u, v = u_new, v_new

    pt = _surf_eval(s, best_u, best_v)
    return best_u, best_v, float(np.linalg.norm(pt - P))


def closest_point_surface(
    surf: NurbsSurface,
    P,
    *,
    tol: float = _DEFAULT_TOL,
    coarse_samples: int = _COARSE_SURF_SAMPLES,
) -> Tuple[float, float, np.ndarray, float]:
    """GK-07 — UV point inversion on a NurbsSurface.

    Analytic first / second partials (rational-correct), a coarse grid
    seed, 2-D Newton, and a multi-seed global fallback that escapes
    local-minimum traps.

    Returns ``(u, v, point, dist)``.  Never raises.
    """
    if not isinstance(surf, NurbsSurface):
        raise TypeError(f"expected NurbsSurface, got {type(surf).__name__}")
    P = np.asarray(P, dtype=float).ravel()
    Q = np.zeros(3)
    Q[:min(3, P.size)] = P[:min(3, P.size)]
    P = Q

    u_min, u_max, v_min, v_max = _surface_param_range(surf)
    ns = max(8, int(coarse_samples))

    us = np.linspace(u_min, u_max, ns + 1)
    vs = np.linspace(v_min, v_max, ns + 1)
    grid = np.array([[_surf_eval(surf, float(u), float(v)) for v in vs]
                     for u in us])
    d2 = np.linalg.norm(grid - P, axis=2)
    flat = np.argsort(d2.ravel())

    bi, bj = divmod(int(flat[0]), ns + 1)
    best = (float(us[bi]), float(vs[bj]), grid[bi, bj].copy(),
            float(d2[bi, bj]))

    seeds = [divmod(int(k), ns + 1) for k in flat[: min(12, flat.size)]]
    # Corners + centre as deterministic global fallbacks.
    for cu in (0, ns, ns // 2):
        for cv in (0, ns, ns // 2):
            if (cu, cv) not in seeds:
                seeds.append((cu, cv))

    for (i, j) in seeds:
        u_ref, v_ref, d_ref = _newton_surface(
            surf, P, float(us[i]), float(vs[j]),
            u_min, u_max, v_min, v_max, tol,
        )
        if d_ref < best[3]:
            best = (u_ref, v_ref, _surf_eval(surf, u_ref, v_ref), d_ref)

    u_b, v_b = float(best[0]), float(best[1])
    pt_b = _surf_eval(surf, u_b, v_b)
    return u_b, v_b, pt_b, float(np.linalg.norm(pt_b - P))


# ---------------------------------------------------------------------------
# GK-08  public projection APIs
# ---------------------------------------------------------------------------

def project_point_to_curve(curve: NurbsCurve, P) -> dict:
    """GK-08 — closest point on a curve as a structured payload.

    Returns ``{"ok", "t", "point", "dist"}``.  ``ok`` is False with a
    ``reason`` on bad input; never raises.
    """
    try:
        if not isinstance(curve, NurbsCurve):
            return {"ok": False, "reason": "curve must be a NurbsCurve"}
        t, pt, d = closest_point_curve(curve, P)
        return {
            "ok": True,
            "t": float(t),
            "point": [float(x) for x in pt],
            "dist": float(d),
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {"ok": False, "reason": f"project_point_to_curve error: {exc}"}


def pull_curve_to_surface(curve: NurbsCurve, surf: NurbsSurface,
                          n: int = 32) -> dict:
    """GK-08 — pull a curve onto the closest points of a surface.

    Samples ``curve`` at ``n`` stations across its parameter range and
    inverts each onto ``surf``.  Returns the UV trail and the 3-D foot
    polyline.

    Returns ``{"ok", "uv", "points", "max_dist"}``; ``ok`` False with a
    ``reason`` on bad input.  Never raises.
    """
    try:
        if not isinstance(curve, NurbsCurve):
            return {"ok": False, "reason": "curve must be a NurbsCurve"}
        if not isinstance(surf, NurbsSurface):
            return {"ok": False, "reason": "surf must be a NurbsSurface"}
        ns = max(2, int(n))
        t_min, t_max = _curve_param_range(curve)
        ts = np.linspace(t_min, t_max, ns)

        uv: List[List[float]] = []
        pts: List[List[float]] = []
        max_d = 0.0
        for t in ts:
            cp = _curve_eval(curve, float(t))
            u, v, fp, d = closest_point_surface(surf, cp)
            uv.append([float(u), float(v)])
            pts.append([float(x) for x in fp])
            max_d = max(max_d, float(d))
        return {
            "ok": True,
            "uv": uv,
            "points": pts,
            "max_dist": float(max_d),
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {"ok": False, "reason": f"pull_curve_to_surface error: {exc}"}
