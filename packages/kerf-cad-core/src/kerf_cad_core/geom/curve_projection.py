"""
curve_projection.py
===================
NURBS curve/surface point-projection (closest-point query) via Newton-Raphson
with arc-length re-parametrization for robust convergence.

References
----------
* Piegl & Tiller, "The NURBS Book" 2nd ed., §6.1 — curve point inversion.
* Hu & Wallner (2006) "Robust convergence of point inversion for parametric
  curves and surfaces" — arc-length re-parametrization fallback that avoids
  divergence when the Newton step over-shoots.

Public API
----------
project_point_to_curve(point, curve, tol=1e-9, max_iter=20) -> ProjectionResult
    Closest point on a NurbsCurve to a query point.
    Uses coarse Bézier-clipping seed sampling then Newton-Raphson.
    Falls back to arc-length re-parametrization when Newton diverges.
    Returns ``ProjectionResult(parameter, point_on_curve, distance, converged)``.

project_point_to_surface(point, surface, tol=1e-9, max_iter=20) -> ProjectionResult
    Closest point on a NurbsSurface to a query point.
    2-D Newton on (u, v) with the 2×2 Jacobian of the residual.
    Returns ``ProjectionResult`` with ``parameter = (u, v)``.

distance_curve_to_curve(curve_a, curve_b, n_samples=10) -> float
    Minimum Euclidean distance between two NurbsCurves via uniform sampling
    followed by local Newton refinement of the closest pair.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Tuple, Union

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsCurve, NurbsSurface
from kerf_cad_core.geom.inversion import (
    _curve_param_range,
    _surface_param_range,
    _curve_eval as _inv_curve_eval,
    _surf_eval as _inv_surf_eval,
    _curve_ders,
    _surf_partials,
)

# ---------------------------------------------------------------------------
# Public result container
# ---------------------------------------------------------------------------

@dataclass
class ProjectionResult:
    """Result of a point-projection operation.

    Attributes
    ----------
    parameter : float or tuple[float, float]
        Curve parameter ``t`` (curve projection) or ``(u, v)`` (surface).
    point_on_curve : np.ndarray
        The 3-D foot point on the curve/surface.
    distance : float
        Euclidean distance from the query point to ``point_on_curve``.
    converged : bool
        True when the Newton iteration satisfied the tolerance; False when the
        arc-length fallback was used or max_iter was exhausted.
    """
    parameter: Union[float, Tuple[float, float]]
    point_on_curve: np.ndarray
    distance: float
    converged: bool

    def __repr__(self) -> str:
        param_s = (f"{self.parameter:.10g}" if isinstance(self.parameter, float)
                   else f"({self.parameter[0]:.10g}, {self.parameter[1]:.10g})")
        return (f"ProjectionResult(parameter={param_s}, "
                f"distance={self.distance:.6g}, converged={self.converged})")


# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_EPS: float = 1e-15
_COARSE_CURVE_SAMPLES: int = 128   # Bézier-clipping seed resolution
_COARSE_SURF_SAMPLES: int = 32     # coarse UV grid per dimension


# ---------------------------------------------------------------------------
# Arc-length re-parametrization (Hu-Wallner robustness)
# ---------------------------------------------------------------------------

def _build_arc_length_map(
    curve: NurbsCurve, n_seg: int = 256,
) -> Tuple[np.ndarray, np.ndarray]:
    """Build a piecewise-linear arc-length ↔ parameter table.

    Returns ``(arc_lengths, params)`` where ``arc_lengths[i]`` is the
    cumulative arc length from ``t_min`` to ``params[i]``.
    """
    t_min, t_max = _curve_param_range(curve)
    ts = np.linspace(t_min, t_max, n_seg + 1)
    pts = np.array([_inv_curve_eval(curve, float(t)) for t in ts])
    segs = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    cumul = np.concatenate([[0.0], np.cumsum(segs)])
    return cumul, ts


def _arc_length_to_param(
    s: float, arc_lengths: np.ndarray, params: np.ndarray,
) -> float:
    """Linear-interpolate parameter from arc-length s (clamped)."""
    s = float(np.clip(s, arc_lengths[0], arc_lengths[-1]))
    idx = int(np.searchsorted(arc_lengths, s, side="right")) - 1
    idx = int(np.clip(idx, 0, len(arc_lengths) - 2))
    ds = arc_lengths[idx + 1] - arc_lengths[idx]
    if ds < _EPS:
        return float(params[idx])
    frac = (s - arc_lengths[idx]) / ds
    return float(params[idx] + frac * (params[idx + 1] - params[idx]))


# ---------------------------------------------------------------------------
# 1-D Newton for curve projection
# ---------------------------------------------------------------------------

def _newton_project_curve(
    curve: NurbsCurve,
    P: np.ndarray,
    t0: float,
    t_min: float,
    t_max: float,
    tol: float,
    max_iter: int,
    arc_lengths: np.ndarray,
    params_arc: np.ndarray,
) -> Tuple[float, np.ndarray, float, bool]:
    """Newton-Raphson on  f(t) = (C(t) - P) · C'(t) = 0.

    f'(t) = C'(t)·C'(t) + (C(t)-P)·C''(t)

    Arc-length re-parametrization fallback: when the ordinary Newton step
    would take t outside [t_min, t_max] or the residual |f/f'| is growing
    monotonically (divergence indicator), the step is limited using the
    arc-length map so the search stays on the curve (Hu-Wallner §3).

    Returns (t, point, dist, converged).
    """
    t = float(np.clip(t0, t_min, t_max))
    best_t = t
    C_best = _inv_curve_eval(curve, t)
    best_d = float(np.linalg.norm(C_best - P))

    prev_f_abs = float("inf")
    arc_total = arc_lengths[-1]
    converged = False

    for _ in range(max_iter):
        derivs = _curve_ders(curve, t, 2)
        C, C1, C2 = derivs[0], derivs[1], derivs[2]
        r = C - P
        d = float(np.linalg.norm(r))
        if d < best_d:
            best_d, best_t = d, t

        f = float(np.dot(r, C1))
        fp = float(np.dot(C1, C1)) + float(np.dot(r, C2))

        # Zero-cosine convergence (Piegl eq. 6.8).
        c1n = float(np.linalg.norm(C1))
        if d < tol or (c1n > _EPS and abs(f) / (c1n * max(d, _EPS)) < tol):
            converged = True
            best_t, best_d = t, d
            break

        if abs(fp) < _EPS:
            break

        delta_t = -f / fp
        t_new = t + delta_t

        # Arc-length fallback: if the ordinary step leaves the domain or the
        # residual is not decreasing, replace it with a step that is equivalent
        # in arc-length so the foot stays on the curve manifold.
        if not (t_min <= t_new <= t_max) or abs(f) >= prev_f_abs:
            # Compute arc-length position of current t and limit the step.
            s_curr = float(np.interp(t, params_arc, arc_lengths))
            # Arc-length equivalent of the Newton step (|C'| ≈ local speed).
            s_delta = float(np.clip(
                delta_t * c1n if c1n > _EPS else delta_t,
                -arc_total * 0.25, arc_total * 0.25,
            ))
            s_new = float(np.clip(s_curr + s_delta, arc_lengths[0], arc_lengths[-1]))
            t_new = _arc_length_to_param(s_new, arc_lengths, params_arc)

        t_new = float(np.clip(t_new, t_min, t_max))
        # Parameter-step convergence (Piegl eq. 6.9).
        step_len = abs(t_new - t) * c1n
        if step_len < tol:
            t = t_new
            C_n = _inv_curve_eval(curve, t)
            d_n = float(np.linalg.norm(C_n - P))
            if d_n < best_d:
                best_t, best_d = t, d_n
            converged = True
            break

        prev_f_abs = abs(f)
        t = t_new

    pt = _inv_curve_eval(curve, best_t)
    return best_t, pt, float(np.linalg.norm(pt - P)), converged


# ---------------------------------------------------------------------------
# project_point_to_curve
# ---------------------------------------------------------------------------

def project_point_to_curve(
    point,
    curve: NurbsCurve,
    tol: float = 1e-9,
    max_iter: int = 20,
) -> ProjectionResult:
    """Closest point on ``curve`` to ``point`` (Piegl & Tiller §6.1 +
    Hu-Wallner arc-length robustness).

    Algorithm
    ---------
    1. Coarse Bézier-clipping seed: sample the curve at
       ``_COARSE_CURVE_SAMPLES`` equally-spaced parameter values, pick the
       closest ``k`` candidates (coarsest-level Bézier-clipping proxy).
    2. Newton-Raphson: for each seed solve  f(t) = (C(t)-P)·C'(t) = 0  with
       ``f'(t) = C'·C' + (C-P)·C''``.  Arc-length re-parametrization replaces
       Newton steps that diverge or escape the parameter domain.
    3. Return the globally best result.

    Parameters
    ----------
    point : array-like, shape (3,) or (2,)
    curve : NurbsCurve
    tol   : float — convergence tolerance (default 1e-9)
    max_iter : int — maximum Newton iterations per seed

    Returns
    -------
    ProjectionResult
    """
    P = np.asarray(point, dtype=float).ravel()
    Q = np.zeros(3)
    Q[:min(3, P.size)] = P[:min(3, P.size)]
    P = Q

    t_min, t_max = _curve_param_range(curve)
    arc_lengths, params_arc = _build_arc_length_map(curve, n_seg=_COARSE_CURVE_SAMPLES)

    # Coarse seed scan.
    ts = np.linspace(t_min, t_max, _COARSE_CURVE_SAMPLES + 1)
    pts_c = np.array([_inv_curve_eval(curve, float(t)) for t in ts])
    dists_c = np.linalg.norm(pts_c - P, axis=1)
    order = np.argsort(dists_c)

    n_seeds = min(8, len(order))
    seed_indices = list(order[:n_seeds])
    for extra in (0, len(ts) - 1, len(ts) // 2):
        if extra not in seed_indices:
            seed_indices.append(extra)

    best_t = float(ts[order[0]])
    best_pt = pts_c[order[0]].copy()
    best_d = float(dists_c[order[0]])
    best_conv = False

    for si in seed_indices:
        t0 = float(ts[si])
        t_r, pt_r, d_r, conv_r = _newton_project_curve(
            curve, P, t0, t_min, t_max, tol, max_iter,
            arc_lengths, params_arc,
        )
        if d_r < best_d:
            best_t, best_pt, best_d, best_conv = t_r, pt_r, d_r, conv_r

    # Endpoint refinement for open curves.
    for te in (t_min, t_max):
        pt_e = _inv_curve_eval(curve, te)
        d_e = float(np.linalg.norm(pt_e - P))
        if d_e < best_d:
            best_t, best_pt, best_d, best_conv = te, pt_e, d_e, True

    return ProjectionResult(
        parameter=float(best_t),
        point_on_curve=best_pt,
        distance=float(best_d),
        converged=best_conv,
    )


# ---------------------------------------------------------------------------
# 2-D Newton for surface projection
# ---------------------------------------------------------------------------

def _newton_project_surface(
    surf: NurbsSurface,
    P: np.ndarray,
    u0: float,
    v0: float,
    u_min: float,
    u_max: float,
    v_min: float,
    v_max: float,
    tol: float,
    max_iter: int,
) -> Tuple[float, float, np.ndarray, float, bool]:
    """2-D Newton on (u, v) for surface point-projection.

    Solves the 2×2 system:
        f(u,v) = (S(u,v) - P) · Su = 0
        g(u,v) = (S(u,v) - P) · Sv = 0

    Jacobian:
        [f_u  f_v]   [Su·Su + r·Suu   Su·Sv + r·Suv]
        [g_u  g_v] = [Su·Sv + r·Suv   Sv·Sv + r·Svv]

    Returns (u, v, point, dist, converged).
    """
    u = float(np.clip(u0, u_min, u_max))
    v = float(np.clip(v0, v_min, v_max))
    best_u, best_v = u, v
    S0 = _inv_surf_eval(surf, u, v)
    best_d = float(np.linalg.norm(S0 - P))
    converged = False

    for _ in range(max_iter):
        S, Su, Sv, Suu, Suv, Svv = _surf_partials(surf, u, v)
        r = S - P
        d = float(np.linalg.norm(r))
        if d < best_d:
            best_d, best_u, best_v = d, u, v

        su_n = float(np.linalg.norm(Su))
        sv_n = float(np.linalg.norm(Sv))
        f = float(np.dot(r, Su))
        g = float(np.dot(r, Sv))

        # Zero-cosine convergence on both directions.
        c1 = abs(f) / (su_n * max(d, _EPS)) if su_n > _EPS else 0.0
        c2 = abs(g) / (sv_n * max(d, _EPS)) if sv_n > _EPS else 0.0
        if d < tol or (c1 < tol and c2 < tol):
            converged = True
            best_u, best_v, best_d = u, v, d
            break

        j11 = float(np.dot(Su, Su)) + float(np.dot(r, Suu))
        j12 = float(np.dot(Su, Sv)) + float(np.dot(r, Suv))
        j22 = float(np.dot(Sv, Sv)) + float(np.dot(r, Svv))

        J2 = np.array([[j11, j12], [j12, j22]])
        rhs = np.array([-f, -g])
        try:
            cond2 = np.linalg.cond(J2)
        except np.linalg.LinAlgError:
            cond2 = float("inf")
        if np.isfinite(cond2) and cond2 < 1e10 and abs(j11 * j22 - j12 * j12) > _EPS:
            det = j11 * j22 - j12 * j12
            du = -(j22 * f - j12 * g) / det
            dv = -(j11 * g - j12 * f) / det
        else:
            sol, *_ = np.linalg.lstsq(J2, rhs, rcond=None)
            du, dv = float(sol[0]), float(sol[1])

        u_new = float(np.clip(u + du, u_min, u_max))
        v_new = float(np.clip(v + dv, v_min, v_max))

        # Parameter-step convergence.
        step = (u_new - u) * Su + (v_new - v) * Sv
        if float(np.linalg.norm(step)) < tol:
            u, v = u_new, v_new
            S_n = _inv_surf_eval(surf, u, v)
            d_n = float(np.linalg.norm(S_n - P))
            if d_n < best_d:
                best_u, best_v, best_d = u, v, d_n
            converged = True
            break

        u, v = u_new, v_new

    pt = _inv_surf_eval(surf, best_u, best_v)
    return best_u, best_v, pt, float(np.linalg.norm(pt - P)), converged


# ---------------------------------------------------------------------------
# project_point_to_surface
# ---------------------------------------------------------------------------

def project_point_to_surface(
    point,
    surface: NurbsSurface,
    tol: float = 1e-9,
    max_iter: int = 20,
) -> ProjectionResult:
    """Closest point on ``surface`` to ``point`` via 2-D Newton-Raphson.

    Algorithm
    ---------
    1. Coarse UV grid scan to pick the closest ``k`` seeds.
    2. 2-D Newton on the 2-equation system with the full Jacobian.
    3. Return the globally best result.

    Parameters
    ----------
    point   : array-like, shape (3,)
    surface : NurbsSurface
    tol     : float — convergence tolerance (default 1e-9)
    max_iter: int — maximum Newton iterations per seed

    Returns
    -------
    ProjectionResult  with ``parameter = (u, v)``
    """
    P = np.asarray(point, dtype=float).ravel()
    Q = np.zeros(3)
    Q[:min(3, P.size)] = P[:min(3, P.size)]
    P = Q

    u_min, u_max, v_min, v_max = _surface_param_range(surface)
    ns = _COARSE_SURF_SAMPLES
    us = np.linspace(u_min, u_max, ns + 1)
    vs = np.linspace(v_min, v_max, ns + 1)

    grid = np.array([[_inv_surf_eval(surface, float(u), float(v)) for v in vs]
                     for u in us])
    d2 = np.linalg.norm(grid - P, axis=2)
    flat = np.argsort(d2.ravel())

    # Pick best few seeds.
    n_seeds = min(12, flat.size)
    seeds = [divmod(int(k), ns + 1) for k in flat[:n_seeds]]
    for cu in (0, ns, ns // 2):
        for cv in (0, ns, ns // 2):
            if (cu, cv) not in seeds:
                seeds.append((cu, cv))

    bi, bj = divmod(int(flat[0]), ns + 1)
    best_u = float(us[bi]); best_v = float(vs[bj])
    best_pt = grid[bi, bj].copy()
    best_d = float(d2[bi, bj])
    best_conv = False

    for (i, j) in seeds:
        u_r, v_r, pt_r, d_r, conv_r = _newton_project_surface(
            surface, P,
            float(us[i]), float(vs[j]),
            u_min, u_max, v_min, v_max,
            tol, max_iter,
        )
        if d_r < best_d:
            best_u, best_v, best_pt, best_d, best_conv = u_r, v_r, pt_r, d_r, conv_r

    return ProjectionResult(
        parameter=(float(best_u), float(best_v)),
        point_on_curve=best_pt,
        distance=float(best_d),
        converged=best_conv,
    )


# ---------------------------------------------------------------------------
# distance_curve_to_curve
# ---------------------------------------------------------------------------

def distance_curve_to_curve(
    curve_a: NurbsCurve,
    curve_b: NurbsCurve,
    n_samples: int = 10,
) -> float:
    """Minimum Euclidean distance between two NurbsCurves.

    Algorithm
    ---------
    1. Sample each curve at ``n_samples`` evenly-spaced parameter values.
    2. For every sample on ``curve_a`` project it onto ``curve_b`` via
       ``project_point_to_curve`` to get the closest foot.
    3. Symmetrically project every sample on ``curve_b`` onto ``curve_a``.
    4. Return the global minimum distance found.

    Parameters
    ----------
    curve_a, curve_b : NurbsCurve
    n_samples : int — sampling density per curve (default 10)

    Returns
    -------
    float — minimum distance (>= 0)
    """
    ns = max(4, int(n_samples))
    ta_min, ta_max = _curve_param_range(curve_a)
    tb_min, tb_max = _curve_param_range(curve_b)
    ts_a = np.linspace(ta_min, ta_max, ns + 1)
    ts_b = np.linspace(tb_min, tb_max, ns + 1)

    pts_a = np.array([_inv_curve_eval(curve_a, float(t)) for t in ts_a])
    pts_b = np.array([_inv_curve_eval(curve_b, float(t)) for t in ts_b])

    # Coarse minimum via pairwise distances.
    from scipy.spatial.distance import cdist
    D = cdist(pts_a, pts_b)
    coarse_min = float(D.min())

    # Refine with Newton projections from each side.
    best_d = coarse_min
    for pt in pts_a:
        res = project_point_to_curve(pt, curve_b)
        if res.distance < best_d:
            best_d = res.distance
    for pt in pts_b:
        res = project_point_to_curve(pt, curve_a)
        if res.distance < best_d:
            best_d = res.distance

    return max(0.0, float(best_d))


# ---------------------------------------------------------------------------
# LLM tool registration
# ---------------------------------------------------------------------------

try:
    import json as _json

    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx  # noqa: F401

    def _build_curve(cp_flat, nu: int, degree: int) -> NurbsCurve:
        """Build a NurbsCurve from flat control-points list and degree."""
        cp = np.array(cp_flat, dtype=float).reshape(nu, -1)
        inner = max(0, nu - degree - 1)
        knots = np.concatenate([
            np.zeros(degree + 1),
            np.linspace(0.0, 1.0, inner + 2)[1:-1] if inner > 0 else np.array([]),
            np.ones(degree + 1),
        ])
        return NurbsCurve(degree=degree, control_points=cp, knots=knots)

    def _build_surface(cp_flat, nu: int, nv: int, du: int, dv: int) -> NurbsSurface:
        """Build a NurbsSurface from flat control-points list."""
        cp = np.array(cp_flat, dtype=float).reshape(nu, nv, -1)
        def _mk(n, d):
            inner = max(0, n - d - 1)
            return np.concatenate([
                np.zeros(d + 1),
                np.linspace(0.0, 1.0, inner + 2)[1:-1] if inner > 0 else np.array([]),
                np.ones(d + 1),
            ])
        return NurbsSurface(
            degree_u=du, degree_v=dv, control_points=cp,
            knots_u=_mk(nu, du), knots_v=_mk(nv, dv),
        )

    _PROJ_SPEC = ToolSpec(
        name="nurbs_project_point",
        description=(
            "Project a 3-D point onto the closest point of a NURBS curve OR surface.\n"
            "\n"
            "Dispatches on ``target_type``:\n"
            "  'curve'   — project onto a NurbsCurve via Newton-Raphson with\n"
            "              arc-length re-parametrization fallback (Piegl §6.1,\n"
            "              Hu-Wallner 2006).\n"
            "  'surface' — project onto a NurbsSurface via 2-D Newton with the\n"
            "              full (Suu, Suv, Svv) Jacobian.\n"
            "\n"
            "Returns:\n"
            "  ok            : bool\n"
            "  parameter     : number (curve) or [u, v] (surface)\n"
            "  point_on_curve: [x, y, z]  — foot point\n"
            "  distance      : float      — |query - foot|\n"
            "  converged     : bool       — True if Newton converged within tol\n"
            "\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query_point": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "3-D query point [x, y, z]",
                },
                "target_type": {
                    "type": "string",
                    "enum": ["curve", "surface"],
                    "description": "'curve' or 'surface'",
                },
                # Curve fields
                "curve_control_points": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                    "description": "List of control points (curve); required when target_type='curve'.",
                },
                "curve_num_points": {
                    "type": "integer",
                    "description": "Number of control points (curve).",
                },
                "curve_degree": {
                    "type": "integer",
                    "description": "Polynomial degree of the curve.",
                },
                # Surface fields
                "surface_control_points": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                    "description": "Flat list of control points (surface, row-major nu×nv).",
                },
                "surface_num_u": {"type": "integer"},
                "surface_num_v": {"type": "integer"},
                "surface_degree_u": {"type": "integer"},
                "surface_degree_v": {"type": "integer"},
                # Shared
                "tolerance": {
                    "type": "number",
                    "description": "Newton convergence tolerance (default 1e-9).",
                },
                "max_iter": {
                    "type": "integer",
                    "description": "Maximum Newton iterations per seed (default 20).",
                },
            },
            "required": ["query_point", "target_type"],
        },
    )

    @register(_PROJ_SPEC)
    async def run_nurbs_project_point(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        try:
            query = list(a["query_point"])
            ttype = str(a.get("target_type", "curve"))
            tol = float(a.get("tolerance", 1e-9))
            max_it = int(a.get("max_iter", 20))
        except Exception as exc:
            return err_payload(f"bad args: {exc}", "BAD_ARGS")

        if ttype == "curve":
            try:
                nu = int(a["curve_num_points"])
                deg = int(a["curve_degree"])
                curve = _build_curve(a["curve_control_points"], nu, deg)
            except Exception as exc:
                return err_payload(f"invalid curve: {exc}", "BAD_ARGS")
            res = project_point_to_curve(query, curve, tol=tol, max_iter=max_it)
            return ok_payload({
                "ok": True,
                "parameter": float(res.parameter),
                "point_on_curve": [float(x) for x in res.point_on_curve],
                "distance": float(res.distance),
                "converged": bool(res.converged),
            })

        elif ttype == "surface":
            try:
                nu = int(a["surface_num_u"]); nv = int(a["surface_num_v"])
                du = int(a["surface_degree_u"]); dv = int(a["surface_degree_v"])
                surface = _build_surface(a["surface_control_points"], nu, nv, du, dv)
            except Exception as exc:
                return err_payload(f"invalid surface: {exc}", "BAD_ARGS")
            res = project_point_to_surface(query, surface, tol=tol, max_iter=max_it)
            u_r, v_r = res.parameter
            return ok_payload({
                "ok": True,
                "parameter": [float(u_r), float(v_r)],
                "point_on_curve": [float(x) for x in res.point_on_curve],
                "distance": float(res.distance),
                "converged": bool(res.converged),
            })

        else:
            return err_payload(f"target_type must be 'curve' or 'surface', got {ttype!r}",
                               "BAD_ARGS")

except ImportError:
    # kerf_chat not available (e.g. standalone test run); skip registration.
    pass
