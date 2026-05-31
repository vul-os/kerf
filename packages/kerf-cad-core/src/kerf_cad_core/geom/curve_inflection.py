"""
NURBS-CURVE-INFLECTION
======================
Find inflection points of a 2D NURBS curve — where signed curvature κ(t)
changes sign (from positive to negative or vice-versa).

Theory
------
For a plane curve C(t) = (x(t), y(t)) the *signed* curvature is:

    κ_signed(t) = (x'·y'' − y'·x'') / |C'|³

A point where κ_signed(t) = 0 AND dκ/dt ≠ 0 is called an *inflection point*
(do Carmo §1.5; Sapidis "Designing Fair Curves and Surfaces" §3).

At an inflection point the curve transitions from bending left (κ > 0) to
bending right (κ < 0) or vice-versa — the osculating circle switches side.

Algorithm
---------
1. Sample t uniformly in [t_min, t_max] at `num_samples` positions.
2. Compute κ_signed(t_i) at each sample via analytical NURBS 1st/2nd
   derivatives (Piegl & Tiller §9.1 / §9.2).
3. Detect adjacent-sample sign changes of κ_signed (ignoring near-zero
   samples with |κ| < threshold to suppress false positives in near-zero
   curvature regions).
4. For each detected sign-change interval [t_lo, t_hi], refine with 5
   iterations of bisection to locate the zero crossing to high precision.

Honest caveats
--------------
* 2D curves only.  Input must be a NurbsCurve with 2D control points, or a 3D
  curve whose z-components are negligible.  3D space-curve inflections (where
  the osculating plane changes) are not computed.
* Near-zero-curvature regions (|κ| < threshold) are treated as zero during
  sign-change detection.  Curves with very low curvature throughout (e.g.
  near-lines) may yield 0 inflections even when the curvature technically
  crosses zero — raise the threshold to suppress false positives, or lower it
  to detect gentle transitions.
* A straight line (κ ≡ 0) has no well-defined inflection points.
  `num_inflections = 0` and `honest_caveat` states the reason.
* Sample density controls detection reliability: undersampled curves may miss
  inflections that occur within a single sample interval.

Applications
------------
* Fairness analysis — even-κ-sign curves are "fair" (no unwanted inflections)
* Sketch QC — flag unintended S-curves in sketch segments
* Toolpath transitions — avoid κ-sign changes during constant-feed machining
* Clothoid design — inflection = boundary between left/right clothoid arcs

References
----------
do Carmo, M.P. (1976) "Differential Geometry of Curves and Surfaces" §1.5.
Sapidis, N.S. ed. (1994) "Designing Fair Curves and Surfaces" §3
    (AMS SIAM Geometric Design Publications).
Piegl, L. & Tiller, W. (1997) "The NURBS Book" §9.1/§9.2 (curve derivatives).
Farin, G. (1997) "Curves and Surfaces for CAGD" §5.5 (curvature of a curve).

Public API
----------
InflectionResult   — dataclass with result fields.
find_curve_inflections(curve_or_points, num_samples=200, threshold=1e-9)
    -> InflectionResult
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Sequence, Tuple, Union

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsCurve, curve_derivative

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SPEED_TOL: float = 1e-12   # |C'| below this → singular
_BISECT_ITERS: int = 5       # bisection refinement iterations per crossing


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class InflectionResult:
    """Result of find_curve_inflections().

    Attributes
    ----------
    inflection_t_params : list[float]
        Parameter values t where κ_signed changes sign (refined by bisection).
    num_inflections : int
        Number of inflection points detected.  Equals len(inflection_t_params).
    signed_curvature_samples : list[tuple[float, float]]
        Uniform samples (t, κ_signed) across the curve's parameter domain.
        Useful for plotting the full curvature profile.
    honest_caveat : str
        Plain-language caveat about scope, accuracy, and edge cases.
    """

    inflection_t_params: List[float] = field(default_factory=list)
    num_inflections: int = 0
    signed_curvature_samples: List[Tuple[float, float]] = field(default_factory=list)
    honest_caveat: str = ""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _param_range(curve: NurbsCurve) -> Tuple[float, float]:
    """Return (t_min, t_max) of the clamped NURBS domain."""
    t_min = float(curve.knots[curve.degree])
    t_max = float(curve.knots[-(curve.degree + 1)])
    return t_min, t_max


def _signed_kappa(curve: NurbsCurve, t: float) -> float:
    """Evaluate the signed curvature κ_signed at parameter t.

    For a plane curve C(t) = (x(t), y(t)):
        κ_signed = (x'·y'' − y'·x'') / (x'² + y'²)^(3/2)

    Returns 0.0 when the curve is singular (|C'| ≈ 0) or when the
    second derivative cannot be computed.
    """
    try:
        d1 = curve_derivative(curve, t, order=1)
        d2 = curve_derivative(curve, t, order=2)
        d1 = np.asarray(d1, dtype=float).ravel()
        d2 = np.asarray(d2, dtype=float).ravel()

        xp = float(d1[0])
        yp = float(d1[1] if d1.size > 1 else 0.0)
        xpp = float(d2[0])
        ypp = float(d2[1] if d2.size > 1 else 0.0)
    except Exception:  # noqa: BLE001
        return 0.0

    speed_sq = xp * xp + yp * yp
    if speed_sq < _SPEED_TOL ** 2:
        return 0.0

    speed = math.sqrt(speed_sq)
    return (xp * ypp - yp * xpp) / (speed ** 3)


def _bisect_zero(
    curve: NurbsCurve,
    t_lo: float,
    t_hi: float,
    k_lo: float,
    k_hi: float,
    iters: int,
) -> float:
    """Bisect [t_lo, t_hi] to find the sign change of κ_signed.

    Uses the given endpoint values to avoid redundant evaluations.
    """
    for _ in range(iters):
        t_mid = 0.5 * (t_lo + t_hi)
        k_mid = _signed_kappa(curve, t_mid)
        if k_lo * k_mid <= 0.0:
            t_hi = t_mid
            k_hi = k_mid
        else:
            t_lo = t_mid
            k_lo = k_mid
    return 0.5 * (t_lo + t_hi)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_curve_inflections(
    curve_or_points: Union[NurbsCurve, Sequence],
    num_samples: int = 200,
    threshold: float = 1e-9,
) -> InflectionResult:
    """Find inflection points of a 2D NURBS curve.

    An inflection point is a parameter t* where the signed curvature
    κ_signed(t) changes sign — i.e. the curve transitions from concave to
    convex or vice-versa (do Carmo §1.5; Sapidis §3).

    Parameters
    ----------
    curve_or_points : NurbsCurve or sequence
        A 2D NurbsCurve object (control points in ℝ² or ℝ³ with z≈0).
        If a sequence of (t, κ_signed) pairs is passed instead of a
        NurbsCurve, inflection detection is performed directly on those
        samples (no NURBS evaluation).  This path does not perform
        bisection refinement.
    num_samples : int
        Number of uniform parameter samples for initial sign-change
        detection (default 200).
    threshold : float
        Near-zero curvature threshold.  Samples with |κ| < threshold are
        treated as zero during sign-change detection to suppress false
        positives in near-flat regions.  Default 1e-9.

    Returns
    -------
    InflectionResult
        inflection_t_params, num_inflections, signed_curvature_samples,
        honest_caveat.

    Never raises — degenerate inputs return a zero-inflection result with
    an honest caveat explaining the condition.

    References
    ----------
    do Carmo §1.5 (Inflection points); Sapidis §3 (Designing Fair Curves);
    Piegl & Tiller §9.1/§9.2 (NURBS derivatives).
    """

    # ------------------------------------------------------------------
    # Branch: raw (t, kappa) samples passed instead of a NurbsCurve
    # ------------------------------------------------------------------
    if not isinstance(curve_or_points, NurbsCurve):
        # Accept a list/array of (t, kappa) pairs for direct detection.
        try:
            samples_arr = [(float(row[0]), float(row[1]))
                           for row in curve_or_points]
        except (TypeError, IndexError, ValueError) as exc:
            return InflectionResult(
                honest_caveat=(
                    "Input must be a NurbsCurve or a sequence of (t, κ) pairs.  "
                    f"Received: {type(curve_or_points).__name__!r}.  "
                    f"Error: {exc}  "
                    "3D space-curve inflections not supported; 2D only."
                ),
            )

        inflection_ts = _detect_sign_changes_from_samples(
            samples_arr, threshold, curve=None
        )
        caveat = (
            "HONEST: sign-change detection on pre-computed (t, κ) samples; "
            "bisection refinement is only available for NurbsCurve inputs.  "
            "Near-zero-curvature regions (|κ| < threshold) are treated as "
            "zero; gentle curvature crossings may be missed."
        )
        return InflectionResult(
            inflection_t_params=inflection_ts,
            num_inflections=len(inflection_ts),
            signed_curvature_samples=samples_arr,
            honest_caveat=caveat,
        )

    # ------------------------------------------------------------------
    # Main path: NurbsCurve input
    # ------------------------------------------------------------------
    curve: NurbsCurve = curve_or_points
    num_samples = max(3, int(num_samples))
    threshold = float(threshold)

    t_min, t_max = _param_range(curve)
    ts = np.linspace(t_min, t_max, num_samples)

    # Step 1 — sample signed κ across the parameter domain.
    kappa_vals: List[float] = []
    for t in ts:
        kappa_vals.append(_signed_kappa(curve, float(t)))

    kappa_arr = np.array(kappa_vals)
    signed_samples: List[Tuple[float, float]] = [
        (float(ts[i]), float(kappa_arr[i])) for i in range(num_samples)
    ]

    # ------------------------------------------------------------------
    # Straight-line / all-zero curvature guard.
    # ------------------------------------------------------------------
    kappa_abs_max = float(np.max(np.abs(kappa_arr)))
    if kappa_abs_max < threshold:
        caveat = (
            "HONEST: The curve has near-zero curvature at all sampled points "
            "(max |κ| = {:.2e} < threshold {:.2e}).  This typically indicates "
            "a straight line or a curve that is very nearly straight across the "
            "entire parameter domain.  No inflection points are defined for a "
            "line (κ ≡ 0 everywhere).  If the curve is not a line, lower the "
            "threshold or increase num_samples.  2D only — 3D space-curve "
            "inflections not supported."
        ).format(kappa_abs_max, threshold)
        return InflectionResult(
            inflection_t_params=[],
            num_inflections=0,
            signed_curvature_samples=signed_samples,
            honest_caveat=caveat,
        )

    # ------------------------------------------------------------------
    # Step 2 — detect sign changes; refine each bracket with bisection.
    # ------------------------------------------------------------------
    inflection_ts: List[float] = []

    for i in range(num_samples - 1):
        k0 = kappa_arr[i]
        k1 = kappa_arr[i + 1]
        t0 = float(ts[i])
        t1 = float(ts[i + 1])

        # Skip near-zero samples (suppress false positives in flat regions).
        k0_eff = k0 if abs(k0) >= threshold else 0.0
        k1_eff = k1 if abs(k1) >= threshold else 0.0

        if k0_eff == 0.0 and k1_eff == 0.0:
            # Both effectively zero — no crossing here.
            continue

        if k0_eff * k1_eff < 0.0:
            # Sign change detected — refine by bisection.
            t_inflection = _bisect_zero(
                curve, t0, t1, k0, k1, iters=_BISECT_ITERS
            )
            inflection_ts.append(t_inflection)
        elif k0_eff == 0.0 and k1_eff != 0.0:
            # Curvature just left zero — the inflection is at t0 itself.
            # Check if the previous interval was of opposite sign.
            if i > 0:
                k_prev = kappa_arr[i - 1]
                if abs(k_prev) >= threshold and k_prev * k1_eff < 0.0:
                    inflection_ts.append(t0)

    # ------------------------------------------------------------------
    # Build the honest caveat.
    # ------------------------------------------------------------------
    caveat = (
        "HONEST: 2D curves only — 3D space-curve inflections (osculating-plane "
        "flips requiring torsion) are not supported.  Curvature is evaluated "
        "from NURBS analytical 1st/2nd derivatives; samples with |κ| < "
        "threshold ({:.2e}) are treated as zero during sign-change detection.  "
        "Near-zero-curvature regions may produce false positives if threshold "
        "is too low, or false negatives if too high.  Bisection uses {} "
        "iterations per crossing.  Increase num_samples for dense oscillating "
        "curves.  Refs: do Carmo §1.5; Sapidis §3."
    ).format(threshold, _BISECT_ITERS)

    return InflectionResult(
        inflection_t_params=inflection_ts,
        num_inflections=len(inflection_ts),
        signed_curvature_samples=signed_samples,
        honest_caveat=caveat,
    )


def _detect_sign_changes_from_samples(
    samples: List[Tuple[float, float]],
    threshold: float,
    curve: "NurbsCurve | None",
) -> List[float]:
    """Detect sign changes in pre-computed (t, κ) sample list.

    Internal helper shared by the raw-samples branch of
    find_curve_inflections.  Bisection is only used when `curve` is not None.
    """
    inflection_ts: List[float] = []
    n = len(samples)
    for i in range(n - 1):
        t0, k0 = samples[i]
        t1, k1 = samples[i + 1]

        k0_eff = k0 if abs(k0) >= threshold else 0.0
        k1_eff = k1 if abs(k1) >= threshold else 0.0

        if k0_eff == 0.0 and k1_eff == 0.0:
            continue

        if k0_eff * k1_eff < 0.0:
            if curve is not None:
                t_inf = _bisect_zero(curve, t0, t1, k0, k1, iters=_BISECT_ITERS)
            else:
                # Linear interpolation to zero.
                t_inf = t0 + (t1 - t0) * abs(k0) / (abs(k0) + abs(k1))
            inflection_ts.append(t_inf)
        elif k0_eff == 0.0 and k1_eff != 0.0:
            if i > 0:
                _, k_prev = samples[i - 1]
                if abs(k_prev) >= threshold and k_prev * k1_eff < 0.0:
                    inflection_ts.append(t0)

    return inflection_ts


# ---------------------------------------------------------------------------
# LLM tool registration (gated import pattern)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import (  # type: ignore[import]
        ToolSpec,
        err_payload,
        ok_payload,
        register,
    )
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    _inflection_spec = ToolSpec(
        name="nurbs_find_curve_inflections",
        description=(
            "Find inflection points of a 2D NURBS curve — parameter values t* where "
            "the signed curvature κ(t) changes sign (do Carmo §1.5; Sapidis §3).\n"
            "\n"
            "An inflection point is where the curve transitions from bending left "
            "(κ > 0) to bending right (κ < 0) or vice-versa.  The osculating circle "
            "switches side at each inflection.\n"
            "\n"
            "Algorithm: uniform sampling of κ_signed(t) → sign-change detection → "
            "5-iteration bisection refinement per bracket.\n"
            "\n"
            "Returns:\n"
            "  inflection_t_params        : [t*, ...] refined parameter values at inflections\n"
            "  num_inflections            : count of inflection points\n"
            "  signed_curvature_samples   : [[t, κ_signed], ...] uniform sample grid\n"
            "  honest_caveat              : scope and accuracy caveats\n"
            "\n"
            "Applications: fairness analysis, sketch QC, toolpath transition planning, "
            "clothoid design.\n"
            "\n"
            "HONEST: 2D only.  Near-zero-curvature regions (|κ| < threshold) may "
            "produce false positives or suppress genuine gentle crossings.\n"
            "Never raises — returns {ok:false, reason} for invalid inputs."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "degree": {
                    "type": "integer",
                    "description": "B-spline degree (>= 1; degree 2+ needed for curvature).",
                },
                "control_points": {
                    "type": "array",
                    "description": (
                        "List of 2D control points [[x,y], ...] or [[x,y,z], ...] "
                        "(z is ignored; curve must lie in XY-plane)."
                    ),
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "knots": {
                    "type": "array",
                    "description": "Knot vector (non-decreasing, clamped).",
                    "items": {"type": "number"},
                },
                "weights": {
                    "type": "array",
                    "description": "Optional per-control-point weights for rational NURBS.",
                    "items": {"type": "number"},
                },
                "num_samples": {
                    "type": "integer",
                    "description": "Number of uniform parameter samples for detection (default 200).",
                },
                "threshold": {
                    "type": "number",
                    "description": (
                        "Near-zero curvature threshold; samples with |κ| < threshold "
                        "are treated as zero.  Default 1e-9.  Raise to suppress false "
                        "positives in near-flat regions."
                    ),
                },
            },
            "required": ["degree", "control_points", "knots"],
        },
    )

    @register(_inflection_spec)
    def _tool_nurbs_find_curve_inflections(
        params: dict, ctx: "ProjectCtx"  # type: ignore[type-arg]
    ):
        try:
            degree = int(params["degree"])
            cps = np.array(params["control_points"], dtype=float)
            if cps.ndim == 1:
                cps = cps.reshape(-1, 2)
            knots = np.array(params["knots"], dtype=float)
            weights = params.get("weights")
            if weights is not None:
                weights = np.array(weights, dtype=float)

            curve = NurbsCurve(
                degree=degree,
                control_points=cps,
                knots=knots,
                weights=weights,
            )

            n_samples = int(params.get("num_samples") or 200)
            thresh = float(params.get("threshold") or 1e-9)

            result = find_curve_inflections(curve, num_samples=n_samples, threshold=thresh)

            return ok_payload({
                "inflection_t_params": result.inflection_t_params,
                "num_inflections": result.num_inflections,
                "signed_curvature_samples": [
                    {"t": t, "kappa_signed": k}
                    for t, k in result.signed_curvature_samples
                ],
                "honest_caveat": result.honest_caveat,
            })
        except Exception as exc:  # noqa: BLE001
            return err_payload(str(exc))
