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
* Sampling-based — does NOT solve κ=0 analytically.  For analytic root-finding
  via Sturm sequences on the polynomial numerator of κ_signed, see
  :func:`find_curve_inflections_sturm`.

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
# Sturm-sequence analytic inflection finder (v3)
# ---------------------------------------------------------------------------
#
# Theory (Marden §1.4; Uspensky "Theory of Equations" §5)
# --------------------------------------------------------
# For a 2D non-rational B-spline of degree d on knot span [u_lo, u_hi]:
#   C(t) = (x(t), y(t))  is a degree-d polynomial in t.
#   x'(t), y'(t) have degree d-1;  x''(t), y''(t) have degree d-2.
#   p(t) := x'(t)·y''(t) - y'(t)·x''(t)  has degree 2d-3.
#
# Sturm's theorem gives the exact count of distinct real roots of p in (a, b]:
#   V(t) = number of sign changes in the Sturm sequence (p_0, p_1, …, p_k)
#          evaluated at t (zeros excluded from the sign-change count).
#   count of distinct roots in (a, b] = V(a) - V(b).
#
# Polynomial conventions
# ----------------------
# A polynomial p(t) is represented as a 1-D numpy array of coefficients
# *in ascending order*: p[0] + p[1]*t + p[2]*t^2 + ... + p[n]*t^n.
# (This is the convention of numpy.polynomial.polynomial, NOT numpy.polyval.)
#
# Bernstein-to-power basis conversion
# ------------------------------------
# For a degree-d Bezier segment with Bernstein control points B[0..d]:
#   x(t) = Σ_{i=0}^{d}  B[i]  * C(d,i) * t^i * (1-t)^(d-i)   for t in [0,1]
# We first map [u_lo, u_hi] → [0, 1] and convert to monomial (power) basis
# using the change-of-basis matrix M[i,j] = (-1)^(j-i) * C(d-i, j-i) * C(d, i)
# (Farin §5.1; Farouki-Rajan 1987).
#
# Refs: Marden (1966) "Geometry of Polynomials" §1.4;
#       Uspensky (1948) "Theory of Equations" §5 (Sturm chains);
#       Farin (2002) §5.1 (Bernstein → monomial);
#       Farouki & Rajan (1987) CAGD 4(4) pp. 229-254.


def _poly_mul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Multiply two polynomials in ascending-coefficient form."""
    if len(a) == 0 or len(b) == 0:
        return np.zeros(1)
    return np.polymul(a[::-1], b[::-1])[::-1]


def _poly_sub(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Subtract polynomial b from a, ascending-coefficient form."""
    la, lb = len(a), len(b)
    n = max(la, lb)
    out = np.zeros(n)
    out[:la] += a
    out[:lb] -= b
    return out


def _poly_deriv(p: np.ndarray) -> np.ndarray:
    """Differentiate polynomial in ascending-coefficient form.

    Returns zero polynomial (array([0.])) for degree-0 (constant) input.
    """
    if len(p) <= 1:
        return np.array([0.0])
    return np.array([p[i] * i for i in range(1, len(p))], dtype=float)


def _poly_trim(p: np.ndarray, atol: float = 1e-14) -> np.ndarray:
    """Remove trailing near-zero coefficients (leading terms in ascending order)."""
    arr = np.asarray(p, dtype=float)
    while len(arr) > 1 and abs(arr[-1]) <= atol:
        arr = arr[:-1]
    return arr


def _poly_divrem(a: np.ndarray, b: np.ndarray) -> tuple:
    """Polynomial division a / b.  Returns (quotient, remainder) in ascending form."""
    a = _poly_trim(np.asarray(a, dtype=float))
    b = _poly_trim(np.asarray(b, dtype=float))
    if len(b) == 0 or (len(b) == 1 and abs(b[0]) < 1e-15):
        raise ZeroDivisionError("Divisor polynomial is zero")
    # Use numpy's polynomial in descending form then reverse back.
    q_desc, r_desc = np.polydiv(a[::-1], b[::-1])
    q = _poly_trim(q_desc[::-1])
    r = _poly_trim(r_desc[::-1])
    return q, r


def _poly_eval(p: np.ndarray, t: float) -> float:
    """Evaluate polynomial in ascending-coefficient form at scalar t."""
    # Horner's method (ascending → reverse for polyval direction)
    return float(np.polyval(p[::-1], t))


def _poly_degree(p: np.ndarray) -> int:
    """Degree of trimmed polynomial."""
    arr = _poly_trim(p)
    return max(0, len(arr) - 1)


def _sturm_sequence(p: np.ndarray) -> list:
    """Build the Sturm sequence for polynomial p.

    Returns [p_0, p_1, p_2, ...] where:
      p_0 = p  (trimmed)
      p_1 = p' (formal derivative)
      p_{k+1} = -rem(p_{k-1}, p_k)

    Terminates when the remainder is the zero polynomial.
    All polynomials are in ascending-coefficient form.
    Coefficients are normalized by the leading coefficient of p_1 to avoid
    exponential growth (sign is all that matters for Sturm counting).
    """
    p0 = _poly_trim(p)
    p1 = _poly_trim(_poly_deriv(p0))

    if _poly_degree(p1) == 0 and abs(_poly_eval(p1, 0.0)) < 1e-15:
        # p is a constant — no roots.
        return [p0]

    seq = [p0, p1]
    max_steps = _poly_degree(p0) + 2
    for _ in range(max_steps):
        prev = seq[-2]
        cur = seq[-1]
        if _poly_degree(cur) == 0:
            break
        try:
            _, r = _poly_divrem(prev, cur)
        except ZeroDivisionError:
            break
        neg_r = _poly_trim(-r)
        if _poly_degree(neg_r) == 0 and abs(_poly_eval(neg_r, 0.0)) < 1e-15:
            break
        seq.append(neg_r)

    return seq


def _sturm_sign_changes(seq: list, t: float) -> int:
    """Count sign changes in the Sturm sequence evaluated at t.

    Zeros are excluded from the sign-change count (standard Sturm convention).
    """
    signs = []
    for p in seq:
        v = _poly_eval(p, t)
        if v > 0.0:
            signs.append(1)
        elif v < 0.0:
            signs.append(-1)
        # v == 0 → skip (standard convention)

    count = 0
    for i in range(len(signs) - 1):
        if signs[i] * signs[i + 1] < 0:
            count += 1
    return count


def _bernstein_to_monomial(ctrl: np.ndarray) -> np.ndarray:
    """Convert Bernstein control points to monomial (power) basis.

    Parameters
    ----------
    ctrl : 1-D array of length d+1
        Bernstein control-point values for one coordinate (x or y) on [0,1].

    Returns
    -------
    p : 1-D array of length d+1
        Monomial coefficients in ascending order: p[0] + p[1]*t + ... + p[d]*t^d.

    Algorithm: B(t) = Σ_i ctrl[i] * C(d,i) * t^i * (1-t)^(d-i).
    Expand (1-t)^(d-i) via binomial theorem → collect powers of t.
    Change-of-basis: M[j, i] = C(d,i) * C(d-i, j-i) * (-1)^(j-i)  for j>=i,
    else 0.  Coefficient of t^j is Σ_i M[j,i] * ctrl[i].
    (Farin 2002 §5.1; Farouki-Rajan 1987.)
    """
    ctrl = np.asarray(ctrl, dtype=float)
    d = len(ctrl) - 1
    from math import comb
    mono = np.zeros(d + 1)
    for j in range(d + 1):
        s = 0.0
        for i in range(j + 1):
            s += comb(d, i) * comb(d - i, j - i) * ((-1) ** (j - i)) * ctrl[i]
        mono[j] = s
    return mono


def _bezier_span_poly(bezier_cps: np.ndarray, coord_idx: int) -> np.ndarray:
    """Extract monomial polynomial for one coordinate from Bezier CPs on [0,1].

    Parameters
    ----------
    bezier_cps : array of shape (d+1, dim)
        Bernstein control points for a single Bezier segment.
    coord_idx : int
        0 for x, 1 for y.

    Returns
    -------
    Monomial coefficients in ascending order for the segment's coordinate.
    """
    ctrl = bezier_cps[:, coord_idx]
    return _bernstein_to_monomial(ctrl)


def _count_roots_sturm(
    p: np.ndarray,
    a: float,
    b: float,
    seq: list,
) -> int:
    """Count distinct real roots of p in the open interval (a, b).

    Uses the pre-computed Sturm sequence `seq`.
    """
    va = _sturm_sign_changes(seq, a)
    vb = _sturm_sign_changes(seq, b)
    return max(0, va - vb)


def _bisect_poly_root(
    p: np.ndarray,
    a: float,
    b: float,
    tol: float,
) -> float:
    """Bisect to find one root of p in [a, b] (assumes sign change exists).

    Runs until interval width < tol or max 64 iterations.
    """
    fa = _poly_eval(p, a)
    fb = _poly_eval(p, b)

    # If no sign change, return midpoint (numerical precision edge case)
    if fa * fb > 0.0:
        return 0.5 * (a + b)

    for _ in range(64):
        if b - a < tol:
            break
        mid = 0.5 * (a + b)
        fm = _poly_eval(p, mid)
        if fa * fm <= 0.0:
            b = mid
            fb = fm
        else:
            a = mid
            fa = fm
    return 0.5 * (a + b)


def _isolate_roots_in_span(
    p: np.ndarray,
    seq: list,
    a: float,
    b: float,
    tol: float,
    depth: int = 0,
    max_depth: int = 52,
) -> list:
    """Recursively isolate all roots of p in (a, b) using Sturm count.

    Returns list of root values (float) in ascending order, each refined to
    within tol via bisection.
    """
    n_roots = _count_roots_sturm(p, a, b, seq)
    if n_roots == 0:
        return []
    if b - a < tol or depth >= max_depth:
        # One root in this tiny interval — bisect to refine.
        return [_bisect_poly_root(p, a, b, tol)]
    if n_roots == 1:
        return [_bisect_poly_root(p, a, b, tol)]

    # Multiple roots: subdivide and recurse.
    mid = 0.5 * (a + b)
    left_roots = _isolate_roots_in_span(p, seq, a, mid, tol, depth + 1, max_depth)
    right_roots = _isolate_roots_in_span(p, seq, mid, b, tol, depth + 1, max_depth)
    return left_roots + right_roots


def _get_unique_knot_spans(curve: NurbsCurve) -> list:
    """Return list of (u_lo, u_hi) for each distinct non-zero knot span."""
    knots = np.asarray(curve.knots, dtype=float)
    t_min = float(knots[curve.degree])
    t_max = float(knots[-(curve.degree + 1)])
    seen = []
    prev = None
    for u in knots:
        u = float(u)
        if u < t_min - 1e-14 or u > t_max + 1e-14:
            continue
        if prev is not None and u - prev > 1e-14:
            seen.append((prev, u))
        prev = u
    # Ensure full domain is covered even for single-span curves
    if not seen and t_max - t_min > 1e-14:
        seen.append((t_min, t_max))
    return seen


_HONEST_CAVEAT_STURM: str = (
    "HONEST: Analytic Sturm-sequence method (method='sturm-analytic').  "
    "2D non-rational curves only — rational NURBS (weights ≠ 1) are NOT "
    "supported by this method (the numerator κ_signed is no longer a "
    "polynomial in t for rational curves); use find_curve_inflections for "
    "those.  Each Bezier segment's coordinate polynomials are converted from "
    "Bernstein to monomial (power) basis (Farin §5.1; Farouki-Rajan 1987), "
    "and inflection roots are determined by Sturm's theorem (Marden §1.4; "
    "Uspensky §5) applied to p(t) = x'(t)·y''(t) − y'(t)·x''(t).  "
    "Roots are isolated by recursive interval bisection to tol.  "
    "Roots within tol of a knot boundary are attributed to the left span "
    "(open-right intervals).  "
    "is_fair_class_a = True iff ≤ 1 inflection AND no abrupt κ-jump (>5× mean).  "
    "Refs: Marden (1966) §1.4; Uspensky (1948) §5; Farin (2002) §5.1; "
    "Farouki-Rajan (1987) CAGD 4(4)."
)


def find_curve_inflections_sturm(
    curve: NurbsCurve,
    tol: float = 1e-9,
) -> "CurveInflectionReport":
    """Find inflection points of a 2D NURBS curve using Sturm sequences.

    Computes the *analytic* roots of the signed-curvature numerator
    p(t) = x'(t)·y''(t) − y'(t)·x''(t) on each Bezier span of the
    B-spline, using Sturm's theorem for exact root counting followed by
    recursive bisection for isolation.

    This is a *v3* method (Sturm-analytic) complementary to:
      - v1: find_curve_inflections_v1 — sampling + bisection (legacy)
      - v2: find_curve_inflections   — sampling + bisection (current, Class-A)

    Parameters
    ----------
    curve : NurbsCurve
        2D non-rational NURBS curve.  Control points may be 2D or 3D with
        z-components negligible.  *Rational NURBS (non-unit weights) are
        not supported — a warning is added and the method falls back to
        returning a report with an honest_caveat explaining the limitation.*
    tol : float
        Bisection tolerance for root isolation (default 1e-9).

    Returns
    -------
    CurveInflectionReport
        Same structure as v2 ``find_curve_inflections``.  The
        ``honest_caveat`` field notes ``method='sturm-analytic'``.
        Never raises — degenerate inputs return zero-inflection report.

    Algorithm
    ---------
    1. Decompose the non-rational B-spline into Bezier segments (one per
       knot span) by raising each internal knot to multiplicity d.
    2. For each Bezier segment (Bernstein CPs on [u_lo, u_hi]):
       a. Map local parameter s ∈ [0, 1] to global u ∈ [u_lo, u_hi].
       b. Convert x(s), y(s) from Bernstein to monomial basis.
       c. Differentiate to get x'(s), y'(s), x''(s), y''(s).
       d. Form p(s) = x'(s)·y''(s) − y'(s)·x''(s) (degree 2d−3).
       e. Build Sturm sequence {p_0=p, p_1=p', p_{k+1}=−rem(p_{k-1},p_k)}.
       f. Count roots in (0, 1) via V(0) − V(1).
       g. If n_roots > 0, isolate each root by recursive Sturm-bisection.
    3. Map isolated roots from [0, 1] back to [u_lo, u_hi].
    4. Evaluate InflectionPoint fields (xy_mm, curvature_left/right,
       sign_change) using the NURBS evaluator.
    5. Fairness check (Farin §10.6; Sapidis §3): fair iff ≤ 1 inflection
       AND no abrupt κ-jump (|κ| > 5× mean at any inflection).

    References
    ----------
    Marden, M. (1966) "Geometry of Polynomials" §1.4.
    Uspensky, J.V. (1948) "Theory of Equations" §5.
    Farin, G. (2002) "Curves and Surfaces for CAGD" §5.1.
    Farouki, R.T. & Rajan, V.T. (1987) CAGD 4(4) 229-254.
    Piegl, L. & Tiller, W. (1997) "The NURBS Book" §5.4.
    """
    warnings_out: list = []

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
            honest_caveat=_HONEST_CAVEAT_STURM,
        )

    # ------------------------------------------------------------------
    # Guard: rational NURBS not supported (polynomial assumption breaks)
    # ------------------------------------------------------------------
    if curve.is_rational:
        warnings_out.append(
            "find_curve_inflections_sturm: rational NURBS detected (non-unit "
            "weights).  Sturm method requires a polynomial numerator; for rational "
            "curves the numerator of κ_signed is rational, not polynomial.  "
            "Returning zero-inflection report.  Use find_curve_inflections instead."
        )
        return CurveInflectionReport(
            inflection_points=[],
            num_inflections=0,
            max_curvature=0.0,
            min_curvature=0.0,
            is_fair_class_a=True,
            warnings=warnings_out,
            honest_caveat=_HONEST_CAVEAT_STURM,
        )

    # ------------------------------------------------------------------
    # Guard: degree < 3 means p(t) has degree 2d-3 < 0, so no inflections
    # ------------------------------------------------------------------
    d = curve.degree
    if d < 3:
        warnings_out.append(
            f"Curve degree is {d} < 3; p(t) = x'·y'' − y'·x'' has degree "
            f"2d−3 = {2*d-3} ≤ 0.  No inflections for degree < 3 B-splines "
            "(plane curves of degree < 3 have monotone curvature sign per span)."
        )
        return CurveInflectionReport(
            inflection_points=[],
            num_inflections=0,
            max_curvature=0.0,
            min_curvature=0.0,
            is_fair_class_a=True,
            warnings=warnings_out,
            honest_caveat=_HONEST_CAVEAT_STURM,
        )

    tol = float(tol)
    t_min, t_max = _param_range(curve)

    # ------------------------------------------------------------------
    # Decompose into Bezier segments (one per distinct knot span)
    # ------------------------------------------------------------------
    # Build homogeneous control-point array (weights all 1 for non-rational)
    cps = np.asarray(curve.control_points, dtype=float)
    if cps.ndim == 1:
        cps = cps.reshape(-1, 1)
    # Ensure at least 2 columns (x, y)
    if cps.shape[1] < 2:
        warnings_out.append("Control points have fewer than 2 dimensions; cannot compute 2D inflections.")
        return CurveInflectionReport(
            inflection_points=[],
            num_inflections=0,
            max_curvature=0.0,
            min_curvature=0.0,
            is_fair_class_a=True,
            warnings=warnings_out,
            honest_caveat=_HONEST_CAVEAT_STURM,
        )

    # Use _decompose_to_bezier from nurbs.py
    from kerf_cad_core.geom.nurbs import _decompose_to_bezier
    try:
        bezier_segs = _decompose_to_bezier(cps, curve.knots, d)
    except Exception as exc:  # noqa: BLE001
        warnings_out.append(f"Bezier decomposition failed: {exc}")
        return CurveInflectionReport(
            inflection_points=[],
            num_inflections=0,
            max_curvature=0.0,
            min_curvature=0.0,
            is_fair_class_a=True,
            warnings=warnings_out,
            honest_caveat=_HONEST_CAVEAT_STURM,
        )

    # ------------------------------------------------------------------
    # For each Bezier segment, find roots of p(s) in (0, 1)
    # ------------------------------------------------------------------
    all_inflection_u: list = []

    for seg_cps, u_lo, u_hi in bezier_segs:
        span_len = u_hi - u_lo
        if span_len < 1e-14:
            continue

        # seg_cps has shape (d+1, dim), representing the curve on [u_lo, u_hi].
        # The Bezier decomposition uses the global parameterization, so we must
        # interpret the Bernstein parameter s as mapping [0,1] -> [u_lo, u_hi].
        # x'(u) = dx/du = (1/span_len) * dx/ds  (chain rule)
        # so κ numerator w.r.t. global u is:
        #   p_u(u) = x'_u(u)·y''_u(u) - y'_u(u)·x''_u(u)
        # With s = (u - u_lo)/span_len:
        #   x'_s = span_len * x'_u    →  x'_u = x'_s / span_len
        #   x''_u = x''_s / span_len^2
        # Therefore:
        #   p_u = (x'_s/L)·(y''_s/L^2) - (y'_s/L)·(x''_s/L^2)
        #       = (x'_s·y''_s - y'_s·x''_s) / L^3
        # Since L^3 > 0, the sign of p_u equals the sign of p_s.
        # Thus we can find roots of p_s(s) in s ∈ (0, 1) and they correspond
        # to roots of p_u(u) in u ∈ (u_lo, u_hi).

        seg_cps_f = np.asarray(seg_cps, dtype=float)
        if seg_cps_f.shape[1] < 2:
            continue

        # Build monomial polynomials for x(s) and y(s) on [0,1]
        x_poly = _bernstein_to_monomial(seg_cps_f[:, 0])
        y_poly = _bernstein_to_monomial(seg_cps_f[:, 1])

        # Derivatives w.r.t. s
        xp = _poly_deriv(x_poly)   # x'(s), degree d-1
        yp = _poly_deriv(y_poly)   # y'(s), degree d-1
        xpp = _poly_deriv(xp)      # x''(s), degree d-2
        ypp = _poly_deriv(yp)      # y''(s), degree d-2

        # p(s) = x'(s)·y''(s) - y'(s)·x''(s), degree 2d-3
        term1 = _poly_mul(xp, ypp)
        term2 = _poly_mul(yp, xpp)
        p_poly = _poly_trim(_poly_sub(term1, term2))

        if _poly_degree(p_poly) == 0:
            # Constant — either always zero (degenerate) or never zero
            continue

        # Build Sturm sequence for p_poly
        try:
            sturm_seq = _sturm_sequence(p_poly)
        except Exception:  # noqa: BLE001
            continue

        # Collect roots in this span.
        # Sturm counts roots in the OPEN interval (a, b) — roots exactly at
        # s=0 or s=1 are NOT counted by V(a) − V(b).  We handle them
        # explicitly below to avoid missing inflections at knot boundaries.
        roots_s: list = []

        # ---- Interior roots: s in (0, 1) ----
        eps_guard = tol * 0.1
        n_interior = _count_roots_sturm(p_poly, eps_guard, 1.0 - eps_guard, sturm_seq)
        if n_interior > 0:
            try:
                interior_roots = _isolate_roots_in_span(
                    p_poly, sturm_seq, eps_guard, 1.0 - eps_guard, tol
                )
                roots_s.extend(interior_roots)
            except Exception:  # noqa: BLE001
                pass

        # ---- Endpoint s=0: check if p(0) ≈ 0 (only if not the first span,
        #      to avoid attributing the domain start twice) ----
        # We do NOT add s=0 roots here — the previous span's s=1 root covers it.

        # ---- Endpoint s=1: check if p(1) ≈ 0 ----
        # Add only when s=1 corresponds to an interior knot of the domain
        # (i.e. u_hi < t_max), so the last span's endpoint is excluded.
        p_at_1 = abs(_poly_eval(p_poly, 1.0))
        if p_at_1 < tol and u_hi < t_max - tol:
            roots_s.append(1.0)

        # Map roots from [0,1] back to [u_lo, u_hi]
        for s_root in roots_s:
            u_root = u_lo + s_root * span_len
            if t_min - tol <= u_root <= t_max + tol:
                all_inflection_u.append(float(u_root))

    # Deduplicate roots that are within tol of each other (can appear at
    # knot boundaries when adjacent spans both see the same endpoint root).
    all_inflection_u.sort()
    deduped: list = []
    for u in all_inflection_u:
        if not deduped or abs(u - deduped[-1]) > tol * 10:
            deduped.append(u)
    all_inflection_u = deduped

    # ------------------------------------------------------------------
    # Compute curvature statistics for fairness check (using sampled κ)
    # ------------------------------------------------------------------
    _N_STAT = 200
    ts_stat = np.linspace(t_min, t_max, _N_STAT)
    kappa_stat = np.array([_signed_kappa(curve, float(t)) for t in ts_stat])
    kappa_abs = np.abs(kappa_stat)
    max_kappa = float(np.max(kappa_abs))
    min_kappa = float(np.min(kappa_abs))
    mean_kappa = float(np.mean(kappa_abs))

    # ------------------------------------------------------------------
    # Build InflectionPoint objects
    # ------------------------------------------------------------------
    param_range_size = t_max - t_min
    flank_eps = _KAPPA_FLANK_FRAC * param_range_size

    inflection_points: list = []
    for t_star in all_inflection_u:
        try:
            pos = np.asarray(curve.evaluate(float(t_star)), dtype=float).ravel()
            xy: tuple = (float(pos[0]), float(pos[1] if pos.size > 1 else 0.0))
        except Exception:  # noqa: BLE001
            xy = (float("nan"), float("nan"))

        t_left = max(t_min, t_star - flank_eps)
        t_right = min(t_max, t_star + flank_eps)
        k_left = _signed_kappa(curve, t_left)
        k_right = _signed_kappa(curve, t_right)
        sign_chg = (k_left * k_right < 0.0)

        inflection_points.append(InflectionPoint(
            parameter_u=t_star,
            xy_mm=xy,
            curvature_left=k_left,
            curvature_right=k_right,
            sign_change=sign_chg,
        ))

    # ------------------------------------------------------------------
    # Fairness / Class-A check (Farin §10.6; Sapidis §3)
    # ------------------------------------------------------------------
    is_fair = True
    if len(inflection_points) > 1:
        is_fair = False
        warnings_out.append(
            f"Curve has {len(inflection_points)} inflection points — NOT Class-A fair "
            "(Farin §10.6 requires ≤ 1 inflection for a fair curve). "
            "[method=sturm-analytic]"
        )

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
                    f"mean |κ|={mean_kappa:.3e} [method=sturm-analytic]"
                )

    for ip in inflection_points:
        if not ip.sign_change:
            warnings_out.append(
                f"Sturm root at t={ip.parameter_u:.4f} has no confirmed sign change "
                "(may be a double root or numerical artefact near endpoint). "
                "[method=sturm-analytic]"
            )

    return CurveInflectionReport(
        inflection_points=inflection_points,
        num_inflections=len(inflection_points),
        max_curvature=max_kappa,
        min_curvature=min_kappa,
        is_fair_class_a=is_fair,
        warnings=warnings_out,
        honest_caveat=_HONEST_CAVEAT_STURM,
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
