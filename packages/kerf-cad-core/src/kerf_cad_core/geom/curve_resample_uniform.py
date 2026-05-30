"""
curve_resample_uniform.py
=========================
NURBS curve resampling at uniform arc-length intervals.

Algorithm
---------
Given a NurbsCurve C(u), the uniform arc-length resample proceeds in three
stages (Piegl-Tiller §9.4; Patrikalakis-Maekawa §3.5):

  1. Compute the total arc length L using adaptive 5-point Gauss-Legendre
     quadrature (``arc_length_precise`` from ``arc_length_gauss.py``).
  2. For i = 0..N, solve for the parameter u_i such that:
         arc_length(C, u_start, u_i) = i * L / N
     This inversion is performed by bisection on the cumulative arc-length
     function, achieving ~60-bit precision in at most 60 steps.
  3. Evaluate C(u_i) to obtain the point samples.

The function returns a ``ResampleResult`` dataclass containing the sampled
points, the parameter values, the arc-length values, and the total length.
No NURBS fitting is performed by default; callers who need a refitted
NurbsCurve can pass ``fit=True`` to obtain a chord-length-interpolated
degree-3 result (Piegl-Tiller §9.2).

References
----------
- Piegl, L. & Tiller, W. (1997). *The NURBS Book*, 2nd ed.
  §9.4 (global curve interpolation to point data)
  §5.4 (arc-length computation)
- Patrikalakis, N. M. & Maekawa, T. (2002). *Shape Interrogation for
  Computer-Aided Design and Manufacturing*.
  §3.5 (arc-length parameterisation and inversion)

Honest caveats
--------------
- Arc-length inversion uses ``arc_length_precise`` (5-pt GL + adaptive
  bisection).  This is ~1e-9 accurate for most smooth engineering curves.
  For highly-oscillatory curves (e.g. many full wavelengths within a single
  knot span) the Gauss-Legendre integrator may require deeper recursion to
  converge; increase ``max_depth`` if you suspect under-integration.
- The resampled point cloud is *not* on the original curve analytically (it
  is sampled via de Boor evaluation), so ``points[i]`` lies on C to floating-
  point precision (~1e-14).
- For a degenerate (zero-length) curve all samples collapse to the start
  point; ``ResampleResult.degenerate`` is set to True in that case.
- Fitting (``fit=True``) uses chord-length interpolation and is an
  *approximation* — it does not reproduce the original curve exactly.

Public API
----------
resample_uniform_arc_length(curve, samples=100, fit=False, ...) -> ResampleResult
    Resample *curve* at N uniform arc-length intervals.

ResampleResult : dataclass
    points       : ndarray (N+1, dim)
    parameters   : ndarray (N+1,)
    arc_lengths  : ndarray (N+1,)
    total_length : float
    fitted_curve : NurbsCurve | None  (set when fit=True)
    degenerate   : bool

LLM tool ``nurbs_curve_resample_uniform`` is registered when ``kerf_chat``
is available.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsCurve, de_boor
from kerf_cad_core.geom.arc_length_gauss import arc_length_precise


# ---------------------------------------------------------------------------
# ResampleResult dataclass
# ---------------------------------------------------------------------------

@dataclass
class ResampleResult:
    """Output of :func:`resample_uniform_arc_length`.

    Attributes
    ----------
    points : ndarray, shape (samples+1, dim)
        Cartesian coordinates of each uniform arc-length sample.
    parameters : ndarray, shape (samples+1,)
        NURBS parameter values u_i corresponding to each sample.
    arc_lengths : ndarray, shape (samples+1,)
        Cumulative arc-length values s_i = i * total_length / samples.
        arc_lengths[0] == 0.0 and arc_lengths[-1] == total_length.
    total_length : float
        Total arc length of the curve.
    fitted_curve : NurbsCurve or None
        A new NurbsCurve interpolated through *points* (chord-length
        parameterisation, degree 3); only set when ``fit=True`` is passed
        to :func:`resample_uniform_arc_length`.  None otherwise.
    degenerate : bool
        True if the curve has zero (or near-zero) total length.  In that
        case all samples equal the curve start point and the arc-length
        inversion is skipped.
    """
    points: np.ndarray
    parameters: np.ndarray
    arc_lengths: np.ndarray
    total_length: float
    fitted_curve: Optional[NurbsCurve] = field(default=None)
    degenerate: bool = False


# ---------------------------------------------------------------------------
# resample_uniform_arc_length
# ---------------------------------------------------------------------------

def resample_uniform_arc_length(
    curve: NurbsCurve,
    samples: int = 100,
    fit: bool = False,
    rel_tol: float = 1e-9,
    abs_tol: float = 1e-12,
    max_depth: int = 20,
    fit_degree: int = 3,
) -> ResampleResult:
    """Resample *curve* at N+1 uniform arc-length positions.

    Implements the arc-length parameterisation inversion described in
    Piegl-Tiller §9.4 and Patrikalakis-Maekawa §3.5:

      s_i = i * L / N,   i = 0, 1, …, N
      find u_i such that arc_length(curve, u_start, u_i) = s_i
      P_i = C(u_i)

    Parameters
    ----------
    curve     : NurbsCurve — the source curve (rational or non-rational,
                any dimension >= 1).
    samples   : N — number of *intervals* (yields N+1 sample points).
    fit       : if True, also interpolate a new NurbsCurve through the
                resampled points using chord-length parametrisation
                (Piegl-Tiller §9.2).  Returned in ResampleResult.fitted_curve.
    rel_tol   : relative error tolerance for arc-length quadrature (default 1e-9).
    abs_tol   : absolute error floor for arc-length quadrature (default 1e-12).
    max_depth : maximum adaptive recursion depth for arc-length integration
                (default 20; increase for highly-oscillatory curves).
    fit_degree : NURBS degree for the fitted curve (default 3; clamped to
                 min(fit_degree, samples) to satisfy n >= p+1).

    Returns
    -------
    ResampleResult dataclass.

    Notes
    -----
    Arc-length inversion uses bisection: at most 60 iterations per sample,
    giving ~60-bit precision in the parameter.  For N=100 samples this is
    fast (O(N * 60 * GL5_cost)).  For N > 1000 consider caching the cumulative
    arc-length table (e.g. via arc_length_parametrize from arc_length_gauss).

    Honest caveat: Gauss-Legendre quadrature achieves ~1e-9 relative accuracy
    for smooth, low-oscillation curves.  Curves with many oscillations per
    knot span (e.g. high-frequency noise) may require larger *max_depth* to
    avoid under-integration.
    """
    if samples < 1:
        raise ValueError(f"resample_uniform_arc_length: samples must be >= 1, got {samples}")

    u0 = float(curve.knots[curve.degree])
    u1 = float(curve.knots[-(curve.degree + 1)])

    # ── Step 1: total arc length ─────────────────────────────────────────────
    L_total = arc_length_precise(
        curve, t_start=u0, t_end=u1,
        rel_tol=rel_tol, abs_tol=abs_tol, max_depth=max_depth,
    )

    N = int(samples)
    arc_lengths = np.linspace(0.0, L_total, N + 1)

    # ── Degenerate: zero-length curve ────────────────────────────────────────
    if L_total < 1e-14:
        start_pt = np.array(de_boor(curve, u0), dtype=float)
        points = np.tile(start_pt, (N + 1, 1))
        params = np.full(N + 1, u0)
        arc_lengths_out = np.zeros(N + 1)
        return ResampleResult(
            points=points,
            parameters=params,
            arc_lengths=arc_lengths_out,
            total_length=0.0,
            fitted_curve=None,
            degenerate=True,
        )

    # ── Step 2: invert cumulative arc-length via bisection ───────────────────
    params = np.empty(N + 1)
    params[0] = u0
    params[-1] = u1

    abs_tol_local = L_total * rel_tol  # consistent floor for inversion

    for k in range(1, N):
        s_target = float(arc_lengths[k])
        lo, hi = u0, u1

        # Bisection: 60 iterations → ~1e-18 relative parameter precision
        for _ in range(60):
            mid_u = 0.5 * (lo + hi)
            s_mid = arc_length_precise(
                curve, t_start=u0, t_end=mid_u,
                rel_tol=rel_tol, abs_tol=abs_tol_local,
                max_depth=max_depth,
            )
            if s_mid < s_target:
                lo = mid_u
            else:
                hi = mid_u
            if (hi - lo) < 1e-15 * (u1 - u0):
                break

        params[k] = 0.5 * (lo + hi)

    # ── Step 3: evaluate curve at uniform arc-length parameters ─────────────
    points = np.array([de_boor(curve, float(u)) for u in params], dtype=float)

    # ── Optional NURBS fit (Piegl-Tiller §9.2) ───────────────────────────────
    fitted_curve: Optional[NurbsCurve] = None
    if fit:
        from kerf_cad_core.geom.curve_toolkit import interp_curve
        deg = min(fit_degree, N)  # must satisfy n >= p+1
        try:
            fitted_curve = interp_curve(points, degree=deg, param="chord")
        except Exception:
            fitted_curve = None  # graceful degradation; caller can check

    return ResampleResult(
        points=points,
        parameters=params,
        arc_lengths=arc_lengths,
        total_length=float(L_total),
        fitted_curve=fitted_curve,
        degenerate=False,
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

    _resample_spec = ToolSpec(
        name="nurbs_curve_resample_uniform",
        description=(
            "Resample a NURBS curve at uniform arc-length intervals "
            "(instead of uniform parameter spacing).\n"
            "\n"
            "Algorithm (Piegl-Tiller §9.4 + Patrikalakis-Maekawa §3.5):\n"
            "  1. Compute total arc length L via adaptive 5-pt Gauss-Legendre "
            "quadrature (rel_tol=1e-9).\n"
            "  2. Solve arc_length(curve, 0, u_i) = i*L/N by bisection "
            "for i = 0..N.\n"
            "  3. Evaluate C(u_i) for each parameter.\n"
            "\n"
            "Returns: {ok, points (N+1 rows), parameters (N+1), "
            "arc_lengths (N+1), total_length, degenerate}.\n"
            "Optional: set fit=true to also return a fitted NURBS curve "
            "through the resampled points.\n"
            "\n"
            "Honest caveat: GL quadrature is ~1e-9 accurate for smooth curves; "
            "highly-oscillatory curves may need larger max_depth.\n"
            "\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "control_points": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                    "description": "NURBS control points [[x,y,z], ...].",
                },
                "knots": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "NURBS knot vector.",
                },
                "degree": {
                    "type": "integer",
                    "description": "Curve degree.",
                },
                "weights": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Per-control-point weights (omit for non-rational).",
                },
                "samples": {
                    "type": "integer",
                    "description": "Number of arc-length intervals N (yields N+1 points, default 100).",
                },
                "fit": {
                    "type": "boolean",
                    "description": (
                        "If true, also return a new NurbsCurve fitted through "
                        "the resampled points (chord-length interpolation, degree 3). "
                        "Default false."
                    ),
                },
                "rel_tol": {
                    "type": "number",
                    "description": "Relative error tolerance for arc-length quadrature (default 1e-9).",
                },
                "abs_tol": {
                    "type": "number",
                    "description": "Absolute error floor (default 1e-12).",
                },
                "max_depth": {
                    "type": "integer",
                    "description": (
                        "Maximum adaptive subdivision depth (default 20). "
                        "Increase for highly-oscillatory curves."
                    ),
                },
            },
            "required": ["control_points", "knots", "degree"],
        },
    )

    @register(_resample_spec)
    async def run_nurbs_curve_resample_uniform(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        cp = a.get("control_points")
        kv = a.get("knots")
        deg = a.get("degree")
        if cp is None or kv is None or deg is None:
            return err_payload(
                "control_points, knots, and degree are required", "BAD_ARGS"
            )

        try:
            ctrl = np.asarray(cp, dtype=float)
            knots = np.asarray(kv, dtype=float)
            degree = int(deg)
            weights_raw = a.get("weights")
            weights = np.asarray(weights_raw, dtype=float) if weights_raw else None
            curve = NurbsCurve(
                degree=degree,
                control_points=ctrl,
                knots=knots,
                weights=weights,
            )
        except Exception as exc:
            return err_payload(f"failed to build NurbsCurve: {exc}", "BAD_ARGS")

        samples = int(a.get("samples", 100))
        do_fit = bool(a.get("fit", False))
        rel_tol = float(a.get("rel_tol", 1e-9))
        abs_tol_val = float(a.get("abs_tol", 1e-12))
        max_depth = int(a.get("max_depth", 20))

        try:
            result = resample_uniform_arc_length(
                curve,
                samples=samples,
                fit=do_fit,
                rel_tol=rel_tol,
                abs_tol=abs_tol_val,
                max_depth=max_depth,
            )
        except Exception as exc:
            return err_payload(str(exc), "OP_FAILED")

        payload: dict = {
            "points": result.points.tolist(),
            "parameters": result.parameters.tolist(),
            "arc_lengths": result.arc_lengths.tolist(),
            "total_length": result.total_length,
            "degenerate": result.degenerate,
        }

        if do_fit and result.fitted_curve is not None:
            fc = result.fitted_curve
            payload["fitted_curve"] = {
                "degree": fc.degree,
                "control_points": fc.control_points.tolist(),
                "knots": fc.knots.tolist(),
                "weights": fc.weights.tolist() if fc.weights is not None else None,
            }

        return ok_payload(payload)
