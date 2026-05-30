"""
bezier_extract.py
=================
B-spline → multi-Bezier patch decomposition (Piegl & Tiller §5.6).

Public API
----------
extract_bezier_curve(curve) -> list[BezierCurve]
    Decompose a NurbsCurve into a list of Bezier curves, one per knot span.
    Knots are raised to multiplicity = degree at each interior breakpoint.
    Each BezierCurve carries its parameter interval [u_lo, u_hi].

extract_bezier_surface(surface) -> list[list[BezierSurface]]
    Decompose a NurbsSurface into an Mu × Mv grid of Bezier patches.
    The same extraction is applied independently in the u- and v-directions.
    Returns a 2-D list: result[i][j] is the (i, j)-th Bezier patch.

reconstruct_from_beziers(beziers, knots_u, knots_v=None) -> NurbsCurve | NurbsSurface
    Inverse: reassemble a list (or 2-D list) of Bezier patches back into a
    B-spline curve or surface.  The re-assembled curve/surface evaluates
    identically to the original (within floating-point precision).

Dataclasses
-----------
BezierCurve   — degree, control_points (ndarray), u_lo, u_hi, weights (optional)
BezierSurface — degree_u, degree_v, control_points (ndarray nu×nv×dim),
                u_lo, u_hi, v_lo, v_hi, weights (optional)

The implementation reuses the private knot-insertion primitives already in
``kerf_cad_core.geom.nurbs`` (_decompose_to_bezier, _correct_knot_insert) to
avoid duplicating math.

LLM tool
--------
The ``bezier_extract`` tool is registered at module load when the
``kerf_chat`` registry is available.

References
----------
Piegl, L. & Tiller, W. (1997). The NURBS Book, 2nd ed.  §5.6 — Decomposing a
B-spline curve into Bézier segments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Union

import numpy as np

from kerf_cad_core.geom.nurbs import (
    NurbsCurve,
    NurbsSurface,
    _decompose_to_bezier,
    _correct_knot_insert,
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class BezierCurve:
    """A single Bezier curve segment extracted from a B-spline.

    Attributes
    ----------
    degree : int
        Polynomial degree (p).
    control_points : np.ndarray, shape (p+1, dim)
        Cartesian control points.
    u_lo : float
        Lower bound of the parameter interval on the original B-spline.
    u_hi : float
        Upper bound of the parameter interval on the original B-spline.
    weights : np.ndarray or None
        Per-control-point weights for rational segments.  None means
        non-rational (all weights = 1).
    """
    degree: int
    control_points: np.ndarray
    u_lo: float
    u_hi: float
    weights: Optional[np.ndarray] = None

    def evaluate(self, t: float) -> np.ndarray:
        """Evaluate at parameter *t* ∈ [u_lo, u_hi] using de Casteljau.

        Maps *t* to the local [0, 1] parameter and then runs the standard
        de Casteljau recursion in homogeneous space for rational curves.
        """
        span = self.u_hi - self.u_lo
        s = (t - self.u_lo) / span if abs(span) > 1e-14 else 0.0

        P = self.control_points.copy().astype(float)
        W = self.weights
        dim = P.shape[1]

        if W is not None:
            Pw = np.column_stack([P * W[:, None], W])
        else:
            Pw = P.copy()

        pts = Pw.copy()
        for r in range(1, self.degree + 1):
            for j in range(self.degree + 1 - r):
                pts[j] = (1.0 - s) * pts[j] + s * pts[j + 1]

        if W is not None:
            w = float(pts[0, -1])
            if abs(w) > 1e-300:
                return pts[0, :-1] / w
            return pts[0, :-1]
        return pts[0]


@dataclass
class BezierSurface:
    """A single Bezier patch extracted from a NURBS surface.

    Attributes
    ----------
    degree_u, degree_v : int
        Polynomial degrees in u and v.
    control_points : np.ndarray, shape (pu+1, pv+1, dim)
        Cartesian control points.
    u_lo, u_hi : float
        Parameter interval in u.
    v_lo, v_hi : float
        Parameter interval in v.
    weights : np.ndarray or None, shape (pu+1, pv+1)
        Weight grid for rational patches.  None means non-rational.
    """
    degree_u: int
    degree_v: int
    control_points: np.ndarray
    u_lo: float
    u_hi: float
    v_lo: float
    v_hi: float
    weights: Optional[np.ndarray] = None

    def evaluate(self, u: float, v: float) -> np.ndarray:
        """Evaluate at *(u, v)* ∈ [u_lo, u_hi] × [v_lo, v_hi].

        Maps both parameters to [0, 1] and applies de Casteljau in u then v
        (tensor-product Bezier evaluation).  Rational-correct.
        """
        span_u = self.u_hi - self.u_lo
        span_v = self.v_hi - self.v_lo
        s = (u - self.u_lo) / span_u if abs(span_u) > 1e-14 else 0.0
        t = (v - self.v_lo) / span_v if abs(span_v) > 1e-14 else 0.0

        pu = self.degree_u
        pv = self.degree_v
        P = self.control_points.astype(float)
        W = self.weights
        dim = P.shape[2]

        if W is not None:
            nu = pu + 1
            nv = pv + 1
            Pw = np.zeros((nu, nv, dim + 1))
            Pw[:, :, :dim] = P * W[:, :, None]
            Pw[:, :, dim] = W
        else:
            Pw = P.copy()

        # de Casteljau in u-direction: reduce from (pu+1) rows to 1 row
        pts_u = Pw.copy()
        for r in range(1, pu + 1):
            for j in range(pu + 1 - r):
                pts_u[j] = (1.0 - s) * pts_u[j] + s * pts_u[j + 1]
        row = pts_u[0]  # shape (pv+1, dim) or (pv+1, dim+1)

        # de Casteljau in v-direction: reduce from (pv+1) to 1
        pts_v = row.copy()
        for r in range(1, pv + 1):
            for j in range(pv + 1 - r):
                pts_v[j] = (1.0 - t) * pts_v[j] + t * pts_v[j + 1]
        result = pts_v[0]

        if W is not None:
            w = float(result[-1])
            if abs(w) > 1e-300:
                return result[:dim] / w
            return result[:dim]
        return result


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def _unique_interior_breakpoints(knots: np.ndarray, degree: int) -> List[float]:
    """Return the sorted, deduplicated list of interior knot values.

    'Interior' means strictly between the first and last knot (not the clamped
    end repetitions).
    """
    tol = 1e-12
    a = float(knots[0])
    b = float(knots[-1])
    seen: List[float] = []
    for k in knots:
        v = float(k)
        if v > a + tol and v < b - tol:
            if not seen or abs(v - seen[-1]) > tol:
                seen.append(v)
    return seen


# ---------------------------------------------------------------------------
# Core extraction functions
# ---------------------------------------------------------------------------

def extract_bezier_curve(curve: NurbsCurve) -> List[BezierCurve]:
    """Decompose *curve* into a list of Bezier curve segments.

    Algorithm (Piegl & Tiller §5.6):
    1. Build homogeneous control points (w·P, w) for rational curves.
    2. Insert each interior knot to multiplicity = degree using the correct
       Boehm insertion algorithm (_correct_knot_insert).
    3. The resulting CPs partition into (degree+1)-size blocks — one Bezier
       per knot span.

    Parameters
    ----------
    curve : NurbsCurve
        Input B-spline or NURBS curve.

    Returns
    -------
    list[BezierCurve]
        One BezierCurve per distinct knot span.  Adjacent Bezier segments
        share their endpoint CP (the last CP of segment k equals the first CP
        of segment k+1).

    Notes
    -----
    * Non-rational curves: BezierCurve.weights is None.
    * Rational curves: BezierCurve.weights carries the per-CP weights.
    * A curve with a single knot span (no interior knots) is returned as a
      single Bezier of the same degree.
    """
    p = curve.degree
    P = curve.control_points.astype(float)
    U = curve.knots.astype(float)
    W = curve.weights

    # Homogeneous space
    if W is not None:
        Pw = np.column_stack([P * W[:, None], W])
    else:
        Pw = P.copy()

    segs = _decompose_to_bezier(Pw, U, p)

    result: List[BezierCurve] = []
    for seg_Pw, u_lo, u_hi in segs:
        if W is not None:
            seg_w = seg_Pw[:, -1].copy()
            seg_P = np.where(
                seg_w[:, None] > 1e-14,
                seg_Pw[:, :-1] / seg_w[:, None],
                seg_Pw[:, :-1],
            )
            result.append(BezierCurve(
                degree=p,
                control_points=seg_P,
                u_lo=float(u_lo),
                u_hi=float(u_hi),
                weights=seg_w,
            ))
        else:
            result.append(BezierCurve(
                degree=p,
                control_points=seg_Pw.copy(),
                u_lo=float(u_lo),
                u_hi=float(u_hi),
            ))

    return result


def extract_bezier_surface(surface: NurbsSurface) -> List[List[BezierSurface]]:
    """Decompose *surface* into an Mu × Mv grid of Bezier patches.

    Algorithm:
    1. Extract Bezier segments in the u-direction for each v-isocurve column.
    2. For each u-Bezier row, extract Bezier segments in the v-direction.
    3. Assemble into a 2-D list of BezierSurface objects.

    Parameters
    ----------
    surface : NurbsSurface
        Input B-spline or NURBS surface.

    Returns
    -------
    list[list[BezierSurface]]
        Indexed as result[i_u][i_v].  len(result) = number of u-spans,
        len(result[0]) = number of v-spans.

    Notes
    -----
    * Rational surfaces: each BezierSurface.weights carries the (pu+1)×(pv+1)
      weight grid.
    * A single-span surface is returned as a 1×1 grid (one Bezier patch).
    """
    pu = surface.degree_u
    pv = surface.degree_v
    nu = surface.num_control_points_u
    nv = surface.num_control_points_v
    P = surface.control_points.astype(float)
    W = surface.weights

    dim = P.shape[2]

    # Step 1 — decompose in u-direction.
    # For each v-column j, extract Bezier segments along u.
    # All columns must produce the same number of u-segments.

    # Build per-column Bezier decompositions
    u_seg_data: List[List] = []  # u_seg_data[j] = list of (seg_Pw, u_lo, u_hi)
    for j in range(nv):
        col_P = P[:, j, :]
        col_W = W[:, j] if W is not None else None
        if col_W is not None:
            col_Pw = np.column_stack([col_P * col_W[:, None], col_W])
        else:
            col_Pw = col_P.copy()
        col_segs = _decompose_to_bezier(col_Pw, surface.knots_u, pu)
        u_seg_data.append(col_segs)

    mu = len(u_seg_data[0])  # number of u-spans

    # Step 2 — decompose in v-direction for each u-span.
    # Collect the (pu+1)-wide CP block for each u-span across all v-columns,
    # then decompose along v for each row of u-CPs.

    result: List[List[BezierSurface]] = []

    for i_u in range(mu):
        # Assemble the (pu+1) × nv CP grid for this u-span.
        # Each column j contributes pu+1 CPs from u_seg_data[j][i_u][0].
        u_lo = u_seg_data[0][i_u][1]
        u_hi = u_seg_data[0][i_u][2]

        # Shape: (pu+1, nv, dim_hom)
        if W is not None:
            hom_dim = dim + 1
        else:
            hom_dim = dim
        strip_Pw = np.zeros((pu + 1, nv, hom_dim))
        for j in range(nv):
            seg_Pw_j = u_seg_data[j][i_u][0]  # shape (pu+1, hom_dim)
            strip_Pw[:, j, :] = seg_Pw_j

        # Now decompose along v-direction for each of the pu+1 u-rows.
        v_seg_data_row: List[List] = []
        for row_u in range(pu + 1):
            row_Pw = strip_Pw[row_u, :, :]  # shape (nv, hom_dim)
            row_segs = _decompose_to_bezier(row_Pw, surface.knots_v, pv)
            v_seg_data_row.append(row_segs)

        mv = len(v_seg_data_row[0])  # number of v-spans

        row_result: List[BezierSurface] = []
        for i_v in range(mv):
            v_lo = v_seg_data_row[0][i_v][1]
            v_hi = v_seg_data_row[0][i_v][2]

            # Assemble patch CP grid: shape (pu+1, pv+1, hom_dim)
            patch_Pw = np.zeros((pu + 1, pv + 1, hom_dim))
            for row_u in range(pu + 1):
                seg_v = v_seg_data_row[row_u][i_v][0]  # shape (pv+1, hom_dim)
                patch_Pw[row_u, :, :] = seg_v

            if W is not None:
                patch_w = patch_Pw[:, :, -1].copy()  # shape (pu+1, pv+1)
                patch_P = np.where(
                    patch_w[:, :, None] > 1e-14,
                    patch_Pw[:, :, :-1] / patch_w[:, :, None],
                    patch_Pw[:, :, :-1],
                )
                row_result.append(BezierSurface(
                    degree_u=pu,
                    degree_v=pv,
                    control_points=patch_P,
                    u_lo=float(u_lo),
                    u_hi=float(u_hi),
                    v_lo=float(v_lo),
                    v_hi=float(v_hi),
                    weights=patch_w,
                ))
            else:
                row_result.append(BezierSurface(
                    degree_u=pu,
                    degree_v=pv,
                    control_points=patch_Pw.copy(),
                    u_lo=float(u_lo),
                    u_hi=float(u_hi),
                    v_lo=float(v_lo),
                    v_hi=float(v_hi),
                ))

        result.append(row_result)

    return result


# ---------------------------------------------------------------------------
# Reconstruction (inverse round-trip)
# ---------------------------------------------------------------------------

def reconstruct_from_beziers(
    beziers: Union[List[BezierCurve], List[List[BezierSurface]]],
    knots_u: Optional[np.ndarray] = None,
    knots_v: Optional[np.ndarray] = None,
) -> Union[NurbsCurve, NurbsSurface]:
    """Reconstruct a B-spline curve or surface from Bezier segments/patches.

    For **curves** (``beziers`` is a flat list of BezierCurve):
        The segments must cover contiguous, non-overlapping parameter intervals
        (as produced by :func:`extract_bezier_curve`).  Adjacent segments share
        their boundary CP.  The resulting knot vector has multiplicity = degree
        at each internal breakpoint, with clamped ends.

    For **surfaces** (``beziers`` is a 2-D list of BezierSurface):
        Mu × Mv Bezier patches are re-assembled into a single NurbsSurface.
        The reconstruction follows the same logic as for curves, applied
        independently in u and v.

    Parameters
    ----------
    beziers :
        Flat list of BezierCurve, or 2-D list of BezierSurface.
    knots_u : optional
        Pre-computed knot vector for u (or the curve direction).  If None,
        the vector is synthesised from the breakpoints in the Bezier list.
    knots_v : optional
        Pre-computed knot vector for v (surface only).

    Returns
    -------
    NurbsCurve or NurbsSurface
    """
    # Detect curve vs surface
    if len(beziers) == 0:
        raise ValueError("beziers must be non-empty")

    if isinstance(beziers[0], BezierCurve):
        return _reconstruct_curve(beziers, knots_u)  # type: ignore[arg-type]
    else:
        return _reconstruct_surface(beziers, knots_u, knots_v)  # type: ignore[arg-type]


def _build_bspline_knots(breakpoints: List[float], degree: int) -> np.ndarray:
    """Build a clamped B-spline knot vector from breakpoints.

    Each internal breakpoint gets multiplicity = degree; the two ends get
    multiplicity = degree + 1.
    """
    a = breakpoints[0]
    b = breakpoints[-1]
    knots: List[float] = [a] * (degree + 1)
    for bp in breakpoints[1:-1]:
        knots.extend([bp] * degree)
    knots.extend([b] * (degree + 1))
    return np.array(knots, dtype=float)


def _reconstruct_curve(
    beziers: List[BezierCurve],
    knots_u: Optional[np.ndarray],
) -> NurbsCurve:
    """Reconstruct a NurbsCurve from a list of BezierCurve segments."""
    p = beziers[0].degree
    is_rational = beziers[0].weights is not None
    dim = beziers[0].control_points.shape[1]

    # Build merged CP array — adjacent segments share one endpoint;
    # take the average to handle floating-point noise.
    merged_P: List[np.ndarray] = list(beziers[0].control_points.copy())
    for k in range(1, len(beziers)):
        shared_prev = merged_P[-1].copy()
        shared_cur = beziers[k].control_points[0].copy()
        merged_P[-1] = 0.5 * (shared_prev + shared_cur)
        for row in beziers[k].control_points[1:]:
            merged_P.append(row.copy())

    P_arr = np.array(merged_P, dtype=float)

    if is_rational:
        # Merge weights
        merged_W: List[float] = list(beziers[0].weights.copy())  # type: ignore[union-attr]
        for k in range(1, len(beziers)):
            w_prev = merged_W[-1]
            w_cur = float(beziers[k].weights[0])  # type: ignore[index]
            merged_W[-1] = 0.5 * (w_prev + w_cur)
            for wv in beziers[k].weights[1:]:  # type: ignore[union-attr]
                merged_W.append(float(wv))
        W_arr = np.array(merged_W, dtype=float)
    else:
        W_arr = None

    # Build knot vector
    if knots_u is not None:
        U = np.asarray(knots_u, dtype=float)
    else:
        breakpoints = [beziers[0].u_lo] + [seg.u_hi for seg in beziers]
        U = _build_bspline_knots(breakpoints, p)

    # Validate: num_knots must equal num_CPs + degree + 1
    n = len(P_arr)
    expected = n + p + 1
    if len(U) != expected:
        # Fallback: synthesise from breakpoints
        breakpoints = [beziers[0].u_lo] + [seg.u_hi for seg in beziers]
        U = _build_bspline_knots(breakpoints, p)

    return NurbsCurve(degree=p, control_points=P_arr, knots=U, weights=W_arr)


def _reconstruct_surface(
    beziers: List[List[BezierSurface]],
    knots_u: Optional[np.ndarray],
    knots_v: Optional[np.ndarray],
) -> NurbsSurface:
    """Reconstruct a NurbsSurface from an Mu × Mv grid of BezierSurface patches."""
    mu = len(beziers)
    mv = len(beziers[0])
    pu = beziers[0][0].degree_u
    pv = beziers[0][0].degree_v
    dim = beziers[0][0].control_points.shape[2]
    is_rational = beziers[0][0].weights is not None

    # Merge in u: for each v-column j (0..pv), reconstruct the u-direction CPs
    # by treating each row of u-patches as a curve.

    total_nu = (mu - 1) * pu + (pu + 1)  # merged u-CP count
    total_nv = (mv - 1) * pv + (pv + 1)  # merged v-CP count

    merged_P = np.zeros((total_nu, total_nv, dim))
    merged_W = np.zeros((total_nu, total_nv)) if is_rational else None

    for j_v in range(mv):
        # Determine v-column indices for this v-span
        if j_v == 0:
            v_start = 0
        else:
            v_start = j_v * pv  # shared CP at boundary

        for i_u in range(mu):
            # Determine u-row indices
            if i_u == 0:
                u_start = 0
            else:
                u_start = i_u * pu

            patch = beziers[i_u][j_v]
            P_patch = patch.control_points  # (pu+1, pv+1, dim)
            W_patch = patch.weights          # (pu+1, pv+1) or None

            for ru in range(pu + 1):
                ri = u_start + ru
                for rv in range(pv + 1):
                    rj = v_start + rv
                    if ri < total_nu and rj < total_nv:
                        # Average at shared boundaries
                        if (i_u > 0 and ru == 0) or (j_v > 0 and rv == 0):
                            # This point was already written by a neighbour;
                            # average to smooth floating-point noise.
                            existing = merged_P[ri, rj, :]
                            new_val = P_patch[ru, rv, :]
                            merged_P[ri, rj, :] = 0.5 * (existing + new_val)
                            if is_rational and merged_W is not None:
                                existing_w = merged_W[ri, rj]
                                new_w = float(W_patch[ru, rv])  # type: ignore[index]
                                merged_W[ri, rj] = 0.5 * (existing_w + new_w)
                        else:
                            merged_P[ri, rj, :] = P_patch[ru, rv, :]
                            if is_rational and merged_W is not None:
                                merged_W[ri, rj] = float(W_patch[ru, rv])  # type: ignore[index]

    # Build knot vectors
    if knots_u is not None:
        U = np.asarray(knots_u, dtype=float)
    else:
        u_breakpoints = [beziers[0][0].u_lo] + [beziers[i_u][0].u_hi for i_u in range(mu)]
        U = _build_bspline_knots(u_breakpoints, pu)

    if knots_v is not None:
        V = np.asarray(knots_v, dtype=float)
    else:
        v_breakpoints = [beziers[0][0].v_lo] + [beziers[0][j_v].v_hi for j_v in range(mv)]
        V = _build_bspline_knots(v_breakpoints, pv)

    # Validate
    nu_cp = merged_P.shape[0]
    nv_cp = merged_P.shape[1]
    expected_U = nu_cp + pu + 1
    expected_V = nv_cp + pv + 1
    if len(U) != expected_U:
        u_breakpoints = [beziers[0][0].u_lo] + [beziers[i_u][0].u_hi for i_u in range(mu)]
        U = _build_bspline_knots(u_breakpoints, pu)
    if len(V) != expected_V:
        v_breakpoints = [beziers[0][0].v_lo] + [beziers[0][j_v].v_hi for j_v in range(mv)]
        V = _build_bspline_knots(v_breakpoints, pv)

    return NurbsSurface(
        degree_u=pu,
        degree_v=pv,
        control_points=merged_P,
        knots_u=U,
        knots_v=V,
        weights=merged_W,
    )


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

    _bezier_extract_spec = ToolSpec(
        name="bezier_extract",
        description=(
            "Decompose a B-spline curve or surface into multi-Bezier patches "
            "(one per knot span) via Piegl & Tiller §5.6 knot-multiplicity "
            "insertion.  Useful for FEA tet-mesh handoff, GPU-friendly "
            "rendering, and IGES export.\n"
            "\n"
            "For a **curve**: provide degree, control_points [[x,y,z],...], "
            "and knots [k0,k1,...].  Optionally provide weights for NURBS.\n"
            "\n"
            "For a **surface**: provide degree_u, degree_v, control_points "
            "(nu×nv×3 as nested arrays), knots_u, knots_v.  Optionally "
            "provide weights (nu×nv).\n"
            "\n"
            "Returns: {ok, type, segments} where segments is a list of "
            "Bezier curve dicts [{degree, control_points, u_lo, u_hi, "
            "weights?}] for curves, or a 2-D list of patch dicts for surfaces."
            "\n"
            "Errors: {ok: false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["curve", "surface"],
                    "description": "Whether to decompose a curve or a surface.",
                },
                "degree": {
                    "type": "integer",
                    "description": "Curve degree (required for curve).",
                },
                "degree_u": {
                    "type": "integer",
                    "description": "Surface degree in u (required for surface).",
                },
                "degree_v": {
                    "type": "integer",
                    "description": "Surface degree in v (required for surface).",
                },
                "control_points": {
                    "type": "array",
                    "description": (
                        "For curves: [[x,y,z],...].  "
                        "For surfaces: [[[x,y,z],...],...]  (nu×nv×3)."
                    ),
                },
                "knots": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Knot vector for curve.",
                },
                "knots_u": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Knot vector in u (surface).",
                },
                "knots_v": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Knot vector in v (surface).",
                },
                "weights": {
                    "type": "array",
                    "description": "Weights array (optional, for rational NURBS).",
                },
            },
            "required": ["type", "control_points"],
        },
    )

    @register(_bezier_extract_spec)
    async def run_bezier_extract(ctx: "ProjectCtx", args: bytes) -> str:  # type: ignore[name-defined]
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        geom_type = a.get("type", "curve")
        cps_raw = a.get("control_points", [])
        weights_raw = a.get("weights", None)

        if not cps_raw:
            return err_payload("control_points must be non-empty", "BAD_ARGS")

        try:
            if geom_type == "curve":
                knots_raw = a.get("knots", None)
                degree = int(a.get("degree", 3))
                if knots_raw is None:
                    return err_payload("knots is required for a curve", "BAD_ARGS")
                cp_arr = np.array(cps_raw, dtype=float)
                if cp_arr.ndim == 1:
                    cp_arr = cp_arr.reshape(-1, 1)
                knots_arr = np.array(knots_raw, dtype=float)
                w_arr = np.array(weights_raw, dtype=float) if weights_raw else None
                curve = NurbsCurve(
                    degree=degree,
                    control_points=cp_arr,
                    knots=knots_arr,
                    weights=w_arr,
                )
                segs = extract_bezier_curve(curve)
                segments_out = []
                for seg in segs:
                    d = {
                        "degree": seg.degree,
                        "control_points": seg.control_points.tolist(),
                        "u_lo": seg.u_lo,
                        "u_hi": seg.u_hi,
                    }
                    if seg.weights is not None:
                        d["weights"] = seg.weights.tolist()
                    segments_out.append(d)
                return ok_payload({
                    "type": "curve",
                    "num_segments": len(segments_out),
                    "segments": segments_out,
                })

            elif geom_type == "surface":
                degree_u = int(a.get("degree_u", 3))
                degree_v = int(a.get("degree_v", 3))
                knots_u_raw = a.get("knots_u", None)
                knots_v_raw = a.get("knots_v", None)
                if knots_u_raw is None or knots_v_raw is None:
                    return err_payload("knots_u and knots_v are required for a surface", "BAD_ARGS")
                cp_arr = np.array(cps_raw, dtype=float)
                if cp_arr.ndim != 3:
                    return err_payload("control_points must be a 3-D array (nu×nv×dim)", "BAD_ARGS")
                knots_u_arr = np.array(knots_u_raw, dtype=float)
                knots_v_arr = np.array(knots_v_raw, dtype=float)
                w_arr = np.array(weights_raw, dtype=float) if weights_raw else None
                surf = NurbsSurface(
                    degree_u=degree_u,
                    degree_v=degree_v,
                    control_points=cp_arr,
                    knots_u=knots_u_arr,
                    knots_v=knots_v_arr,
                    weights=w_arr,
                )
                patches = extract_bezier_surface(surf)
                patches_out = []
                for row in patches:
                    row_out = []
                    for patch in row:
                        d = {
                            "degree_u": patch.degree_u,
                            "degree_v": patch.degree_v,
                            "control_points": patch.control_points.tolist(),
                            "u_lo": patch.u_lo,
                            "u_hi": patch.u_hi,
                            "v_lo": patch.v_lo,
                            "v_hi": patch.v_hi,
                        }
                        if patch.weights is not None:
                            d["weights"] = patch.weights.tolist()
                        row_out.append(d)
                    patches_out.append(row_out)
                return ok_payload({
                    "type": "surface",
                    "num_patches_u": len(patches_out),
                    "num_patches_v": len(patches_out[0]) if patches_out else 0,
                    "patches": patches_out,
                })
            else:
                return err_payload(f"unknown type '{geom_type}'; must be 'curve' or 'surface'", "BAD_ARGS")

        except Exception as exc:
            return err_payload(str(exc), "OP_FAILED")
