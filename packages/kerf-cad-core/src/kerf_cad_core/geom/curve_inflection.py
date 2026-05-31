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
(do Carmo §1.5; Sapidis "Designing Fair Curves and Surfaces" §3;
Farin §10.6 curvature of polynomial/rational curves).

At an inflection point the curve transitions from bending left (κ > 0) to
bending right (κ < 0) or vice-versa — the osculating circle switches side.

Fairness / Class-A criteria (Farin §10.6; Sapidis §3)
------------------------------------------------------
A curve is considered *fair* (Class-A) if it has at most one inflection point
and no abrupt curvature jumps.  Naval-architecture and automotive styling
require fair curves to avoid reflective highlight discontinuities.

Algorithm
---------
1. Sample t uniformly in [t_min, t_max] at `num_samples` positions.
2. Compute κ_signed(t_i) at each sample via analytical NURBS 1st/2nd
   derivatives (Piegl & Tiller §9.1 / §9.2).
3. Detect adjacent-sample sign changes of κ_signed (ignoring near-zero
   samples with |κ| < tol to suppress false positives in near-zero
   curvature regions).
4. For each detected sign-change interval [t_lo, t_hi], refine with 5
   iterations of bisection to locate the zero crossing to high precision.
5. At each refined crossing, evaluate curvature just left and right of t*
   to populate InflectionPoint.curvature_left / curvature_right.

Honest caveats
--------------
* 2D curves only.  Input must be a NurbsCurve with 2D control points, or a 3D
  curve whose z-components are negligible.  3D space-curve inflections (where
  the osculating plane changes, requiring torsion analysis) are NOT computed.
* Near-zero-curvature regions (|κ| < tol) are treated as zero during sign-
  change detection.  Curves with very low curvature throughout (e.g. near-
  lines) may yield 0 inflections — raise tol to suppress false positives, or
  lower it to detect gentle transitions.
* A straight line (κ ≡ 0) has no well-defined inflection points.
  `num_inflections = 0` and `honest_caveat` states the reason.
* Sample density controls detection reliability: undersampled curves may miss
  inflections that occur within a single sample interval.
* Sampling-based — does NOT solve κ=0 analytically.  Algebraic root-finding
  (Sturm sequences on B-spline coefficients) is not implemented.

Applications
------------
* Fairness analysis — Class-A surface validation (naval/automotive styling)
* Sketch QC — flag unintended S-curves in sketch segments
* Toolpath transitions — avoid κ-sign changes during constant-feed machining
* Clothoid design — inflection = boundary between left/right clothoid arcs

References
----------
do Carmo, M.P. (1976) "Differential Geometry of Curves and Surfaces" §1.5.
Sapidis, N.S. ed. (1994) "Designing Fair Curves and Surfaces" §3
    (AMS SIAM Geometric Design Publications).
Piegl, L. & Tiller, W. (1997) "The NURBS Book" §5.3 (derivatives) §9.1/§9.2.
Farin, G. (2002) "Curves and Surfaces for CAGD" §10.6 (curvature; fairness).

Public API (v2 — typed, Class-A aware)
---------------------------------------
InflectionPoint       — per-inflection dataclass with xy_mm, κ_left/right.
CurveInflectionReport — full report with fairness flag and warnings.
find_curve_inflections(curve, num_samples=200, tol=1e-6)
    -> CurveInflectionReport

Legacy API (v1 — kept for backward compatibility)
-------------------------------------------------
InflectionResult      — legacy dataclass (v1).
find_curve_inflections_v1(curve_or_points, num_samples=200, threshold=1e-9)
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

# Fraction of parameter range used to sample left/right curvature at each
# inflection point for sign_change and curvature_left/curvature_right fields.
_KAPPA_FLANK_FRAC: float = 1e-4

# Curvature jump threshold: if |κ_left| or |κ_right| is more than this factor
# above the mean |κ|, flag it as an abrupt jump in the fairness check.
_ABRUPT_JUMP_FACTOR: float = 5.0


# ---------------------------------------------------------------------------
# Dataclasses (v2 — typed, Class-A aware)
# ---------------------------------------------------------------------------

@dataclass
class InflectionPoint:
    """A single inflection point of a 2D NURBS curve.

    Attributes
    ----------
    parameter_u : float
        NURBS parameter value t* at which κ_signed = 0 (sign change).
        Refined by 5-iteration bisection from the coarse sample bracket.
    xy_mm : tuple[float, float]
        Cartesian coordinates (x, y) in model units (mm) at t*.
        Computed by evaluating the NURBS curve at ``parameter_u``.
    curvature_left : float
        Signed curvature κ_signed just before t* (at t* − ε).
    curvature_right : float
        Signed curvature κ_signed just after t* (at t* + ε).
    sign_change : bool
        True if curvature_left and curvature_right have opposite signs.
        Should always be True for a genuine inflection; False only if the
        crossing is extremely close to an endpoint or a numerical artefact.
    """

    parameter_u: float
    xy_mm: Tuple[float, float]
    curvature_left: float
    curvature_right: float
    sign_change: bool


@dataclass
class CurveInflectionReport:
    """Full inflection-point report for a 2D NURBS curve.

    Attributes
    ----------
    inflection_points : list[InflectionPoint]
        Detected inflection points, ordered by parameter_u.
    num_inflections : int
        Number of inflection points.  Equals len(inflection_points).
    max_curvature : float
        Maximum |κ_signed| across all samples (0.0 for a straight line).
    min_curvature : float
        Minimum |κ_signed| across all samples.
    is_fair_class_a : bool
        True if the curve meets the Class-A fairness criterion:
        at most 1 inflection AND no abrupt κ-jumps (Farin §10.6; Sapidis §3).
        Straight lines (κ ≡ 0) and circles (κ = const) are considered fair.
        Curves with ≥ 2 inflections are NOT fair.
    warnings : list[str]
        Human-readable warnings for edge cases (near-line curvature,
        abrupt curvature jumps, high sample density needed, etc.).
    honest_caveat : str
        Fixed plain-language statement of scope, accuracy, and limitations.
    """

    inflection_points: List[InflectionPoint] = field(default_factory=list)
    num_inflections: int = 0
    max_curvature: float = 0.0
    min_curvature: float = 0.0
    is_fair_class_a: bool = True
    warnings: List[str] = field(default_factory=list)
    honest_caveat: str = ""


# ---------------------------------------------------------------------------
# Legacy dataclass (v1 — kept for backward compatibility)
# ---------------------------------------------------------------------------

@dataclass
class InflectionResult:
    """Legacy result of find_curve_inflections_v1().

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
# Legacy public API (v1)
# ---------------------------------------------------------------------------

def find_curve_inflections_v1(
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
# v2 Public API — InflectionPoint + CurveInflectionReport
# ---------------------------------------------------------------------------

_HONEST_CAVEAT_V2: str = (
    "HONEST: 2D curves only — 3D space-curve inflections (osculating-plane "
    "flips, requiring torsion) are NOT supported.  Curvature is evaluated via "
    "NURBS analytical 1st/2nd derivatives (Piegl-Tiller §5.3/§9.2); samples "
    "with |κ| < tol are treated as zero during sign-change detection.  "
    "Sampling-based — does NOT solve κ=0 analytically.  Near-zero-curvature "
    "regions may produce false positives (tol too low) or missed crossings "
    "(tol too high).  Bisection uses 5 iterations per bracket; increase "
    "num_samples for densely oscillating curves.  "
    "is_fair_class_a = True iff ≤ 1 inflection AND no abrupt κ-jump "
    "(Farin §10.6; Sapidis §3).  "
    "Refs: Piegl-Tiller §5.3/§9.2; Farin §10.6; do Carmo §1.5; Sapidis §3."
)


def find_curve_inflections(
    curve: NurbsCurve,
    num_samples: int = 200,
    tol: float = 1e-6,
) -> "CurveInflectionReport":
    """Find inflection points (κ sign-change) of a 2D NURBS curve.

    Implements Piegl & Tiller §5.3 (derivatives) + Farin §10.6 (curvature)
    for signed curvature κ(u) = (x'·y'' − y'·x'') / (x'² + y'²)^1.5.

    Inflection detection: uniform sampling → adjacent sign-change scan →
    5-iteration bisection refinement per bracket.

    Class-A fairness check (naval-architecture / automotive styling):
    ``is_fair_class_a = True`` iff ``num_inflections ≤ 1`` AND no abrupt
    curvature jump (|κ| > 5× mean) at any inflection.

    Parameters
    ----------
    curve : NurbsCurve
        2D NURBS curve (control points in ℝ² or ℝ³ with z ≈ 0).
    num_samples : int
        Number of uniform parameter samples (default 200).
    tol : float
        Near-zero curvature tolerance.  Samples with |κ| < tol are treated
        as zero for sign-change detection.  Default 1e-6.

    Returns
    -------
    CurveInflectionReport
        inflection_points, num_inflections, max_curvature, min_curvature,
        is_fair_class_a, warnings, honest_caveat.
        Never raises.

    References
    ----------
    Piegl & Tiller (1997) §5.3, §9.2; Farin (2002) §10.6;
    do Carmo (1976) §1.5; Sapidis (1994) §3.
    """
    warnings_out: List[str] = []

    # ------------------------------------------------------------------
    # Guard: must be a NurbsCurve
    # ------------------------------------------------------------------
    if not isinstance(curve, NurbsCurve):
        warnings_out.append(
            f"Input is not a NurbsCurve (got {type(curve).__name__!r}); "
            "returning empty report."
        )
        return CurveInflectionReport(
            inflection_points=[],
            num_inflections=0,
            max_curvature=0.0,
            min_curvature=0.0,
            is_fair_class_a=True,
            warnings=warnings_out,
            honest_caveat=_HONEST_CAVEAT_V2,
        )

    num_samples = max(3, int(num_samples))
    tol = float(tol)

    t_min, t_max = _param_range(curve)
    param_range_size = t_max - t_min
    ts = np.linspace(t_min, t_max, num_samples)

    # ------------------------------------------------------------------
    # Step 1 — sample κ_signed across the parameter domain
    # ------------------------------------------------------------------
    kappa_vals: List[float] = [_signed_kappa(curve, float(t)) for t in ts]
    kappa_arr = np.array(kappa_vals, dtype=float)

    kappa_abs = np.abs(kappa_arr)
    max_kappa = float(np.max(kappa_abs))
    min_kappa = float(np.min(kappa_abs))
    mean_kappa = float(np.mean(kappa_abs))

    # ------------------------------------------------------------------
    # Straight-line / near-zero guard
    # ------------------------------------------------------------------
    if max_kappa < tol:
        warnings_out.append(
            f"Near-zero curvature at all sampled points (max |κ| = {max_kappa:.2e} "
            f"< tol {tol:.2e}).  Likely a straight line or near-straight curve; "
            "κ ≡ 0 everywhere — no inflections defined."
        )
        return CurveInflectionReport(
            inflection_points=[],
            num_inflections=0,
            max_curvature=max_kappa,
            min_curvature=min_kappa,
            is_fair_class_a=True,  # straight lines are fair
            warnings=warnings_out,
            honest_caveat=_HONEST_CAVEAT_V2,
        )

    # ------------------------------------------------------------------
    # Step 2 — detect sign-change brackets; bisect each one
    # ------------------------------------------------------------------
    inflection_params: List[float] = []

    for i in range(num_samples - 1):
        k0 = kappa_arr[i]
        k1 = kappa_arr[i + 1]
        t0 = float(ts[i])
        t1 = float(ts[i + 1])

        k0_eff = k0 if abs(k0) >= tol else 0.0
        k1_eff = k1 if abs(k1) >= tol else 0.0

        if k0_eff == 0.0 and k1_eff == 0.0:
            continue

        if k0_eff * k1_eff < 0.0:
            t_star = _bisect_zero(curve, t0, t1, k0, k1, iters=_BISECT_ITERS)
            inflection_params.append(t_star)
        elif k0_eff == 0.0 and k1_eff != 0.0:
            if i > 0:
                k_prev = kappa_arr[i - 1]
                if abs(k_prev) >= tol and k_prev * k1_eff < 0.0:
                    inflection_params.append(t0)

    # ------------------------------------------------------------------
    # Step 3 — build InflectionPoint objects; compute curvature flanks
    # ------------------------------------------------------------------
    flank_eps = _KAPPA_FLANK_FRAC * param_range_size

    inflection_points: List[InflectionPoint] = []
    for t_star in inflection_params:
        # Evaluate curve position
        try:
            pos = np.asarray(curve.evaluate(t_star), dtype=float).ravel()
            xy = (float(pos[0]), float(pos[1] if pos.size > 1 else 0.0))
        except Exception:  # noqa: BLE001
            xy = (float("nan"), float("nan"))

        # Left/right curvature (clamped to domain)
        t_left = max(t_min, t_star - flank_eps)
        t_right = min(t_max, t_star + flank_eps)
        k_left = _signed_kappa(curve, t_left)
        k_right = _signed_kappa(curve, t_right)

        # sign_change: true if left and right have opposite signs
        sign_chg = (k_left * k_right < 0.0)

        inflection_points.append(InflectionPoint(
            parameter_u=t_star,
            xy_mm=xy,
            curvature_left=k_left,
            curvature_right=k_right,
            sign_change=sign_chg,
        ))

    # ------------------------------------------------------------------
    # Step 4 — fairness / Class-A check (Farin §10.6; Sapidis §3)
    # ------------------------------------------------------------------
    is_fair = True
    if len(inflection_points) > 1:
        is_fair = False
        warnings_out.append(
            f"Curve has {len(inflection_points)} inflection points — NOT Class-A fair "
            "(Farin §10.6 requires ≤ 1 inflection for a fair curve)."
        )

    # Check for abrupt curvature jumps at each inflection
    if mean_kappa > 0.0:
        for ip in inflection_points:
            left_ratio = abs(ip.curvature_left) / mean_kappa
            right_ratio = abs(ip.curvature_right) / mean_kappa
            if left_ratio > _ABRUPT_JUMP_FACTOR or right_ratio > _ABRUPT_JUMP_FACTOR:
                is_fair = False
                warnings_out.append(
                    f"Abrupt curvature jump at t={ip.parameter_u:.4f}: "
                    f"|κ_left|={abs(ip.curvature_left):.3e}, "
                    f"|κ_right|={abs(ip.curvature_right):.3e}, "
                    f"mean |κ|={mean_kappa:.3e} — violates Class-A fairness."
                )

    # Warn if no sign_change (numerical artefact at endpoint)
    for ip in inflection_points:
        if not ip.sign_change:
            warnings_out.append(
                f"Inflection at t={ip.parameter_u:.4f} has no confirmed sign change "
                "(may be a numerical artefact near a curve endpoint)."
            )

    return CurveInflectionReport(
        inflection_points=inflection_points,
        num_inflections=len(inflection_points),
        max_curvature=max_kappa,
        min_curvature=min_kappa,
        is_fair_class_a=is_fair,
        warnings=warnings_out,
        honest_caveat=_HONEST_CAVEAT_V2,
    )


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
            "the signed curvature κ(t) changes sign.  Used for fairness analysis and "
            "naval-architecture/automotive Class-A surface validation.\n"
            "\n"
            "An inflection point is where the curve transitions from bending left "
            "(κ > 0) to bending right (κ < 0) or vice-versa — the osculating circle "
            "switches side (Piegl-Tiller §5.3; Farin §10.6; do Carmo §1.5).\n"
            "\n"
            "κ(u) = (x'·y'' − y'·x'') / (x'² + y'²)^1.5  [signed 2D curvature]\n"
            "\n"
            "Algorithm: sample κ(u) at num_samples uniform u-values → adjacent "
            "sign-change detection (|κ| < tol treated as zero) → 5-iteration "
            "bisection refinement per bracket.\n"
            "\n"
            "Returns CurveInflectionReport:\n"
            "  inflection_points  : [{parameter_u, xy_mm, curvature_left, "
            "curvature_right, sign_change}, ...]\n"
            "  num_inflections    : count\n"
            "  max_curvature      : max |κ| over samples\n"
            "  min_curvature      : min |κ| over samples\n"
            "  is_fair_class_a    : True iff ≤ 1 inflection AND no abrupt κ-jump\n"
            "  warnings           : list of diagnostic strings\n"
            "  honest_caveat      : scope / accuracy caveats\n"
            "\n"
            "Applications: Class-A fairness QC, sketch QC, toolpath transitions, "
            "clothoid / fresnel-transition design.\n"
            "\n"
            "HONEST: 2D only — 3D space-curve torsion not supported.  "
            "Sampling-based, not analytical root-finding.  "
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
                "tol": {
                    "type": "number",
                    "description": (
                        "Near-zero curvature tolerance; samples with |κ| < tol "
                        "are treated as zero.  Default 1e-6.  Raise to suppress false "
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
            tol = float(params.get("tol") or 1e-6)

            report = find_curve_inflections(curve, num_samples=n_samples, tol=tol)

            return ok_payload({
                "inflection_points": [
                    {
                        "parameter_u": ip.parameter_u,
                        "xy_mm": list(ip.xy_mm),
                        "curvature_left": ip.curvature_left,
                        "curvature_right": ip.curvature_right,
                        "sign_change": ip.sign_change,
                    }
                    for ip in report.inflection_points
                ],
                "num_inflections": report.num_inflections,
                "max_curvature": report.max_curvature,
                "min_curvature": report.min_curvature,
                "is_fair_class_a": report.is_fair_class_a,
                "warnings": report.warnings,
                "honest_caveat": report.honest_caveat,
            })
        except Exception as exc:  # noqa: BLE001
            return err_payload(str(exc))
