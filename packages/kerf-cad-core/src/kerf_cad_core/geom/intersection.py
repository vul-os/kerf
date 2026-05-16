"""
intersection.py
===============
Pure-Python intersection geometry: curve-surface, surface-surface, and
curve-curve intersections (Rhino parity).

Public API
----------
curve_surface_intersect(curve, surface, *, tol, samples_c, samples_u, samples_v)
    -> list[dict]
    Find all intersection points between a NurbsCurve and a NurbsSurface.
    Strategy: subdivide curve parameter space into segments and the surface into
    (u, v) patches, cull non-overlapping AABBs, then refine each candidate pair
    via Newton iteration on the residual  surface(u, v) - curve(t) = 0.
    Returns a list of dicts, each with:
        t       : float   -- curve parameter
        u, v    : float   -- surface parameters
        point   : list[float, float, float]  -- 3-D intersection point
    Never raises.  Duplicate hits closer than ``tol`` are merged.

surface_surface_intersect(surf_a, surf_b, *, tol, samples_u, samples_v, step, max_steps)
    -> dict
    Compute intersection curve(s) between two NurbsSurfaces via a marching
    method.
    Returns a dict with:
        ok          : bool
        reason      : str        (empty on success)
        branches    : list[dict] -- one dict per branch, each with:
            points  : list[[x,y,z]]  -- ordered 3-D polyline vertices
            params_a: list[[u,v]]    -- surface A parameters per vertex
            params_b: list[[u,v]]    -- surface B parameters per vertex
            closed  : bool
        branch_count: int
    Never raises.

curve_curve_intersect(curve_a, curve_b, *, tol, samples_a, samples_b)
    -> list[dict]
    Find all intersection points between two NurbsCurves (planar or 3-D).
    Returns a list of dicts, each with:
        ta      : float  -- parameter on curve_a
        tb      : float  -- parameter on curve_b
        point   : list[float, float, float]
    Never raises.  Duplicate hits closer than ``tol`` are merged.

Implementation note
-------------------
The surface_evaluate function in geom/nurbs.py has a known limitation with its
basis_functions computation.  This module implements a correct NURBS surface
evaluator (_nurbs_surface_eval) that properly handles the triangular recurrence
for B-spline basis functions, while still using the NurbsSurface/NurbsCurve data
structures from geom/nurbs.py.  Curve evaluation uses de_boor from nurbs.py
which works correctly for NurbsCurve.
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsCurve, NurbsSurface, de_boor

# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_DEFAULT_TOL: float = 1e-6
_DEFAULT_SAMPLES_C: int = 64
_DEFAULT_SAMPLES_UV: int = 24
_DEFAULT_MARCH_STEP: float = 0.02
_DEFAULT_MAX_STEPS: int = 2000
_MAX_NEWTON_ITER: int = 40
_MIN_BRANCH_PTS: int = 2


# ---------------------------------------------------------------------------
# Correct NURBS evaluators
# ---------------------------------------------------------------------------

def _find_span(n: int, degree: int, u: float, knots: np.ndarray) -> int:
    """Binary-search knot span index (standard algorithm)."""
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


def _basis_fns(span: int, u: float, degree: int, knots: np.ndarray) -> np.ndarray:
    """Compute the (degree+1) non-zero B-spline basis functions at u.

    Uses the correct triangular recurrence (Cox-de Boor).  Returns N[0..degree]
    where N[j] = N_{span-degree+j,degree}(u).
    """
    N = np.zeros(degree + 1)
    N[0] = 1.0
    left = np.zeros(degree + 1)
    right = np.zeros(degree + 1)
    for j in range(1, degree + 1):
        left[j] = u - knots[span + 1 - j]
        right[j] = knots[span + j] - u
        saved = 0.0
        for r in range(j):
            denom = right[r + 1] + left[j - r]
            if abs(denom) < 1e-15:
                temp = 0.0
            else:
                temp = N[r] / denom
            N[r] = saved + right[r + 1] * temp
            saved = left[j - r] * temp
        N[j] = saved
    return N


def _nurbs_curve_eval(c: NurbsCurve, t: float) -> np.ndarray:
    """Evaluate NurbsCurve at t, return 3-element array (uses de_boor)."""
    pt = de_boor(c, float(t))
    arr = np.asarray(pt, dtype=float).ravel()
    out = np.zeros(3)
    n = min(3, arr.size)
    out[:n] = arr[:n]
    return out


def _nurbs_surface_eval(s: NurbsSurface, u: float, v: float) -> np.ndarray:
    """Evaluate NurbsSurface at (u, v) using the correct Cox-de Boor algorithm."""
    n_u = s.num_control_points_u - 1
    n_v = s.num_control_points_v - 1
    span_u = _find_span(n_u, s.degree_u, float(u), s.knots_u)
    span_v = _find_span(n_v, s.degree_v, float(v), s.knots_v)
    Nu = _basis_fns(span_u, float(u), s.degree_u, s.knots_u)
    Nv = _basis_fns(span_v, float(v), s.degree_v, s.knots_v)
    dim = s.control_points.shape[2]
    result = np.zeros(dim)
    for i in range(s.degree_u + 1):
        for j in range(s.degree_v + 1):
            idx_i = span_u - s.degree_u + i
            idx_j = span_v - s.degree_v + j
            result += Nu[i] * Nv[j] * s.control_points[idx_i, idx_j]
    out = np.zeros(3)
    n = min(3, dim)
    out[:n] = result[:n]
    return out


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _curve_param_range(c: NurbsCurve) -> Tuple[float, float]:
    return float(c.knots[c.degree]), float(c.knots[-(c.degree + 1)])


def _surface_param_range(s: NurbsSurface) -> Tuple[float, float, float, float]:
    return (
        float(s.knots_u[0]), float(s.knots_u[-1]),
        float(s.knots_v[0]), float(s.knots_v[-1]),
    )


def _curve_eval(c: NurbsCurve, t: float) -> np.ndarray:
    return _nurbs_curve_eval(c, t)


def _surf_eval(s: NurbsSurface, u: float, v: float) -> np.ndarray:
    return _nurbs_surface_eval(s, u, v)


def _surf_partials(
    s: NurbsSurface, u: float, v: float
) -> Tuple[np.ndarray, np.ndarray]:
    """Central finite-difference partials dp/du and dp/dv."""
    u_min, u_max, v_min, v_max = _surface_param_range(s)
    hu = max(1e-6, (u_max - u_min) * 1e-4)
    hv = max(1e-6, (v_max - v_min) * 1e-4)
    u0 = float(np.clip(u, u_min, u_max))
    v0 = float(np.clip(v, v_min, v_max))
    up = min(u_max, u0 + hu); um = max(u_min, u0 - hu)
    vp = min(v_max, v0 + hv); vm = max(v_min, v0 - hv)
    dp_du = (_surf_eval(s, up, v0) - _surf_eval(s, um, v0)) / (up - um + 1e-15)
    dp_dv = (_surf_eval(s, u0, vp) - _surf_eval(s, u0, vm)) / (vp - vm + 1e-15)
    return dp_du, dp_dv


def _surf_normal(s: NurbsSurface, u: float, v: float) -> np.ndarray:
    dp_du, dp_dv = _surf_partials(s, u, v)
    n = np.cross(dp_du, dp_dv)
    nrm = np.linalg.norm(n)
    if nrm < 1e-15:
        return np.array([0.0, 0.0, 1.0])
    return n / nrm


def _aabb(pts: List[np.ndarray]) -> Tuple[np.ndarray, np.ndarray]:
    arr = np.stack(pts)
    return arr.min(axis=0), arr.max(axis=0)


def _aabb_overlap(lo_a: np.ndarray, hi_a: np.ndarray,
                  lo_b: np.ndarray, hi_b: np.ndarray,
                  tol: float) -> bool:
    for i in range(3):
        if lo_a[i] - tol > hi_b[i] or lo_b[i] - tol > hi_a[i]:
            return False
    return True


def _merge_close_hits(
    hits: List[dict],
    tol: float,
    key: str = "point",
) -> List[dict]:
    merged: List[dict] = []
    for h in hits:
        p = np.array(h[key])
        close = any(
            np.linalg.norm(p - np.array(m[key])) < tol
            for m in merged
        )
        if not close:
            merged.append(h)
    return merged


# ---------------------------------------------------------------------------
# Newton: curve-surface
# ---------------------------------------------------------------------------

def _newton_curve_surface(
    curve: NurbsCurve,
    surface: NurbsSurface,
    t0: float,
    u0: float,
    v0: float,
    *,
    tol: float = _DEFAULT_TOL,
    max_iter: int = _MAX_NEWTON_ITER,
) -> Optional[Tuple[float, float, float]]:
    """Refine a curve-surface intersection via Newton iteration.

    Solves F(t, u, v) = surface(u,v) - curve(t) = 0  (3 eq, 3 unknowns).
    Returns (t, u, v) on convergence, else None.
    """
    t_min, t_max = _curve_param_range(curve)
    u_min, u_max, v_min, v_max = _surface_param_range(surface)

    t = float(np.clip(t0, t_min, t_max))
    u = float(np.clip(u0, u_min, u_max))
    v = float(np.clip(v0, v_min, v_max))

    ht = max(1e-6, (t_max - t_min) * 1e-4)

    for _ in range(max_iter):
        S = _surf_eval(surface, u, v)
        C = _curve_eval(curve, t)
        F = S - C
        if np.linalg.norm(F) < tol:
            return (t, u, v)

        dp_du, dp_dv = _surf_partials(surface, u, v)
        tp = min(t_max, t + ht); tm = max(t_min, t - ht)
        dC_dt = (_curve_eval(curve, tp) - _curve_eval(curve, tm)) / (tp - tm + 1e-15)

        # Jacobian columns: [dp_du, dp_dv, -dC_dt]  shape (3, 3)
        J = np.column_stack([dp_du, dp_dv, -dC_dt])
        det = np.linalg.det(J)
        if abs(det) < 1e-20:
            # Fall back to pseudo-inverse
            delta, *_ = np.linalg.lstsq(J, -F, rcond=None)
        else:
            delta = np.linalg.solve(J, -F)

        u_new = float(np.clip(u + delta[0], u_min, u_max))
        v_new = float(np.clip(v + delta[1], v_min, v_max))
        t_new = float(np.clip(t + delta[2], t_min, t_max))

        if (abs(u_new - u) < tol * 1e-2 and
                abs(v_new - v) < tol * 1e-2 and
                abs(t_new - t) < tol * 1e-2):
            return (t_new, u_new, v_new)

        u, v, t = u_new, v_new, t_new

    # Accept if residual is small
    F_fin = _surf_eval(surface, u, v) - _curve_eval(curve, t)
    if np.linalg.norm(F_fin) < tol * 1e3:
        return (t, u, v)
    return None


# ---------------------------------------------------------------------------
# curve_surface_intersect
# ---------------------------------------------------------------------------

def curve_surface_intersect(
    curve: NurbsCurve,
    surface: NurbsSurface,
    *,
    tol: float = _DEFAULT_TOL,
    samples_c: int = _DEFAULT_SAMPLES_C,
    samples_u: int = _DEFAULT_SAMPLES_UV,
    samples_v: int = _DEFAULT_SAMPLES_UV,
) -> List[dict]:
    """Find all intersection points between a NurbsCurve and a NurbsSurface.

    Parameters
    ----------
    curve : NurbsCurve
    surface : NurbsSurface
    tol : float
        Spatial convergence tolerance and duplicate-merge radius.
    samples_c : int
        Number of curve subdivisions for AABB cull.
    samples_u, samples_v : int
        Number of surface subdivisions in U and V for AABB cull.

    Returns
    -------
    list of dict with keys: t, u, v, point.  Never raises.
    """
    try:
        return _curve_surface_intersect_impl(
            curve, surface,
            tol=tol, samples_c=samples_c,
            samples_u=samples_u, samples_v=samples_v,
        )
    except Exception:
        return []


def _curve_surface_intersect_impl(
    curve: NurbsCurve,
    surface: NurbsSurface,
    *,
    tol: float,
    samples_c: int,
    samples_u: int,
    samples_v: int,
) -> List[dict]:
    if not isinstance(curve, NurbsCurve):
        return []
    if not isinstance(surface, NurbsSurface):
        return []

    t_min, t_max = _curve_param_range(curve)
    u_min, u_max, v_min, v_max = _surface_param_range(surface)

    sc = max(4, int(samples_c))
    su = max(4, int(samples_u))
    sv = max(4, int(samples_v))

    t_vals = np.linspace(t_min, t_max, sc + 1)
    u_vals = np.linspace(u_min, u_max, su + 1)
    v_vals = np.linspace(v_min, v_max, sv + 1)

    c_pts = [_curve_eval(curve, float(t)) for t in t_vals]
    s_pts = {
        (i, j): _surf_eval(surface, float(u_vals[i]), float(v_vals[j]))
        for i in range(su + 1)
        for j in range(sv + 1)
    }

    candidates: List[Tuple[float, float, float]] = []

    for ci in range(sc):
        c_seg = [c_pts[ci], c_pts[ci + 1]]
        c_lo, c_hi = _aabb(c_seg)

        for si in range(su):
            for sj in range(sv):
                s_seg = [
                    s_pts[(si, sj)], s_pts[(si + 1, sj)],
                    s_pts[(si, sj + 1)], s_pts[(si + 1, sj + 1)],
                ]
                s_lo, s_hi = _aabb(s_seg)

                if not _aabb_overlap(c_lo, c_hi, s_lo, s_hi, tol * 10):
                    continue

                t0 = (t_vals[ci] + t_vals[ci + 1]) * 0.5
                u0 = (u_vals[si] + u_vals[si + 1]) * 0.5
                v0 = (v_vals[sj] + v_vals[sj + 1]) * 0.5
                candidates.append((t0, u0, v0))

    hits: List[dict] = []
    for t0, u0, v0 in candidates:
        result = _newton_curve_surface(curve, surface, t0, u0, v0, tol=tol)
        if result is None:
            continue
        t_ref, u_ref, v_ref = result
        S = _surf_eval(surface, u_ref, v_ref)
        C = _curve_eval(curve, t_ref)
        if np.linalg.norm(S - C) > tol * 1e3:
            continue
        pt = ((S + C) * 0.5).tolist()
        hits.append({"t": t_ref, "u": u_ref, "v": v_ref, "point": pt})

    return _merge_close_hits(hits, tol)


# ---------------------------------------------------------------------------
# Newton: surface-surface seed
# ---------------------------------------------------------------------------

def _newton_surf_surf_point(
    surf_a: NurbsSurface,
    surf_b: NurbsSurface,
    uA0: float, vA0: float,
    uB0: float, vB0: float,
    *,
    tol: float = _DEFAULT_TOL,
    max_iter: int = _MAX_NEWTON_ITER,
) -> Optional[Tuple[float, float, float, float]]:
    """Newton refinement for surface-surface intersection seed.

    Solves surf_a(uA, vA) - surf_b(uB, vB) = 0  (3 eq, 4 unknowns).
    Uses least-norm pseudo-inverse solution.
    Returns (uA, vA, uB, vB) or None.
    """
    uA_min, uA_max, vA_min, vA_max = _surface_param_range(surf_a)
    uB_min, uB_max, vB_min, vB_max = _surface_param_range(surf_b)

    uA = float(np.clip(uA0, uA_min, uA_max))
    vA = float(np.clip(vA0, vA_min, vA_max))
    uB = float(np.clip(uB0, uB_min, uB_max))
    vB = float(np.clip(vB0, vB_min, vB_max))

    for _ in range(max_iter):
        PA = _surf_eval(surf_a, uA, vA)
        PB = _surf_eval(surf_b, uB, vB)
        F = PA - PB
        if np.linalg.norm(F) < tol:
            return (uA, vA, uB, vB)

        dpA_du, dpA_dv = _surf_partials(surf_a, uA, vA)
        dpB_du, dpB_dv = _surf_partials(surf_b, uB, vB)

        J = np.column_stack([dpA_du, dpA_dv, -dpB_du, -dpB_dv])  # (3, 4)
        # Least-norm: delta = J^T (J J^T)^-1 (-F)
        JJT = J @ J.T
        try:
            lam = np.linalg.solve(JJT, -F)
        except np.linalg.LinAlgError:
            break
        delta = J.T @ lam

        uA_new = float(np.clip(uA + delta[0], uA_min, uA_max))
        vA_new = float(np.clip(vA + delta[1], vA_min, vA_max))
        uB_new = float(np.clip(uB + delta[2], uB_min, uB_max))
        vB_new = float(np.clip(vB + delta[3], vB_min, vB_max))

        if (abs(uA_new - uA) < tol * 1e-2 and abs(vA_new - vA) < tol * 1e-2 and
                abs(uB_new - uB) < tol * 1e-2 and abs(vB_new - vB) < tol * 1e-2):
            return (uA_new, vA_new, uB_new, vB_new)

        uA, vA, uB, vB = uA_new, vA_new, uB_new, vB_new

    PA = _surf_eval(surf_a, uA, vA)
    PB = _surf_eval(surf_b, uB, vB)
    if np.linalg.norm(PA - PB) < tol * 1e3:
        return (uA, vA, uB, vB)
    return None


# ---------------------------------------------------------------------------
# Marching
# ---------------------------------------------------------------------------

def _march_branch(
    surf_a: NurbsSurface,
    surf_b: NurbsSurface,
    uA_seed: float, vA_seed: float,
    uB_seed: float, vB_seed: float,
    step: float,
    tol: float,
    max_steps: int,
) -> dict:
    """March in both directions from a seed to build one intersection branch."""

    def _collect(uA0, vA0, uB0, vB0, sign):
        pts, pa, pb = [], [], []
        uA, vA, uB, vB = uA0, vA0, uB0, vB0
        uA_min, uA_max, vA_min, vA_max = _surface_param_range(surf_a)
        uB_min, uB_max, vB_min, vB_max = _surface_param_range(surf_b)
        for _ in range(max_steps // 2):
            nA = _surf_normal(surf_a, uA, vA)
            nB = _surf_normal(surf_b, uB, vB)
            tang = np.cross(nA, nB)
            t_nrm = np.linalg.norm(tang)
            if t_nrm < 1e-12:
                break
            tang /= t_nrm

            PA = _surf_eval(surf_a, uA, vA)
            PB = _surf_eval(surf_b, uB, vB)
            P_curr = (PA + PB) * 0.5
            P_next = P_curr + sign * step * tang

            # Project P_next onto each surface via tangent-plane approximation
            dpA_du, dpA_dv = _surf_partials(surf_a, uA, vA)
            dpB_du, dpB_dv = _surf_partials(surf_b, uB, vB)

            delta = P_next - PA
            norm_uA = np.dot(delta, dpA_du) / (np.dot(dpA_du, dpA_du) + 1e-15)
            norm_vA = np.dot(delta, dpA_dv) / (np.dot(dpA_dv, dpA_dv) + 1e-15)
            uA_g = float(np.clip(uA + norm_uA, uA_min, uA_max))
            vA_g = float(np.clip(vA + norm_vA, vA_min, vA_max))

            delta_b = P_next - PB
            norm_uB = np.dot(delta_b, dpB_du) / (np.dot(dpB_du, dpB_du) + 1e-15)
            norm_vB = np.dot(delta_b, dpB_dv) / (np.dot(dpB_dv, dpB_dv) + 1e-15)
            uB_g = float(np.clip(uB + norm_uB, uB_min, uB_max))
            vB_g = float(np.clip(vB + norm_vB, vB_min, vB_max))

            refined = _newton_surf_surf_point(
                surf_a, surf_b, uA_g, vA_g, uB_g, vB_g, tol=tol
            )
            if refined is None:
                break
            uA_new, vA_new, uB_new, vB_new = refined

            PA_new = _surf_eval(surf_a, uA_new, vA_new)
            if np.linalg.norm(PA_new - P_curr) < tol * 0.1:
                break

            pts.append(((PA_new + _surf_eval(surf_b, uB_new, vB_new)) * 0.5).tolist())
            pa.append([uA_new, vA_new])
            pb.append([uB_new, vB_new])
            uA, vA, uB, vB = uA_new, vA_new, uB_new, vB_new

            # Stop at boundary
            on_bnd = (
                abs(uA_new - uA_min) < tol * 10 or abs(uA_new - uA_max) < tol * 10 or
                abs(vA_new - vA_min) < tol * 10 or abs(vA_new - vA_max) < tol * 10 or
                abs(uB_new - uB_min) < tol * 10 or abs(uB_new - uB_max) < tol * 10 or
                abs(vB_new - vB_min) < tol * 10 or abs(vB_new - vB_max) < tol * 10
            )
            if on_bnd:
                break
        return pts, pa, pb

    PA_s = _surf_eval(surf_a, uA_seed, vA_seed)
    PB_s = _surf_eval(surf_b, uB_seed, vB_seed)
    seed_pt = ((PA_s + PB_s) * 0.5).tolist()

    fwd_pts, fwd_pa, fwd_pb = _collect(uA_seed, vA_seed, uB_seed, vB_seed, +1.0)
    bwd_pts, bwd_pa, bwd_pb = _collect(uA_seed, vA_seed, uB_seed, vB_seed, -1.0)

    all_pts = list(reversed(bwd_pts)) + [seed_pt] + fwd_pts
    all_pa  = list(reversed(bwd_pa))  + [[uA_seed, vA_seed]] + fwd_pa
    all_pb  = list(reversed(bwd_pb))  + [[uB_seed, vB_seed]] + fwd_pb

    closed = False
    if len(all_pts) >= 4:
        p0 = np.array(all_pts[0]); p1 = np.array(all_pts[-1])
        if np.linalg.norm(p1 - p0) < step * 3:
            closed = True

    return {"points": all_pts, "params_a": all_pa, "params_b": all_pb, "closed": closed}


# ---------------------------------------------------------------------------
# surface_surface_intersect
# ---------------------------------------------------------------------------

def surface_surface_intersect(
    surf_a: NurbsSurface,
    surf_b: NurbsSurface,
    *,
    tol: float = _DEFAULT_TOL,
    samples_u: int = _DEFAULT_SAMPLES_UV,
    samples_v: int = _DEFAULT_SAMPLES_UV,
    step: float = _DEFAULT_MARCH_STEP,
    max_steps: int = _DEFAULT_MAX_STEPS,
) -> dict:
    """Compute intersection curve(s) between two NurbsSurfaces.

    Parameters
    ----------
    surf_a, surf_b : NurbsSurface
    tol : float
    samples_u, samples_v : int  -- Grid resolution for seeding.
    step : float  -- Marching step (scaled by bounding-box diagonal).
    max_steps : int

    Returns
    -------
    dict with ok, reason, branches, branch_count.  Never raises.
    """
    try:
        return _surface_surface_intersect_impl(
            surf_a, surf_b,
            tol=tol, samples_u=samples_u, samples_v=samples_v,
            step=step, max_steps=max_steps,
        )
    except Exception as exc:
        return {
            "ok": False,
            "reason": f"surface_surface_intersect internal error: {exc}",
            "branches": [],
            "branch_count": 0,
        }


def _surface_surface_intersect_impl(
    surf_a: NurbsSurface,
    surf_b: NurbsSurface,
    *,
    tol: float,
    samples_u: int,
    samples_v: int,
    step: float,
    max_steps: int,
) -> dict:
    if not isinstance(surf_a, NurbsSurface):
        return {"ok": False, "reason": "surf_a must be a NurbsSurface",
                "branches": [], "branch_count": 0}
    if not isinstance(surf_b, NurbsSurface):
        return {"ok": False, "reason": "surf_b must be a NurbsSurface",
                "branches": [], "branch_count": 0}

    su = max(4, int(samples_u))
    sv = max(4, int(samples_v))

    uA_min, uA_max, vA_min, vA_max = _surface_param_range(surf_a)
    uB_min, uB_max, vB_min, vB_max = _surface_param_range(surf_b)

    uA_vals = np.linspace(uA_min, uA_max, su + 1)
    vA_vals = np.linspace(vA_min, vA_max, sv + 1)
    uB_vals = np.linspace(uB_min, uB_max, su + 1)
    vB_vals = np.linspace(vB_min, vB_max, sv + 1)

    pA = np.array([[_surf_eval(surf_a, float(u), float(v))
                    for v in vA_vals] for u in uA_vals])
    pB = np.array([[_surf_eval(surf_b, float(u), float(v))
                    for v in vB_vals] for u in uB_vals])

    # Estimate step size from bounding boxes
    bboxA = np.max(pA.reshape(-1, 3), axis=0) - np.min(pA.reshape(-1, 3), axis=0)
    bboxB = np.max(pB.reshape(-1, 3), axis=0) - np.min(pB.reshape(-1, 3), axis=0)
    diag_avg = (np.linalg.norm(bboxA) + np.linalg.norm(bboxB)) * 0.5
    actual_step = step if diag_avg < 1e-10 else step * diag_avg

    seed_tol = max(tol * 1e3, actual_step * 2)
    raw_seeds: List[Tuple[float, float, float, float]] = []

    for i in range(su + 1):
        for j in range(sv + 1):
            pA_ij = pA[i, j]
            dists = np.linalg.norm(pB.reshape(-1, 3) - pA_ij, axis=1)
            k_best = int(np.argmin(dists))
            if dists[k_best] < seed_tol:
                bi = k_best // (sv + 1)
                bj = k_best % (sv + 1)
                raw_seeds.append((
                    float(uA_vals[i]), float(vA_vals[j]),
                    float(uB_vals[bi]), float(vB_vals[bj]),
                ))

    # Refine seeds
    refined_seeds: List[Tuple[float, float, float, float]] = []
    for (uA, vA, uB, vB) in raw_seeds:
        r = _newton_surf_surf_point(surf_a, surf_b, uA, vA, uB, vB, tol=tol)
        if r is not None:
            refined_seeds.append(r)

    # Merge close seeds
    merged_seeds: List[Tuple[float, float, float, float]] = []
    for s in refined_seeds:
        PA = _surf_eval(surf_a, s[0], s[1])
        close = any(
            np.linalg.norm(PA - _surf_eval(surf_a, m[0], m[1])) < actual_step * 2
            for m in merged_seeds
        )
        if not close:
            merged_seeds.append(s)

    if not merged_seeds:
        return {"ok": True, "reason": "", "branches": [], "branch_count": 0}

    branches: List[dict] = []
    visited_pts: List[np.ndarray] = []

    for seed in merged_seeds:
        uA_s, vA_s, uB_s, vB_s = seed
        seed_pt = _surf_eval(surf_a, uA_s, vA_s)
        too_close = any(
            np.linalg.norm(seed_pt - vp) < actual_step * 3
            for vp in visited_pts
        )
        if too_close:
            continue

        branch = _march_branch(
            surf_a, surf_b, uA_s, vA_s, uB_s, vB_s,
            step=actual_step, tol=tol, max_steps=max_steps,
        )
        if len(branch["points"]) < _MIN_BRANCH_PTS:
            continue

        branches.append(branch)
        for pt in branch["points"]:
            visited_pts.append(np.array(pt))

    return {
        "ok": True,
        "reason": "",
        "branches": branches,
        "branch_count": len(branches),
    }


# ---------------------------------------------------------------------------
# Newton: curve-curve
# ---------------------------------------------------------------------------

def _newton_curve_curve(
    curve_a: NurbsCurve,
    curve_b: NurbsCurve,
    ta0: float,
    tb0: float,
    *,
    tol: float = _DEFAULT_TOL,
    max_iter: int = _MAX_NEWTON_ITER,
) -> Optional[Tuple[float, float]]:
    """Newton refinement for curve-curve intersection.

    Solves F(ta, tb) = curve_a(ta) - curve_b(tb) = 0  (3 eq, 2 unknowns).
    Returns (ta, tb) or None.
    """
    ta_min, ta_max = _curve_param_range(curve_a)
    tb_min, tb_max = _curve_param_range(curve_b)

    ta = float(np.clip(ta0, ta_min, ta_max))
    tb = float(np.clip(tb0, tb_min, tb_max))

    h_a = max(1e-6, (ta_max - ta_min) * 1e-4)
    h_b = max(1e-6, (tb_max - tb_min) * 1e-4)

    for _ in range(max_iter):
        A = _curve_eval(curve_a, ta)
        B = _curve_eval(curve_b, tb)
        F = A - B
        if np.linalg.norm(F) < tol:
            return (ta, tb)

        ta_p = min(ta_max, ta + h_a); ta_m = max(ta_min, ta - h_a)
        tb_p = min(tb_max, tb + h_b); tb_m = max(tb_min, tb - h_b)

        dA_dt = (_curve_eval(curve_a, ta_p) - _curve_eval(curve_a, ta_m)) / (ta_p - ta_m + 1e-15)
        dB_dt = (_curve_eval(curve_b, tb_p) - _curve_eval(curve_b, tb_m)) / (tb_p - tb_m + 1e-15)

        # J shape (3, 2): columns [dA_dt, -dB_dt]
        J = np.column_stack([dA_dt, -dB_dt])
        JtJ = J.T @ J
        Jtf = J.T @ (-F)
        det = JtJ[0, 0] * JtJ[1, 1] - JtJ[0, 1] * JtJ[1, 0]
        if abs(det) < 1e-20:
            break
        delta_ta = (JtJ[1, 1] * Jtf[0] - JtJ[0, 1] * Jtf[1]) / det
        delta_tb = (JtJ[0, 0] * Jtf[1] - JtJ[1, 0] * Jtf[0]) / det

        ta_new = float(np.clip(ta + delta_ta, ta_min, ta_max))
        tb_new = float(np.clip(tb + delta_tb, tb_min, tb_max))

        if abs(ta_new - ta) < tol * 1e-2 and abs(tb_new - tb) < tol * 1e-2:
            return (ta_new, tb_new)
        ta, tb = ta_new, tb_new

    A = _curve_eval(curve_a, ta); B = _curve_eval(curve_b, tb)
    if np.linalg.norm(A - B) < tol * 1e3:
        return (ta, tb)
    return None


# ---------------------------------------------------------------------------
# curve_curve_intersect
# ---------------------------------------------------------------------------

def curve_curve_intersect(
    curve_a: NurbsCurve,
    curve_b: NurbsCurve,
    *,
    tol: float = _DEFAULT_TOL,
    samples_a: int = _DEFAULT_SAMPLES_C,
    samples_b: int = _DEFAULT_SAMPLES_C,
) -> List[dict]:
    """Find all intersection points between two NurbsCurves.

    Parameters
    ----------
    curve_a, curve_b : NurbsCurve
    tol : float
    samples_a, samples_b : int  -- Sampling intervals per curve.

    Returns
    -------
    list of dict with keys: ta, tb, point.  Never raises.
    """
    try:
        return _curve_curve_intersect_impl(
            curve_a, curve_b, tol=tol,
            samples_a=samples_a, samples_b=samples_b,
        )
    except Exception:
        return []


def _curve_curve_intersect_impl(
    curve_a: NurbsCurve,
    curve_b: NurbsCurve,
    *,
    tol: float,
    samples_a: int,
    samples_b: int,
) -> List[dict]:
    if not isinstance(curve_a, NurbsCurve):
        return []
    if not isinstance(curve_b, NurbsCurve):
        return []

    sa = max(4, int(samples_a))
    sb = max(4, int(samples_b))

    ta_min, ta_max = _curve_param_range(curve_a)
    tb_min, tb_max = _curve_param_range(curve_b)

    ta_vals = np.linspace(ta_min, ta_max, sa + 1)
    tb_vals = np.linspace(tb_min, tb_max, sb + 1)

    a_pts = [_curve_eval(curve_a, float(t)) for t in ta_vals]
    b_pts = [_curve_eval(curve_b, float(t)) for t in tb_vals]

    candidates: List[Tuple[float, float]] = []
    for i in range(sa):
        a_seg = [a_pts[i], a_pts[i + 1]]
        a_lo, a_hi = _aabb(a_seg)
        for j in range(sb):
            b_seg = [b_pts[j], b_pts[j + 1]]
            b_lo, b_hi = _aabb(b_seg)
            if _aabb_overlap(a_lo, a_hi, b_lo, b_hi, tol * 10):
                ta0 = (ta_vals[i] + ta_vals[i + 1]) * 0.5
                tb0 = (tb_vals[j] + tb_vals[j + 1]) * 0.5
                candidates.append((ta0, tb0))

    hits: List[dict] = []
    for ta0, tb0 in candidates:
        result = _newton_curve_curve(curve_a, curve_b, ta0, tb0, tol=tol)
        if result is None:
            continue
        ta_ref, tb_ref = result
        A = _curve_eval(curve_a, ta_ref)
        B = _curve_eval(curve_b, tb_ref)
        if np.linalg.norm(A - B) > tol * 1e3:
            continue
        pt = ((A + B) * 0.5).tolist()
        hits.append({"ta": ta_ref, "tb": tb_ref, "point": pt})

    return _merge_close_hits(hits, tol)


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
    # ------------------------------------------------------------------
    # curve_surface_intersect tool
    # ------------------------------------------------------------------

    _CSI_SPEC = ToolSpec(
        name="curve_surface_intersect",
        description=(
            "Find all intersection points between a NURBS curve and a NURBS surface. "
            "Returns each intersection point with its curve parameter t and surface "
            "parameters (u, v).  Uses subdivision + AABB cull + Newton refinement.\n"
            "\n"
            "Returns:\n"
            "  ok           : bool\n"
            "  intersections: list of {t, u, v, point:[x,y,z]}\n"
            "  count        : int\n"
            "\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "curve_control_points": {
                    "type": "array",
                    "description": "[[x,y,z], ...] control points of the NURBS curve.",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "curve_degree": {"type": "integer"},
                "curve_knots": {"type": "array", "items": {"type": "number"}},
                "surface_control_points": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "surface_degree_u": {"type": "integer"},
                "surface_degree_v": {"type": "integer"},
                "surface_num_u": {"type": "integer"},
                "surface_num_v": {"type": "integer"},
                "tolerance": {"type": "number"},
            },
            "required": [
                "curve_control_points", "curve_degree", "curve_knots",
                "surface_control_points", "surface_degree_u", "surface_degree_v",
                "surface_num_u", "surface_num_v",
            ],
        },
    )

    @register(_CSI_SPEC)
    async def run_curve_surface_intersect(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")
        try:
            c_cp = np.array(a.get("curve_control_points", []), dtype=float)
            c_deg = int(a["curve_degree"])
            c_knots = np.asarray(a["curve_knots"], dtype=float)
            curve = NurbsCurve(degree=c_deg, control_points=c_cp, knots=c_knots)
        except Exception as exc:
            return err_payload(f"invalid curve: {exc}", "BAD_ARGS")
        try:
            nu = int(a["surface_num_u"]); nv = int(a["surface_num_v"])
            scp = np.array(a.get("surface_control_points", []), dtype=float).reshape(nu, nv, -1)
            deg_u = int(a["surface_degree_u"]); deg_v = int(a["surface_degree_v"])
            def _mk(n, d):
                inner = max(0, n - d - 1)
                return np.concatenate([
                    np.zeros(d + 1),
                    np.linspace(0.0, 1.0, inner + 2)[1:-1] if inner > 0 else np.array([]),
                    np.ones(d + 1),
                ])
            surface = NurbsSurface(
                degree_u=deg_u, degree_v=deg_v, control_points=scp,
                knots_u=_mk(nu, deg_u), knots_v=_mk(nv, deg_v),
            )
        except Exception as exc:
            return err_payload(f"invalid surface: {exc}", "BAD_ARGS")
        tol = float(a.get("tolerance", _DEFAULT_TOL))
        hits = curve_surface_intersect(curve, surface, tol=tol)
        return ok_payload({"ok": True, "intersections": hits, "count": len(hits)})

    # ------------------------------------------------------------------
    # surface_surface_intersect tool
    # ------------------------------------------------------------------

    _SSI_SPEC = ToolSpec(
        name="surface_surface_intersect",
        description=(
            "Compute intersection curve(s) between two NURBS surfaces using a marching "
            "method.  Returns polyline branches with 3-D points and parameter pairs.\n"
            "\n"
            "Returns:\n"
            "  ok           : bool\n"
            "  branch_count : int\n"
            "  branches     : list of {points, params_a, params_b, closed}\n"
            "\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "surf_a_control_points": {"type": "array", "items": {"type": "array", "items": {"type": "number"}}},
                "surf_a_degree_u": {"type": "integer"},
                "surf_a_degree_v": {"type": "integer"},
                "surf_a_num_u": {"type": "integer"},
                "surf_a_num_v": {"type": "integer"},
                "surf_b_control_points": {"type": "array", "items": {"type": "array", "items": {"type": "number"}}},
                "surf_b_degree_u": {"type": "integer"},
                "surf_b_degree_v": {"type": "integer"},
                "surf_b_num_u": {"type": "integer"},
                "surf_b_num_v": {"type": "integer"},
                "tolerance": {"type": "number"},
                "step": {"type": "number"},
            },
            "required": [
                "surf_a_control_points", "surf_a_degree_u", "surf_a_degree_v",
                "surf_a_num_u", "surf_a_num_v",
                "surf_b_control_points", "surf_b_degree_u", "surf_b_degree_v",
                "surf_b_num_u", "surf_b_num_v",
            ],
        },
    )

    @register(_SSI_SPEC)
    async def run_surface_surface_intersect(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        def _build(prefix):
            nu = int(a[f"{prefix}num_u"]); nv = int(a[f"{prefix}num_v"])
            cp = np.array(a.get(f"{prefix}control_points", []), dtype=float).reshape(nu, nv, -1)
            du = int(a[f"{prefix}degree_u"]); dv = int(a[f"{prefix}degree_v"])
            def _mk(n, d):
                inner = max(0, n - d - 1)
                return np.concatenate([
                    np.zeros(d + 1),
                    np.linspace(0.0, 1.0, inner + 2)[1:-1] if inner > 0 else np.array([]),
                    np.ones(d + 1),
                ])
            return NurbsSurface(degree_u=du, degree_v=dv, control_points=cp,
                                knots_u=_mk(nu, du), knots_v=_mk(nv, dv))

        try:
            sA = _build("surf_a_"); sB = _build("surf_b_")
        except Exception as exc:
            return err_payload(f"invalid surface: {exc}", "BAD_ARGS")

        tol = float(a.get("tolerance", _DEFAULT_TOL))
        step = float(a.get("step", _DEFAULT_MARCH_STEP))
        result = surface_surface_intersect(sA, sB, tol=tol, step=step)
        if not result["ok"]:
            return err_payload(result["reason"], "OP_FAILED")
        return ok_payload(result)
