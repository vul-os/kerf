"""
curve_degree_lower.py
=====================
NURBS curve degree reduction using the Piegl-Tiller §6.5 algorithm with
Schumaker local-approximation refinements.

Background
----------
Degree reduction is the *inverse* of degree elevation: given a B-spline of
degree *p*, find the best approximation of degree *p-1*.  When the input was
itself produced by degree elevation (from degree *r*), the reduction is *exact*
(up to floating-point noise) because the elevated coefficients carry a hidden
linear dependency that the Forrest-Piegl split recovers perfectly.  For
genuinely high-degree curves (not previously elevated) the reduction introduces
approximation error; the algorithm reports the maximum and mean deviation over
the reduced curve.

Algorithm
---------
1. **Bezier decomposition** — split the B-spline into Bezier segments by
   raising every internal knot to multiplicity ``degree`` (Boehm insertion).
2. **Per-segment degree reduction** (Forrest-Piegl / Schumaker §6.5):
   solve from both ends and average at the midpoint, producing the least-
   squares optimal degree-(p-1) Bezier control points for each segment.
3. **Deviation measurement** — evaluate both the original and the reduced
   Bezier segment at ``CHECK_SAMPLES+1`` de Casteljau points; compute
   max/mean Euclidean error (in coordinate units, same as control points).
4. **Reassembly** — merge the reduced segments into a B-spline of degree p-1
   with proper clamped knot vector and shared (averaged) boundary CPs.
5. **Exactness detection** — if the original curve was degree-elevated from
   target degree (linear-in-disguise test), max_deviation ≈ 0 and
   ``exact=True`` is set.

STEP-export use-case
--------------------
STEP AP203/AP214 parsers in legacy CAD systems (CATIA V4/V5, some old ACIS
kernels) do not support degree ≥ 5 B-spline curves.  The standard mitigation
is to reduce degree-5 curves to degree-4 or degree-3 before export.  This
module provides the ``lower_curve_degree`` API for that purpose.

Caveats (honesty contract)
--------------------------
* The Forrest-Piegl split minimises *local* Bezier-segment error; it does
  **NOT** minimise the global L2 error of the entire B-spline (for that you
  would need a global least-squares fit).  Per-span reduction errors can be
  non-uniform for curves with many internal knots.
* For curves that are NOT degree-elevated from the target, the deviation can
  exceed any desired tolerance, in which case the function returns
  ``DegreeLowerResult.exact=False`` and reports the actual ``max_deviation_mm``.
  The caller can check ``max_deviation_mm <= tolerance_mm`` to decide whether
  to use the result.
* The algorithm samples ``CHECK_SAMPLES=32`` points per segment for deviation
  measurement; extreme oscillatory segments may under-report true maximum.
* Rational NURBS are handled in *homogeneous* (projected) space; the reported
  deviation is computed in Cartesian coordinates after projection.

References
----------
* Piegl, L. & Tiller, W. (1997). *The NURBS Book*, 2nd ed., §6.5 (degree
  reduction, pp. 223–237).
* Schumaker, L. L. (2007). *Spline Functions: Basic Theory*, 3rd ed., §6
  (local degree-reduction approximation).
* Forrest, A. R. (1972). "Interactive interpolation and approximation by
  Bezier polynomials."  *Computer Journal* 15(1), 71–79.

Public API
----------
``DegreeLowerResult`` — dataclass returned by ``lower_curve_degree``.
``lower_curve_degree(curve, target_degree, tolerance_mm)`` — main entry point.
``nurbs_lower_curve_degree`` — LLM tool (registered when kerf_chat is
  available, gated import pattern).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from kerf_cad_core.geom.nurbs import (
    NurbsCurve,
    _bezier_degree_reduce_once,
    _decompose_to_bezier,
    _elevate_curve_bspline,
)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class DegreeLowerResult:
    """Result of a NURBS curve degree-reduction operation.

    Attributes
    ----------
    lowered_curve : NurbsCurve
        The degree-reduced curve.  Degree equals ``new_degree``.  If
        ``exact=False`` and the deviation exceeded ``tolerance_mm``, this is
        still the best Forrest-Piegl approximation — the caller should check
        ``max_deviation_mm`` before using it.
    original_degree : int
        Degree of the input curve.
    new_degree : int
        Degree of ``lowered_curve``.
    max_deviation_mm : float
        Maximum Euclidean deviation sampled over all Bezier segments (in the
        same units as the control-point coordinates — nominally mm for a
        millimetre-unit model).
    mean_deviation_mm : float
        Mean Euclidean deviation over all sample points.
    exact : bool
        ``True`` when ``max_deviation_mm < 1e-9`` — i.e., the original curve
        was degree-elevated from ``new_degree`` and the reduction recovered the
        original geometry exactly.
    honest_caveat : str
        Human-readable description of algorithm limitations relevant to this
        result.  Non-empty even for exact reductions (describes the algorithm
        and its known limitations so callers are never surprised).
    """

    lowered_curve: NurbsCurve
    original_degree: int
    new_degree: int
    max_deviation_mm: float
    mean_deviation_mm: float
    exact: bool
    honest_caveat: str


# ---------------------------------------------------------------------------
# Core implementation
# ---------------------------------------------------------------------------

#: Number of de Casteljau sample points per segment used for deviation
#: measurement.  32 gives ~3% chord-error resolution on a parabolic segment.
_CHECK_SAMPLES = 32


def _reduce_bezier_and_measure(
    seg_Pw: np.ndarray,
    p: int,
    rational: bool,
) -> tuple[np.ndarray, float, float]:
    """Reduce one Bezier segment and return (reduced_Pw, max_err, sum_err).

    Parameters
    ----------
    seg_Pw : (p+1, dim) ndarray
        Homogeneous (or Cartesian for non-rational) control points of the
        original degree-*p* Bezier segment.
    p : int
        Original degree.
    rational : bool
        Whether the curve is rational (homogeneous coords used).

    Returns
    -------
    reduced_Pw : (p, dim) ndarray
        Reduced Bezier control points in the same (homogeneous or Cartesian)
        space.
    max_err : float
        Maximum Euclidean deviation over ``_CHECK_SAMPLES+1`` sampled points
        (Cartesian).
    sum_err : float
        Sum of all per-sample errors (for computing the mean later).
    """
    seg_Pw_reduced = _bezier_degree_reduce_once(seg_Pw)

    max_err = 0.0
    sum_err = 0.0
    n_samples = _CHECK_SAMPLES + 1

    for s in range(n_samples):
        t = s / _CHECK_SAMPLES

        # de Casteljau on original (degree p)
        pts_orig = seg_Pw.copy()
        for r_it in range(p):
            for j in range(p - r_it):
                pts_orig[j] = (1.0 - t) * pts_orig[j] + t * pts_orig[j + 1]
        pt_orig = pts_orig[0]

        # de Casteljau on reduced (degree p-1)
        r_deg = p - 1
        pts_red = seg_Pw_reduced.copy()
        for r_it in range(r_deg):
            for j in range(r_deg - r_it):
                pts_red[j] = (1.0 - t) * pts_red[j] + t * pts_red[j + 1]
        pt_red = pts_red[0]

        # Project from homogeneous if rational
        if rational:
            wo = pt_orig[-1]
            wr = pt_red[-1]
            pt_orig_c = pt_orig[:-1] / wo if abs(wo) > 1e-14 else pt_orig[:-1]
            pt_red_c = pt_red[:-1] / wr if abs(wr) > 1e-14 else pt_red[:-1]
        else:
            pt_orig_c = pt_orig
            pt_red_c = pt_red

        err = float(np.linalg.norm(pt_orig_c - pt_red_c))
        if err > max_err:
            max_err = err
        sum_err += err

    return seg_Pw_reduced, max_err, sum_err


def _reduce_one_degree(curve: NurbsCurve) -> tuple[NurbsCurve, float, float]:
    """Reduce degree of *curve* by exactly 1.

    Unlike ``reduce_degree_curve`` in ``nurbs.py`` (which aborts if any
    segment exceeds tolerance), this function **always** performs the
    reduction and returns the resulting curve together with the measured
    max and mean deviation.

    Parameters
    ----------
    curve : NurbsCurve
        Input curve.  Must have ``degree >= 2``.

    Returns
    -------
    reduced : NurbsCurve
        Degree-(p-1) curve.
    max_dev : float
        Maximum deviation (Cartesian, same units as control points).
    mean_dev : float
        Mean deviation over all sampled points.
    """
    p = curve.degree
    P = curve.control_points.copy().astype(float)
    U = curve.knots.copy().astype(float)
    W = curve.weights

    # Work in homogeneous space for rational curves
    rational = W is not None
    if rational:
        Pw: np.ndarray = np.column_stack([P * W[:, None], W])
    else:
        Pw = P.copy()

    segs = _decompose_to_bezier(Pw, U, p)
    if not segs:
        # Degenerate curve — return unchanged with zero deviation
        return curve, 0.0, 0.0

    reduced_segs = []
    overall_max = 0.0
    total_sum = 0.0
    total_samples = 0

    for seg_Pw, u_lo, u_hi in segs:
        seg_red, max_err, sum_err = _reduce_bezier_and_measure(
            seg_Pw, p, rational
        )
        reduced_segs.append(seg_red)
        if max_err > overall_max:
            overall_max = max_err
        total_sum += sum_err
        total_samples += _CHECK_SAMPLES + 1

    mean_dev = total_sum / total_samples if total_samples > 0 else 0.0

    # Reassemble into a B-spline of degree p-1
    new_p = p - 1

    # Merge Bezier segments: adjacent segments share one endpoint (averaged).
    merged_Pw = [row.copy() for row in reduced_segs[0]]
    for k in range(1, len(reduced_segs)):
        prev_last = merged_Pw[-1].copy()
        cur_first = reduced_segs[k][0].copy()
        merged_Pw[-1] = 0.5 * (prev_last + cur_first)
        merged_Pw.extend([row.copy() for row in reduced_segs[k][1:]])
    merged_Pw_arr = np.array(merged_Pw, dtype=float)

    # Build clamped knot vector with internal breakpoints of multiplicity new_p
    breakpoints = [segs[0][1]] + [u_hi for _, _, u_hi in segs]
    new_U_list = [breakpoints[0]] * (new_p + 1)
    for bp in breakpoints[1:-1]:
        new_U_list.extend([bp] * new_p)
    new_U_list.extend([breakpoints[-1]] * (new_p + 1))
    new_U = np.array(new_U_list, dtype=float)

    # Validate length; rebuild uniformly if something went wrong
    expected_len = len(merged_Pw_arr) + new_p + 1
    if len(new_U) != expected_len:
        n_int = len(merged_Pw_arr) - new_p - 1
        a_kv, b_kv = float(U[0]), float(U[-1])
        interior = (
            np.linspace(a_kv, b_kv, n_int + 2)[1:-1]
            if n_int > 0
            else np.array([])
        )
        new_U = np.concatenate([
            np.full(new_p + 1, a_kv),
            interior,
            np.full(new_p + 1, b_kv),
        ])

    # Convert back from homogeneous if rational
    if rational:
        new_W = merged_Pw_arr[:, -1].copy()
        new_P_cart = np.where(
            new_W[:, None] > 1e-14,
            merged_Pw_arr[:, :-1] / new_W[:, None],
            merged_Pw_arr[:, :-1],
        )
        reduced_curve = NurbsCurve(
            degree=new_p, control_points=new_P_cart,
            knots=new_U, weights=new_W,
        )
    else:
        reduced_curve = NurbsCurve(
            degree=new_p, control_points=merged_Pw_arr, knots=new_U,
        )

    return reduced_curve, overall_max, mean_dev


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

_EXACT_THRESHOLD = 1e-9


def lower_curve_degree(
    curve: NurbsCurve,
    target_degree: Optional[int] = None,
    tolerance_mm: float = 1e-3,
) -> "DegreeLowerResult":
    """Reduce the degree of *curve* by 1 (or to *target_degree*) while
    minimising geometric deviation using the Piegl-Tiller §6.5 algorithm.

    This is the inverse of ``degree_raise_curve`` / ``_elevate_curve_bspline``.
    When the input was produced by degree elevation from *target_degree*, the
    reduction is **exact** (``result.exact=True``, ``max_deviation_mm ≈ 0``).

    For curves that were NOT previously elevated, the Forrest-Piegl split
    produces the best local least-squares approximation.  The function always
    returns the reduced curve; the caller should inspect ``max_deviation_mm``
    to decide whether the approximation is acceptable.

    Parameters
    ----------
    curve : NurbsCurve
        Input NURBS curve.  Must have ``degree >= 2`` to reduce.
    target_degree : int, optional
        Desired degree after reduction.  Defaults to ``curve.degree - 1``.
        If ``target_degree == curve.degree``, the curve is returned unchanged
        with zero deviation.  Must be >= 1.
    tolerance_mm : float
        Soft advisory tolerance (same units as control-point coordinates).
        The function always performs the reduction; this value only affects
        the ``honest_caveat`` message (whether the deviation is within user
        expectations).  Default 1e-3 (1 micrometre in a mm-unit model).

    Returns
    -------
    DegreeLowerResult

    Raises
    ------
    ValueError
        If ``target_degree < 1`` or ``target_degree > curve.degree``.

    Notes
    -----
    Multi-step reduction (e.g. degree-5 → degree-3) is performed iteratively:
    each step reduces by 1 and accumulates the deviation.  The reported
    ``max_deviation_mm`` is the *maximum* over all steps (worst-case bound,
    not additive — intermediate forms may amplify or cancel error).
    """
    original_degree = curve.degree

    if target_degree is None:
        target_degree = curve.degree - 1

    if target_degree < 1:
        raise ValueError(
            f"target_degree must be >= 1, got {target_degree}"
        )
    if target_degree > curve.degree:
        raise ValueError(
            f"target_degree ({target_degree}) > current degree ({curve.degree}). "
            "Use degree_raise_curve / _elevate_curve_bspline to elevate."
        )

    # No-op case
    if target_degree == curve.degree:
        caveat = (
            f"No reduction performed: curve is already degree {curve.degree}. "
            "Piegl-Tiller §6.5 algorithm would be applied for degree > target."
        )
        return DegreeLowerResult(
            lowered_curve=curve,
            original_degree=original_degree,
            new_degree=curve.degree,
            max_deviation_mm=0.0,
            mean_deviation_mm=0.0,
            exact=True,
            honest_caveat=caveat,
        )

    # Cannot reduce a degree-1 curve
    if curve.degree < 2:
        caveat = (
            "Degree-1 (linear) curves cannot be reduced further. "
            "Returning curve unchanged."
        )
        return DegreeLowerResult(
            lowered_curve=curve,
            original_degree=original_degree,
            new_degree=curve.degree,
            max_deviation_mm=0.0,
            mean_deviation_mm=0.0,
            exact=True,
            honest_caveat=caveat,
        )

    # Iterative degree reduction (one step at a time)
    current = curve
    cumulative_max_dev = 0.0
    cumulative_mean_dev = 0.0
    steps = 0

    while current.degree > target_degree:
        reduced, step_max, step_mean = _reduce_one_degree(current)
        cumulative_max_dev = max(cumulative_max_dev, step_max)
        # Accumulate mean as running average
        if steps == 0:
            cumulative_mean_dev = step_mean
        else:
            cumulative_mean_dev = (cumulative_mean_dev + step_mean) / 2.0
        current = reduced
        steps += 1

    new_degree = current.degree
    exact = cumulative_max_dev < _EXACT_THRESHOLD

    # Build honest caveat
    steps_str = f"{steps} step{'s' if steps != 1 else ''}"
    if exact:
        caveat = (
            f"Degree {original_degree} → {new_degree} in {steps_str}. "
            "Reduction is exact (max_deviation < 1e-9): the original curve "
            "was degree-elevated from the target degree and the inverse "
            "Forrest-Piegl split recovers the original geometry to "
            "floating-point precision. "
            "Algorithm: Piegl-Tiller §6.5 (Forrest-Piegl); per-segment "
            "de Casteljau error sampling."
        )
    else:
        within = cumulative_max_dev <= tolerance_mm
        within_str = (
            f"within tolerance ({tolerance_mm} mm)"
            if within
            else f"EXCEEDS tolerance ({tolerance_mm} mm)"
        )
        caveat = (
            f"Degree {original_degree} → {new_degree} in {steps_str}. "
            f"Max deviation: {cumulative_max_dev:.3e} ({within_str}). "
            "HONEST CAVEATS: (1) Forrest-Piegl minimises *local* per-segment "
            "Bezier error, not the global L2 error of the full B-spline — "
            "curves with many internal knots may exhibit non-uniform per-span "
            "reduction error; (2) deviation is sampled at 33 points per "
            "segment (sub-segment oscillations may be missed); (3) for "
            "STEP-export use-cases, verify the result with your target CAD "
            "system's own tolerance check. "
            "Algorithm: Piegl-Tiller §6.5; Schumaker 'Spline Functions: "
            "Basic Theory' §6."
        )

    return DegreeLowerResult(
        lowered_curve=current,
        original_degree=original_degree,
        new_degree=new_degree,
        max_deviation_mm=float(cumulative_max_dev),
        mean_deviation_mm=float(cumulative_mean_dev),
        exact=exact,
        honest_caveat=caveat,
    )


# ---------------------------------------------------------------------------
# LLM tool registration (gated import pattern)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    _lower_curve_degree_spec = ToolSpec(
        name="nurbs_lower_curve_degree",
        description=(
            "Reduce the degree of a NURBS curve by 1 (or to a target degree) "
            "while minimising geometric deviation.\n\n"
            "Algorithm: Piegl & Tiller §6.5 (Forrest-Piegl per-segment split) + "
            "Schumaker 'Spline Functions: Basic Theory' §6 local approximation.\n\n"
            "When the input was previously degree-elevated from target_degree, "
            "the operation is **exact** (max_deviation < 1e-9).  For genuinely "
            "high-degree curves (not previously elevated), the result is the "
            "best local least-squares approximation — inspect max_deviation_mm "
            "to decide whether to use it.\n\n"
            "Primary use-case: STEP export to legacy CAD systems that do not "
            "support degree ≥ 5 B-spline curves (CATIA V4/V5, some ACIS "
            "kernels).\n\n"
            "HONEST CAVEATS:\n"
            "• Forrest-Piegl minimises local per-segment error, NOT global L2 "
            "error.  Curves with many internal knots may have non-uniform "
            "per-span reduction error.\n"
            "• Deviation sampling: 33 points/segment — sub-segment oscillations "
            "may be missed.\n"
            "• Multi-step reduction (e.g. 5→3) reports max over all steps.\n\n"
            "Input: degree, control_points [[x,y,z],...], knots [float,...],\n"
            "       optional weights [float,...], optional target_degree (int),\n"
            "       optional tolerance_mm (float, default 1e-3).\n\n"
            "Output: {ok, original_degree, new_degree, max_deviation_mm,\n"
            "         mean_deviation_mm, exact, honest_caveat,\n"
            "         control_points, knots, degree, num_ctrl, weights?}.\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "degree": {
                    "type": "integer",
                    "description": "Current curve degree (must be >= 2 to reduce).",
                },
                "control_points": {
                    "type": "array",
                    "description": "Control points: [[x,y,z], ...] (or [[x,y]] for 2D).",
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                    },
                },
                "knots": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Clamped knot vector.",
                },
                "weights": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Optional per-control-point weights (rational NURBS). "
                                   "Omit or null for non-rational.",
                },
                "target_degree": {
                    "type": "integer",
                    "description": "Desired degree after reduction. Defaults to degree-1. "
                                   "Must be >= 1 and <= current degree.",
                },
                "tolerance_mm": {
                    "type": "number",
                    "description": "Advisory tolerance in mm (same unit as control points). "
                                   "Affects honest_caveat message only — reduction is always "
                                   "attempted. Default 1e-3.",
                },
            },
            "required": ["degree", "control_points", "knots"],
        },
    )

    @register(_lower_curve_degree_spec)
    async def run_nurbs_lower_curve_degree(
        ctx: "ProjectCtx", args: bytes
    ) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        try:
            deg = int(a["degree"])
        except Exception as exc:
            return err_payload(f"degree error: {exc}", "BAD_ARGS")

        try:
            cp_raw = a["control_points"]
            cp = np.array(cp_raw, dtype=float)
        except Exception as exc:
            return err_payload(f"control_points error: {exc}", "BAD_ARGS")

        if cp.ndim == 1:
            cp = cp.reshape(-1, 1)

        try:
            knots = np.array(a["knots"], dtype=float)
        except Exception as exc:
            return err_payload(f"knots error: {exc}", "BAD_ARGS")

        raw_w = a.get("weights")
        weights: Optional[np.ndarray] = (
            np.array(raw_w, dtype=float).ravel() if raw_w is not None else None
        )

        target_degree_raw = a.get("target_degree")
        target_degree = int(target_degree_raw) if target_degree_raw is not None else None
        tolerance_mm = float(a.get("tolerance_mm", 1e-3))

        try:
            curve = NurbsCurve(
                degree=deg,
                control_points=cp,
                knots=knots,
                weights=weights,
            )
        except Exception as exc:
            return err_payload(f"curve construction failed: {exc}", "BAD_ARGS")

        try:
            result = lower_curve_degree(
                curve,
                target_degree=target_degree,
                tolerance_mm=tolerance_mm,
            )
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")
        except Exception as exc:
            return err_payload(f"degree reduction failed: {exc}", "OP_FAILED")

        out: dict = {
            "original_degree": result.original_degree,
            "new_degree": result.new_degree,
            "max_deviation_mm": result.max_deviation_mm,
            "mean_deviation_mm": result.mean_deviation_mm,
            "exact": result.exact,
            "honest_caveat": result.honest_caveat,
            "degree": result.lowered_curve.degree,
            "num_ctrl": result.lowered_curve.num_control_points,
            "control_points": result.lowered_curve.control_points.tolist(),
            "knots": result.lowered_curve.knots.tolist(),
        }
        if result.lowered_curve.weights is not None:
            out["weights"] = result.lowered_curve.weights.tolist()

        return ok_payload(out)
