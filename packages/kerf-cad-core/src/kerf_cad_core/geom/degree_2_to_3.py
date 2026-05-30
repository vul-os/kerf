"""
degree_2_to_3.py
================
Specialised quadratic → cubic NURBS degree elevation.

Piegl-Tiller §5.5 specialisation: promote a degree-2 B-spline to degree-3
**without any geometric change**.  The general ``_elevate_curve_bspline`` path
in ``nurbs.py`` already handles this correctly; this module provides
semantically-named public entry-points and the body-level normalization pass
used during STEP import.

Background
----------
The standard quadratic-Bezier-segment → cubic-Bezier-segment formula
(Piegl & Tiller §5.5; Lyche-Mørken 1988) is:

  Q_0 = P_0
  Q_1 = P_0/3 + (2/3)*P_1
  Q_2 = (2/3)*P_1 + P_2/3
  Q_3 = P_2

This is an *exact* shape-preserving lift: evaluating the cubic at any t gives
the same 3-D point as evaluating the quadratic at the same t.  The derivation
follows from the Bezier degree-elevation recurrence

  Q_i = (i/(n+1))*P_{i-1} + (1 - i/(n+1))*P_i

applied once (n=2, so n+1=3) which collapses to the closed-form above.

The module applies this segment-by-segment across a full B-spline by:
  1. Decomposing the B-spline into Bezier segments (full knot-insertion to
     achieve multiplicity == degree at every interior breakpoint).
  2. Elevating each Bezier segment.
  3. Reassembling into a clamped B-spline with shared (averaged) boundary
     control points and a degree-3 knot vector.

For rational (weighted) NURBS the elevation is performed in the homogeneous
space ``(w·P_x, w·P_y, w·P_z, w)`` and projected back — this is the
standard and correct approach.

References
----------
* Piegl, L. & Tiller, W. (1997). *The NURBS Book*, 2nd ed., §5.5.
* Lyche, T. & Mørken, K. (1988). "Making the Oslo algorithm more efficient."
  SIAM J. Numer. Anal., 25(6), 1580–1592.
"""

from __future__ import annotations

import copy
import math
from typing import Optional

import numpy as np

from kerf_cad_core.geom.nurbs import (
    NurbsCurve,
    NurbsSurface,
    _decompose_to_bezier,
    _elevate_curve_bspline,
)


# ---------------------------------------------------------------------------
# Core: Bezier segment elevation 2 → 3
# ---------------------------------------------------------------------------


def _elevate_bezier_quad_to_cubic(P: np.ndarray) -> np.ndarray:
    """Exact lift of a single quadratic Bezier segment to cubic.

    Parameters
    ----------
    P : (3, d) float array
        Quadratic Bezier control points.

    Returns
    -------
    Q : (4, d) float array
        Cubic Bezier control points representing the identical geometry.

    Algorithm (Piegl-Tiller §5.5, specialised to n=2):
        Q_0 = P_0
        Q_1 = P_0/3 + (2/3)*P_1
        Q_2 = (2/3)*P_1 + P_2/3
        Q_3 = P_2
    """
    if P.shape[0] != 3:
        raise ValueError(f"Expected 3 control points (quadratic), got {P.shape[0]}")
    Q = np.empty((4, P.shape[1]), dtype=float)
    Q[0] = P[0].copy()
    Q[1] = P[0] / 3.0 + (2.0 / 3.0) * P[1]
    Q[2] = (2.0 / 3.0) * P[1] + P[2] / 3.0
    Q[3] = P[2].copy()
    return Q


# ---------------------------------------------------------------------------
# Curve elevation: quadratic B-spline → cubic B-spline
# ---------------------------------------------------------------------------


def elevate_quadratic_to_cubic_curve(curve: NurbsCurve) -> NurbsCurve:
    """Promote a degree-2 NURBS curve to degree-3 with identical geometry.

    For curves that are already degree >= 3 this is a no-op (the original
    curve is returned unchanged).  For degree-2 inputs the exact Piegl-Tiller
    §5.5 Bezier-segment specialisation is used:

    * Each quadratic Bezier segment is lifted to cubic using the exact
      formula (no approximation, no geometric change).
    * Segments are re-merged into a single B-spline by sharing boundary
      control points (averaged at each interior knot).
    * Rational (weighted) curves are handled in homogeneous space.

    Parameters
    ----------
    curve : NurbsCurve
        Input curve.  Must have ``degree == 2``.

    Returns
    -------
    NurbsCurve
        New curve with ``degree == 3`` and identical evaluation.

    Raises
    ------
    ValueError
        If ``curve.degree != 2`` and the input is not already cubic or higher.
    """
    if curve.degree > 2:
        return curve
    if curve.degree < 2:
        raise ValueError(
            f"elevate_quadratic_to_cubic_curve requires degree-2 input, "
            f"got degree {curve.degree}"
        )

    # Delegate to the general (correct) Bezier-based elevation in nurbs.py.
    # _elevate_curve_bspline handles both rational and non-rational, uses
    # _decompose_to_bezier + _bezier_degree_elevate_once, exactly the same
    # algorithm as our specialised path but already battle-tested.
    #
    # We additionally provide the direct specialised path as the primary
    # implementation for clarity and to ensure the closed-form formula
    # (Q1 = P0/3 + 2/3*P1, Q2 = 2/3*P1 + P2/3) is exercised.

    p = curve.degree  # == 2
    P = curve.control_points.copy().astype(float)
    U = curve.knots.copy().astype(float)
    W = curve.weights

    # Work in homogeneous space when rational.
    if W is not None:
        Pw = np.column_stack([P * W[:, None], W])
    else:
        Pw = P.copy()

    # Decompose into Bezier segments (raises all interior knots to mult=p).
    segs = _decompose_to_bezier(Pw, U, p)
    if not segs:
        # Fallback: defer to general path.
        return _elevate_curve_bspline(curve, times=1)

    # Elevate each segment using the closed-form quadratic→cubic formula.
    elevated_segs = []
    for seg_Pw, u_lo, u_hi in segs:
        if seg_Pw.shape[0] != 3:
            # Unexpected — fall back to general path.
            return _elevate_curve_bspline(curve, times=1)
        elevated_segs.append((_elevate_bezier_quad_to_cubic(seg_Pw), u_lo, u_hi))

    new_p = 3  # target degree

    # Merge segments: adjacent segments share one endpoint — average them.
    merged = [row.copy() for row in elevated_segs[0][0]]
    for k in range(1, len(elevated_segs)):
        seg_e, u_lo, u_hi = elevated_segs[k]
        # Average shared boundary.
        prev_last = merged[-1].copy()
        cur_first = seg_e[0].copy()
        merged[-1] = 0.5 * (prev_last + cur_first)
        merged.extend([row.copy() for row in seg_e[1:]])
    Pw_new = np.array(merged, dtype=float)

    # Build degree-3 clamped knot vector.
    # For n_segs segments of degree 3: n_cp = n_segs*3 + 1 interior CPs
    # Knot vector: p+1 = 4 copies at each end, p = 3 copies at each interior
    # breakpoint.
    breakpoints = [segs[0][1]] + [u_hi for _, _, u_hi in segs]
    new_U_list = [breakpoints[0]] * (new_p + 1)
    for bp in breakpoints[1:-1]:
        new_U_list.extend([bp] * new_p)
    new_U_list.extend([breakpoints[-1]] * (new_p + 1))
    new_U = np.array(new_U_list, dtype=float)

    # Validate / repair knot length.
    expected_len = len(Pw_new) + new_p + 1
    if len(new_U) != expected_len:
        n_int = len(Pw_new) - new_p - 1
        a, b = float(U[0]), float(U[-1])
        interior = (
            np.linspace(a, b, n_int + 2)[1:-1] if n_int > 0 else np.array([])
        )
        new_U = np.concatenate([
            np.full(new_p + 1, a),
            interior,
            np.full(new_p + 1, b),
        ])

    # Convert back from homogeneous.
    if W is not None:
        new_W = Pw_new[:, -1].copy()
        new_P_cart = np.where(
            new_W[:, None] > 1e-14,
            Pw_new[:, :-1] / new_W[:, None],
            Pw_new[:, :-1],
        )
        return NurbsCurve(degree=new_p, control_points=new_P_cart,
                          knots=new_U, weights=new_W)
    return NurbsCurve(degree=new_p, control_points=Pw_new, knots=new_U)


# ---------------------------------------------------------------------------
# Surface elevation: quadratic NURBS surface → cubic
# ---------------------------------------------------------------------------


def elevate_quadratic_to_cubic_surface(surface: NurbsSurface) -> NurbsSurface:
    """Promote a degree-2 NURBS surface to degree-3 in both parametric directions.

    Applied in sequence: first elevate in U, then in V.  Either direction is
    skipped if the surface is already degree >= 3 in that direction.

    Parameters
    ----------
    surface : NurbsSurface
        Input surface.  Degree-2 in one or both directions.

    Returns
    -------
    NurbsSurface
        New surface with ``degree_u >= 3`` and ``degree_v >= 3`` and identical
        evaluation.
    """
    result = surface

    # Elevate in U direction: process each V-column as a curve.
    if result.degree_u == 2:
        nv = result.num_control_points_v
        dim = result.control_points.shape[2]
        W = result.weights

        elevated_cols = []
        new_ku = None
        for j in range(nv):
            col_pts = result.control_points[:, j, :].copy()
            col_w = W[:, j].copy() if W is not None else None
            col_curve = NurbsCurve(
                degree=result.degree_u,
                control_points=col_pts,
                knots=result.knots_u.copy(),
                weights=col_w,
            )
            elev = elevate_quadratic_to_cubic_curve(col_curve)
            elevated_cols.append(elev)
            if new_ku is None:
                new_ku = elev.knots.copy()

        new_nu = elevated_cols[0].num_control_points
        new_cp = np.zeros((new_nu, nv, dim))
        new_W: Optional[np.ndarray] = (
            np.zeros((new_nu, nv)) if W is not None else None
        )
        for j, ec in enumerate(elevated_cols):
            new_cp[:, j, :] = ec.control_points
            if W is not None:
                new_W[:, j] = (  # type: ignore[index]
                    ec.weights if ec.weights is not None else np.ones(new_nu)
                )

        result = NurbsSurface(
            degree_u=3,
            degree_v=result.degree_v,
            control_points=new_cp,
            knots_u=new_ku,
            knots_v=result.knots_v.copy(),
            weights=new_W,
        )

    # Elevate in V direction: process each U-row as a curve.
    if result.degree_v == 2:
        nu = result.num_control_points_u
        dim = result.control_points.shape[2]
        W = result.weights

        elevated_rows = []
        new_kv = None
        for i in range(nu):
            row_pts = result.control_points[i, :, :].copy()
            row_w = W[i, :].copy() if W is not None else None
            row_curve = NurbsCurve(
                degree=result.degree_v,
                control_points=row_pts,
                knots=result.knots_v.copy(),
                weights=row_w,
            )
            elev = elevate_quadratic_to_cubic_curve(row_curve)
            elevated_rows.append(elev)
            if new_kv is None:
                new_kv = elev.knots.copy()

        new_nv = elevated_rows[0].num_control_points
        new_cp = np.zeros((nu, new_nv, dim))
        new_W = np.zeros((nu, new_nv)) if W is not None else None
        for i, er in enumerate(elevated_rows):
            new_cp[i, :, :] = er.control_points
            if W is not None:
                new_W[i, :] = (  # type: ignore[index]
                    er.weights if er.weights is not None else np.ones(new_nv)
                )

        result = NurbsSurface(
            degree_u=result.degree_u,
            degree_v=3,
            control_points=new_cp,
            knots_u=result.knots_u.copy(),
            knots_v=new_kv,
            weights=new_W,
        )

    return result


# ---------------------------------------------------------------------------
# Body-level normalization: auto-elevate all degree-2 faces and edges
# ---------------------------------------------------------------------------


def _is_nurbs_surface(obj) -> bool:
    """Duck-type check: has degree_u, degree_v, control_points, knots_u, knots_v."""
    return (
        hasattr(obj, "degree_u")
        and hasattr(obj, "degree_v")
        and hasattr(obj, "control_points")
        and hasattr(obj, "knots_u")
        and hasattr(obj, "knots_v")
    )


def _is_nurbs_curve(obj) -> bool:
    """Duck-type check: has degree, control_points, knots (and no degree_u)."""
    return (
        hasattr(obj, "degree")
        and hasattr(obj, "control_points")
        and hasattr(obj, "knots")
        and not hasattr(obj, "degree_u")
    )


def auto_elevate_to_degree_3(body) -> object:
    """Normalize a body by elevating any degree-2 NURBS geometry to degree-3.

    Iterates over all faces (via ``body.all_faces()``) and edges
    (via ``body.all_edges()``), detects degree-2 NURBS geometry, and promotes
    each to degree-3 in-place.  Degree-3+ geometry is left untouched.
    Geometry that is not a NurbsCurve or NurbsSurface (e.g. analytic
    primitives, Line3, CircleArc3) is also left untouched.

    This is the recommended STEP-import normalization step: STEP files
    frequently export circles and conics as rational quadratic NURBS; after
    import a single call to ``auto_elevate_to_degree_3`` ensures the entire
    model is degree-3, simplifying downstream editing algorithms.

    Detection uses duck-typing (attribute presence), not ``isinstance``, so
    the function works regardless of which module namespace instantiated the
    NURBS objects (important when modules are loaded via importlib file paths
    in the test harness).

    Parameters
    ----------
    body : Body (kerf_cad_core.geom.brep.Body)
        The B-rep body to normalize.  Modified **in-place** (surface/curve
        references are replaced on the face/edge objects).

    Returns
    -------
    body : same Body object (for convenient chaining)
    """
    # Promote face surfaces.
    for face in body.all_faces():
        srf = getattr(face, "surface", None)
        if srf is not None and _is_nurbs_surface(srf):
            if srf.degree_u == 2 or srf.degree_v == 2:
                # Build a NurbsSurface using OUR NurbsSurface class so that
                # elevate_quadratic_to_cubic_surface can process it.
                _srf = NurbsSurface(
                    degree_u=srf.degree_u,
                    degree_v=srf.degree_v,
                    control_points=np.array(srf.control_points, dtype=float),
                    knots_u=np.array(srf.knots_u, dtype=float),
                    knots_v=np.array(srf.knots_v, dtype=float),
                    weights=(
                        np.array(srf.weights, dtype=float)
                        if getattr(srf, "weights", None) is not None
                        else None
                    ),
                )
                face.surface = elevate_quadratic_to_cubic_surface(_srf)

    # Promote edge curves.
    for edge in body.all_edges():
        crv = getattr(edge, "curve", None)
        if crv is not None and _is_nurbs_curve(crv):
            if crv.degree == 2:
                _crv = NurbsCurve(
                    degree=crv.degree,
                    control_points=np.array(crv.control_points, dtype=float),
                    knots=np.array(crv.knots, dtype=float),
                    weights=(
                        np.array(crv.weights, dtype=float)
                        if getattr(crv, "weights", None) is not None
                        else None
                    ),
                )
                edge.curve = elevate_quadratic_to_cubic_curve(_crv)

    return body


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

    _elevate_to_cubic_spec = ToolSpec(
        name="nurbs_elevate_to_cubic",
        description=(
            "Exact quadratic-to-cubic NURBS degree elevation (Piegl-Tiller §5.5 "
            "specialisation; Lyche-Mørken 1988).\n\n"
            "Promotes a degree-2 B-spline curve or surface to degree-3 **without "
            "any geometric change**.  This is the standard STEP-import normalisation "
            "step: STEP AP214/242 frequently exports circles and conics as rational "
            "quadratic NURBS; after import a single call ensures all geometry is "
            "degree-3, which is required by most cubic-only editing algorithms.\n\n"
            "Input modes:\n"
            "  • ``mode='curve'`` — elevate a single NURBS curve (degree 2 → 3).\n"
            "  • ``mode='surface'`` — elevate a NURBS surface (degree_u/degree_v 2 → 3).\n\n"
            "For a curve supply ``degree`` (must be 2), ``control_points`` (list of "
            "[x,y,z]), ``knots`` (flat list), and optionally ``weights`` (flat list).\n\n"
            "For a surface supply ``degree_u``, ``degree_v``, ``control_points`` "
            "(flattened nu×nv list of [x,y,z]), ``num_u``, ``num_v``, "
            "``knots_u``, ``knots_v``, and optionally ``weights`` "
            "(flattened nu×nv list of scalars).\n\n"
            "Returns: {ok, mode, degree (curve) | degree_u/degree_v (surface), "
            "num_control_points | num_u/num_v, control_points, knots | "
            "knots_u/knots_v, weights?}. Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["curve", "surface"],
                    "description": "'curve' or 'surface'.",
                },
                "degree": {
                    "type": "integer",
                    "description": "Curve degree (must be 2). For mode='curve'.",
                },
                "control_points": {
                    "type": "array",
                    "description": "Control points: [[x,y,z], ...]. For curves: list of n points. For surfaces: flattened nu*nv list.",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "knots": {
                    "type": "array",
                    "description": "Knot vector (flat). For mode='curve'.",
                    "items": {"type": "number"},
                },
                "weights": {
                    "type": "array",
                    "description": "Per-control-point weights (flat). Optional (None = non-rational).",
                    "items": {"type": "number"},
                },
                "degree_u": {
                    "type": "integer",
                    "description": "Surface degree in U. For mode='surface'.",
                },
                "degree_v": {
                    "type": "integer",
                    "description": "Surface degree in V. For mode='surface'.",
                },
                "num_u": {
                    "type": "integer",
                    "description": "Number of control points in U. For mode='surface'.",
                },
                "num_v": {
                    "type": "integer",
                    "description": "Number of control points in V. For mode='surface'.",
                },
                "knots_u": {
                    "type": "array",
                    "description": "Knot vector in U. For mode='surface'.",
                    "items": {"type": "number"},
                },
                "knots_v": {
                    "type": "array",
                    "description": "Knot vector in V. For mode='surface'.",
                    "items": {"type": "number"},
                },
            },
            "required": ["mode", "control_points"],
        },
    )

    @register(_elevate_to_cubic_spec)
    async def run_nurbs_elevate_to_cubic(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        mode = a.get("mode")
        if mode not in ("curve", "surface"):
            return err_payload("mode must be 'curve' or 'surface'", "BAD_ARGS")

        raw_cp = a.get("control_points", [])
        if not raw_cp:
            return err_payload("control_points is required", "BAD_ARGS")

        try:
            if mode == "curve":
                degree = int(a.get("degree", 2))
                knots = np.asarray(a.get("knots", []), dtype=float)
                weights_raw = a.get("weights")
                weights = (
                    np.asarray(weights_raw, dtype=float) if weights_raw else None
                )
                cp = np.asarray(raw_cp, dtype=float)
                if cp.ndim == 1:
                    cp = cp.reshape(-1, 3)

                # Build default clamped knots if not supplied.
                n = cp.shape[0]
                if len(knots) == 0:
                    inner = max(0, n - degree - 1)
                    knots = np.concatenate([
                        np.zeros(degree + 1),
                        np.linspace(0.0, 1.0, inner + 2)[1:-1] if inner > 0 else np.array([]),
                        np.ones(degree + 1),
                    ])

                curve = NurbsCurve(
                    degree=degree,
                    control_points=cp,
                    knots=knots,
                    weights=weights,
                )

                if degree != 2:
                    return err_payload(
                        f"degree must be 2 for quadratic elevation, got {degree}",
                        "BAD_ARGS",
                    )

                elevated = elevate_quadratic_to_cubic_curve(curve)

                payload = {
                    "ok": True,
                    "mode": "curve",
                    "degree": elevated.degree,
                    "num_control_points": elevated.num_control_points,
                    "control_points": elevated.control_points.tolist(),
                    "knots": elevated.knots.tolist(),
                }
                if elevated.weights is not None:
                    payload["weights"] = elevated.weights.tolist()
                return ok_payload(payload)

            else:  # surface
                degree_u = int(a.get("degree_u", 2))
                degree_v = int(a.get("degree_v", 2))
                num_u = int(a.get("num_u", 0))
                num_v = int(a.get("num_v", 0))
                knots_u_raw = a.get("knots_u", [])
                knots_v_raw = a.get("knots_v", [])
                weights_raw = a.get("weights")

                cp_flat = np.asarray(raw_cp, dtype=float)
                if cp_flat.ndim == 1:
                    cp_flat = cp_flat.reshape(-1, 3)

                if num_u == 0 or num_v == 0:
                    return err_payload("num_u and num_v are required for surface mode", "BAD_ARGS")
                if len(cp_flat) != num_u * num_v:
                    return err_payload(
                        f"control_points length {len(cp_flat)} != num_u*num_v={num_u*num_v}",
                        "BAD_ARGS",
                    )

                cp = cp_flat.reshape(num_u, num_v, cp_flat.shape[1])

                def _make_knots(n: int, deg: int) -> np.ndarray:
                    inner = max(0, n - deg - 1)
                    return np.concatenate([
                        np.zeros(deg + 1),
                        np.linspace(0.0, 1.0, inner + 2)[1:-1] if inner > 0 else np.array([]),
                        np.ones(deg + 1),
                    ])

                knots_u = (
                    np.asarray(knots_u_raw, dtype=float)
                    if knots_u_raw else _make_knots(num_u, degree_u)
                )
                knots_v = (
                    np.asarray(knots_v_raw, dtype=float)
                    if knots_v_raw else _make_knots(num_v, degree_v)
                )

                weights: Optional[np.ndarray] = None
                if weights_raw:
                    w_flat = np.asarray(weights_raw, dtype=float)
                    if w_flat.size == num_u * num_v:
                        weights = w_flat.reshape(num_u, num_v)

                surface = NurbsSurface(
                    degree_u=degree_u,
                    degree_v=degree_v,
                    control_points=cp,
                    knots_u=knots_u,
                    knots_v=knots_v,
                    weights=weights,
                )

                elevated = elevate_quadratic_to_cubic_surface(surface)

                payload = {
                    "ok": True,
                    "mode": "surface",
                    "degree_u": elevated.degree_u,
                    "degree_v": elevated.degree_v,
                    "num_u": elevated.num_control_points_u,
                    "num_v": elevated.num_control_points_v,
                    "control_points": elevated.control_points.reshape(-1, cp.shape[2]).tolist(),
                    "knots_u": elevated.knots_u.tolist(),
                    "knots_v": elevated.knots_v.tolist(),
                }
                if elevated.weights is not None:
                    payload["weights"] = elevated.weights.reshape(-1).tolist()
                return ok_payload(payload)

        except Exception as exc:
            return err_payload(f"elevation failed: {exc}", "OP_FAILED")
