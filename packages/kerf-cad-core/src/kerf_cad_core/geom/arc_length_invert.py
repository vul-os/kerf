"""
arc_length_invert.py
====================
NURBS curve arc-length inversion: given target arc length s ∈ [0, L], find
parameter t such that ∫₀^t |C'(τ)| dτ = s.

Reference: Piegl & Tiller §11.2 (curve arc length and reparameterisation) +
           Sederberg "CAGD" §6.4.

Algorithm
---------
Newton–Raphson iteration on f(t) = arc_length(0, t) − s, using
    t_{n+1} = t_n − f(t_n) / |C'(t_n)|
with automatic fall-back to bisection when Newton diverges or when the
speed |C'(t)| is near zero.

Used for
--------
* Chord-length parameterisation
* Even-spaced CAM toolpath sampling
* Rebar layout on curved beams (civil/structural)
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Optional

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsCurve, curve_derivative
from kerf_cad_core.geom.curve_toolkit import curve_length, _curve_speed


__all__ = [
    "ArcLengthInvertResult",
    "invert_arc_length",
]


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------

@dataclass
class ArcLengthInvertResult:
    """Result of :func:`invert_arc_length`.

    Attributes
    ----------
    t_param : float
        Parameter value t ∈ [t_start, t_end] such that arc_length(t_start, t) ≈ s.
    residual_mm : float
        |arc_length(t_start, t) − s| at the returned t_param.  Units inherit
        from the curve's coordinate system (typically mm).
    iterations : int
        Number of Newton / bisection steps consumed.
    honest_caveat : str
        Human-readable caveat about accuracy or degenerate inputs.
    """

    t_param: float
    residual_mm: float
    iterations: int
    honest_caveat: str


# ---------------------------------------------------------------------------
# Core implementation
# ---------------------------------------------------------------------------

_SPEED_EPS = 1e-14   # speed below which Newton step is skipped (use bisection)
_BRACKET_N = 32      # number of coarse samples used to bracket before bisect


def invert_arc_length(
    curve: NurbsCurve,
    target_arc_length_mm: float,
    tol: float = 1e-6,
    max_iter: int = 30,
    *,
    t_start: Optional[float] = None,
    t_end: Optional[float] = None,
) -> ArcLengthInvertResult:
    """Invert arc length on a NURBS curve.

    Find parameter *t* such that ∫_{t_start}^{t} |C'(τ)| dτ = s.

    Parameters
    ----------
    curve : NurbsCurve
        The NURBS curve to invert.
    target_arc_length_mm : float
        Target arc length *s* (same units as the curve's coordinate system).
    tol : float, optional
        Residual tolerance in the same units as *s*.  Defaults to 1e-6.
    max_iter : int, optional
        Maximum Newton / bisection iterations.  Defaults to 30.
    t_start : float, optional
        Start of the domain interval (default: curve start).
    t_end : float, optional
        End of the domain interval (default: curve end).

    Returns
    -------
    ArcLengthInvertResult
        * ``t_param`` — the inverted parameter.
        * ``residual_mm`` — absolute residual |arc_length(t_start, t) − s|.
        * ``iterations`` — iteration count.
        * ``honest_caveat`` — note about accuracy or edge cases.

    Notes
    -----
    * Newton iteration converges super-linearly for smooth curves with
      non-degenerate speed, typically in 3–8 steps.
    * Highly non-uniform knot vectors (spike/flat speed regions) may force
      bisection fall-back, increasing iteration count.
    * Convergence tolerance is on arc-length residual, not parameter residual.
    """
    # ── Domain bounds ─────────────────────────────────────────────────────────
    u0 = float(curve.knots[curve.degree])
    u1 = float(curve.knots[-(curve.degree + 1)])
    a = u0 if t_start is None else float(t_start)
    b = u1 if t_end is None else float(t_end)
    a = max(a, u0)
    b = min(b, u1)

    # ── Total length of the sub-interval ─────────────────────────────────────
    total_length = curve_length(curve, a, b, tol=tol * 1e-3)

    # ── Edge cases ────────────────────────────────────────────────────────────
    s = float(target_arc_length_mm)

    if s <= 0.0:
        caveat = (
            "target_arc_length_mm <= 0: clamped to t_start."
            if s < 0.0
            else "target_arc_length_mm == 0: returning t_start."
        )
        return ArcLengthInvertResult(
            t_param=a,
            residual_mm=0.0,
            iterations=0,
            honest_caveat=caveat,
        )

    if s >= total_length:
        residual = abs(s - total_length)
        if s > total_length:
            warnings.warn(
                f"invert_arc_length: target {s} exceeds curve length {total_length:.6g}; "
                "clamped to t_end.",
                UserWarning,
                stacklevel=2,
            )
            caveat = (
                f"target {s:.6g} > total length {total_length:.6g}; "
                "clamped to t_end."
            )
        else:
            caveat = "target equals total length; returning t_end."
        return ArcLengthInvertResult(
            t_param=b,
            residual_mm=residual,
            iterations=0,
            honest_caveat=caveat,
        )

    # ── Initial guess via linear interpolation on a coarse sample table ───────
    sample_ts = np.linspace(a, b, _BRACKET_N + 1)
    sample_ls = np.zeros(_BRACKET_N + 1)
    for i in range(_BRACKET_N):
        segment_len = curve_length(curve, float(sample_ts[i]), float(sample_ts[i + 1]),
                                   tol=tol * 0.1)
        sample_ls[i + 1] = sample_ls[i] + segment_len

    # Bracket: find index where cumulative length first exceeds s
    idx = int(np.searchsorted(sample_ls, s, side="left"))
    idx = max(1, min(idx, _BRACKET_N))

    # Linear interpolation inside the bracket
    s_lo = sample_ls[idx - 1]
    s_hi = sample_ls[idx]
    t_lo = float(sample_ts[idx - 1])
    t_hi = float(sample_ts[idx])
    if s_hi > s_lo:
        alpha = (s - s_lo) / (s_hi - s_lo)
    else:
        alpha = 0.5
    t = t_lo + alpha * (t_hi - t_lo)

    # ── Newton–Raphson with bisection fall-back ───────────────────────────────
    iters = 0
    caveat_parts: list[str] = []
    bisection_used = False

    for _ in range(max_iter):
        iters += 1
        f = curve_length(curve, a, t, tol=tol * 1e-3) - s
        speed = _curve_speed(curve, t)

        if abs(f) <= tol:
            break

        if speed < _SPEED_EPS:
            # Degenerate point: use bisection step
            bisection_used = True
            if f < 0:
                t_lo = t
                s_lo = curve_length(curve, a, t, tol=tol * 1e-3)
            else:
                t_hi = t
                s_hi = curve_length(curve, a, t, tol=tol * 1e-3)
            t = 0.5 * (t_lo + t_hi)
            continue

        t_new = t - f / speed

        # Check if Newton step stays inside the bracket
        if t_lo <= t_new <= t_hi:
            t = t_new
        else:
            # Newton diverged or overshot: fall back to bisection
            bisection_used = True
            f_lo = curve_length(curve, a, t_lo, tol=tol * 1e-3) - s
            if f_lo < 0:
                t_lo = t if f < 0 else t_lo
                t_hi = t if f > 0 else t_hi
            t = 0.5 * (t_lo + t_hi)

    # ── Final residual ────────────────────────────────────────────────────────
    final_length = curve_length(curve, a, t, tol=tol * 1e-4)
    residual = abs(final_length - s)

    if bisection_used:
        caveat_parts.append(
            "bisection used (Newton diverged or low speed at some point)"
        )
    if residual > tol:
        caveat_parts.append(
            f"residual {residual:.3e} exceeds tol {tol:.3e}; "
            f"increase max_iter or loosen tol."
        )

    caveat = "; ".join(caveat_parts) if caveat_parts else (
        "Newton–Raphson converged normally."
    )

    return ArcLengthInvertResult(
        t_param=float(np.clip(t, a, b)),
        residual_mm=residual,
        iterations=iters,
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
    _invert_arc_length_spec = ToolSpec(
        name="nurbs_invert_arc_length",
        description=(
            "Given a NURBS curve (as control_points + knots + degree) and a "
            "target arc length s ∈ [0, L], find the curve parameter t such that "
            "∫₀^t |C'(τ)| dτ = s.\n"
            "\n"
            "Uses Newton–Raphson iteration (Piegl & Tiller §11.2) with "
            "automatic bisection fall-back for non-uniform or degenerate curves.\n"
            "\n"
            "Returns: {ok, t_param, residual_mm, iterations, honest_caveat}\n"
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
                    "description": "Knot vector of the NURBS curve.",
                },
                "degree": {
                    "type": "integer",
                    "description": "Polynomial degree of the NURBS curve.",
                },
                "weights": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Optional per-control-point weights (rational NURBS). Omit for polynomial.",
                },
                "target_arc_length_mm": {
                    "type": "number",
                    "description": "Target arc length s in the curve's coordinate units.",
                },
                "tol": {
                    "type": "number",
                    "description": "Residual tolerance (default 1e-6, same units as arc length).",
                },
                "max_iter": {
                    "type": "integer",
                    "description": "Maximum Newton/bisection iterations (default 30).",
                },
            },
            "required": ["control_points", "knots", "degree", "target_arc_length_mm"],
        },
    )

    @register(_invert_arc_length_spec)
    async def run_nurbs_invert_arc_length(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        try:
            ctrl = np.array(a["control_points"], dtype=float)
            knots = np.array(a["knots"], dtype=float)
            degree = int(a["degree"])
            s = float(a["target_arc_length_mm"])
            tol = float(a.get("tol", 1e-6))
            max_iter = int(a.get("max_iter", 30))
            weights_raw = a.get("weights")
            weights = np.array(weights_raw, dtype=float) if weights_raw is not None else None
        except (KeyError, ValueError, TypeError) as exc:
            return err_payload(f"bad argument types: {exc}", "BAD_ARGS")

        try:
            curve = NurbsCurve(
                degree=degree,
                control_points=ctrl,
                knots=knots,
                weights=weights,
            )
        except Exception as exc:
            return err_payload(f"could not construct NurbsCurve: {exc}", "BAD_ARGS")

        try:
            result = invert_arc_length(curve, s, tol=tol, max_iter=max_iter)
        except Exception as exc:
            return err_payload(str(exc), "OP_FAILED")

        return ok_payload({
            "t_param": result.t_param,
            "residual_mm": result.residual_mm,
            "iterations": result.iterations,
            "honest_caveat": result.honest_caveat,
        })
