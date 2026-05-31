"""
NURBS-CURVE-EVOLUTE
===================
Compute the evolute E(t) of a 2D NURBS curve C(t).

The evolute is the locus of centres of osculating circles:

    E(t) = C(t) + n̂(t) / κ(t)

where

    n̂(t) — unit principal normal to C at t
    κ(t)  — (unsigned) curvature of C at t

For a plane curve in ℝ² written as C(t) = (x(t), y(t)):

    C'  = (x', y')
    C'' = (x'', y'')
    speed   = |C'| = √(x'² + y'²)
    κ       = (x'·y'' − y'·x'') / speed³        (signed — we use |κ| here)
    n̂  = (−y', x') / speed                      (left-hand unit normal)

    E(t) = C(t) + n̂(t) / κ(t)
         = (x − y'/speed / κ,  y + x'/speed / κ)

Note the sign of n̂: we use the LEFT-hand normal (rotate tangent +90°) so that
the evolute lies on the *concave* side, matching the classical definition
(do Carmo §1.6, formula (1.6.4); Mortenson §4.2).

Cusps of the evolute
---------------------
Cusps occur where dκ/dt = 0 and κ ≠ 0 (i.e. at vertices of the original curve,
where the curvature has a local extremum).  We detect cusps as sign changes of
the finite-difference dκ/dt across samples.

Applications
------------
* Cycloidal gear involute / evolute analysis (gear-tooth profile)
* Cam-profile design — cusps mark the cam's pitch-curve inflections
* CNC offset analysis — evolute predicts self-intersection of offset curves
* Astronomical / spirograph pattern generation

References
----------
do Carmo, M.P. (1976) "Differential Geometry of Curves and Surfaces" §1.6.
Mortenson, M.E. (1985/1997) "Geometric Modeling" §4.2 — Plane Curves and
    Their Evolutes.
Piegl, L. & Tiller, W. (1997) "The NURBS Book" §6.1 (curve derivatives).
Farin, G. (1997) "Curves and Surfaces for CAGD" §2.6 (curvature formulae).

Public API
----------
EvoluteResult   — dataclass with result fields.
compute_curve_evolute(curve, num_samples=200, min_curvature=1e-6)
    -> EvoluteResult

Scope / honest caveats
-----------------------
* 2D curves only.  The input NurbsCurve must have 2D control points (or a 3D
  curve lying flat in the XY-plane; Z components are ignored).
* 3D Frenet-Serret evolutes (torsion component) are NOT supported in this
  module.  For a space curve the evolute would require torsion computation and
  lives on the osculating sphere; see do Carmo §1.7.
* Curvature is computed by finite differences of 1st/2nd NURBS derivatives;
  samples with |κ| < min_curvature are skipped (locally straight → evolute → ∞).
* Cusp detection is sign-change based and limited to the sample resolution;
  high-frequency oscillations may produce false positives.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Tuple

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsCurve, curve_derivative

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SPEED_TOL: float = 1e-12   # |C'| below this → singular / skip


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class EvoluteResult:
    """Result of compute_curve_evolute().

    Attributes
    ----------
    evolute_points : list[tuple[float, float]]
        2D (x, y) evolute sample points E(t_i) for each non-skipped t_i.
        Empty when the curve is straight (all samples skipped).
    t_params : list[float]
        The parameter values t_i corresponding to evolute_points.
    num_samples : int
        Total number of t values sampled (= ``num_samples`` argument).
    num_cusps_detected : int
        Number of cusp-like samples detected (local extrema of |κ| where
        dκ/dt changes sign).
    cusp_t_params : list[float]
        t values at detected cusps.
    honest_caveat : str
        Plain-language caveat about scope and accuracy.
    """

    evolute_points: List[Tuple[float, float]] = field(default_factory=list)
    t_params: List[float] = field(default_factory=list)
    num_samples: int = 0
    num_cusps_detected: int = 0
    cusp_t_params: List[float] = field(default_factory=list)
    honest_caveat: str = ""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _curve_param_range(curve: NurbsCurve) -> Tuple[float, float]:
    """Return (t_min, t_max) of the clamped knot domain."""
    t_min = float(curve.knots[curve.degree])
    t_max = float(curve.knots[-(curve.degree + 1)])
    return t_min, t_max


def _eval_2d(curve: NurbsCurve, t: float) -> Tuple[float, float]:
    """Evaluate the curve, returning only the (x, y) components."""
    pt = curve.evaluate(t)
    arr = np.asarray(pt, dtype=float).ravel()
    return float(arr[0]), float(arr[1] if arr.size > 1 else 0.0)


def _deriv_2d(curve: NurbsCurve, t: float, order: int) -> Tuple[float, float]:
    """Evaluate a derivative, returning only the (x, y) components."""
    d = curve_derivative(curve, t, order=order)
    arr = np.asarray(d, dtype=float).ravel()
    return float(arr[0]), float(arr[1] if arr.size > 1 else 0.0)


def _curvature_2d(
    xp: float, yp: float, xpp: float, ypp: float
) -> Tuple[float, float]:
    """Compute (signed_curvature, speed) from first/second derivatives.

    Signed curvature:  κ = (x'·y'' − y'·x'') / |C'|³
    Speed:             |C'| = √(x'² + y'²)

    Returns (0.0, 0.0) when the curve is singular (speed ≈ 0).
    """
    speed = math.sqrt(xp * xp + yp * yp)
    if speed < _SPEED_TOL:
        return 0.0, 0.0
    kappa_signed = (xp * ypp - yp * xpp) / (speed ** 3)
    return kappa_signed, speed


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_curve_evolute(
    curve: NurbsCurve,
    num_samples: int = 200,
    min_curvature: float = 1e-6,
) -> EvoluteResult:
    """Compute the evolute of a 2D NURBS curve by uniform parameter sampling.

    The evolute is E(t) = C(t) + n̂(t) / κ(t) where n̂ is the left-hand unit
    normal and κ is the unsigned curvature.  Samples where |κ| < min_curvature
    are skipped (the evolute diverges to infinity for locally straight segments).

    Parameters
    ----------
    curve : NurbsCurve
        A 2D NURBS curve (control points in ℝ² or ℝ³ with z≈0).
        Degree ≥ 2 required for meaningful curvature (degree 1 = straight line,
        evolute is empty).
    num_samples : int
        Number of uniform parameter samples in [t_min, t_max] (default 200).
    min_curvature : float
        Samples with |κ(t)| < min_curvature are skipped.  Default 1e-6.

    Returns
    -------
    EvoluteResult
        evolute_points, t_params, num_samples, num_cusps_detected,
        cusp_t_params, honest_caveat.

    Never raises — degenerate inputs return an empty result with an honest
    caveat.

    References
    ----------
    do Carmo §1.6; Mortenson §4.2; Piegl & Tiller §6.1.
    """
    if not isinstance(curve, NurbsCurve):
        return EvoluteResult(
            num_samples=0,
            honest_caveat=(
                "Input must be a NurbsCurve.  "
                "3D evolutes (Frenet-Serret) not yet supported; 2D only."
            ),
        )

    num_samples = max(3, int(num_samples))
    min_curvature = float(min_curvature)

    t_min, t_max = _curve_param_range(curve)
    ts = np.linspace(t_min, t_max, num_samples)

    # ------------------------------------------------------------------
    # Pass 1 — collect (t, kappa_signed, evolute_x, evolute_y) per sample
    # ------------------------------------------------------------------
    valid_t: List[float] = []
    evolute_pts: List[Tuple[float, float]] = []
    kappa_arr: List[float] = []          # signed κ for cusp detection

    for t in ts:
        t_f = float(t)
        try:
            cx, cy = _eval_2d(curve, t_f)
            xp, yp = _deriv_2d(curve, t_f, order=1)
            xpp, ypp = _deriv_2d(curve, t_f, order=2)
        except Exception:
            continue

        kappa_signed, speed = _curvature_2d(xp, yp, xpp, ypp)
        kappa_abs = abs(kappa_signed)

        if kappa_abs < min_curvature:
            # Record as skipped — still include in kappa array for tracking
            kappa_arr.append(kappa_signed)
            continue

        # Left-hand unit normal: rotate tangent 90° CCW.
        # T̂ = (x', y') / speed  →  n̂_left = (−y', x') / speed
        nx = -yp / speed
        ny = xp / speed

        # E(t) = C(t) + n̂ / κ
        # Using SIGNED κ so the centre of curvature is always on the correct
        # (concave) side automatically:
        #   n̂_left / κ_signed gives the centre of curvature on the inside.
        inv_kappa = 1.0 / kappa_signed
        ex = cx + nx * inv_kappa
        ey = cy + ny * inv_kappa

        valid_t.append(t_f)
        evolute_pts.append((ex, ey))
        kappa_arr.append(kappa_signed)

    # ------------------------------------------------------------------
    # Pass 2 — cusp detection: local extrema of |κ| (do Carmo §1.6)
    # Cusps of the evolute ↔ vertices of C (points where dκ/dt = 0, κ≠0).
    # Algorithm: windowed local extremum of |κ| with amplitude guard.
    # Use a window of W samples on each side.  A sample is a cusp candidate
    # when its |κ| is the strict max or min within the window AND the window
    # amplitude (max - min) exceeds 1% of the global |κ| range.  This guard
    # suppresses floating-point chatter on constant-curvature curves (circles)
    # where the kappa array is numerically flat to machine precision.
    # For closed curves the |κ| array is extended with wrap-around padding.
    # ------------------------------------------------------------------
    cusp_t_params: List[float] = []

    # Build the |κ| array over all samples.
    kabs: List[float] = []
    for t_f in ts.tolist():
        try:
            xp, yp = _deriv_2d(curve, t_f, order=1)
            xpp, ypp = _deriv_2d(curve, t_f, order=2)
            ks, _ = _curvature_2d(xp, yp, xpp, ypp)
        except Exception:
            ks = 0.0
        kabs.append(abs(ks))

    n_ks = len(kabs)
    ks_arr = np.array(kabs)
    kappa_global_range = float(ks_arr.max() - ks_arr.min())

    # Only proceed if the curvature actually varies (skip flat/constant curves).
    if kappa_global_range > 1e-8:
        min_amplitude = kappa_global_range * 0.005   # 0.5% noise guard for window
        # Window half-width: ~5% of num_samples, at least 2.
        W = max(2, min(num_samples // 20, 15))

        # Detect closed curve (C(t_min) ≈ C(t_max)).
        try:
            sx, sy = _eval_2d(curve, t_min)
            ex2, ey2 = _eval_2d(curve, t_max)
            closed = math.sqrt((ex2 - sx) ** 2 + (ey2 - sy) ** 2) < 1e-6
        except Exception:
            closed = False

        if closed:
            # For a closed curve, the last sample is a duplicate of the first.
            # Use only the unique interior samples (indices 0..n_ks-2) and wrap.
            core = ks_arr[:-1]
            n_core = len(core)
            # Circular padding of width W on each side.
            padded = np.concatenate([core[-W:], core, core[:W]])
        else:
            core = ks_arr
            n_core = n_ks
            padded = core

        ts_list = ts.tolist()

        for i in range(n_core):
            k_curr = kabs[i]
            if k_curr < min_curvature:
                continue

            pi = i + W if closed else i
            lo = max(0, pi - W)
            hi = min(len(padded) - 1, pi + W)
            window = padded[lo:hi + 1]

            w_max = float(window.max())
            w_min = float(window.min())
            amplitude = w_max - w_min

            # Require the window to have meaningful variation (suppresses
            # floating-point noise on locally-flat segments).  Since we only
            # reach here when kappa_global_range > 1e-8, even a very small
            # min_amplitude (0.5% of global range) is safe.
            if amplitude < min_amplitude:
                continue  # locally flat within the window — skip

            # Strict local maximum of |κ|
            others_max = float(np.delete(window, pi - lo).max()) if len(window) > 1 else -1.0
            if k_curr > others_max and k_curr >= w_max - 1e-14:
                cusp_t_params.append(float(ts_list[i]))
                continue

            # Strict local minimum of |κ|
            others_min = float(np.delete(window, pi - lo).min()) if len(window) > 1 else 1e300
            if k_curr < others_min and k_curr <= w_min + 1e-14:
                cusp_t_params.append(float(ts_list[i]))

    caveat = (
        "HONEST: 2D curves only; 3D Frenet-Serret evolutes (with torsion) are "
        "not yet supported.  Curvature is evaluated from NURBS analytical "
        "1st/2nd derivatives; samples with |κ| < min_curvature are skipped "
        "(evolute diverges to infinity there).  Cusp detection is sign-change "
        "based and depends on sample density — may miss cusps for highly "
        "undersampled curves.  References: do Carmo §1.6; Mortenson §4.2."
    )

    return EvoluteResult(
        evolute_points=evolute_pts,
        t_params=valid_t,
        num_samples=num_samples,
        num_cusps_detected=len(cusp_t_params),
        cusp_t_params=cusp_t_params,
        honest_caveat=caveat,
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
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    _evolute_spec = ToolSpec(
        name="nurbs_compute_curve_evolute",
        description=(
            "Compute the evolute E(t) of a 2D NURBS curve C(t).\n"
            "\n"
            "The evolute is the locus of centres of osculating circles:\n"
            "  E(t) = C(t) + n̂(t) / κ(t)\n"
            "where n̂ is the unit left-hand normal and κ is the curvature.\n"
            "\n"
            "Applications: cycloidal-gear design, cam-profile cusp analysis, "
            "CNC offset self-intersection prediction.\n"
            "\n"
            "Returns:\n"
            "  evolute_points      : [[x,y], ...] evolute sample coordinates\n"
            "  t_params            : parameter values for each evolute point\n"
            "  num_samples         : total samples taken\n"
            "  num_cusps_detected  : number of cusp-like extrema found\n"
            "  cusp_t_params       : t values at detected cusps\n"
            "  honest_caveat       : scope and accuracy caveats\n"
            "\n"
            "HONEST: 2D only.  3D Frenet-Serret evolutes not yet supported.\n"
            "Samples where |κ| < min_curvature are skipped (evolute → ∞).\n"
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
                        "(z components are ignored for the 2D evolute)."
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
                    "description": "Optional per-control-point weights (rational NURBS).",
                    "items": {"type": "number"},
                },
                "num_samples": {
                    "type": "integer",
                    "description": "Number of uniform parameter samples (default 200).",
                },
                "min_curvature": {
                    "type": "number",
                    "description": (
                        "Samples with |κ| < min_curvature are skipped "
                        "(evolute diverges). Default 1e-6."
                    ),
                },
            },
            "required": ["degree", "control_points", "knots"],
        },
    )

    @register(_evolute_spec)
    def _tool_nurbs_compute_curve_evolute(
        params: dict, ctx: "ProjectCtx"  # type: ignore[type-arg]
    ) -> str:
        try:
            degree = int(params["degree"])
            raw_cp = params["control_points"]
            cps = np.array(raw_cp, dtype=float)
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

            num_samples = int(params.get("num_samples") or 200)
            min_curvature = float(params.get("min_curvature") or 1e-6)

            result = compute_curve_evolute(curve, num_samples=num_samples,
                                           min_curvature=min_curvature)

            return ok_payload({
                "evolute_points": [list(p) for p in result.evolute_points],
                "t_params": result.t_params,
                "num_samples": result.num_samples,
                "num_evolute_points": len(result.evolute_points),
                "num_cusps_detected": result.num_cusps_detected,
                "cusp_t_params": result.cusp_t_params,
                "honest_caveat": result.honest_caveat,
            })
        except Exception as exc:  # noqa: BLE001
            return err_payload(str(exc))
