"""
curve_split.py
==============
NURBS curve and surface splitting at an arbitrary parameter value.

Implements Piegl & Tiller §5.3: insert the split knot until its multiplicity
equals the curve degree, then partition control points and knots at the split
point.  Both halves are re-parametrised to [0, 1].

Rational (weighted) NURBS are handled correctly: knot insertion is performed
in homogeneous space (w·P, w), then projected back to Cartesian, matching the
exact Boehm / Piegl–Tiller algorithm.

Public API
----------
split_curve_at(curve, t) -> tuple[NurbsCurve, NurbsCurve]
    Split a NurbsCurve at parameter *t* into left [0, t] and right [t, 1]
    sub-curves, both re-parametrised to [0, 1].

split_curve_at_multiple(curve, t_values) -> list[NurbsCurve]
    Iteratively split at each value in *t_values* (sorted ascending).
    Returns N+1 sub-curves for N split points.

split_surface_at_u(surface, u) -> tuple[NurbsSurface, NurbsSurface]
    Split a NurbsSurface along the u-direction at parameter *u*.

split_surface_at_v(surface, v) -> tuple[NurbsSurface, NurbsSurface]
    Split a NurbsSurface along the v-direction at parameter *v*.

References
----------
- Piegl, L. & Tiller, W. (1997). *The NURBS Book*, 2nd ed.  §5.2–5.3.
"""

from __future__ import annotations

from typing import List, Tuple

import numpy as np

from kerf_cad_core.geom.nurbs import (
    NurbsCurve,
    NurbsSurface,
    find_span,
    knot_insertion,
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_TOL = 1e-10  # knot-equality tolerance


def _knot_multiplicity(knots: np.ndarray, u: float) -> int:
    """Count how many times *u* appears in *knots* (within _TOL)."""
    return int(np.sum(np.abs(knots - u) < _TOL))


def _insert_knot_once(curve: NurbsCurve, u: float) -> NurbsCurve:
    """Insert knot *u* into *curve* exactly once.

    Uses the standard Boehm recurrence in homogeneous coordinates
    (Piegl & Tiller Algorithm A5.1) to handle rational NURBS correctly.
    """
    p = curve.degree
    n = curve.num_control_points - 1
    U = curve.knots
    P = curve.control_points
    W = curve.weights
    dim = P.shape[1]

    # Work in homogeneous coordinates
    if W is not None:
        Pw = np.zeros((n + 1, dim + 1))
        Pw[:, :dim] = P * W[:, np.newaxis]
        Pw[:, dim] = W
    else:
        Pw = P  # non-rational: treat as-is (no homogeneous projection needed)

    k = find_span(n, p, u, U)
    s = _knot_multiplicity(U, u)  # current multiplicity

    # New knot vector
    new_U = np.empty(len(U) + 1)
    new_U[:k + 1] = U[:k + 1]
    new_U[k + 1] = u
    new_U[k + 2:] = U[k + 1:]

    # New control points (or homogeneous for rational)
    nc = n + 2  # new number of CPs
    if W is not None:
        new_Pw = np.zeros((nc, dim + 1))
    else:
        new_Pw = np.zeros((nc, dim))

    # Copy unaffected points
    new_Pw[:k - p + 1] = Pw[:k - p + 1]
    new_Pw[k - s + 1:] = Pw[k - s:]

    # Compute blended CPs in the affected range
    for i in range(k - p + 1, k - s + 1):
        denom = U[i + p] - U[i]
        alpha = (u - U[i]) / denom if abs(denom) > 1e-15 else 0.0
        new_Pw[i] = alpha * Pw[i] + (1.0 - alpha) * Pw[i - 1]

    if W is not None:
        new_w = new_Pw[:, dim]
        safe = np.abs(new_w) > 1e-300
        new_P = np.where(safe[:, np.newaxis],
                         new_Pw[:, :dim] / new_w[:, np.newaxis],
                         new_Pw[:, :dim])
        new_weights: np.ndarray | None = new_w.copy()
    else:
        new_P = new_Pw
        new_weights = None

    return NurbsCurve(degree=p, control_points=new_P, knots=new_U, weights=new_weights)


def _insert_knot_rational(
    curve: NurbsCurve,
    u: float,
    num_insertions: int,
) -> NurbsCurve:
    """Insert knot *u* into *curve* *num_insertions* times.

    Iterates :func:`_insert_knot_once` for correctness and simplicity.
    For rational NURBS the Boehm recurrence is performed in homogeneous space.
    """
    for _ in range(num_insertions):
        curve = _insert_knot_once(curve, u)
    return curve


def _ensure_multiplicity(curve: NurbsCurve, u: float, target_mult: int) -> NurbsCurve:
    """Insert knot *u* until its multiplicity in curve.knots is *target_mult*.

    If the current multiplicity >= target_mult, returns the curve unchanged.
    *target_mult* may be up to degree+1 (split point).
    """
    current = _knot_multiplicity(curve.knots, u)
    needed = target_mult - current
    if needed <= 0:
        return curve
    return _insert_knot_rational(curve, u, needed)


def _rescale_knots(knots: np.ndarray, a: float, b: float) -> np.ndarray:
    """Linearly map *knots* so the domain becomes [a, b]."""
    lo = float(knots[0])
    hi = float(knots[-1])
    span = hi - lo
    if abs(span) < 1e-15:
        return np.full_like(knots, a)
    return a + (b - a) * (knots - lo) / span


# ---------------------------------------------------------------------------
# Public API: curve split
# ---------------------------------------------------------------------------


def split_curve_at(
    curve: NurbsCurve,
    t: float,
) -> Tuple[NurbsCurve, NurbsCurve]:
    """Split *curve* at parameter *t* into left and right sub-curves.

    Implements Piegl & Tiller §5.3: insert knot *t* until its multiplicity
    equals the curve degree (``p`` insertions required beyond any existing
    multiplicity at *t*).  After insertion the control-point net is partitioned
    at the split index to produce two independent curves.  Both sub-curves are
    re-parametrised so their knot domains are [0, 1].

    Parameters
    ----------
    curve:
        Input NURBS curve.  May be rational or non-rational.  The knot domain
        must be normalised to [0, 1] (or *t* must lie within the existing
        domain).
    t:
        Split parameter.  Must satisfy ``knots[degree] < t < knots[-(degree+1)]``
        (strictly inside the open domain) to produce two non-degenerate curves.

    Returns
    -------
    (left, right):
        ``left``  covers the original domain from the start up to *t*, re-parametrised to [0, 1].
        ``right`` covers from *t* to the end of the original domain, re-parametrised to [0, 1].

    Raises
    ------
    ValueError
        If *t* is outside the curve's knot domain.
    """
    U = curve.knots
    p = curve.degree
    u0 = float(U[p])
    u1 = float(U[-(p + 1)])
    t = float(t)

    if t < u0 - _TOL or t > u1 + _TOL:
        raise ValueError(
            f"Split parameter t={t} is outside the curve domain [{u0}, {u1}]."
        )
    # Clamp to domain (handles floating-point boundary fuzz)
    t = min(max(t, u0), u1)

    # Insert knot *t* until its multiplicity = degree + 1.
    # Multiplicity p+1 is the "split" multiplicity: it makes the knot vector
    # into a join of two clamped sub-curves, each having p+1 copies of t at
    # their shared endpoint (Piegl & Tiller §5.3).
    refined = _ensure_multiplicity(curve, t, p + 1)

    new_U = refined.knots
    new_P = refined.control_points
    new_W = refined.weights

    # After inserting to multiplicity p+1, the knot vector contains p+1
    # consecutive copies of t.  The leftmost of these is at index `first_t`
    # and the rightmost at `last_t = first_t + p`.
    # After inserting t to multiplicity p+1, the knot vector has p+1 consecutive
    # copies of t starting at index `first_t`.
    first_t = int(np.searchsorted(new_U, t - _TOL, side='left'))
    last_t = first_t + p  # last index of the t-block (inclusive)

    # Sub-curve partition (Piegl & Tiller §5.3):
    #   left:  CPs [0 .. first_t - 1], knots new_U[0 .. last_t]  (ends with p+1 copies of t)
    #   right: CPs [first_t .. end],   knots new_U[first_t ..]   (starts with p+1 copies of t)
    # Both CPs are *not* shared — each sub-curve has its own endpoint at t (which
    # evaluates to the same 3D point but is stored independently).
    left_knots = new_U[:last_t + 1].copy()
    right_knots = new_U[first_t:].copy()

    left_P = new_P[:first_t].copy()
    right_P = new_P[first_t:].copy()

    left_W: np.ndarray | None = None
    right_W: np.ndarray | None = None
    if new_W is not None:
        left_W = new_W[:first_t].copy()
        right_W = new_W[first_t:].copy()

    # Re-parametrise each sub-curve to [0, 1]
    left_knots = _rescale_knots(left_knots, 0.0, 1.0)
    right_knots = _rescale_knots(right_knots, 0.0, 1.0)

    left_curve = NurbsCurve(
        degree=p,
        control_points=left_P,
        knots=left_knots,
        weights=left_W,
    )
    right_curve = NurbsCurve(
        degree=p,
        control_points=right_P,
        knots=right_knots,
        weights=right_W,
    )
    return left_curve, right_curve


def split_curve_at_multiple(
    curve: NurbsCurve,
    t_values: List[float],
) -> List[NurbsCurve]:
    """Split *curve* at each value in *t_values*.

    The split parameters are interpreted in the *original* curve's domain.
    Internally the curve is re-parametrised to [0, 1] after each split so that
    subsequent splits use a consistent [0, 1] coordinate system.

    Parameters
    ----------
    curve:
        Input NURBS curve.
    t_values:
        Split parameters in the original curve domain, sorted ascending.
        Duplicates are silently skipped.

    Returns
    -------
    list[NurbsCurve]
        N+1 sub-curves for N distinct split values.  Each curve has domain [0, 1].
    """
    if not t_values:
        return [curve]

    # Normalise the original curve to [0, 1] so all t_values are in [0, 1].
    U = curve.knots
    p = curve.degree
    domain_lo = float(U[p])
    domain_hi = float(U[-(p + 1)])
    domain_span = domain_hi - domain_lo

    # Map t_values to [0, 1], sort, remove duplicates / out-of-range.
    mapped: list[float] = []
    for t in t_values:
        t_norm = (float(t) - domain_lo) / domain_span if abs(domain_span) > 1e-15 else 0.0
        if _TOL < t_norm < 1.0 - _TOL:
            mapped.append(t_norm)
    mapped = sorted(set(f"{v:.15f}" for v in mapped))  # deduplicate via string
    mapped = [float(v) for v in mapped]

    if not mapped:
        return [curve]

    # Re-parametrise the input to [0, 1] once.
    from kerf_cad_core.geom.nurbs import normalize_knots
    work = normalize_knots(curve)

    segments: list[NurbsCurve] = []
    remaining = work
    # Accumulated left domain consumed so far (in [0,1] of the *original* curve)
    left_consumed = 0.0

    for t_norm in mapped:
        # t_norm is in [0,1] of the *original* normalised curve.
        # But 'remaining' has its own [0,1] domain covering [left_consumed, next].
        # We need to map t_norm into remaining's domain.
        # remaining covers [left_consumed, 1.0] of the original.
        # So t_in_remaining = (t_norm - left_consumed) / (1.0 - left_consumed)
        frac = (t_norm - left_consumed) / (1.0 - left_consumed + 1e-300)
        if frac <= _TOL or frac >= 1.0 - _TOL:
            continue  # skip degenerate split
        left_seg, remaining = split_curve_at(remaining, frac)
        segments.append(left_seg)
        left_consumed = t_norm

    segments.append(remaining)
    return segments


# ---------------------------------------------------------------------------
# Public API: surface split
# ---------------------------------------------------------------------------


def _surface_knot_insert_u(
    surface: NurbsSurface,
    u: float,
    num_insertions: int,
) -> NurbsSurface:
    """Insert knot *u* into the u-direction of *surface* *num_insertions* times.

    Applies 1D knot insertion to each row of iso-v curves (i.e., for each
    fixed v-index, the u-direction control-point row is refined).
    """
    if num_insertions <= 0:
        return surface

    n_v = surface.num_control_points_v
    # Build a temporary curve for each v-row, insert, collect results.
    rows_P: list[np.ndarray] = []
    rows_W: list[np.ndarray] | None = [] if surface.weights is not None else None
    new_knots_u: np.ndarray | None = None

    for j in range(n_v):
        row_P = surface.control_points[:, j, :]  # shape (n_u, dim)
        row_W = surface.weights[:, j] if surface.weights is not None else None
        tmp_curve = NurbsCurve(
            degree=surface.degree_u,
            control_points=row_P.copy(),
            knots=surface.knots_u.copy(),
            weights=row_W.copy() if row_W is not None else None,
        )
        refined = _insert_knot_rational(tmp_curve, u, num_insertions)
        rows_P.append(refined.control_points)
        if rows_W is not None and refined.weights is not None:
            rows_W.append(refined.weights)
        if new_knots_u is None:
            new_knots_u = refined.knots

    # Stack: shape (new_n_u, n_v, dim)
    stacked_P = np.stack(rows_P, axis=1)  # (new_n_u, n_v, dim)
    new_weights: np.ndarray | None = None
    if rows_W is not None and rows_W:
        new_weights = np.stack(rows_W, axis=1)  # (new_n_u, n_v)

    return NurbsSurface(
        degree_u=surface.degree_u,
        degree_v=surface.degree_v,
        control_points=stacked_P,
        knots_u=new_knots_u,
        knots_v=surface.knots_v.copy(),
        weights=new_weights,
    )


def _surface_knot_insert_v(
    surface: NurbsSurface,
    v: float,
    num_insertions: int,
) -> NurbsSurface:
    """Insert knot *v* into the v-direction of *surface* *num_insertions* times."""
    if num_insertions <= 0:
        return surface

    n_u = surface.num_control_points_u
    cols_P: list[np.ndarray] = []
    cols_W: list[np.ndarray] | None = [] if surface.weights is not None else None
    new_knots_v: np.ndarray | None = None

    for i in range(n_u):
        col_P = surface.control_points[i, :, :]  # shape (n_v, dim)
        col_W = surface.weights[i, :] if surface.weights is not None else None
        tmp_curve = NurbsCurve(
            degree=surface.degree_v,
            control_points=col_P.copy(),
            knots=surface.knots_v.copy(),
            weights=col_W.copy() if col_W is not None else None,
        )
        refined = _insert_knot_rational(tmp_curve, v, num_insertions)
        cols_P.append(refined.control_points)
        if cols_W is not None and refined.weights is not None:
            cols_W.append(refined.weights)
        if new_knots_v is None:
            new_knots_v = refined.knots

    # Stack: shape (n_u, new_n_v, dim)
    stacked_P = np.stack(cols_P, axis=0)  # (n_u, new_n_v, dim)
    new_weights: np.ndarray | None = None
    if cols_W is not None and cols_W:
        new_weights = np.stack(cols_W, axis=0)  # (n_u, new_n_v)

    return NurbsSurface(
        degree_u=surface.degree_u,
        degree_v=surface.degree_v,
        control_points=stacked_P,
        knots_u=surface.knots_u.copy(),
        knots_v=new_knots_v,
        weights=new_weights,
    )


def split_surface_at_u(
    surface: NurbsSurface,
    u: float,
) -> Tuple[NurbsSurface, NurbsSurface]:
    """Split *surface* at u-parameter *u*.

    Inserts knot *u* in the u-direction until its multiplicity equals
    ``degree_u``, then partitions the control-point grid.  Both halves are
    re-parametrised so their u-knot domains become [0, 1]; the v-direction is
    unchanged.

    Parameters
    ----------
    surface:
        Input NURBS surface.
    u:
        Split u-parameter.  Must lie strictly within the surface u-domain.

    Returns
    -------
    (left, right):
        ``left``  covers u ∈ [0, u_split], re-parametrised to [0, 1].
        ``right`` covers u ∈ [u_split, 1], re-parametrised to [0, 1].
    """
    Ku = surface.knots_u
    pu = surface.degree_u
    u0 = float(Ku[pu])
    u1 = float(Ku[-(pu + 1)])
    u = float(u)

    if u < u0 - _TOL or u > u1 + _TOL:
        raise ValueError(
            f"Split parameter u={u} is outside the surface u-domain [{u0}, {u1}]."
        )
    u = min(max(u, u0), u1)

    # Raise multiplicity to degree+1 in u-direction (split multiplicity)
    current_s = _knot_multiplicity(Ku, u)
    needed = (pu + 1) - current_s
    if needed > 0:
        refined = _surface_knot_insert_u(surface, u, needed)
    else:
        refined = surface

    new_Ku = refined.knots_u
    P = refined.control_points  # (new_n_u, n_v, dim)
    W = refined.weights  # (new_n_u, n_v) or None

    first_t = int(np.searchsorted(new_Ku, u - _TOL, side='left'))
    last_t = first_t + pu  # p+1 copies occupy first_t..first_t+p

    left_Ku = _rescale_knots(new_Ku[:last_t + 1].copy(), 0.0, 1.0)
    right_Ku = _rescale_knots(new_Ku[first_t:].copy(), 0.0, 1.0)

    left_P = P[:first_t, :, :].copy()
    right_P = P[first_t:, :, :].copy()

    left_W = W[:first_t, :].copy() if W is not None else None
    right_W = W[first_t:, :].copy() if W is not None else None

    left_surf = NurbsSurface(
        degree_u=pu,
        degree_v=surface.degree_v,
        control_points=left_P,
        knots_u=left_Ku,
        knots_v=surface.knots_v.copy(),
        weights=left_W,
    )
    right_surf = NurbsSurface(
        degree_u=pu,
        degree_v=surface.degree_v,
        control_points=right_P,
        knots_u=right_Ku,
        knots_v=surface.knots_v.copy(),
        weights=right_W,
    )
    return left_surf, right_surf


def split_surface_at_v(
    surface: NurbsSurface,
    v: float,
) -> Tuple[NurbsSurface, NurbsSurface]:
    """Split *surface* at v-parameter *v*.

    Mirrors :func:`split_surface_at_u` but operates on the v-direction.

    Returns
    -------
    (bottom, top):
        ``bottom`` covers v ∈ [0, v_split], re-parametrised to [0, 1].
        ``top``    covers v ∈ [v_split, 1], re-parametrised to [0, 1].
    """
    Kv = surface.knots_v
    pv = surface.degree_v
    v0 = float(Kv[pv])
    v1 = float(Kv[-(pv + 1)])
    v = float(v)

    if v < v0 - _TOL or v > v1 + _TOL:
        raise ValueError(
            f"Split parameter v={v} is outside the surface v-domain [{v0}, {v1}]."
        )
    v = min(max(v, v0), v1)

    current_s = _knot_multiplicity(Kv, v)
    needed = (pv + 1) - current_s
    if needed > 0:
        refined = _surface_knot_insert_v(surface, v, needed)
    else:
        refined = surface

    new_Kv = refined.knots_v
    P = refined.control_points  # (n_u, new_n_v, dim)
    W = refined.weights  # (n_u, new_n_v) or None

    first_t = int(np.searchsorted(new_Kv, v - _TOL, side='left'))
    last_t = first_t + pv

    bottom_Kv = _rescale_knots(new_Kv[:last_t + 1].copy(), 0.0, 1.0)
    top_Kv = _rescale_knots(new_Kv[first_t:].copy(), 0.0, 1.0)

    bottom_P = P[:, :first_t, :].copy()
    top_P = P[:, first_t:, :].copy()

    bottom_W = W[:, :first_t].copy() if W is not None else None
    top_W = W[:, first_t:].copy() if W is not None else None

    bottom_surf = NurbsSurface(
        degree_u=surface.degree_u,
        degree_v=pv,
        control_points=bottom_P,
        knots_u=surface.knots_u.copy(),
        knots_v=bottom_Kv,
        weights=bottom_W,
    )
    top_surf = NurbsSurface(
        degree_u=surface.degree_u,
        degree_v=pv,
        control_points=top_P,
        knots_u=surface.knots_u.copy(),
        knots_v=top_Kv,
        weights=top_W,
    )
    return bottom_surf, top_surf


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

    # ---- nurbs_split_curve --------------------------------------------------

    _split_curve_spec = ToolSpec(
        name="nurbs_split_curve",
        description=(
            "Split a NURBS curve at one or more parameter values using "
            "full-multiplicity knot insertion (Piegl–Tiller §5.3).  Both "
            "sub-curves are re-parametrised to [0, 1].  Handles rational "
            "(weighted) NURBS correctly.\n"
            "\n"
            "Returns: {ok, segments: [{control_points, knots, degree, weights?}, ...]}\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "control_points": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                    "description": "Control points [[x,y,z], ...] of the NURBS curve.",
                },
                "knots": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Knot vector (clamped [0,1] expected).",
                },
                "degree": {
                    "type": "integer",
                    "description": "Curve degree.",
                },
                "weights": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Optional per-control-point weights for rational NURBS.",
                },
                "t_values": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": (
                        "One or more parameter values in [0,1] at which to split. "
                        "A single value produces 2 sub-curves; N values produce N+1."
                    ),
                },
            },
            "required": ["control_points", "knots", "degree", "t_values"],
        },
    )

    @register(_split_curve_spec)
    async def run_nurbs_split_curve(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")
        try:
            cps = np.array(a["control_points"], dtype=float)
            knots = np.array(a["knots"], dtype=float)
            degree = int(a["degree"])
            weights = np.array(a["weights"], dtype=float) if a.get("weights") else None
            t_values = [float(v) for v in a["t_values"]]
            curve = NurbsCurve(degree=degree, control_points=cps, knots=knots, weights=weights)
        except Exception as exc:
            return err_payload(f"bad input: {exc}", "BAD_ARGS")
        try:
            if len(t_values) == 1:
                left, right = split_curve_at(curve, t_values[0])
                segments = [left, right]
            else:
                segments = split_curve_at_multiple(curve, t_values)
        except Exception as exc:
            return err_payload(str(exc), "OP_FAILED")

        def _seg_dict(c: NurbsCurve) -> dict:
            d = {
                "control_points": c.control_points.tolist(),
                "knots": c.knots.tolist(),
                "degree": c.degree,
            }
            if c.weights is not None:
                d["weights"] = c.weights.tolist()
            return d

        return ok_payload({"segments": [_seg_dict(s) for s in segments]})

    # ---- nurbs_split_surface -------------------------------------------------

    _split_surface_spec = ToolSpec(
        name="nurbs_split_surface",
        description=(
            "Split a NURBS surface at a u or v parameter value using "
            "full-multiplicity knot insertion in the specified direction.  "
            "Both halves are re-parametrised to [0, 1] in the split direction; "
            "the orthogonal direction is unchanged.\n"
            "\n"
            "Returns: {ok, left: {control_points, knots_u, knots_v, degree_u, degree_v, weights?}, "
            "right: {...}}\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "control_points": {
                    "type": "array",
                    "description": "3D array [nu][nv][dim] of control points.",
                },
                "knots_u": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "u knot vector.",
                },
                "knots_v": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "v knot vector.",
                },
                "degree_u": {"type": "integer"},
                "degree_v": {"type": "integer"},
                "weights": {
                    "type": "array",
                    "description": "Optional 2D weight array [nu][nv].",
                },
                "direction": {
                    "type": "string",
                    "enum": ["u", "v"],
                    "description": "Direction to split: 'u' or 'v'.",
                },
                "t": {
                    "type": "number",
                    "description": "Split parameter in [0, 1].",
                },
            },
            "required": ["control_points", "knots_u", "knots_v",
                         "degree_u", "degree_v", "direction", "t"],
        },
    )

    @register(_split_surface_spec)
    async def run_nurbs_split_surface(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")
        try:
            cps = np.array(a["control_points"], dtype=float)
            ku = np.array(a["knots_u"], dtype=float)
            kv = np.array(a["knots_v"], dtype=float)
            du = int(a["degree_u"])
            dv = int(a["degree_v"])
            weights = np.array(a["weights"], dtype=float) if a.get("weights") else None
            direction = str(a["direction"])
            t = float(a["t"])
            if cps.ndim != 3:
                raise ValueError("control_points must be 3D array [nu][nv][dim]")
            surface = NurbsSurface(
                degree_u=du, degree_v=dv,
                control_points=cps, knots_u=ku, knots_v=kv,
                weights=weights,
            )
        except Exception as exc:
            return err_payload(f"bad input: {exc}", "BAD_ARGS")
        try:
            if direction == "u":
                left, right = split_surface_at_u(surface, t)
            elif direction == "v":
                left, right = split_surface_at_v(surface, t)
            else:
                return err_payload("direction must be 'u' or 'v'", "BAD_ARGS")
        except Exception as exc:
            return err_payload(str(exc), "OP_FAILED")

        def _srf_dict(s: NurbsSurface) -> dict:
            d = {
                "control_points": s.control_points.tolist(),
                "knots_u": s.knots_u.tolist(),
                "knots_v": s.knots_v.tolist(),
                "degree_u": s.degree_u,
                "degree_v": s.degree_v,
            }
            if s.weights is not None:
                d["weights"] = s.weights.tolist()
            return d

        return ok_payload({"left": _srf_dict(left), "right": _srf_dict(right)})
