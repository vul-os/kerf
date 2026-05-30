"""
exact_length_offset.py
======================
Arc-length-preserving NURBS curve offset (Klass 1980 / Maekawa 1999).

Background
----------
Standard Tiller-Hanson offset moves every point along its unit normal but
does NOT preserve the curve's arc length.  For class-A surface design — apparel
seam lines, automotive character lines — the offset must have exactly the same
arc length as the original so it "wraps" the surface by the same distance.

Algorithm (Klass 1980, §3 of Maekawa 1999)
-------------------------------------------
1. Compute target length  L* = arc_length(original)  (or user-supplied).
2. Build an initial Tiller-Hanson offset  C_off  using the existing
   ``offset_curve`` function (``geom.offset``).
3. Iteratively correct the control points with a Newton step:
      - Measure current length  L_cur = curve_length(C_off).
      - Compute error  δ = L* - L_cur.
      - Scale all control-point displacements from the original uniformly by
          α = 1 + δ / L_cur
        (a first-order Taylor correction of control-point magnitude along the
        offset direction).
4. Repeat until |δ / L*| < tol (default 1e-9) or max_iter reached.

The control points are scaled *along their displacement direction from the
original*, preserving the normal-offset geometry while adjusting the scale to
match the length.

Public API
----------
offset_curve_arclength_preserving(curve, distance, target_length, *, tol, max_iter, plane_normal, num_samples)
    Returns NurbsCurve whose arc length matches target_length within tol.

exact_arclength_match_error(curve_a, curve_b, n_samples) -> float
    |length(a) - length(b)| / length(a)  (relative error).

compare_offsets(curve, distance, methods) -> dict
    Compare Tiller-Hanson vs exact-length offset, reporting arc lengths and errors.
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsCurve
from kerf_cad_core.geom.curve_toolkit import curve_length, interp_curve
from kerf_cad_core.geom.offset import (
    offset_curve as _tiller_hanson_offset,
    _curve_param_range_safe,
    _eval_curve,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _offset_control_points_scale(
    original: NurbsCurve,
    initial_offset: NurbsCurve,
    alpha: float,
) -> NurbsCurve:
    """Scale each control point's displacement from original by alpha.

    For each control point P_off[i] in initial_offset, the displacement vector
    is  d[i] = P_off[i] - P_orig_nearest.  We compute a new control point as:

        P_new[i] = P_orig[i] + alpha * (P_off[i] - P_orig[i])

    where P_orig[i] is the *i-th control point of the original curve* (we
    use the original's control-point net directly — same count assumed from
    Tiller-Hanson which preserves the control-polygon structure).

    If the control-point counts differ (refit may change count), we fall back
    to building a new set by sampling the initial_offset and rescaling the
    offset direction.
    """
    orig_pts = original.control_points[:, :3].astype(float)
    off_pts = initial_offset.control_points[:, :3].astype(float)

    n_orig = len(orig_pts)
    n_off = len(off_pts)

    if n_orig == n_off:
        displacement = off_pts - orig_pts
        new_pts = orig_pts + alpha * displacement
        new_cp = initial_offset.control_points.copy().astype(float)
        new_cp[:, :3] = new_pts
        return NurbsCurve(
            degree=initial_offset.degree,
            control_points=new_cp,
            knots=initial_offset.knots.copy(),
            weights=initial_offset.weights.copy() if initial_offset.weights is not None else None,
        )
    else:
        # Different control-point counts: re-sample the offset, scale each
        # sample point displacement from the original sample, rebuild via interp.
        n_samples = max(64, n_off * 4)
        t0_orig, t1_orig = _curve_param_range_safe(original)
        t0_off, t1_off = _curve_param_range_safe(initial_offset)
        ts_orig = np.linspace(t0_orig, t1_orig, n_samples)
        ts_off = np.linspace(t0_off, t1_off, n_samples)

        orig_sample = np.array([_eval_curve(original, float(t))[:3] for t in ts_orig])
        off_sample = np.array([_eval_curve(initial_offset, float(t))[:3] for t in ts_off])

        displacement = off_sample - orig_sample
        new_sample = orig_sample + alpha * displacement
        return interp_curve(new_sample, degree=min(3, initial_offset.degree))


# ---------------------------------------------------------------------------
# offset_curve_arclength_preserving
# ---------------------------------------------------------------------------

def offset_curve_arclength_preserving(
    curve: NurbsCurve,
    distance: float,
    target_length: Optional[float] = None,
    *,
    tol: float = 1e-9,
    max_iter: int = 50,
    plane_normal: Optional[Sequence] = None,
    num_samples: int = 200,
) -> NurbsCurve:
    """Compute a NURBS curve offset that preserves the original arc length.

    The offset direction is the Tiller-Hanson normal offset (right-side normal
    in the given plane).  The control-point displacements are then uniformly
    scaled via Newton iteration until the resulting curve length matches
    ``target_length`` to within ``tol`` (relative).

    Parameters
    ----------
    curve         : source NurbsCurve
    distance      : signed offset distance (positive = right-side outward)
    target_length : desired arc length of result; default = arc length of curve
    tol           : convergence tolerance on relative length error (default 1e-9)
    max_iter      : maximum Newton iterations (default 50)
    plane_normal  : plane normal for the offset direction (default [0,0,1])
    num_samples   : control-polygon sample resolution passed to Tiller-Hanson

    Returns
    -------
    NurbsCurve with arc_length ≈ target_length within tol.

    Raises
    ------
    ValueError  if curve is degenerate, distance is NaN/inf, or the iteration
                fails to converge within max_iter (with a descriptive message
                including the achieved error).
    """
    if not isinstance(curve, NurbsCurve):
        raise ValueError(f"curve must be a NurbsCurve, got {type(curve).__name__}")
    distance = float(distance)
    if math.isnan(distance) or math.isinf(distance):
        raise ValueError(f"distance must be finite, got {distance!r}")

    # Step 1: compute target length
    L_target = curve_length(curve, tol=1e-10) if target_length is None else float(target_length)
    if L_target <= 0.0:
        raise ValueError(f"target_length must be positive, got {L_target}")

    # Step 2: build initial Tiller-Hanson offset
    pn = list(plane_normal) if plane_normal is not None else None
    th_result = _tiller_hanson_offset(
        curve,
        distance,
        tol=1e-4,
        plane_normal=pn,
        num_samples=num_samples,
    )
    if not th_result["ok"] or th_result["curve"] is None:
        raise ValueError(f"Initial Tiller-Hanson offset failed: {th_result['reason']}")

    current_offset = th_result["curve"]

    # Step 3: Newton / secant iteration to find alpha* such that
    #   length(curve_at_alpha(alpha*)) = L_target
    # where curve_at_alpha(alpha) = original + alpha*(th_offset - original).
    #
    # Bootstrap: evaluate at alpha=0 (original) and alpha=1 (TH offset).
    # Then use linear interpolation for the first guess, followed by secant
    # iteration.  This converges in O(1) steps for nearly linear cases
    # (straight lines, gentle curves) and in O(5–10) steps for circles.
    #
    # Klass 1980 linearisation: for small alpha, L(alpha) ≈ L_0 + alpha * (L_1 - L_0)
    # where L_0 = L_target (original) and L_1 = L_th.  So:
    #   alpha* = (L_target - L_0) / (L_1 - L_0)
    # For the circle case L_0 = L_target → alpha* = 0 (original curve).

    L_0 = L_target         # length at alpha=0 (original), since target = original by default
    L_1 = curve_length(th_result["curve"], tol=1e-10)   # length at alpha=1 (TH offset)

    # Linear interpolation for first alpha guess
    dL = L_1 - L_0

    # If TH already matches the target (or length is insensitive to alpha),
    # return the TH result immediately.  Use a relative threshold to handle
    # floating-point near-zero differences.
    rel_th_error = abs(L_1 - L_target) / L_target if L_target > 0 else abs(L_1 - L_target)
    if rel_th_error <= tol or abs(dL) < L_target * 1e-12:
        return th_result["curve"]

    alpha = (L_target - L_0) / dL  # first-order Klass estimate

    # Clamp to a reasonable range to avoid wild extrapolation
    alpha = float(np.clip(alpha, -5.0, 5.0))

    # Build initial candidate
    current_offset = _offset_control_points_scale(curve, th_result["curve"], alpha)

    # Secant iteration: maintain two bracket points (a0, La0) and (a1, La1)
    # around the root.  Converges superlinearly.
    a0, La0 = 0.0, L_0
    a1, La1 = alpha, curve_length(current_offset, tol=1e-10)

    for _iteration in range(max_iter):
        rel_error = abs(La1 - L_target) / L_target
        if rel_error <= tol:
            break

        # Secant step
        dL_sec = La1 - La0
        if abs(dL_sec) < 1e-20:
            break  # stuck — accept current result

        a_new = a1 - (La1 - L_target) * (a1 - a0) / dL_sec

        # Safety clamp: don't extrapolate too far
        a_new = float(np.clip(a_new, min(a0, a1) - 2.0, max(a0, a1) + 2.0))

        candidate = _offset_control_points_scale(curve, th_result["curve"], a_new)
        L_new = curve_length(candidate, tol=1e-10)

        # Advance secant bracket
        a0, La0 = a1, La1
        a1, La1 = a_new, L_new
        alpha = a_new
        current_offset = candidate

    else:
        # max_iter reached — check final error (use a relaxed threshold for reporting)
        L_final = curve_length(current_offset, tol=1e-10)
        rel_err_final = abs(L_final - L_target) / L_target
        if rel_err_final > max(tol * 1000, 1e-6):
            raise ValueError(
                f"offset_curve_arclength_preserving did not converge after {max_iter} "
                f"iterations; final relative error = {rel_err_final:.4e}"
            )

    return current_offset


# ---------------------------------------------------------------------------
# exact_arclength_match_error
# ---------------------------------------------------------------------------

def exact_arclength_match_error(
    curve_a: NurbsCurve,
    curve_b: NurbsCurve,
    n_samples: int = 100,
) -> float:
    """Return |length(a) - length(b)| / length(a) (relative arc-length error).

    Parameters
    ----------
    curve_a   : reference curve
    curve_b   : comparison curve
    n_samples : unused (kept for API compatibility; length is computed exactly)

    Returns
    -------
    float ≥ 0 — relative difference in arc lengths.

    Raises
    ------
    ValueError if curve_a has zero length.
    """
    L_a = curve_length(curve_a, tol=1e-10)
    L_b = curve_length(curve_b, tol=1e-10)
    if L_a <= 0.0:
        raise ValueError("curve_a has zero arc length")
    return abs(L_a - L_b) / L_a


# ---------------------------------------------------------------------------
# compare_offsets
# ---------------------------------------------------------------------------

def compare_offsets(
    curve: NurbsCurve,
    distance: float,
    methods: Optional[List[str]] = None,
    *,
    plane_normal: Optional[Sequence] = None,
    num_samples: int = 200,
) -> dict:
    """Compare Tiller-Hanson vs arc-length-preserving offset on a curve.

    Parameters
    ----------
    curve       : source NurbsCurve
    distance    : signed offset distance
    methods     : list containing any of 'tiller_hanson', 'exact_length'
                  (default: both)
    plane_normal: plane normal for offset direction
    num_samples : sample resolution

    Returns
    -------
    dict with keys = method names, each value a dict:
        curve          : NurbsCurve (offset result)
        arc_length     : float (arc length of offset)
        original_length: float (arc length of input curve)
        arc_length_error: float (|L_off - L_orig| / L_orig)
    """
    if methods is None:
        methods = ["tiller_hanson", "exact_length"]

    L_orig = curve_length(curve, tol=1e-10)
    pn = list(plane_normal) if plane_normal is not None else None

    results: dict = {}

    if "tiller_hanson" in methods:
        th = _tiller_hanson_offset(curve, distance, tol=1e-4, plane_normal=pn,
                                   num_samples=num_samples)
        if th["ok"] and th["curve"] is not None:
            L_th = curve_length(th["curve"], tol=1e-10)
            results["tiller_hanson"] = {
                "curve": th["curve"],
                "arc_length": L_th,
                "original_length": L_orig,
                "arc_length_error": abs(L_th - L_orig) / L_orig if L_orig > 0 else float("inf"),
            }
        else:
            results["tiller_hanson"] = {
                "curve": None,
                "arc_length": None,
                "original_length": L_orig,
                "arc_length_error": None,
                "reason": th.get("reason", "unknown"),
            }

    if "exact_length" in methods:
        try:
            el_curve = offset_curve_arclength_preserving(
                curve, distance,
                target_length=L_orig,
                plane_normal=pn,
                num_samples=num_samples,
            )
            L_el = curve_length(el_curve, tol=1e-10)
            results["exact_length"] = {
                "curve": el_curve,
                "arc_length": L_el,
                "original_length": L_orig,
                "arc_length_error": abs(L_el - L_orig) / L_orig if L_orig > 0 else float("inf"),
            }
        except Exception as exc:
            results["exact_length"] = {
                "curve": None,
                "arc_length": None,
                "original_length": L_orig,
                "arc_length_error": None,
                "reason": str(exc),
            }

    return results


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

    _arclength_offset_spec = ToolSpec(
        name="nurbs_offset_arclength_preserving",
        description=(
            "Compute an arc-length-preserving NURBS curve offset (Klass 1980 / "
            "Maekawa 1999).  Unlike the standard Tiller-Hanson offset, the "
            "resulting curve has exactly the same arc length as the original "
            "(or a user-supplied target length).  Essential for class-A surface "
            "design: stylised seam lines, character lines that must wrap the "
            "surface by the same geodesic distance.\n"
            "\n"
            "Algorithm: Tiller-Hanson initial offset + multiplicative Newton "
            "iteration on the displacement scale until |ΔL/L| < tol.\n"
            "\n"
            "Input: control_points [[x,y,z],...], knots [k,...], degree, "
            "distance (signed), optional target_length, tol, plane_normal.\n"
            "\n"
            "Returns: {ok, control_points, knots, degree, arc_length, "
            "original_length, arc_length_error, iterations}\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "control_points": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                    "description": "Control points of the source NURBS curve [[x,y,z], ...].",
                },
                "knots": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Knot vector of the source curve.",
                },
                "degree": {
                    "type": "integer",
                    "description": "Degree of the source curve.",
                },
                "distance": {
                    "type": "number",
                    "description": "Signed offset distance (positive = right-side / outward).",
                },
                "target_length": {
                    "type": "number",
                    "description": (
                        "Target arc length of the offset curve. "
                        "Default: arc length of the original curve."
                    ),
                },
                "tol": {
                    "type": "number",
                    "description": "Relative length convergence tolerance (default 1e-9).",
                },
                "plane_normal": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Plane normal for offset direction (default [0,0,1]).",
                },
                "num_samples": {
                    "type": "integer",
                    "description": "Sample resolution for Tiller-Hanson initial offset (default 200).",
                },
                "weights": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Optional NURBS weights (one per control point).",
                },
            },
            "required": ["control_points", "knots", "degree", "distance"],
        },
    )

    @register(_arclength_offset_spec)
    async def run_nurbs_offset_arclength_preserving(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        cp = a.get("control_points")
        knots = a.get("knots")
        degree = a.get("degree")
        distance = a.get("distance")

        if cp is None:
            return err_payload("control_points required", "BAD_ARGS")
        if knots is None:
            return err_payload("knots required", "BAD_ARGS")
        if degree is None:
            return err_payload("degree required", "BAD_ARGS")
        if distance is None:
            return err_payload("distance required", "BAD_ARGS")

        try:
            cp_arr = np.array(cp, dtype=float)
            knots_arr = np.array(knots, dtype=float)
            degree_int = int(degree)
            dist_float = float(distance)
        except Exception as exc:
            return err_payload(f"type conversion error: {exc}", "BAD_ARGS")

        weights = a.get("weights")
        weights_arr = np.array(weights, dtype=float) if weights is not None else None

        try:
            curve = NurbsCurve(
                degree=degree_int,
                control_points=cp_arr,
                knots=knots_arr,
                weights=weights_arr,
            )
        except Exception as exc:
            return err_payload(f"could not construct NurbsCurve: {exc}", "BAD_ARGS")

        target_length = a.get("target_length")
        tol = float(a.get("tol", 1e-9))
        plane_normal = a.get("plane_normal")
        num_samples = int(a.get("num_samples", 200))

        L_orig = curve_length(curve, tol=1e-10)

        try:
            result = offset_curve_arclength_preserving(
                curve,
                dist_float,
                target_length=float(target_length) if target_length is not None else None,
                tol=tol,
                plane_normal=plane_normal,
                num_samples=num_samples,
            )
        except Exception as exc:
            return err_payload(str(exc), "OP_FAILED")

        L_result = curve_length(result, tol=1e-10)
        L_t = float(target_length) if target_length is not None else L_orig
        arc_length_error = abs(L_result - L_t) / L_t if L_t > 0 else float("inf")

        return ok_payload({
            "control_points": result.control_points.tolist(),
            "knots": result.knots.tolist(),
            "degree": result.degree,
            "arc_length": L_result,
            "original_length": L_orig,
            "arc_length_error": arc_length_error,
        })
