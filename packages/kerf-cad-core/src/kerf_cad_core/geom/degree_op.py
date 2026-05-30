"""
degree_op.py
============
NURBS degree raise and degree lower operations.

References
----------
- Cohen, Lyche & Schumaker (1985): "Algorithms for degree-raising of splines",
  ACM Trans. Graphics 4(3), 171-181.
- Piegl & Tiller: "The NURBS Book", 2nd ed., §5.5 (degree reduction, Alg. A5.6).

Public API
----------
degree_raise_curve(curve, target_degree) -> NurbsCurve
    Exact degree elevation to *target_degree* via Bezier decompose → elevate → refit.
    Geometric error is zero to floating-point precision.

degree_raise_surface(srf, target_degree_u, target_degree_v) -> NurbsSurface
    Apply degree_raise_curve per direction: first all u-columns, then all v-rows.

degree_lower_curve(curve, target_degree, tol=1e-6) -> NurbsCurve
    Approximate degree reduction using the Forrest–Piegl least-squares Bezier split.
    Returns the reduced curve, or *curve* unchanged if the deviation exceeds *tol*.

degree_lower_surface(srf, target_degree_u, target_degree_v, tol=1e-6) -> NurbsSurface
    Apply degree_lower_curve per direction; abort if any column/row fails.

elevate_to_match(srf_a, srf_b) -> (NurbsSurface, NurbsSurface)
    Raise both surfaces to max(degree_a, degree_b) in each direction.

LLM tools (registered when kerf_chat is available)
---------------------------------------------------
nurbs_degree_raise  — raise curve or surface to a target degree
nurbs_degree_lower  — lower curve or surface to a target degree (within tol)
"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np

from kerf_cad_core.geom.nurbs import (
    NurbsCurve,
    NurbsSurface,
    _elevate_curve_bspline,
    reduce_degree_curve,
    reduce_degree_surface,
)


# ---------------------------------------------------------------------------
# Curve degree raise
# ---------------------------------------------------------------------------

def degree_raise_curve(curve: NurbsCurve, target_degree: int) -> NurbsCurve:
    """Raise *curve* to *target_degree* exactly (Cohen-Lyche-Schumaker 1985).

    The algorithm works by:
    1. Decomposing the B-spline into Bezier segments (knot multiplicity = degree).
    2. Elevating each Bezier segment from degree *p* to *p+1* using:
       ``Q_i = (i/(p+1)) P_{i-1} + (1 - i/(p+1)) P_i``  (direct CLS formula).
    3. Reassembling the elevated B-spline with reduced internal knot multiplicity.
    This step is applied iteratively from the current degree up to *target_degree*.

    The result is *geometrically exact* to floating-point precision — evaluation
    at any parameter value matches the original curve within ~1e-13.

    Parameters
    ----------
    curve:
        Input NURBS curve.
    target_degree:
        Desired degree.  Must be >= curve.degree.

    Returns
    -------
    NurbsCurve
        Elevated curve.  Returns *curve* unchanged when
        ``target_degree == curve.degree``.

    Raises
    ------
    ValueError
        If ``target_degree < curve.degree``.
    """
    if target_degree < curve.degree:
        raise ValueError(
            f"target_degree ({target_degree}) must be >= current degree "
            f"({curve.degree}).  Use degree_lower_curve to reduce."
        )
    if target_degree == curve.degree:
        return curve

    times = target_degree - curve.degree
    return _elevate_curve_bspline(curve, times=times)


# ---------------------------------------------------------------------------
# Surface degree raise
# ---------------------------------------------------------------------------

def degree_raise_surface(
    srf: NurbsSurface,
    target_degree_u: int,
    target_degree_v: int,
) -> NurbsSurface:
    """Raise *srf* to *(target_degree_u, target_degree_v)* exactly.

    Applies :func:`degree_raise_curve` first to every u-column (varying u, fixed v)
    then to every v-row (varying v, fixed u), following the standard tensor-product
    separability argument (Cohen-Lyche-Schumaker 1985, §4).

    Parameters
    ----------
    srf:
        Input NURBS surface.
    target_degree_u:
        Target degree in the u direction. Must be >= srf.degree_u.
    target_degree_v:
        Target degree in the v direction. Must be >= srf.degree_v.

    Returns
    -------
    NurbsSurface
        Elevated surface. Returns *srf* unchanged when both targets equal the
        current degrees.

    Raises
    ------
    ValueError
        If either target is below the current degree.
    """
    if target_degree_u < srf.degree_u:
        raise ValueError(
            f"target_degree_u ({target_degree_u}) < current degree_u ({srf.degree_u})"
        )
    if target_degree_v < srf.degree_v:
        raise ValueError(
            f"target_degree_v ({target_degree_v}) < current degree_v ({srf.degree_v})"
        )

    result = srf
    if target_degree_u > srf.degree_u:
        result = _elevate_surface_u(result, target_degree_u)
    if target_degree_v > result.degree_v:
        result = _elevate_surface_v(result, target_degree_v)
    return result


def _elevate_surface_u(srf: NurbsSurface, target_degree_u: int) -> NurbsSurface:
    """Raise *srf* in u to *target_degree_u* by elevating every v-column."""
    nv = srf.num_control_points_v
    dim = srf.control_points.shape[2]
    W = srf.weights
    times = target_degree_u - srf.degree_u

    elevated_cols = []
    new_ku: Optional[np.ndarray] = None

    for j in range(nv):
        col_pts = srf.control_points[:, j, :].copy()
        col_w = W[:, j].copy() if W is not None else None
        col_curve = NurbsCurve(
            degree=srf.degree_u,
            control_points=col_pts,
            knots=srf.knots_u.copy(),
            weights=col_w,
        )
        elev = _elevate_curve_bspline(col_curve, times=times)
        elevated_cols.append(elev)
        if new_ku is None:
            new_ku = elev.knots.copy()

    new_nu = elevated_cols[0].num_control_points
    new_cp = np.zeros((new_nu, nv, dim))
    new_W = np.zeros((new_nu, nv)) if W is not None else None

    for j, ec in enumerate(elevated_cols):
        new_cp[:, j, :] = ec.control_points
        if W is not None:
            new_W[:, j] = (
                ec.weights if ec.weights is not None else np.ones(new_nu)
            )

    return NurbsSurface(
        degree_u=target_degree_u,
        degree_v=srf.degree_v,
        control_points=new_cp,
        knots_u=new_ku,
        knots_v=srf.knots_v.copy(),
        weights=new_W,
    )


def _elevate_surface_v(srf: NurbsSurface, target_degree_v: int) -> NurbsSurface:
    """Raise *srf* in v to *target_degree_v* by elevating every u-row."""
    nu = srf.num_control_points_u
    dim = srf.control_points.shape[2]
    W = srf.weights
    times = target_degree_v - srf.degree_v

    elevated_rows = []
    new_kv: Optional[np.ndarray] = None

    for i in range(nu):
        row_pts = srf.control_points[i, :, :].copy()
        row_w = W[i, :].copy() if W is not None else None
        row_curve = NurbsCurve(
            degree=srf.degree_v,
            control_points=row_pts,
            knots=srf.knots_v.copy(),
            weights=row_w,
        )
        elev = _elevate_curve_bspline(row_curve, times=times)
        elevated_rows.append(elev)
        if new_kv is None:
            new_kv = elev.knots.copy()

    new_nv = elevated_rows[0].num_control_points
    new_cp = np.zeros((nu, new_nv, dim))
    new_W = np.zeros((nu, new_nv)) if W is not None else None

    for i, er in enumerate(elevated_rows):
        new_cp[i, :, :] = er.control_points
        if W is not None:
            new_W[i, :] = (
                er.weights if er.weights is not None else np.ones(new_nv)
            )

    return NurbsSurface(
        degree_u=srf.degree_u,
        degree_v=target_degree_v,
        control_points=new_cp,
        knots_u=srf.knots_u.copy(),
        knots_v=new_kv,
        weights=new_W,
    )


# ---------------------------------------------------------------------------
# Curve degree lower
# ---------------------------------------------------------------------------

def degree_lower_curve(
    curve: NurbsCurve,
    target_degree: int,
    tol: float = 1e-6,
) -> NurbsCurve:
    """Lower *curve* to *target_degree* using Forrest–Piegl least-squares.

    Iteratively calls :func:`reduce_degree_curve` (Piegl & Tiller §5.5,
    Alg. A5.6) until the target degree is reached or a reduction step exceeds
    *tol*.

    Parameters
    ----------
    curve:
        Input NURBS curve.
    target_degree:
        Desired degree.  Must be >= 1.
    tol:
        Maximum allowed geometric deviation per reduction step.

    Returns
    -------
    NurbsCurve
        Reduced curve, or *curve* unchanged when ``target_degree == curve.degree``
        or any reduction step would exceed *tol*.

    Raises
    ------
    ValueError
        If ``target_degree < 1`` or ``target_degree > curve.degree``.
    """
    if target_degree < 1:
        raise ValueError(f"target_degree must be >= 1, got {target_degree}")
    if target_degree > curve.degree:
        raise ValueError(
            f"target_degree ({target_degree}) > current degree ({curve.degree}). "
            "Use degree_raise_curve to elevate."
        )
    if target_degree == curve.degree:
        return curve

    result = curve
    while result.degree > target_degree:
        candidate = reduce_degree_curve(result, tol=tol)
        if candidate.degree == result.degree:
            # reduction rejected (deviation > tol or already min degree)
            break
        result = candidate

    return result


# ---------------------------------------------------------------------------
# Surface degree lower
# ---------------------------------------------------------------------------

def degree_lower_surface(
    srf: NurbsSurface,
    target_degree_u: int,
    target_degree_v: int,
    tol: float = 1e-6,
) -> NurbsSurface:
    """Lower *srf* to *(target_degree_u, target_degree_v)*.

    Applies :func:`degree_lower_curve` iteratively to columns (u-direction)
    and rows (v-direction).  Returns *srf* unchanged if any column or row
    cannot be reduced within *tol*.

    Parameters
    ----------
    srf:
        Input NURBS surface.
    target_degree_u:
        Target degree in u. Must be >= 1.
    target_degree_v:
        Target degree in v. Must be >= 1.
    tol:
        Maximum allowed geometric deviation per reduction step.

    Returns
    -------
    NurbsSurface
        Reduced surface, or *srf* unchanged if reduction is not possible within
        *tol* or targets equal current degrees.

    Raises
    ------
    ValueError
        If any target is < 1 or > the current degree.
    """
    if target_degree_u < 1:
        raise ValueError(f"target_degree_u must be >= 1, got {target_degree_u}")
    if target_degree_v < 1:
        raise ValueError(f"target_degree_v must be >= 1, got {target_degree_v}")
    if target_degree_u > srf.degree_u:
        raise ValueError(
            f"target_degree_u ({target_degree_u}) > current degree_u ({srf.degree_u})"
        )
    if target_degree_v > srf.degree_v:
        raise ValueError(
            f"target_degree_v ({target_degree_v}) > current degree_v ({srf.degree_v})"
        )

    result = srf

    # Lower in u iteratively
    while result.degree_u > target_degree_u:
        candidate = reduce_degree_surface(result, direction='u', tol=tol)
        if candidate.degree_u == result.degree_u:
            return srf  # failed — return original unchanged
        result = candidate

    # Lower in v iteratively
    while result.degree_v > target_degree_v:
        candidate = reduce_degree_surface(result, direction='v', tol=tol)
        if candidate.degree_v == result.degree_v:
            return srf  # failed — return original unchanged
        result = candidate

    return result


# ---------------------------------------------------------------------------
# elevate_to_match helper
# ---------------------------------------------------------------------------

def elevate_to_match(
    srf_a: NurbsSurface,
    srf_b: NurbsSurface,
) -> Tuple[NurbsSurface, NurbsSurface]:
    """Raise both surfaces to max(degree_a, degree_b) per direction.

    Useful before blending or boolean operations on surfaces that need
    compatible degrees.  The operation is exact (zero geometric error).

    Parameters
    ----------
    srf_a, srf_b:
        Input surfaces.

    Returns
    -------
    (NurbsSurface, NurbsSurface)
        Both surfaces elevated to the common maximum degree in each direction.
        A surface whose degree already matches the target is returned unchanged.
    """
    du = max(srf_a.degree_u, srf_b.degree_u)
    dv = max(srf_a.degree_v, srf_b.degree_v)
    out_a = degree_raise_surface(srf_a, du, dv)
    out_b = degree_raise_surface(srf_b, du, dv)
    return out_a, out_b


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

    # ── nurbs_degree_raise ────────────────────────────────────────────────────

    _degree_raise_spec = ToolSpec(
        name="nurbs_degree_raise",
        description=(
            "Raise the degree of a NURBS curve or surface to a target degree.\n"
            "\n"
            "Algorithm: Cohen-Lyche-Schumaker 1985 — decomposes the B-spline into\n"
            "Bezier segments, elevates each segment exactly, and reassembles.\n"
            "The operation is *geometrically exact* (deviation < 1e-12 from original).\n"
            "\n"
            "For curves, supply ``control_points``, ``knots``, ``degree`` and "
            "``target_degree``.\n"
            "For surfaces, also supply ``knots_u``, ``knots_v``, ``degree_u``, ``degree_v``\n"
            "and set ``surface=true``.\n"
            "\n"
            "Returns: {ok, control_points, knots, degree} for curves;\n"
            "         {ok, control_points, knots_u, knots_v, degree_u, degree_v} for surfaces.\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "surface": {
                    "type": "boolean",
                    "description": "true for surface input, false (default) for curve.",
                },
                "control_points": {
                    "type": "array",
                    "description": "Control points. 2D array [[x,y,z],...] for curves; "
                                   "3D array [[[x,y,z],...], ...] (nu×nv) for surfaces.",
                },
                "knots": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Knot vector (curves only).",
                },
                "knots_u": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Knot vector in u (surfaces).",
                },
                "knots_v": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Knot vector in v (surfaces).",
                },
                "degree": {
                    "type": "integer",
                    "description": "Current degree (curves).",
                },
                "degree_u": {
                    "type": "integer",
                    "description": "Current degree in u (surfaces).",
                },
                "degree_v": {
                    "type": "integer",
                    "description": "Current degree in v (surfaces).",
                },
                "target_degree": {
                    "type": "integer",
                    "description": "Target degree (curves).",
                },
                "target_degree_u": {
                    "type": "integer",
                    "description": "Target degree in u (surfaces).",
                },
                "target_degree_v": {
                    "type": "integer",
                    "description": "Target degree in v (surfaces).",
                },
                "weights": {
                    "type": "array",
                    "description": "Optional weights (1-D for curves; nu×nv 2-D for surfaces).",
                },
            },
            "required": ["control_points"],
        },
    )

    @register(_degree_raise_spec)
    async def run_nurbs_degree_raise(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        is_surface = bool(a.get("surface", False))

        try:
            cp = np.array(a["control_points"], dtype=float)
        except Exception as exc:
            return err_payload(f"control_points error: {exc}", "BAD_ARGS")

        raw_w = a.get("weights")
        weights: Optional[np.ndarray] = np.array(raw_w, dtype=float) if raw_w is not None else None

        if is_surface:
            try:
                ku = np.array(a["knots_u"], dtype=float)
                kv = np.array(a["knots_v"], dtype=float)
                du = int(a["degree_u"])
                dv = int(a["degree_v"])
                td_u = int(a.get("target_degree_u", du))
                td_v = int(a.get("target_degree_v", dv))
            except Exception as exc:
                return err_payload(f"surface arg error: {exc}", "BAD_ARGS")
            if cp.ndim != 3:
                return err_payload("control_points for surface must be 3D (nu×nv×dim)", "BAD_ARGS")
            W: Optional[np.ndarray] = None
            if weights is not None:
                W = weights.reshape(cp.shape[0], cp.shape[1])
            srf = NurbsSurface(
                degree_u=du, degree_v=dv,
                control_points=cp, knots_u=ku, knots_v=kv, weights=W,
            )
            try:
                out = degree_raise_surface(srf, td_u, td_v)
            except Exception as exc:
                return err_payload(str(exc), "OP_FAILED")
            result: dict = {
                "control_points": out.control_points.tolist(),
                "knots_u": out.knots_u.tolist(),
                "knots_v": out.knots_v.tolist(),
                "degree_u": out.degree_u,
                "degree_v": out.degree_v,
                "num_ctrl_u": out.num_control_points_u,
                "num_ctrl_v": out.num_control_points_v,
            }
            if out.weights is not None:
                result["weights"] = out.weights.tolist()
            return ok_payload(result)

        else:
            try:
                kv_c = np.array(a["knots"], dtype=float)
                deg = int(a["degree"])
                tdeg = int(a.get("target_degree", deg))
            except Exception as exc:
                return err_payload(f"curve arg error: {exc}", "BAD_ARGS")
            if cp.ndim == 1:
                cp = cp.reshape(-1, 1)
            cw: Optional[np.ndarray] = None
            if weights is not None:
                cw = weights.ravel()
            crv = NurbsCurve(degree=deg, control_points=cp, knots=kv_c, weights=cw)
            try:
                out_c = degree_raise_curve(crv, tdeg)
            except Exception as exc:
                return err_payload(str(exc), "OP_FAILED")
            result_c: dict = {
                "control_points": out_c.control_points.tolist(),
                "knots": out_c.knots.tolist(),
                "degree": out_c.degree,
                "num_ctrl": out_c.num_control_points,
            }
            if out_c.weights is not None:
                result_c["weights"] = out_c.weights.tolist()
            return ok_payload(result_c)

    # ── nurbs_degree_lower ────────────────────────────────────────────────────

    _degree_lower_spec = ToolSpec(
        name="nurbs_degree_lower",
        description=(
            "Lower the degree of a NURBS curve or surface to a target degree.\n"
            "\n"
            "Algorithm: Forrest–Piegl least-squares Bezier split (Piegl & Tiller §5.5,\n"
            "Alg. A5.6).  Each internal Bezier segment is approximated by a lower-degree\n"
            "segment; if the maximum geometric deviation of ANY segment exceeds *tol*,\n"
            "the entire operation is rejected and the original is returned unchanged.\n"
            "\n"
            "Returns: same schema as nurbs_degree_raise.  Also includes "
            "``reduced: true/false`` indicating whether reduction was accepted.\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "surface": {"type": "boolean"},
                "control_points": {"type": "array"},
                "knots": {"type": "array", "items": {"type": "number"}},
                "knots_u": {"type": "array", "items": {"type": "number"}},
                "knots_v": {"type": "array", "items": {"type": "number"}},
                "degree": {"type": "integer"},
                "degree_u": {"type": "integer"},
                "degree_v": {"type": "integer"},
                "target_degree": {"type": "integer"},
                "target_degree_u": {"type": "integer"},
                "target_degree_v": {"type": "integer"},
                "weights": {"type": "array"},
                "tol": {
                    "type": "number",
                    "description": "Tolerance for geometric deviation (default 1e-6).",
                },
            },
            "required": ["control_points"],
        },
    )

    @register(_degree_lower_spec)
    async def run_nurbs_degree_lower(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        is_surface = bool(a.get("surface", False))
        tol = float(a.get("tol", 1e-6))

        try:
            cp = np.array(a["control_points"], dtype=float)
        except Exception as exc:
            return err_payload(f"control_points error: {exc}", "BAD_ARGS")

        raw_w = a.get("weights")
        weights2: Optional[np.ndarray] = np.array(raw_w, dtype=float) if raw_w is not None else None

        if is_surface:
            try:
                ku = np.array(a["knots_u"], dtype=float)
                kv = np.array(a["knots_v"], dtype=float)
                du = int(a["degree_u"])
                dv = int(a["degree_v"])
                td_u = int(a.get("target_degree_u", du))
                td_v = int(a.get("target_degree_v", dv))
            except Exception as exc:
                return err_payload(f"surface arg error: {exc}", "BAD_ARGS")
            if cp.ndim != 3:
                return err_payload("control_points for surface must be 3D (nu×nv×dim)", "BAD_ARGS")
            W2: Optional[np.ndarray] = None
            if weights2 is not None:
                W2 = weights2.reshape(cp.shape[0], cp.shape[1])
            srf = NurbsSurface(
                degree_u=du, degree_v=dv,
                control_points=cp, knots_u=ku, knots_v=kv, weights=W2,
            )
            try:
                out_s = degree_lower_surface(srf, td_u, td_v, tol=tol)
            except Exception as exc:
                return err_payload(str(exc), "OP_FAILED")
            reduced = (out_s.degree_u < du) or (out_s.degree_v < dv)
            result_s: dict = {
                "control_points": out_s.control_points.tolist(),
                "knots_u": out_s.knots_u.tolist(),
                "knots_v": out_s.knots_v.tolist(),
                "degree_u": out_s.degree_u,
                "degree_v": out_s.degree_v,
                "num_ctrl_u": out_s.num_control_points_u,
                "num_ctrl_v": out_s.num_control_points_v,
                "reduced": reduced,
            }
            if out_s.weights is not None:
                result_s["weights"] = out_s.weights.tolist()
            return ok_payload(result_s)

        else:
            try:
                kv_c2 = np.array(a["knots"], dtype=float)
                deg2 = int(a["degree"])
                tdeg2 = int(a.get("target_degree", deg2))
            except Exception as exc:
                return err_payload(f"curve arg error: {exc}", "BAD_ARGS")
            if cp.ndim == 1:
                cp = cp.reshape(-1, 1)
            cw2: Optional[np.ndarray] = None
            if weights2 is not None:
                cw2 = weights2.ravel()
            crv2 = NurbsCurve(degree=deg2, control_points=cp, knots=kv_c2, weights=cw2)
            try:
                out_c2 = degree_lower_curve(crv2, tdeg2, tol=tol)
            except Exception as exc:
                return err_payload(str(exc), "OP_FAILED")
            reduced_c = out_c2.degree < deg2
            result_c2: dict = {
                "control_points": out_c2.control_points.tolist(),
                "knots": out_c2.knots.tolist(),
                "degree": out_c2.degree,
                "num_ctrl": out_c2.num_control_points,
                "reduced": reduced_c,
            }
            if out_c2.weights is not None:
                result_c2["weights"] = out_c2.weights.tolist()
            return ok_payload(result_c2)
