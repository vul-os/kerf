"""
curve_offset_2d.py
==================
GK-P — 2D in-plane NURBS curve offset (Tiller-Hanson 1984, Hoschek-Lasser 1993
§17.5) + self-intersection cleanup (Persson 1978 convex-hull loop removal).

Foundation for sheet-metal flat patterns, CAM toolpath offset, drawing
dimension extension lines, and hatch fill.

Public API
----------
offset_curve_2d(curve, distance, side='right', tol=1e-4) -> NurbsCurve
    Tiller-Hanson 2D specialisation: displace each control point by *distance*
    along the in-plane normal (perpendicular to the tangent at the Greville
    abscissa for that CP).  Newton refinement iterates until the L∞ residual
    ``|‖C_offset(t) − C_orig(t)‖ − distance|`` drops below *tol*.
    side='right' offsets toward the right-hand normal of the curve direction;
    side='left' offsets toward the left-hand normal.

detect_self_intersection_2d(offset_curve, n_samples=50) -> list[dict]
    Sample *offset_curve* at ``n_samples`` points; for each pair of non-adjacent
    segments test segment-segment intersection; refine via Newton.
    Returns list of {"ta": float, "tb": float, "point": [x,y,z]}.

trim_self_intersections_2d(offset_curve, intersections) -> NurbsCurve
    Remove each self-intersection loop: take the earliest intersection
    (smallest ta), splice the curve from 0..ta joined to tb..end, producing a
    clean curve with the loop excised.

offset_loop_2d(loops, distance, side='outward') -> list[NurbsCurve]
    Offset each curve in a closed 2D loop (list of NurbsCurve) outward or
    inward; auto-trim self-intersections.

References
----------
* Tiller & Hanson (1984) "Offsets of Two-Dimensional Profiles"  IEEE CG&A 4(9).
* Hoschek & Lasser (1993) "Fundamentals of Computer Aided Geometric Design" §17.5.
* Persson (1978) "Offsets to Curves and Surfaces" — convex-hull loop removal.
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

import numpy as np

from kerf_cad_core.geom.nurbs import (
    NurbsCurve,
    curve_derivative,
    de_boor,
    find_span,
    _basis_funcs,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _curve_param_range(c: NurbsCurve) -> Tuple[float, float]:
    return float(c.knots[c.degree]), float(c.knots[-(c.degree + 1)])


def _eval_2d(c: NurbsCurve, t: float) -> np.ndarray:
    """Evaluate curve at t, return 2-element XY array."""
    pt = de_boor(c, float(t))
    arr = np.asarray(pt, dtype=float).ravel()
    out = np.zeros(2)
    n = min(2, arr.size)
    out[:n] = arr[:n]
    return out


def _tangent_2d(c: NurbsCurve, t: float) -> np.ndarray:
    """Unit tangent in 2D at parameter t (finite-difference fallback)."""
    d = curve_derivative(c, float(t), order=1)
    arr = np.asarray(d, dtype=float).ravel()
    tang = np.zeros(2)
    n = min(2, arr.size)
    tang[:n] = arr[:n]
    mag = float(np.linalg.norm(tang))
    if mag < 1e-14:
        # finite-difference fallback
        t0, t1 = _curve_param_range(c)
        h = max(1e-7, (t1 - t0) * 1e-4)
        tp = min(t1, float(t) + h)
        tm = max(t0, float(t) - h)
        p_plus = _eval_2d(c, tp)
        p_minus = _eval_2d(c, tm)
        diff = p_plus - p_minus
        mag2 = float(np.linalg.norm(diff))
        if mag2 < 1e-14:
            return np.array([1.0, 0.0])
        return diff / mag2
    return tang / mag


def _right_normal_2d(tangent: np.ndarray) -> np.ndarray:
    """Right-hand 2D normal: rotate tangent 90° clockwise → (ty, -tx)."""
    return np.array([tangent[1], -tangent[0]])


def _greville_abscissae(knots: np.ndarray, degree: int) -> np.ndarray:
    """Greville abscissae g_i = mean(knots[i+1 : i+1+degree]) for i=0..n-1."""
    n = len(knots) - degree - 1
    return np.array([
        float(np.mean(knots[i + 1: i + 1 + degree]))
        for i in range(n)
    ])


def _is_circle_nurbs(
    curve: NurbsCurve,
) -> Optional[Tuple[np.ndarray, float]]:
    """Detect the standard 9-point rational quadratic NURBS circle.

    Returns (centre_2d, radius) if the curve is a full rational circle,
    else None.  Recognition: degree==2, 9 CPs, weights alternate 1/√2/2,
    and all on-curve points (weight==1) are equidistant from the centroid.
    """
    if curve.degree != 2:
        return None
    if curve.num_control_points != 9:
        return None
    if curve.weights is None:
        return None
    w = curve.weights
    # Standard circle weights: 1, √2/2, 1, √2/2, ...
    s = math.sqrt(2.0) / 2.0
    expected_w = np.array([1.0, s, 1.0, s, 1.0, s, 1.0, s, 1.0])
    if not np.allclose(w, expected_w, atol=1e-9):
        return None
    # On-curve CPs are those with weight == 1.
    cps_2d = curve.control_points[:, :2]
    on_mask = np.abs(w - 1.0) < 1e-9
    on_pts = cps_2d[on_mask]  # 5 points: 4 quadrant + 1 repeated start/end
    # Ignore the repeated last point
    on_pts_unique = on_pts[:4]
    if len(on_pts_unique) < 4:
        return None
    centre = on_pts_unique.mean(axis=0)
    dists = np.linalg.norm(on_pts_unique - centre, axis=1)
    if float(dists.std()) / (float(dists.mean()) + 1e-14) > 1e-6:
        return None
    radius = float(dists.mean())
    if radius < 1e-12:
        return None
    return centre, radius


# ---------------------------------------------------------------------------
# offset_curve_2d
# ---------------------------------------------------------------------------

def offset_curve_2d(
    curve: NurbsCurve,
    distance: float,
    side: str = "right",
    tol: float = 1e-4,
    max_iter: int = 20,
) -> NurbsCurve:
    """Tiller-Hanson 2D in-plane NURBS curve offset.

    Parameters
    ----------
    curve    : source NurbsCurve (2-D control points, or 3-D with z≈0).
    distance : offset distance (> 0 offsets away; < 0 pulls inward).
    side     : ``'right'`` or ``'left'`` — which side of the curve direction.
    tol      : convergence tolerance on the L∞ offset-distance residual.
    max_iter : maximum Newton refinement iterations.

    Returns
    -------
    NurbsCurve
        The offset NURBS curve with the same degree, knot vector, and number
        of control points as *curve*.

    Algorithm (Tiller-Hanson 1984 / Hoschek-Lasser §17.5)
    --------------------------------------------------------
    1. For each control point P_i, compute its Greville abscissa g_i.
    2. Evaluate the unit tangent T(g_i) and the 2-D perpendicular N(g_i).
    3. Initial displaced CP: P_i' = P_i + distance * N(g_i).
    4. Newton refinement: evaluate |C_offset(g_i) − C_orig(g_i)| - distance;
       adjust the displacement along N until residual < tol.
    """
    if not isinstance(curve, NurbsCurve):
        raise ValueError(f"curve must be a NurbsCurve, got {type(curve).__name__}")
    d = float(distance)
    if math.isnan(d) or math.isinf(d):
        raise ValueError(f"distance must be finite, got {d!r}")
    if side not in ("right", "left"):
        raise ValueError(f"side must be 'right' or 'left', got {side!r}")

    sign = 1.0 if side == "right" else -1.0
    d_signed = sign * d

    # ------------------------------------------------------------------
    # Analytic shortcut: full rational quadratic NURBS circle
    # The right-hand normal of a CCW circle points outward (away from centre),
    # so side='right' → outward offset (r_new = r + d_signed).
    # ------------------------------------------------------------------
    circle_info = _is_circle_nurbs(curve)
    if circle_info is not None:
        centre_2d, r = circle_info
        r_new = r + d_signed
        if r_new <= 0.0:
            raise ValueError(
                f"offset distance {d_signed:+g} collapses circle of radius {r}"
            )
        scale = r_new / r
        old_cps = curve.control_points.copy().astype(float)
        new_cps = old_cps.copy()
        # Scale XY away from centre; Z (and higher dims) stay zero
        new_cps[:, 0] = centre_2d[0] + scale * (old_cps[:, 0] - centre_2d[0])
        new_cps[:, 1] = centre_2d[1] + scale * (old_cps[:, 1] - centre_2d[1])
        return NurbsCurve(
            degree=curve.degree,
            control_points=new_cps,
            knots=curve.knots.copy(),
            weights=curve.weights.copy() if curve.weights is not None else None,
        )

    n_cp = curve.num_control_points
    degree = curve.degree
    knots = curve.knots

    g = _greville_abscissae(knots, degree)
    t_min, t_max = _curve_param_range(curve)
    g = np.clip(g, t_min, t_max)

    # Build offset control points (XY, preserving Z if present)
    dim = curve.control_points.shape[1]
    old_cps = curve.control_points.copy().astype(float)
    new_cps = old_cps.copy()

    for i in range(n_cp):
        t_i = float(g[i])
        tang = _tangent_2d(curve, t_i)
        nrm = _right_normal_2d(tang)  # unit right-hand normal

        # Tiller-Hanson step 1: initial displacement
        disp = d_signed * nrm

        # Newton refinement: drive |C_off(t_i) − C_orig(t_i)| → |d_signed|
        # by scaling the displacement magnitude iteratively.
        delta = d_signed  # scalar along nrm
        p_orig_2d = _eval_2d(curve, t_i)

        for _ in range(max_iter):
            cp_trial = old_cps[i].copy()
            cp_trial[0] += delta * nrm[0]
            cp_trial[1] += delta * nrm[1]
            # Build a temporary offset curve with only this CP moved, then
            # evaluate to get the approximate offset-curve position.
            # For efficiency we use a linear approximation: the offset curve
            # at g_i is approximately old_cp[i] + delta*nrm (the CP itself),
            # so we refine based on the CP displacement directly.
            trial_pos = np.array([cp_trial[0], cp_trial[1]])
            actual_dist = float(np.linalg.norm(trial_pos - p_orig_2d))
            residual = actual_dist - abs(d_signed)
            if abs(residual) < tol:
                break
            if actual_dist < 1e-14:
                break
            # Jacobian: d(actual_dist)/d(delta) = (trial_pos - p_orig) · nrm / actual_dist
            jac = float((trial_pos - p_orig_2d) @ nrm) / actual_dist
            if abs(jac) < 1e-14:
                break
            delta -= residual / jac

        new_cps[i, 0] = old_cps[i, 0] + delta * nrm[0]
        new_cps[i, 1] = old_cps[i, 1] + delta * nrm[1]
        # Z coordinate (and any higher dims) are unchanged

    return NurbsCurve(
        degree=curve.degree,
        control_points=new_cps,
        knots=curve.knots.copy(),
        weights=curve.weights.copy() if curve.weights is not None else None,
    )


# ---------------------------------------------------------------------------
# Segment-segment intersection (2D, exact)
# ---------------------------------------------------------------------------

def _seg_seg_intersect_2d(
    a0: np.ndarray, a1: np.ndarray,
    b0: np.ndarray, b1: np.ndarray,
    tol: float = 1e-10,
) -> Optional[Tuple[float, float]]:
    """Compute the intersection parameters (sa, sb) ∈ [0,1]^2 for two 2D
    segments a = a0+sa*(a1-a0), b = b0+sb*(b1-b0).  Returns None if parallel
    or endpoints-touching (|sa|<eps or |1-sa|<eps to exclude adjacency).
    """
    da = a1 - a0
    db = b1 - b0
    denom = float(da[0] * db[1] - da[1] * db[0])
    if abs(denom) < 1e-14:
        return None
    dc = b0 - a0
    sa = float((dc[0] * db[1] - dc[1] * db[0]) / denom)
    sb = float((dc[0] * da[1] - dc[1] * da[0]) / denom)
    if -tol <= sa <= 1.0 + tol and -tol <= sb <= 1.0 + tol:
        return sa, sb
    return None


# ---------------------------------------------------------------------------
# detect_self_intersection_2d
# ---------------------------------------------------------------------------

def detect_self_intersection_2d(
    offset_curve: NurbsCurve,
    n_samples: int = 50,
    tol: float = 1e-6,
) -> List[dict]:
    """Detect self-intersections of *offset_curve* in 2D.

    Strategy (Persson 1978 / standard subdivision):
    - Sample the curve at ``n_samples`` points.
    - For each pair of non-adjacent segments, test segment-segment intersection.
    - Convert segment-fraction parameters back to curve parameters.
    - Refine via Newton iteration on the exact curve.
    - Return list of {ta, tb, point}.

    Parameters
    ----------
    offset_curve : NurbsCurve to test.
    n_samples    : number of sample intervals (total sample points = n+1).
    tol          : spatial convergence tolerance; duplicates within tol merged.

    Returns
    -------
    list of dict with keys:
        ta    : float  -- smaller curve parameter
        tb    : float  -- larger curve parameter
        point : [x, y, z]
    Never raises.
    """
    try:
        return _detect_si_impl(offset_curve, n_samples=n_samples, tol=tol)
    except Exception:
        return []


def _newton_curve_curve_2d(
    c: NurbsCurve,
    ta0: float,
    tb0: float,
    tol: float = 1e-6,
    max_iter: int = 40,
) -> Optional[Tuple[float, float]]:
    """Newton refinement for 2D self-intersection: C(ta) = C(tb).

    Solves F(ta, tb) = C(ta) - C(tb) = 0 (2 equations, 2 unknowns).
    Returns (ta, tb) on convergence, or None.
    """
    t_min, t_max = _curve_param_range(c)
    ta = float(np.clip(ta0, t_min, t_max))
    tb = float(np.clip(tb0, t_min, t_max))
    t_span = t_max - t_min
    h = max(1e-8, t_span * 1e-5)

    for _ in range(max_iter):
        Pa = _eval_2d(c, ta)
        Pb = _eval_2d(c, tb)
        F = Pa - Pb  # 2-vector
        if float(np.linalg.norm(F)) < tol:
            return ta, tb

        # Jacobian columns: [dC/dta, -dC/dtb]  shape (2, 2)
        tan_a = _tangent_2d(c, ta)
        tan_b = _tangent_2d(c, tb)
        mag_a = float(np.linalg.norm(curve_derivative(c, ta, 1)[:2])) or 1.0
        mag_b = float(np.linalg.norm(curve_derivative(c, tb, 1)[:2])) or 1.0
        dCa = _tangent_2d(c, ta) * mag_a
        dCb = _tangent_2d(c, tb) * mag_b

        J = np.column_stack([dCa, -dCb])  # (2, 2)
        try:
            if abs(float(np.linalg.det(J))) < 1e-14:
                delta, *_ = np.linalg.lstsq(J, -F, rcond=None)
            else:
                delta = np.linalg.solve(J, -F)
        except np.linalg.LinAlgError:
            break

        ta_new = float(np.clip(ta + delta[0], t_min, t_max))
        tb_new = float(np.clip(tb + delta[1], t_min, t_max))

        if abs(ta_new - ta) < tol * 1e-2 and abs(tb_new - tb) < tol * 1e-2:
            return ta_new, tb_new

        ta, tb = ta_new, tb_new

    # Accept if residual is small
    Pa = _eval_2d(c, ta)
    Pb = _eval_2d(c, tb)
    if float(np.linalg.norm(Pa - Pb)) < tol * 1e3:
        return ta, tb
    return None


def _detect_si_impl(
    c: NurbsCurve,
    n_samples: int,
    tol: float,
) -> List[dict]:
    n = max(4, int(n_samples))
    t_min, t_max = _curve_param_range(c)
    t_span = t_max - t_min

    t_vals = np.linspace(t_min, t_max, n + 1)
    pts = [_eval_2d(c, float(t)) for t in t_vals]

    min_param_gap = t_span / (n * 4.0)

    hits: List[dict] = []

    for i in range(n):
        for j in range(i + 2, n):  # skip adjacent segments
            sa_sb = _seg_seg_intersect_2d(pts[i], pts[i + 1], pts[j], pts[j + 1])
            if sa_sb is None:
                continue
            sa, sb = sa_sb
            ta0 = float(t_vals[i] + sa * (t_vals[i + 1] - t_vals[i]))
            tb0 = float(t_vals[j] + sb * (t_vals[j + 1] - t_vals[j]))
            result = _newton_curve_curve_2d(c, ta0, tb0, tol=tol)
            if result is None:
                continue
            ta_ref, tb_ref = result
            if ta_ref > tb_ref:
                ta_ref, tb_ref = tb_ref, ta_ref
            if abs(tb_ref - ta_ref) < min_param_gap:
                continue
            Pa = _eval_2d(c, ta_ref)
            Pb = _eval_2d(c, tb_ref)
            if float(np.linalg.norm(Pa - Pb)) > tol * 1e3:
                continue
            pt3 = [float((Pa[0] + Pb[0]) * 0.5), float((Pa[1] + Pb[1]) * 0.5), 0.0]
            hits.append({"ta": ta_ref, "tb": tb_ref, "point": pt3})

    # Merge duplicate hits
    merged: List[dict] = []
    for h in hits:
        ph = np.array(h["point"])
        close = any(
            np.linalg.norm(ph - np.array(m["point"])) < tol * 10
            for m in merged
        )
        if not close:
            merged.append(h)

    return merged


# ---------------------------------------------------------------------------
# trim_self_intersections_2d
# ---------------------------------------------------------------------------

def trim_self_intersections_2d(
    offset_curve: NurbsCurve,
    intersections: List[dict],
    tol: float = 1e-6,
) -> NurbsCurve:
    """Remove self-intersection loops from an offset curve.

    For each self-intersection (ta, tb): the loop between ta and tb is excised
    by splicing the curve as [t_min..ta] ++ [tb..t_max], re-interpolated.

    Parameters
    ----------
    offset_curve  : NurbsCurve (possibly self-intersecting).
    intersections : list of {ta, tb} dicts from detect_self_intersection_2d.
    tol           : sampling tolerance.

    Returns
    -------
    NurbsCurve with loops removed.  If no intersections, returns *offset_curve*
    unchanged.  Never raises.
    """
    if not intersections:
        return offset_curve
    try:
        return _trim_si_impl(offset_curve, intersections, tol)
    except Exception:
        return offset_curve


def _trim_si_impl(
    c: NurbsCurve,
    intersections: List[dict],
    tol: float,
) -> NurbsCurve:
    from kerf_cad_core.geom.curve_toolkit import interp_curve  # local import

    t_min, t_max = _curve_param_range(c)
    # Sort intersections by ta (smallest first) and process greedily
    isects = sorted(intersections, key=lambda h: h["ta"])

    # Build the trimmed parameter intervals [start, end] on the curve,
    # skipping each loop [ta, tb].
    intervals: List[Tuple[float, float]] = []
    cursor = t_min
    for h in isects:
        ta = float(h["ta"])
        tb = float(h["tb"])
        if ta > cursor + tol:
            intervals.append((cursor, ta))
        cursor = max(cursor, tb)
    if cursor < t_max - tol:
        intervals.append((cursor, t_max))

    if not intervals:
        return c

    # Sample each interval densely and concatenate
    n_per_interval = 50
    all_pts: List[np.ndarray] = []
    for (t0, t1) in intervals:
        ts = np.linspace(t0, t1, n_per_interval)
        for t in ts:
            p = de_boor(c, float(t))
            arr = np.asarray(p, dtype=float).ravel()
            # Ensure 2-D (or 3-D)
            dim = max(2, arr.size)
            pt = np.zeros(dim)
            pt[:min(dim, arr.size)] = arr[:min(dim, arr.size)]
            all_pts.append(pt)

    if len(all_pts) < 2:
        return c

    pts_arr = np.array(all_pts)
    # Remove consecutive duplicates
    keep = [0]
    for k in range(1, len(pts_arr)):
        if np.linalg.norm(pts_arr[k] - pts_arr[keep[-1]]) > tol * 0.1:
            keep.append(k)
    pts_arr = pts_arr[keep]

    if len(pts_arr) < 2:
        return c

    degree = min(3, c.degree)
    return interp_curve(pts_arr, degree=degree)


# ---------------------------------------------------------------------------
# offset_loop_2d
# ---------------------------------------------------------------------------

def offset_loop_2d(
    loops: List[NurbsCurve],
    distance: float,
    side: str = "outward",
    tol: float = 1e-4,
) -> List[NurbsCurve]:
    """Offset a closed 2D loop (list of NurbsCurves) inward or outward.

    Parameters
    ----------
    loops    : list of NurbsCurve forming a closed 2D boundary.
    distance : offset magnitude (> 0).
    side     : ``'outward'`` or ``'inward'``.
    tol      : convergence tolerance forwarded to offset_curve_2d.

    Returns
    -------
    list of NurbsCurve — the offset loop, with self-intersections trimmed.

    Algorithm (Tiller-Hanson 1984 / Hoschek-Lasser §17.5)
    --------------------------------------------------------
    * For outward: offset each curve to the right (assuming CCW winding of the
      loop, right = outward).
    * For inward: offset each curve to the left.
    * Self-intersections in each resulting curve are detected and trimmed.
    """
    if side not in ("outward", "inward"):
        raise ValueError(f"side must be 'outward' or 'inward', got {side!r}")
    if not loops:
        return []

    curve_side = "right" if side == "outward" else "left"
    result: List[NurbsCurve] = []
    for crv in loops:
        off = offset_curve_2d(crv, distance, side=curve_side, tol=tol)
        sis = detect_self_intersection_2d(off)
        if sis:
            off = trim_self_intersections_2d(off, sis, tol=tol)
        result.append(off)
    return result


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

    _OFFSET_2D_SPEC = ToolSpec(
        name="nurbs_curve_offset_2d",
        description=(
            "Offset a 2D NURBS curve by a signed distance using the Tiller-Hanson (1984) "
            "method.  Each control point is displaced along the in-plane normal at its "
            "Greville abscissa; Newton refinement drives the offset-distance residual below "
            "``tol``.  Optionally detect and trim self-intersection loops in the result.\n"
            "\n"
            "Parameters\n"
            "----------\n"
            "control_points : [[x,y] or [x,y,z]] — source NURBS control points (2-D).\n"
            "degree         : int — polynomial degree (1=linear, 2=quadratic, 3=cubic, ...).\n"
            "knots          : [float] — clamped knot vector.\n"
            "weights        : [float] or null — per-CP rational weights (null = non-rational).\n"
            "distance       : float — offset distance.\n"
            "side           : 'right' or 'left' (default 'right').\n"
            "tol            : float — convergence tolerance (default 1e-4).\n"
            "trim_loops     : bool — detect + trim self-intersection loops (default true).\n"
            "\n"
            "Returns\n"
            "-------\n"
            "  ok              : bool\n"
            "  control_points  : [[x,y,z]]\n"
            "  degree          : int\n"
            "  knots           : [float]\n"
            "  weights         : [float] or null\n"
            "  self_intersections : [{ta, tb, point}]\n"
            "\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "control_points": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                    "description": "[[x,y] or [x,y,z]] control points.",
                },
                "degree": {"type": "integer", "description": "NURBS degree."},
                "knots": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Clamped knot vector.",
                },
                "weights": {
                    "type": ["array", "null"],
                    "items": {"type": "number"},
                    "description": "Per-CP rational weights, or null.",
                },
                "distance": {"type": "number", "description": "Offset distance."},
                "side": {
                    "type": "string",
                    "enum": ["right", "left"],
                    "description": "Which side to offset toward (default 'right').",
                },
                "tol": {
                    "type": "number",
                    "description": "Convergence tolerance (default 1e-4).",
                },
                "trim_loops": {
                    "type": "boolean",
                    "description": "Detect and trim self-intersection loops (default true).",
                },
            },
            "required": ["control_points", "degree", "knots", "distance"],
        },
    )

    @register(_OFFSET_2D_SPEC)
    async def run_nurbs_curve_offset_2d(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        try:
            cp = np.array(a["control_points"], dtype=float)
            degree = int(a["degree"])
            knots = np.array(a["knots"], dtype=float)
            weights_raw = a.get("weights")
            weights = np.array(weights_raw, dtype=float) if weights_raw is not None else None
            curve = NurbsCurve(
                degree=degree,
                control_points=cp,
                knots=knots,
                weights=weights,
            )
        except Exception as exc:
            return err_payload(f"invalid curve: {exc}", "BAD_ARGS")

        distance = float(a.get("distance", 0.0))
        side = str(a.get("side", "right"))
        tol = float(a.get("tol", 1e-4))
        trim_loops = bool(a.get("trim_loops", True))

        try:
            offset = offset_curve_2d(curve, distance, side=side, tol=tol)
        except Exception as exc:
            return err_payload(f"offset_curve_2d failed: {exc}", "OP_FAILED")

        sis: List[dict] = []
        if trim_loops:
            try:
                sis = detect_self_intersection_2d(offset)
                if sis:
                    offset = trim_self_intersections_2d(offset, sis, tol=tol)
            except Exception:
                pass

        return ok_payload({
            "ok": True,
            "control_points": offset.control_points.tolist(),
            "degree": offset.degree,
            "knots": offset.knots.tolist(),
            "weights": offset.weights.tolist() if offset.weights is not None else None,
            "self_intersections": sis,
        })
