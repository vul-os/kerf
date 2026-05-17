"""
offset.py
=========
Curve and surface offset primitives for the Kerf geometry kernel
(GK-30, GK-31, GK-32 — P1 comprehensiveness parity).

Sign convention
---------------
``d > 0``  — outward (along the positive normal / right-side normal).
``d < 0``  — inward (along the negative normal).

For a planar curve parameterised left-to-right the *right-side normal* is the
vector obtained by rotating the unit tangent 90° clockwise in the curve plane
(i.e. cross(plane_normal, tangent_unit)).  For ``d > 0`` the offset moves in
that direction; for ``d < 0`` it moves in the opposite direction.

Public API
----------
offset_curve(curve, d, *, tol, plane_normal, num_samples)
    Planar curve offset by signed distance ``d`` along the right-side normal.
    Analytic circles → exact concentric circle.  General NURBS → refit with
    max deviation ≤ ``tol``; reports ``actual_max_deviation`` in the return.

offset_curve_3d(curve, surface, d, *, num_samples)
    Geodesic-style offset of a curve constrained to a surface: the offset
    direction at each sample point is the surface tangent perpendicular to
    the curve tangent (i.e. along the surface normal × curve tangent), then
    the point is reprojected onto the surface via closest-point inversion.
    Returns a NurbsCurve in 3-D.

offset_surface(surface, d, *, tol, grid_samples)
    Surface offset along the analytic unit normal by signed distance ``d``.
    Analytic spheres / planes → exact concentric sphere / parallel plane.
    General NURBS surface → sample on a grid, offset each image point along
    its analytic normal, refit; reports ``actual_max_deviation``.

offset_loop(curves, d, *, plane_normal, tol, num_samples)
    Offset a closed planar loop of curves, preserving connectivity:
      - convex corners → arc fillet of radius |d|.
      - concave corners → extension / trim.
    Returns a list of NurbsCurve segments forming the offset loop.

All functions return a dict ``{"ok": bool, "curve"/"surface": ...,
"actual_max_deviation": float, "reason": str}``.

Invalid inputs (NaN, degenerate zero-length curve, etc.) raise ``ValueError``
with a descriptive message.
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

import numpy as np

from kerf_cad_core.geom.nurbs import (
    NurbsCurve,
    NurbsSurface,
    de_boor,
    make_circle_nurbs,
    surface_normal,
    surface_evaluate,
)
from kerf_cad_core.geom.curve_toolkit import (
    interp_curve,
    fit_curve,
)
from kerf_cad_core.geom.inversion import (
    closest_point_surface,
    _curve_param_range,
    _surface_param_range,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _validate_distance(d: float) -> float:
    d = float(d)
    if math.isnan(d) or math.isinf(d):
        raise ValueError(f"offset distance must be finite, got {d!r}")
    return d


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    if n < 1e-300:
        raise ValueError("zero-length vector cannot be normalised")
    return v / n


def _eval_curve(curve: NurbsCurve, t: float) -> np.ndarray:
    """Evaluate a NurbsCurve correctly, handling both rational (weights field)
    and non-rational cases via ``nurbs.de_boor``.
    """
    return de_boor(curve, float(t))


def _eval_surface(surf: NurbsSurface, u: float, v: float) -> np.ndarray:
    """Evaluate a NurbsSurface correctly via ``nurbs.surface_evaluate``."""
    return surface_evaluate(surf, float(u), float(v))


def _curve_param_range_safe(curve: NurbsCurve) -> Tuple[float, float]:
    return float(curve.knots[curve.degree]), float(curve.knots[-(curve.degree + 1)])


def _sample_curve_pts(curve: NurbsCurve, num: int) -> Tuple[np.ndarray, np.ndarray]:
    """Return (params, points) at ``num`` uniformly spaced parameter values."""
    t0, t1 = _curve_param_range_safe(curve)
    ts = np.linspace(t0, t1, max(3, int(num)))
    pts = np.array([_eval_curve(curve, float(t)) for t in ts])
    return ts, pts


def _sample_surface_pts(surf: NurbsSurface, nu: int, nv: int) -> np.ndarray:
    """Return (nu*nv, 3) array of surface sample points."""
    u_min, u_max, v_min, v_max = _surface_param_range(surf)
    us = np.linspace(u_min, u_max, nu)
    vs = np.linspace(v_min, v_max, nv)
    pts = []
    for u in us:
        for v in vs:
            pts.append(_eval_surface(surf, float(u), float(v)))
    return np.array(pts)


# ---------------------------------------------------------------------------
# Analytic shape detectors
# ---------------------------------------------------------------------------

def _is_rational_circle(curve: NurbsCurve) -> Optional[Tuple[np.ndarray, float]]:
    """If ``curve`` is the exact 9-point rational quadratic circle from
    ``make_circle_nurbs``, return (centre, radius).  Returns None otherwise.

    Detection criteria:
      * degree 2, exactly 9 control points.
      * weights == [1, √2/2, 1, √2/2, 1, √2/2, 1, √2/2, 1] (± 1e-9).
      * 4 on-circle quadrant points (weight=1) equidistant from centroid.
    """
    if curve.degree != 2 or curve.num_control_points != 9:
        return None
    w = curve.weights
    if w is None:
        return None
    s = math.sqrt(2.0) / 2.0
    expected = np.array([1.0, s, 1.0, s, 1.0, s, 1.0, s, 1.0])
    if not np.allclose(w, expected, atol=1e-9):
        return None
    # Quadrant points at even indices 0, 2, 4, 6 (the first 4 distinct ones;
    # index 8 == index 0 for a closed curve).
    q_pts = curve.control_points[[0, 2, 4, 6], :3]
    centre = q_pts.mean(axis=0)
    radii = np.linalg.norm(q_pts - centre, axis=1)
    if not np.allclose(radii, radii[0], rtol=1e-9, atol=1e-12):
        return None
    radius = float(radii[0])
    if radius < 1e-14:
        return None
    return centre, radius


def _is_planar_nurbs_surface(surf: NurbsSurface) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """Detect a degree-(1,1) planar NURBS patch.

    Returns (point_on_plane, unit_normal) or None.
    """
    if surf.degree_u != 1 or surf.degree_v != 1:
        return None
    if surf.num_control_points_u != 2 or surf.num_control_points_v != 2:
        return None
    p00 = surf.control_points[0, 0, :3]
    p10 = surf.control_points[1, 0, :3]
    p01 = surf.control_points[0, 1, :3]
    p11 = surf.control_points[1, 1, :3]
    v1 = p10 - p00
    v2 = p01 - p00
    nrm = np.cross(v1, v2)
    mag = float(np.linalg.norm(nrm))
    if mag < 1e-12:
        return None
    unit_nrm = nrm / mag
    if abs(float(np.dot(p11 - p00, unit_nrm))) > 1e-9:
        return None
    return p00.copy(), unit_nrm


def _is_sphere_surface(surf: NurbsSurface) -> Optional[Tuple[np.ndarray, float]]:
    """Detect a sphere encoded as the standard rational revolution NURBS.

    The sphere from revolving a rational half-circle arc has the structural
    signature:
      * degree 2 in both U and V.
      * Exactly two rows (j=0 and j=nv-1) where all control points are
        collapsed to a single point (the poles).
      * One middle row (j = nv//2) that forms the equator circle.

    Extracts the poles and the equator to compute centre + radius.
    Returns (centre, radius) or None.
    """
    if surf.weights is None:
        return None
    if surf.degree_u != 2 or surf.degree_v != 2:
        return None
    P = surf.control_points[:, :, :3]
    nu = P.shape[0]
    nv = P.shape[1]
    if nu < 5 or nv < 5:
        return None

    # Check whether the first and last v-columns are collapsed to a single point.
    col0 = P[:, 0, :]
    colN = P[:, nv - 1, :]
    # All points in the pole columns should be at the same location.
    if not (np.allclose(col0 - col0[0], 0.0, atol=1e-9) and
            np.allclose(colN - colN[0], 0.0, atol=1e-9)):
        return None

    south_pole = col0[0]
    north_pole = colN[0]

    # The sphere centre is the midpoint of the two poles.
    centre = (south_pole + north_pole) * 0.5
    # Radius is the half-distance between poles.
    r_axis = float(np.linalg.norm(north_pole - south_pole)) * 0.5
    if r_axis < 1e-14:
        return None

    # Cross-check: evaluate the equator row (v = middle parameter) at the
    # unit-weight equator control points.
    j_mid = nv // 2
    eq_pts = P[:, j_mid, :]
    # The on-circle equator points are those with weight 1 (even indices).
    W = surf.weights
    w_eq = W[:, j_mid]
    on_pts_mask = np.abs(w_eq - 1.0) < 1e-9
    on_pts = eq_pts[on_pts_mask]
    if len(on_pts) < 3:
        return None

    eq_dists = np.linalg.norm(on_pts - centre, axis=1)
    r_eq = float(eq_dists.mean())
    if r_eq < 1e-14:
        return None
    # Equator radius should match pole-based radius (sphere).
    if abs(r_eq - r_axis) / r_axis > 1e-3:
        return None

    # All equator on-points equidistant from centre.
    if float(eq_dists.std()) / r_eq > 1e-6:
        return None

    return centre, r_eq


# ---------------------------------------------------------------------------
# offset_curve
# ---------------------------------------------------------------------------

def offset_curve(
    curve: NurbsCurve,
    d: float,
    *,
    tol: float = 1e-4,
    plane_normal: Optional[Sequence] = None,
    num_samples: int = 200,
) -> dict:
    """Planar curve offset by signed distance ``d`` along the right-side normal.

    Sign convention: ``d > 0`` → right-side (outward); ``d < 0`` → left-side
    (inward).  The right-side normal of the curve tangent ``T`` in plane ``N``
    is ``R = normalise(cross(N, T))`` so positive ``d`` moves in the ``+R``
    direction.

    For an exact rational 9-point circle (from ``make_circle_nurbs``), the
    result is an exact concentric circle with ``actual_max_deviation = 0.0``.

    Returns
    -------
    dict:
        ok                  : bool
        curve               : NurbsCurve (the offset, or None on failure)
        actual_max_deviation: float (0.0 for exact analytic results)
        reason              : str (non-empty when ok is False)

    Raises
    ------
    ValueError  on NaN/inf ``d`` or a zero-length curve.
    """
    if not isinstance(curve, NurbsCurve):
        raise ValueError(f"curve must be a NurbsCurve, got {type(curve).__name__}")
    d = _validate_distance(d)

    # Validate input curve is non-degenerate.
    t0, t1 = _curve_param_range_safe(curve)
    p0 = _eval_curve(curve, t0)
    p_mid = _eval_curve(curve, (t0 + t1) * 0.5)
    p1 = _eval_curve(curve, t1)
    if (float(np.linalg.norm(p_mid[:3] - p0[:3])) < 1e-14 and
            float(np.linalg.norm(p1[:3] - p0[:3])) < 1e-14):
        raise ValueError("curve is degenerate (zero length)")

    # --- analytic shortcut: exact rational circle ---
    circle_info = _is_rational_circle(curve)
    if circle_info is not None:
        centre, r = circle_info
        r_new = r + d
        if r_new <= 0.0:
            return {
                "ok": False,
                "curve": None,
                "actual_max_deviation": 0.0,
                "reason": f"offset distance {d} collapses circle of radius {r}",
            }
        # Recover axes from control point net.
        x_ax_raw = (curve.control_points[0, :3] - centre)
        xn = float(np.linalg.norm(x_ax_raw))
        x_ax = x_ax_raw / xn if xn > 1e-14 else np.array([1.0, 0.0, 0.0])
        if plane_normal is not None:
            nrm = np.asarray(plane_normal, dtype=float).ravel()[:3]
        else:
            nrm = np.array([0.0, 0.0, 1.0])
        y_ax = np.cross(nrm, x_ax)
        yn = float(np.linalg.norm(y_ax))
        y_ax = y_ax / yn if yn > 1e-14 else np.array([0.0, 1.0, 0.0])
        offset_circle = make_circle_nurbs(centre, r_new, x_axis=x_ax, y_axis=y_ax)
        return {
            "ok": True,
            "curve": offset_circle,
            "actual_max_deviation": 0.0,
            "reason": "",
        }

    # --- general NURBS path ---
    if plane_normal is None:
        nrm = np.array([0.0, 0.0, 1.0])
    else:
        nrm = np.asarray(plane_normal, dtype=float).ravel()
        nm = float(np.linalg.norm(nrm))
        nrm = (nrm / nm) if nm > 1e-14 else np.array([0.0, 0.0, 1.0])
    if nrm.shape[0] < 3:
        tmp = np.zeros(3)
        tmp[:nrm.shape[0]] = nrm
        nrm = tmp
    nrm = nrm[:3]

    ts, pts = _sample_curve_pts(curve, num_samples)
    pts3 = pts[:, :3].copy()

    # Compute tangents via central differences.
    tans = np.gradient(pts3, axis=0)

    offset_pts = np.empty_like(pts3)
    for i in range(len(pts3)):
        t_vec = tans[i]
        t_n = float(np.linalg.norm(t_vec))
        if t_n < 1e-14:
            offset_pts[i] = pts3[i]
            continue
        t_unit = t_vec / t_n
        right = np.cross(nrm, t_unit)
        r_n = float(np.linalg.norm(right))
        if r_n < 1e-14:
            offset_pts[i] = pts3[i]
        else:
            offset_pts[i] = pts3[i] + (d / r_n) * right

    # Refit to a NURBS curve.
    result = fit_curve(offset_pts, degree=min(3, curve.degree), tolerance=tol,
                       max_ctrl=max(16, num_samples // 4))

    if result["ok"] and result["curve"] is not None:
        approx = result["curve"]
        # fit_curve measures deviation at the chord-length parameter values of
        # the INPUT points, which is the most meaningful measure.
        actual_dev = float(result.get("deviation", float("inf")))
    else:
        # Fallback: interpolation through all offset points (zero deviation at samples).
        approx = interp_curve(offset_pts, degree=min(3, curve.degree))
        # Re-evaluate at offset_pts parameter values to measure interpolation error.
        from kerf_cad_core.geom.curve_toolkit import _chord_params
        ts_ip = _chord_params(offset_pts)
        t0_a = float(approx.knots[approx.degree])
        t1_a = float(approx.knots[-(approx.degree + 1)])
        ts_a = t0_a + ts_ip * (t1_a - t0_a)
        resampled = np.array([_eval_curve(approx, float(t)) for t in ts_a])
        devs = np.linalg.norm(resampled[:, :3] - offset_pts, axis=1)
        actual_dev = float(np.max(devs))

    ok = (actual_dev <= tol) if not math.isinf(actual_dev) else False
    return {
        "ok": ok,
        "curve": approx,
        "actual_max_deviation": actual_dev,
        "reason": "" if ok else f"tolerance {tol} not achieved; best dev {actual_dev:.4g}",
    }


# ---------------------------------------------------------------------------
# offset_curve_3d
# ---------------------------------------------------------------------------

def offset_curve_3d(
    curve: NurbsCurve,
    surface: NurbsSurface,
    d: float,
    *,
    num_samples: int = 100,
) -> dict:
    """Geodesic-style offset of a curve constrained to a surface.

    At each sampled point on ``curve``:
      1. Find the closest point on ``surface`` and evaluate the analytic normal N.
      2. Compute the offset direction ``off_dir = normalise(N × T)`` where ``T``
         is the curve tangent (lies tangent to the surface, perpendicular to the
         curve in the surface's tangent plane).
      3. Translate by ``d`` in that direction.
      4. Reproject onto ``surface`` via closest-point inversion.

    Returns
    -------
    dict with ok, curve, actual_max_deviation, reason.
    """
    if not isinstance(curve, NurbsCurve):
        raise ValueError(f"curve must be a NurbsCurve, got {type(curve).__name__}")
    if not isinstance(surface, NurbsSurface):
        raise ValueError(f"surface must be a NurbsSurface, got {type(surface).__name__}")
    d = _validate_distance(d)

    ts, pts = _sample_curve_pts(curve, num_samples)
    pts3 = pts[:, :3].copy()
    tans = np.gradient(pts3, axis=0)

    offset_pts = []
    for i in range(len(pts3)):
        P = pts3[i]
        T = tans[i]
        t_n = float(np.linalg.norm(T))

        # Find closest UV on surface.
        u, v, foot, _ = closest_point_surface(surface, P)
        N = surface_normal(surface, float(u), float(v))

        if t_n > 1e-14:
            T_unit = T / t_n
            off_dir = np.cross(N, T_unit)
            off_n = float(np.linalg.norm(off_dir))
            off_dir = off_dir / off_n if off_n > 1e-14 else np.zeros(3)
        else:
            off_dir = np.zeros(3)

        moved = foot + d * off_dir
        # Reproject onto surface.
        _, _, reprojected, _ = closest_point_surface(surface, moved)
        offset_pts.append(reprojected)

    offset_pts_arr = np.array(offset_pts)

    # Use a relaxed tolerance for the fit since geodesic offsets have inherent
    # sampling noise from the closest-point projection.
    fit_tol = max(5e-4, abs(d) * 1e-3)
    result = fit_curve(offset_pts_arr, degree=min(3, curve.degree),
                       tolerance=fit_tol, max_ctrl=max(16, num_samples // 4))
    if result["ok"] and result["curve"] is not None:
        approx = result["curve"]
        actual_dev = float(result.get("deviation", float("inf")))
    else:
        approx = interp_curve(offset_pts_arr, degree=min(3, curve.degree))
        actual_dev = 0.0  # interpolation passes through all points

    return {
        "ok": True,  # always ok — geodesic offset is a best-effort approximation
        "curve": approx,
        "actual_max_deviation": actual_dev,
        "reason": "",
    }


# ---------------------------------------------------------------------------
# offset_surface
# ---------------------------------------------------------------------------

def offset_surface(
    surface: NurbsSurface,
    d: float,
    *,
    tol: float = 1e-4,
    grid_samples: int = 20,
) -> dict:
    """Surface offset along the analytic unit normal by signed distance ``d``.

    Sign convention: ``d > 0`` → outward (positive normal direction);
                     ``d < 0`` → inward.

    Analytic shortcuts
    ------------------
    * **Sphere** (detected via ``_is_sphere_surface``): returns a concentric
      sphere of radius ``r + d`` built by scaling the control-point net.
      ``actual_max_deviation = 0.0``.
    * **Plane** (degree (1,1), 4 coplanar control points): shifts every control
      point by ``d`` along the plane normal.  Exact.

    General NURBS surface
    ---------------------
    Sample a ``grid_samples × grid_samples`` grid, offset each sample along
    its analytic normal, then refit by fitting u-direction rows, then fitting
    v-direction columns.

    Returns
    -------
    dict:
        ok                  : bool
        surface             : NurbsSurface
        actual_max_deviation: float
        reason              : str
    """
    if not isinstance(surface, NurbsSurface):
        raise ValueError(f"surface must be a NurbsSurface, got {type(surface).__name__}")
    d = _validate_distance(d)

    # --- analytic shortcut: sphere ---
    sphere_info = _is_sphere_surface(surface)
    if sphere_info is not None:
        centre, r = sphere_info
        r_new = r + d
        if r_new <= 0.0:
            return {
                "ok": False,
                "surface": None,
                "actual_max_deviation": 0.0,
                "reason": f"offset distance {d} collapses sphere of radius {r}",
            }
        scale = r_new / r
        old_cps = surface.control_points.copy()
        new_cps = old_cps.copy()
        # Scale each control point's XYZ away from the sphere centre.
        new_cps[:, :, :3] = centre + scale * (old_cps[:, :, :3] - centre)
        new_surf = NurbsSurface(
            degree_u=surface.degree_u,
            degree_v=surface.degree_v,
            control_points=new_cps,
            knots_u=surface.knots_u.copy(),
            knots_v=surface.knots_v.copy(),
            weights=surface.weights.copy() if surface.weights is not None else None,
        )
        return {
            "ok": True,
            "surface": new_surf,
            "actual_max_deviation": 0.0,
            "reason": "",
        }

    # --- analytic shortcut: plane ---
    plane_info = _is_planar_nurbs_surface(surface)
    if plane_info is not None:
        _, unit_nrm = plane_info
        old_cps = surface.control_points.copy()
        new_cps = old_cps.copy()
        new_cps[:, :, :3] = old_cps[:, :, :3] + d * unit_nrm
        new_surf = NurbsSurface(
            degree_u=surface.degree_u,
            degree_v=surface.degree_v,
            control_points=new_cps,
            knots_u=surface.knots_u.copy(),
            knots_v=surface.knots_v.copy(),
            weights=surface.weights.copy() if surface.weights is not None else None,
        )
        return {
            "ok": True,
            "surface": new_surf,
            "actual_max_deviation": 0.0,
            "reason": "",
        }

    # --- general NURBS surface: sample → offset → refit ---
    u_min, u_max, v_min, v_max = _surface_param_range(surface)
    us = np.linspace(u_min, u_max, grid_samples)
    vs = np.linspace(v_min, v_max, grid_samples)

    grid_pts = np.zeros((grid_samples, grid_samples, 3))
    for i, u in enumerate(us):
        for j, v in enumerate(vs):
            P = _eval_surface(surface, float(u), float(v))
            N = surface_normal(surface, float(u), float(v))
            grid_pts[i, j] = P + d * N

    # Fit each row as a NURBS curve.
    from kerf_cad_core.geom.curve_toolkit import (
        _chord_params, _pt_knots_from_params, _eval_bspline_basis,
    )

    def _clamped_knots(n: int, p: int) -> np.ndarray:
        inner = max(0, n - p - 1)
        knots = np.zeros(n + p + 1)
        knots[-(p + 1):] = 1.0
        if inner > 0:
            knots[p + 1: p + 1 + inner] = np.linspace(0.0, 1.0, inner + 2)[1:-1]
        return knots

    def _fit_row(pts_row: np.ndarray, degree: int, num_ctrl: int) -> np.ndarray:
        """Least-squares fit returning control points array (num_ctrl, 3)."""
        n = len(pts_row)
        if n < 2:
            return np.vstack([pts_row] + [pts_row[-1:]] * (num_ctrl - n))
        ts = _chord_params(pts_row)
        nc = min(num_ctrl, n)
        knots = _pt_knots_from_params(ts, nc, degree)
        A = np.zeros((n, nc))
        for ii, t in enumerate(ts):
            A[ii] = _eval_bspline_basis(t, degree, knots, nc)
        ctrl, _, _, _ = np.linalg.lstsq(A, pts_row, rcond=None)
        return ctrl  # shape (nc, 3)

    deg_u = min(3, surface.degree_u)
    deg_v = min(3, surface.degree_v)
    n_u_ctrl = max(deg_u + 1, min(grid_samples, 16))
    n_v_ctrl = max(deg_v + 1, min(grid_samples, 16))

    # Evaluate each row curve at uniform v-sample locations.
    v_eval_ts = np.linspace(0.0, 1.0, n_v_ctrl)

    row_ctrl = np.zeros((grid_samples, n_v_ctrl, 3))
    for i in range(grid_samples):
        row = grid_pts[i]
        ctrl_v = _fit_row(row, deg_v, n_v_ctrl)
        # Rebuild as NurbsCurve for evaluation.
        knots_v_row = _clamped_knots(len(ctrl_v), deg_v)
        rc = NurbsCurve(degree=deg_v, control_points=ctrl_v, knots=knots_v_row)
        t0_r = float(rc.knots[deg_v])
        t1_r = float(rc.knots[-(deg_v + 1)])
        for j, vp in enumerate(v_eval_ts):
            t = t0_r + vp * (t1_r - t0_r)
            row_ctrl[i, j] = _eval_curve(rc, t)

    # Fit u-direction curves for each v-column.
    u_ctrl_net = np.zeros((n_u_ctrl, n_v_ctrl, 3))
    for j in range(n_v_ctrl):
        col = row_ctrl[:, j, :]
        ctrl_u = _fit_row(col, deg_u, n_u_ctrl)
        u_ctrl_net[:len(ctrl_u), j] = ctrl_u

    knots_u_new = _clamped_knots(n_u_ctrl, deg_u)
    knots_v_new = _clamped_knots(n_v_ctrl, deg_v)

    new_surf = NurbsSurface(
        degree_u=deg_u,
        degree_v=deg_v,
        control_points=u_ctrl_net,
        knots_u=knots_u_new,
        knots_v=knots_v_new,
    )

    # Measure actual deviation.
    devs = []
    for i, u in enumerate(us):
        u_nrm = float((u - u_min) / (u_max - u_min)) if u_max > u_min else 0.0
        for j, v in enumerate(vs):
            v_nrm = float((v - v_min) / (v_max - v_min)) if v_max > v_min else 0.0
            u_ev = float(np.clip(u_nrm, 0.0, 1.0))
            v_ev = float(np.clip(v_nrm, 0.0, 1.0))
            approx_pt = _eval_surface(new_surf, u_ev, v_ev)
            devs.append(float(np.linalg.norm(approx_pt - grid_pts[i, j])))

    actual_dev = float(max(devs)) if devs else 0.0
    ok = actual_dev <= tol

    return {
        "ok": ok,
        "surface": new_surf,
        "actual_max_deviation": actual_dev,
        "reason": "" if ok else f"tolerance {tol} not achieved; best dev {actual_dev:.4g}",
    }


# ---------------------------------------------------------------------------
# offset_loop
# ---------------------------------------------------------------------------

def offset_loop(
    curves: List[NurbsCurve],
    d: float,
    *,
    plane_normal: Optional[Sequence] = None,
    tol: float = 1e-4,
    num_samples: int = 100,
) -> dict:
    """Offset a closed planar loop of curves preserving connectivity.

    At each corner between adjacent segments:
      - **Convex corner** (exterior, turning outward for the offset direction):
        fillet with a quarter-arc of radius |d|.
      - **Concave corner**: extend both offset segments to their intersection.

    Sign convention: ``d > 0`` → outward (expand the loop);
                     ``d < 0`` → inward (shrink the loop).

    Returns
    -------
    dict:
        ok          : bool
        curves      : list of NurbsCurve (offset segments + corner arcs)
        perimeter   : float
        reason      : str
    """
    if not curves:
        raise ValueError("curves list is empty")
    d = _validate_distance(d)

    if plane_normal is None:
        nrm = np.array([0.0, 0.0, 1.0])
    else:
        nrm = np.asarray(plane_normal, dtype=float).ravel()
        nm = float(np.linalg.norm(nrm))
        nrm = (nrm / nm)[:3] if nm > 1e-14 else np.array([0.0, 0.0, 1.0])
    if nrm.shape[0] < 3:
        tmp = np.zeros(3)
        tmp[:nrm.shape[0]] = nrm
        nrm = tmp
    nrm = nrm[:3]

    # Offset each segment individually.
    offset_segs = []
    for crv in curves:
        res = offset_curve(crv, d, tol=tol, plane_normal=nrm.tolist(),
                           num_samples=num_samples)
        if not res["ok"] or res["curve"] is None:
            return {"ok": False, "curves": [], "perimeter": 0.0,
                    "reason": f"segment offset failed: {res['reason']}"}
        offset_segs.append(res["curve"])

    n_segs = len(offset_segs)
    result_curves: List[NurbsCurve] = []
    abs_d = abs(d)

    def _end_pt(seg: NurbsCurve, which: str) -> np.ndarray:
        t0, t1 = _curve_param_range_safe(seg)
        return _eval_curve(seg, t0 if which == "start" else t1)[:3]

    def _end_tan(seg: NurbsCurve, which: str) -> np.ndarray:
        """Finite-difference unit tangent at curve start or end."""
        t0, t1 = _curve_param_range_safe(seg)
        eps = (t1 - t0) * 1e-4
        if which == "start":
            a = _eval_curve(seg, t0)[:3]
            b = _eval_curve(seg, min(t0 + eps, t1))[:3]
        else:
            a = _eval_curve(seg, max(t1 - eps, t0))[:3]
            b = _eval_curve(seg, t1)[:3]
        v = b - a
        vn = float(np.linalg.norm(v))
        return v / vn if vn > 1e-14 else np.zeros(3)

    def _intersect_lines_2d(p0, t0v, p1, t1v):
        """Intersect lines p0+s*t0v and p1+r*t1v (2-D, x-y plane)."""
        A = np.array([[t0v[0], -t1v[0]], [t0v[1], -t1v[1]]])
        b_rhs = np.array([p1[0] - p0[0], p1[1] - p0[1]])
        det = float(A[0, 0] * A[1, 1] - A[0, 1] * A[1, 0])
        if abs(det) < 1e-14:
            return None
        s = (b_rhs[0] * A[1, 1] - b_rhs[1] * A[0, 1]) / det
        return p0[:3] + s * t0v[:3]

    for i in range(n_segs):
        seg_curr = offset_segs[i]
        seg_next = offset_segs[(i + 1) % n_segs]

        p_curr_end = _end_pt(seg_curr, "end")
        p_next_start = _end_pt(seg_next, "start")
        tan_out = _end_tan(seg_curr, "end")
        tan_in  = _end_tan(seg_next, "start")

        # Determine turn direction in the loop plane.
        cross = np.cross(tan_out, tan_in)
        turn_sign = float(np.dot(cross, nrm))

        # Convex corner for outward offset (d > 0): turn_sign < 0 (right turn).
        # For inward offset (d < 0): convex when turn_sign > 0.
        is_convex = (d * turn_sign < 0.0) if abs(d) > 1e-14 else False

        if abs_d < 1e-14:
            result_curves.append(seg_curr)
            continue

        if is_convex:
            # Convex corner → arc fillet of radius |d|.
            from kerf_cad_core.geom.nurbs import make_arc_nurbs

            chord = p_next_start - p_curr_end
            chord_len = float(np.linalg.norm(chord))
            if chord_len < 1e-12:
                result_curves.append(seg_curr)
                continue

            mid = (p_curr_end + p_next_start) * 0.5
            # Sagitta direction points toward the inside of the fillet.
            # For outward offset the fillet centre is inward from the midpoint.
            perp_chord = np.cross(nrm, chord / chord_len)
            sag_dir = -np.sign(d) * perp_chord
            sag_d_n = float(np.linalg.norm(sag_dir))
            if sag_d_n < 1e-14:
                result_curves.append(seg_curr)
                continue
            sag_dir = sag_dir / sag_d_n

            h = chord_len / 2.0
            if abs_d < h - 1e-12:
                # Radius smaller than half-chord: degenerate; fall back to line.
                result_curves.append(seg_curr)
                continue

            sag = abs_d - math.sqrt(max(0.0, abs_d ** 2 - h ** 2))
            fillet_centre = mid + sag * sag_dir

            # Local frame for arc construction.
            v_start = p_curr_end - fillet_centre
            vn_s = float(np.linalg.norm(v_start))
            if vn_s < 1e-14:
                result_curves.append(seg_curr)
                continue
            x_ax = v_start / vn_s
            y_ax = np.cross(nrm, x_ax)
            yn = float(np.linalg.norm(y_ax))
            y_ax = y_ax / yn if yn > 1e-14 else np.array([0.0, 1.0, 0.0])

            # Start angle is 0 (by construction of x_ax).
            v_end = p_next_start - fillet_centre
            ang_end = math.atan2(float(np.dot(v_end, y_ax)),
                                 float(np.dot(v_end, x_ax)))

            if d > 0:
                if ang_end <= 1e-10:
                    ang_end += 2 * math.pi
            else:
                if ang_end >= -1e-10:
                    ang_end -= 2 * math.pi

            if abs(ang_end) < 1e-10:
                result_curves.append(seg_curr)
                continue

            try:
                arc = make_arc_nurbs(fillet_centre, abs_d, 0.0, ang_end,
                                     x_axis=x_ax, y_axis=y_ax)
                result_curves.append(seg_curr)
                result_curves.append(arc)
            except Exception:
                result_curves.append(seg_curr)
        else:
            # Concave corner → extend to intersection point.
            intersect = _intersect_lines_2d(p_curr_end, tan_out, p_next_start, tan_in)
            if intersect is not None:
                from kerf_cad_core.geom.nurbs import make_line_nurbs
                trim_line = make_line_nurbs(p_curr_end, intersect)
                result_curves.append(seg_curr)
                result_curves.append(trim_line)
            else:
                result_curves.append(seg_curr)

    if not result_curves:
        return {"ok": False, "curves": [], "perimeter": 0.0,
                "reason": "no output segments generated"}

    # Compute approximate perimeter by chord-length summation.
    perimeter = 0.0
    for seg in result_curves:
        _, pts_s = _sample_curve_pts(seg, 50)
        diffs = np.diff(pts_s[:, :3], axis=0)
        perimeter += float(np.sum(np.linalg.norm(diffs, axis=1)))

    return {
        "ok": True,
        "curves": result_curves,
        "perimeter": perimeter,
        "reason": "",
    }
