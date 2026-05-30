"""NURBS iso-curve extraction.

Given a NurbsSurface S(u, v) and a fixed parameter value, extracts the
corresponding iso-curve as a parametric NurbsCurve (not just sampled points).

Algorithm — Piegl & Tiller §5.3 (knot-insertion approach):

For a *u-iso* at u=u₀:
    1. Treat each row of the surface control net as a degree-p_u B-spline curve
       in the u direction.
    2. Insert the knot u₀ exactly (p_u + 1 − s) times into the u knot vector
       so that u₀ has multiplicity p_u + 1, making it a Bezier breakpoint.
    3. The column of new control points that corresponds to span(u₀) forms the
       control polygon of the iso-curve C(t) = S(u₀, t).
    4. The degree of the resulting curve is degree_v; the knot vector is
       knots_v unchanged.

For a *v-iso* at v=v₀, the roles are symmetric.

Rational surfaces (weights != None) are handled in homogeneous coordinates:
  Pw_ij = [w_ij * x_ij, w_ij * y_ij, w_ij * z_ij, w_ij]
The output NurbsCurve carries the correct Cartesian control points and weight
vector extracted from the homogeneous result.

Honest caveat
-------------
Surfaces with non-clamped knot vectors (first/last knot multiplicities < p+1)
do NOT clamp to their control polygon at the boundary.  Extracting an iso-curve
at the exact boundary parameter of such a surface will give numerically correct
results (the algorithm works regardless), but the extracted curve's endpoints
may not coincide with the corner points of the control net — which can look
surprising.  Use clamped (open) knot vectors for predictable endpoint behaviour.

Public API
----------
    extract_iso_curve_u(srf, u)  -> NurbsCurve  (fixed-u iso, varies in v)
    extract_iso_curve_v(srf, v)  -> NurbsCurve  (fixed-v iso, varies in u)
    extract_iso_grid(srf, u_count, v_count) -> {"u_curves": [...], "v_curves": [...]}
"""

from __future__ import annotations

import numpy as np
from typing import List, Dict

from kerf_cad_core.geom.nurbs import (
    NurbsCurve,
    NurbsSurface,
    find_span,  # used in _insert_knot_direction
)

__all__ = [
    "extract_iso_curve_u",
    "extract_iso_curve_v",
    "extract_iso_grid",
]


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------


def _homogeneous_cps(cps: np.ndarray, weights) -> np.ndarray:
    """Return homogeneous control points Pw (…, dim+1) from Cartesian + weights."""
    dim = cps.shape[-1]
    if weights is None:
        # All weights = 1; Pw = [x, y, z, 1]
        shape = cps.shape[:-1] + (dim + 1,)
        Pw = np.ones(shape, dtype=float)
        Pw[..., :dim] = cps
        return Pw
    # weights array has same leading shape as cps[..., 0]
    w = weights[..., np.newaxis]          # broadcast: (…, 1)
    xyz_w = cps * w                       # (…, dim)
    return np.concatenate([xyz_w, w], axis=-1)


def _cartesian_from_homogeneous(Pw: np.ndarray):
    """Split homogeneous CPs back into Cartesian CPs + weight vector.

    If all weights are 1 (within 1e-12) the returned weights array is None.
    """
    w = Pw[..., -1]
    xyz = Pw[..., :-1] / w[..., np.newaxis]
    if np.allclose(w, 1.0, atol=1e-12):
        return xyz, None
    return xyz, w


# ---------------------------------------------------------------------------
# Knot-insertion along one parametric direction — vectorised over the other
# ---------------------------------------------------------------------------


def _insert_knot_direction(
    cps_2d: np.ndarray,
    knots: np.ndarray,
    degree: int,
    u_bar: float,
) -> tuple:
    """Insert u_bar into *knots* until it has multiplicity *degree+1*.

    Parameters
    ----------
    cps_2d : (n_insert, n_other, dim_h) array of homogeneous CPs.
        - For u-iso: axis-0 = u direction, axis-1 = v direction.
        - For v-iso: axis-0 = v direction, axis-1 = u direction.
    knots  : 1-D knot vector for the insert direction (length m+1 = n+degree+2).
    degree : B-spline degree in the insert direction.
    u_bar  : parameter value to insert.

    Returns
    -------
    new_cps  : updated control-point array (same shape except axis-0 grows).
    new_knots: updated knot vector.

    The algorithm follows Piegl-Tiller Algorithm A5.1 (knot insertion),
    applied simultaneously to every "row" (slice along axis-1).
    """
    s_existing = int(np.sum(np.abs(knots - u_bar) < 1e-10))
    num_to_insert = degree + 1 - s_existing
    if num_to_insert <= 0:
        return cps_2d, knots.copy()

    P = cps_2d

    for _ in range(num_to_insert):
        n_curr = P.shape[0] - 1
        k = find_span(n_curr, degree, u_bar, knots)
        s_curr = int(np.sum(np.abs(knots - u_bar) < 1e-10))

        # New knot vector
        new_knots = np.zeros(len(knots) + 1)
        new_knots[:k + 1] = knots[:k + 1]
        new_knots[k + 1] = u_bar
        new_knots[k + 2:] = knots[k + 1:]

        # New control points (shape: n_curr+2, n_other, dim_h)
        new_P = np.zeros((n_curr + 2, P.shape[1], P.shape[2]))

        # Pass-through unchanged points
        for j in range(k - degree + 1):
            new_P[j] = P[j]
        for j in range(k - s_curr, n_curr + 1):
            new_P[j + 1] = P[j]

        # Blend points in the affected span
        for j in range(k - degree + 1, k - s_curr + 1):
            denom = knots[j + degree] - knots[j]
            if abs(denom) < 1e-14:
                alpha = 0.0
            else:
                alpha = (u_bar - knots[j]) / denom
            new_P[j] = (1.0 - alpha) * P[j - 1] + alpha * P[j]

        P = new_P
        knots = new_knots

    return P, knots


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_iso_curve_u(srf: NurbsSurface, u: float) -> NurbsCurve:
    """Extract the iso-curve C(t) = S(u₀, t) as a NurbsCurve.

    Parameters
    ----------
    srf : NurbsSurface
    u   : fixed u parameter (must lie in [knots_u[0], knots_u[-1]])

    Returns
    -------
    NurbsCurve of degree = srf.degree_v with n_v control points.
    """
    u = float(u)
    u0 = float(srf.knots_u[0])
    u1 = float(srf.knots_u[-1])
    if u < u0 - 1e-10 or u > u1 + 1e-10:
        raise ValueError(f"u={u!r} out of knot range [{u0}, {u1}]")
    u = float(np.clip(u, u0, u1))

    # Build homogeneous CP array: shape (nu, nv, dim+1)
    Pw = _homogeneous_cps(srf.control_points, srf.weights)  # (nu, nv, dim+1)

    degree_u = srf.degree_u
    knots_u = srf.knots_u.copy()

    # Insert u until multiplicity degree_u+1
    new_Pw, new_ku = _insert_knot_direction(Pw, knots_u, degree_u, u)

    # Find the iso-curve row: after full knot insertion, the contiguous run of
    # u in new_ku spans [a, b].  The iso CP row is at index max(0, a - 1).
    # This is correct for left boundary (a=0 -> row 0), interior (a-1), and
    # right boundary (a = first occurrence of u_end -> last valid row).
    mask = np.abs(new_ku - u) < 1e-10
    first_occ = int(np.argmax(mask))   # index of first u in new_ku
    iso_idx = max(0, first_occ - 1)
    iso_idx = min(iso_idx, new_Pw.shape[0] - 1)
    iso_Pw = new_Pw[iso_idx, :, :]  # (nv, dim+1)

    iso_xyz, iso_w = _cartesian_from_homogeneous(iso_Pw)
    return NurbsCurve(
        degree=srf.degree_v,
        control_points=iso_xyz,
        knots=srf.knots_v.copy(),
        weights=iso_w,
    )


def extract_iso_curve_v(srf: NurbsSurface, v: float) -> NurbsCurve:
    """Extract the iso-curve C(t) = S(t, v₀) as a NurbsCurve.

    Parameters
    ----------
    srf : NurbsSurface
    v   : fixed v parameter (must lie in [knots_v[0], knots_v[-1]])

    Returns
    -------
    NurbsCurve of degree = srf.degree_u with n_u control points.
    """
    v = float(v)
    v0 = float(srf.knots_v[0])
    v1 = float(srf.knots_v[-1])
    if v < v0 - 1e-10 or v > v1 + 1e-10:
        raise ValueError(f"v={v!r} out of knot range [{v0}, {v1}]")
    v = float(np.clip(v, v0, v1))

    # Build homogeneous CP array: shape (nu, nv, dim+1)
    Pw = _homogeneous_cps(srf.control_points, srf.weights)  # (nu, nv, dim+1)

    # For v-iso we work in the v direction: transpose so v is axis-0
    # Pw_T shape: (nv, nu, dim+1)
    Pw_T = np.transpose(Pw, (1, 0, 2))

    degree_v = srf.degree_v
    knots_v = srf.knots_v.copy()

    new_Pw_T, new_kv = _insert_knot_direction(Pw_T, knots_v, degree_v, v)

    mask = np.abs(new_kv - v) < 1e-10
    first_occ = int(np.argmax(mask))
    iso_idx = max(0, first_occ - 1)
    iso_idx = min(iso_idx, new_Pw_T.shape[0] - 1)
    iso_Pw = new_Pw_T[iso_idx, :, :]  # (nu, dim+1)

    iso_xyz, iso_w = _cartesian_from_homogeneous(iso_Pw)
    return NurbsCurve(
        degree=srf.degree_u,
        control_points=iso_xyz,
        knots=srf.knots_u.copy(),
        weights=iso_w,
    )


def extract_iso_grid(
    srf: NurbsSurface,
    u_count: int,
    v_count: int,
) -> Dict[str, List[NurbsCurve]]:
    """Extract a grid of iso-curves.

    Parameters
    ----------
    srf     : NurbsSurface
    u_count : number of u-iso-curves (evenly spaced u values).
    v_count : number of v-iso-curves (evenly spaced v values).

    Returns
    -------
    dict with keys:
        "u_curves": list of *u_count* NurbsCurve objects (fixed-u, vary v).
        "v_curves": list of *v_count* NurbsCurve objects (fixed-v, vary u).
    """
    if u_count < 1 or v_count < 1:
        raise ValueError("u_count and v_count must be >= 1")

    u0, u1 = float(srf.knots_u[0]), float(srf.knots_u[-1])
    v0, v1 = float(srf.knots_v[0]), float(srf.knots_v[-1])

    u_params = np.linspace(u0, u1, u_count)
    v_params = np.linspace(v0, v1, v_count)

    u_curves = [extract_iso_curve_u(srf, float(u)) for u in u_params]
    v_curves = [extract_iso_curve_v(srf, float(v)) for v in v_params]

    return {"u_curves": u_curves, "v_curves": v_curves}


# ---------------------------------------------------------------------------
# LLM tool registration
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import (  # type: ignore[import]
        ToolSpec,
        err_payload,
        ok_payload,
        register,
    )
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json

    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:
    # ------------------------------------------------------------------
    # Shared surface deserialization helper
    # ------------------------------------------------------------------

    def _parse_surface(a: dict):
        """Return NurbsSurface or an error string."""
        try:
            du = int(a["degree_u"])
            dv = int(a["degree_v"])
            nu = int(a["num_u"])
            nv = int(a["num_v"])
        except (KeyError, TypeError, ValueError) as exc:
            return f"degree_u/degree_v/num_u/num_v required and must be integers: {exc}"

        raw_cp = a.get("control_points")
        ku_raw = a.get("knots_u")
        kv_raw = a.get("knots_v")
        if raw_cp is None or ku_raw is None or kv_raw is None:
            return "control_points, knots_u, knots_v are required"

        try:
            flat = np.asarray(raw_cp, dtype=float)
            if flat.ndim == 1:
                dim = len(flat) // (nu * nv)
                flat = flat.reshape(nu, nv, dim)
            elif flat.ndim == 2:
                dim = flat.shape[1]
                flat = flat.reshape(nu, nv, dim)
            else:
                flat = flat.reshape(nu, nv, flat.shape[-1])
        except Exception as exc:
            return f"could not reshape control_points to ({nu},{nv},dim): {exc}"

        try:
            ku = np.asarray(ku_raw, dtype=float)
            kv = np.asarray(kv_raw, dtype=float)
        except Exception as exc:
            return f"invalid knots: {exc}"

        weights = None
        raw_w = a.get("weights")
        if raw_w is not None:
            try:
                weights = np.asarray(raw_w, dtype=float).reshape(nu, nv)
            except Exception as exc:
                return f"invalid weights: {exc}"

        try:
            return NurbsSurface(
                degree_u=du,
                degree_v=dv,
                control_points=flat,
                knots_u=ku,
                knots_v=kv,
                weights=weights,
            )
        except Exception as exc:
            return f"NurbsSurface construction failed: {exc}"

    # ------------------------------------------------------------------
    # nurbs_extract_iso_u
    # ------------------------------------------------------------------

    _extract_iso_u_spec = ToolSpec(
        name="nurbs_extract_iso_u",
        description=(
            "Extract a u-iso-curve C(t) = S(u0, t) from a NURBS surface as a "
            "full parametric NurbsCurve (not just sampled points).  The result "
            "has degree = surface degree_v and the same v knot vector; control "
            "points are computed via the Piegl-Tiller §5.3 knot-insertion "
            "algorithm.\n\n"
            "Returns:\n"
            "  ok              : bool\n"
            "  degree          : int — degree of extracted curve\n"
            "  control_points  : [[x,y,z], ...] — cartesian control points\n"
            "  knots           : [k, ...] — knot vector\n"
            "  weights         : [w, ...] or null (null = non-rational)\n"
            "  num_control_pts : int\n\n"
            "Errors: {ok:false, reason, code}."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "degree_u": {"type": "integer", "description": "Surface degree in U."},
                "degree_v": {"type": "integer", "description": "Surface degree in V."},
                "num_u": {"type": "integer", "description": "Number of CPs in U direction."},
                "num_v": {"type": "integer", "description": "Number of CPs in V direction."},
                "control_points": {
                    "type": "array",
                    "description": "Flat list of [[x,y,z], ...] in row-major (u-first) order.",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "knots_u": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Knot vector in U direction.",
                },
                "knots_v": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Knot vector in V direction.",
                },
                "weights": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Flat (nu*nv) weight array for rational surfaces; omit for non-rational.",
                },
                "u": {
                    "type": "number",
                    "description": "Fixed u parameter value at which to extract the iso-curve.",
                },
            },
            "required": ["degree_u", "degree_v", "num_u", "num_v", "control_points",
                         "knots_u", "knots_v", "u"],
        },
    )

    @register(_extract_iso_u_spec)
    async def run_nurbs_extract_iso_u(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")

        u_val = a.get("u")
        if u_val is None:
            return err_payload("'u' parameter is required", "BAD_ARGS")

        srf = _parse_surface(a)
        if isinstance(srf, str):
            return err_payload(srf, "BAD_ARGS")

        try:
            curve = extract_iso_curve_u(srf, float(u_val))
        except Exception as exc:
            return err_payload(f"iso-curve extraction failed: {exc}", "OP_FAILED")

        return ok_payload({
            "degree": curve.degree,
            "control_points": curve.control_points.tolist(),
            "knots": curve.knots.tolist(),
            "weights": curve.weights.tolist() if curve.weights is not None else None,
            "num_control_pts": curve.num_control_points,
        })

    # ------------------------------------------------------------------
    # nurbs_extract_iso_v
    # ------------------------------------------------------------------

    _extract_iso_v_spec = ToolSpec(
        name="nurbs_extract_iso_v",
        description=(
            "Extract a v-iso-curve C(t) = S(t, v0) from a NURBS surface as a "
            "full parametric NurbsCurve.  The result has degree = surface degree_u "
            "and the same u knot vector; control points are computed via the "
            "Piegl-Tiller §5.3 knot-insertion algorithm.\n\n"
            "Returns:\n"
            "  ok              : bool\n"
            "  degree          : int\n"
            "  control_points  : [[x,y,z], ...]\n"
            "  knots           : [k, ...]\n"
            "  weights         : [w, ...] or null\n"
            "  num_control_pts : int\n\n"
            "Errors: {ok:false, reason, code}."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "degree_u": {"type": "integer"},
                "degree_v": {"type": "integer"},
                "num_u": {"type": "integer"},
                "num_v": {"type": "integer"},
                "control_points": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "knots_u": {"type": "array", "items": {"type": "number"}},
                "knots_v": {"type": "array", "items": {"type": "number"}},
                "weights": {"type": "array", "items": {"type": "number"}},
                "v": {
                    "type": "number",
                    "description": "Fixed v parameter value at which to extract the iso-curve.",
                },
            },
            "required": ["degree_u", "degree_v", "num_u", "num_v", "control_points",
                         "knots_u", "knots_v", "v"],
        },
    )

    @register(_extract_iso_v_spec)
    async def run_nurbs_extract_iso_v(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")

        v_val = a.get("v")
        if v_val is None:
            return err_payload("'v' parameter is required", "BAD_ARGS")

        srf = _parse_surface(a)
        if isinstance(srf, str):
            return err_payload(srf, "BAD_ARGS")

        try:
            curve = extract_iso_curve_v(srf, float(v_val))
        except Exception as exc:
            return err_payload(f"iso-curve extraction failed: {exc}", "OP_FAILED")

        return ok_payload({
            "degree": curve.degree,
            "control_points": curve.control_points.tolist(),
            "knots": curve.knots.tolist(),
            "weights": curve.weights.tolist() if curve.weights is not None else None,
            "num_control_pts": curve.num_control_points,
        })
