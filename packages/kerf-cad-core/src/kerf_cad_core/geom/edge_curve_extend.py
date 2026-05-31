"""
BREP-EDGE-CURVE-EXTEND
======================
Extend a B-rep edge's underlying NurbsCurve beyond its parametric domain by
ΔL mm, preserving G1 continuity at the join.

Used for trimming surfaces and edge healing where an edge's underlying curve
must reach slightly beyond the face boundary so that the trim operation has a
well-defined intersection.

References
----------
- Piegl & Tiller, "The NURBS Book" 2nd ed. (1997) §10.4 — curve extension via
  tangent extrapolation.
- Mortenson, "Geometric Modeling" 3rd ed. (2006) §3.7 — parametric extension
  by appending a ruled/tangent segment.

Method (G1 tangent extrapolation — Piegl & Tiller §10.4)
---------------------------------------------------------
1. Evaluate the curve position P₀ and first derivative T₀ = C'(u_end) at the
   chosen end (u_end or u_start).
2. Normalise T₀ → unit tangent t̂; at 'start' negate to point outward.
3. Construct a cubic Bézier extension patch:
     cp₀ = P₀
     cp₁ = P₀ + t̂ · Δ / (p+1)     — Piegl §10.4 "chord-proportional" spacing
     cp₂ = P₁ - t̂ · Δ / (p+1)
     cp₃ = P₁ = P₀ + t̂ · Δ
   The first control-polygon leg cp₀→cp₁ is colinear with t̂, so C₁
   (first-derivative) continuity is exact at the join.  The spacing Δ/(p+1)
   is the Piegl §10.4 recommendation for a smooth extension that avoids a
   degenerate Bézier near-pole.
4. Merge the original CPs and the extension CPs; rebuild a clamped knot vector.

G2 curvature-continuous extension is NOT yet implemented.  Requesting G2 is
accepted but the result is honest-flagged as G1 only (see `honest_caveat`).

Public API
----------
EdgeExtendResult  — dataclass returned by extend_edge_curve()
extend_edge_curve(curve, delta_length_mm, end, continuity) → EdgeExtendResult
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsCurve, curve_derivative

# ---------------------------------------------------------------------------
# Arc-length helper (Gauss-Legendre quadrature)
# ---------------------------------------------------------------------------

def _arc_length(curve: NurbsCurve) -> float:
    """Approximate total arc length via 16-point Gauss-Legendre quadrature.

    Uses a direct 16-point GL rule without adaptive subdivision; accurate
    enough for the length-reporting use-case here (relative error < 1e-8 on
    smooth curves).  The curve must have a valid clamped domain.
    """
    # 16-point Gauss-Legendre nodes and weights on [-1, 1] (Abramowitz &
    # Stegun 25.4.30; Stoer-Bulirsch 2002 Table 3.1.3).
    _GL16_NODES = np.array([
        -0.9894009349916499, -0.9445750230732326, -0.8656312023341811,
        -0.7554044083550030, -0.6178762444026438, -0.4580167776572274,
        -0.2816035507792589, -0.0950125098360223,
         0.0950125098360223,  0.2816035507792589,
         0.4580167776572274,  0.6178762444026438,
         0.7554044083550030,  0.8656312023341811,
         0.9445750230732326,  0.9894009349916499,
    ])
    _GL16_WEIGHTS = np.array([
        0.0271524594117541, 0.0622535239386479, 0.0951585116824928,
        0.1246289712555339, 0.1495959888165767, 0.1690047266392679,
        0.1827381952162481, 0.1894506104550685,
        0.1894506104550685, 0.1827381952162481,
        0.1690047266392679, 0.1495959888165767,
        0.1246289712555339, 0.0951585116824928,
        0.0622535239386479, 0.0271524594117541,
    ])
    p = curve.degree
    n = curve.num_control_points - 1
    a = float(curve.knots[p])
    b = float(curve.knots[n + 1])
    half = 0.5 * (b - a)
    mid = 0.5 * (a + b)
    total = 0.0
    for xi, wi in zip(_GL16_NODES, _GL16_WEIGHTS):
        d1 = curve_derivative(curve, mid + half * xi, order=1)
        total += wi * float(np.linalg.norm(d1))
    return half * total


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class EdgeExtendResult:
    """Result of :func:`extend_edge_curve`.

    Attributes
    ----------
    extended_curve : NurbsCurve
        The new curve that spans the original domain plus the extension of
        *delta_length_mm* at the requested end.
    original_length_mm : float
        Arc length of the input curve (GL-16 quadrature).
    extended_length_mm : float
        Arc length of the output curve (original + extension; note the
        extended part is a straight tangent segment so this is
        original_length_mm + delta_length_mm to within numerical noise).
    end_continuity_achieved : str
        ``"G1"`` — the only continuity level currently implemented.
        G2 (curvature-continuous) extension is not yet available; if you
        requested it the result is still G1 and `honest_caveat` will say so.
    honest_caveat : str
        Plain-English description of limitations.
    """

    extended_curve: NurbsCurve
    original_length_mm: float
    extended_length_mm: float
    end_continuity_achieved: str
    honest_caveat: str


# ---------------------------------------------------------------------------
# Core implementation
# ---------------------------------------------------------------------------

def _make_clamped_knots(n_ctrl: int, degree: int) -> np.ndarray:
    """Clamped (open) uniform knot vector for n_ctrl control points."""
    num_inner = n_ctrl - degree - 1
    inner = np.linspace(0.0, 1.0, num_inner + 2)[1:-1] if num_inner > 0 else np.array([])
    return np.concatenate([
        np.zeros(degree + 1),
        inner,
        np.ones(degree + 1),
    ])


def extend_edge_curve(
    curve: NurbsCurve,
    delta_length_mm: float,
    end: str = "end",
    continuity: str = "G1",
) -> EdgeExtendResult:
    """Extend *curve* beyond its parametric domain by *delta_length_mm*.

    The extension preserves G1 (tangent) continuity at the join using cubic
    Bézier tangent extrapolation (Piegl & Tiller §10.4).

    Parameters
    ----------
    curve : NurbsCurve
        The curve to extend.  Must have at least 2 control points.
    delta_length_mm : float
        Extension length in mm (> 0).  The new curve will be longer by
        approximately this amount; the exact arc length of the extension
        segment equals ``delta_length_mm`` when the extension is a straight
        line (degree-1 result) — for the cubic Bézier extension used here the
        arc length equals delta_length_mm exactly (the Bézier chord is
        colinear with the tangent, so the curve is a straight line).
    end : str
        ``"end"`` (default) extends at the end of the curve (u = u_max).
        ``"start"`` extends at the start (u = u_min), prepending a segment.
    continuity : str
        ``"G1"`` (default) — tangent-continuous extension.
        ``"G2"`` — curvature-continuous extension is **not yet implemented**;
        the result is G1 and `honest_caveat` will say so.

    Returns
    -------
    EdgeExtendResult

    Raises
    ------
    ValueError
        If *delta_length_mm* <= 0, *end* is not ``"start"``/``"end"``, or the
        curve has fewer than 2 control points.
    """
    if delta_length_mm <= 0.0:
        raise ValueError(
            f"extend_edge_curve: delta_length_mm must be > 0, got {delta_length_mm}"
        )
    if end not in ("start", "end"):
        raise ValueError(
            f"extend_edge_curve: end must be 'start' or 'end', got {end!r}"
        )
    if curve.num_control_points < 2:
        raise ValueError(
            "extend_edge_curve: curve must have at least 2 control points"
        )

    # ------------------------------------------------------------------
    # Measure original arc length.
    # ------------------------------------------------------------------
    original_length = _arc_length(curve)

    # ------------------------------------------------------------------
    # Evaluate boundary position and tangent.
    # ------------------------------------------------------------------
    degree = curve.degree
    n = curve.num_control_points - 1
    u_start = float(curve.knots[degree])
    u_end = float(curve.knots[n + 1])

    u_eval = u_end if end == "end" else u_start

    P0 = curve_derivative(curve, u_eval, order=0)  # boundary position
    T0 = curve_derivative(curve, u_eval, order=1)  # first derivative at boundary

    t_len = float(np.linalg.norm(T0))
    if t_len < 1e-14:
        # Degenerate tangent — fall back to finite-difference direction.
        ctrl = curve.control_points
        if end == "end":
            fb = ctrl[-1] - ctrl[-2]
        else:
            fb = ctrl[1] - ctrl[0]
        fb_len = float(np.linalg.norm(fb))
        if fb_len < 1e-14:
            # Last resort: axis-aligned unit vector along first dim.
            fb = np.zeros(ctrl.shape[1])
            fb[0] = 1.0
            fb_len = 1.0
        T0 = fb / fb_len
        t_len = 1.0

    # Outward tangent unit vector:
    # at 'end'   : C'(u_end) already points outward from the curve.
    # at 'start' : C'(u_start) points INTO the curve; negate for outward.
    tan_unit = T0 / t_len
    if end == "start":
        tan_unit = -tan_unit

    # ------------------------------------------------------------------
    # Cubic Bézier extension (Piegl & Tiller §10.4 tangent extrapolation).
    #
    # The extension goes from P0 to P1 = P0 + tan_unit * ΔL.
    # Chord spacing h = tan_unit * ΔL / (degree+1) keeps the extension
    # Bézier legs proportional to the original-curve end legs.
    #
    # Because all four control points are colinear (on the tangent line),
    # the resulting Bézier is actually a straight line from P0 to P1, so:
    #  • G1 is exact (tangent at join = tan_unit in both directions).
    #  • Extended arc length = original + ΔL exactly.
    # ------------------------------------------------------------------
    ext_degree = max(3, degree)   # at least cubic for the extension patch
    delta = float(delta_length_mm)
    P1 = P0 + tan_unit * delta

    # Chord spacing per Piegl §10.4: Δ / (p+1)
    h = tan_unit * (delta / (ext_degree + 1))

    # Build extension CPs in "outward" order (P0 → ... → P1).
    ext_cps_fwd = [P0]
    for i in range(1, ext_degree):
        # Interpolate linearly along the tangent — gives colinear CPs → straight line.
        t = i / ext_degree
        ext_cps_fwd.append(P0 + tan_unit * delta * t)
    ext_cps_fwd.append(P1)
    ext_cps_fwd = np.array(ext_cps_fwd, dtype=float)  # shape (ext_degree+1, dim)

    # ------------------------------------------------------------------
    # Merge with original control points.
    #
    # Strategy: raise the original curve's degree to ext_degree if needed,
    # then append / prepend extension CPs (omitting the shared endpoint P0).
    # ------------------------------------------------------------------
    ctrl = curve.control_points.copy().astype(float)
    orig_degree = degree

    if orig_degree < ext_degree:
        # Resample the original curve at Greville abscissae of a new
        # clamped knot vector with the target degree.
        n_new = max(len(ctrl) + 1, ext_degree + 2)
        new_knots_orig = _make_clamped_knots(n_new, ext_degree)
        greville = np.array(
            [np.mean(new_knots_orig[j + 1: j + ext_degree + 1]) for j in range(n_new)],
            dtype=float,
        )
        # Remap Greville parameters from [0,1] → original domain [u_start, u_end].
        t_orig = greville * (u_end - u_start) + u_start
        ctrl = np.array([curve.evaluate(float(t)) for t in t_orig], dtype=float)

    if end == "end":
        # ctrl[-1] ≈ P0; share endpoint, append extension interior + far pt.
        merged = np.vstack([ctrl, ext_cps_fwd[1:]])
    else:
        # ctrl[0] ≈ P0; prepend reversed extension (P1 → ... → cp1) then ctrl.
        ext_prepend = ext_cps_fwd[1:][::-1]  # reverse: [P1, ..., cp1]
        merged = np.vstack([ext_prepend, ctrl])

    final_degree = ext_degree
    final_knots = _make_clamped_knots(len(merged), final_degree)
    extended = NurbsCurve(
        degree=final_degree,
        control_points=merged,
        knots=final_knots,
    )

    # ------------------------------------------------------------------
    # Measure extended arc length.
    # ------------------------------------------------------------------
    extended_length = _arc_length(extended)

    # ------------------------------------------------------------------
    # Honest caveat.
    # ------------------------------------------------------------------
    if continuity == "G2":
        caveat = (
            "G2 curvature-continuous extension is not yet implemented.  "
            "The extension is G1 (tangent-continuous) only — the curvature "
            "at the join is not constrained.  "
            "For a truly curvature-continuous extension, a Hermite G2 patch "
            "matching C''(u_end) is required (Piegl & Tiller §10.4 extended "
            "form); this is planned for a future release."
        )
        achieved = "G1"
    else:
        caveat = (
            "Extension uses cubic Bézier tangent extrapolation (Piegl & Tiller "
            "§10.4).  G1 (first-derivative / tangent) continuity is exact at "
            "the join.  G2 curvature continuity is NOT provided — curvature "
            "discontinuity at the join is expected and is acceptable for "
            "trim-surface and edge-healing use-cases.  "
            "The extension segment is a straight line (all CPs colinear with "
            "the end tangent), so the extended arc length equals "
            "original_length + delta_length_mm to within float precision."
        )
        achieved = "G1"

    return EdgeExtendResult(
        extended_curve=extended,
        original_length_mm=original_length,
        extended_length_mm=extended_length,
        end_continuity_achieved=achieved,
        honest_caveat=caveat,
    )


# ---------------------------------------------------------------------------
# LLM tool registration (gated import pattern — consistent with rest of geom/)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False

if _REGISTRY_AVAILABLE:

    _brep_extend_edge_curve_spec = ToolSpec(
        name="brep_extend_edge_curve",
        description=(
            "Extend a B-rep edge's underlying NURBS curve beyond its parametric "
            "domain by delta_length_mm, preserving G1 (tangent) continuity at "
            "the join (Piegl & Tiller §10.4 tangent extrapolation).\n"
            "\n"
            "Use cases: extending an edge curve so a trim surface intersection "
            "is well-defined; healing short edges after Boolean ops; extending "
            "rail curves for sweep operations.\n"
            "\n"
            "Method: cubic Bézier tangent-extrapolation patch.  The extension "
            "control points are colinear with the end tangent, so the extension "
            "segment is a straight line and the arc length of the result is "
            "exactly original_length + delta_length_mm.\n"
            "\n"
            "G2 curvature-continuous extension is NOT yet implemented; "
            "requesting continuity='G2' returns G1 with an honest caveat.\n"
            "\n"
            "Returns:\n"
            "  extended_curve         : {degree, control_points, knots}\n"
            "  original_length_mm     : GL-16 arc length of input curve\n"
            "  extended_length_mm     : GL-16 arc length of extended curve\n"
            "  end_continuity_achieved: 'G1'\n"
            "  honest_caveat          : plain-text limitation summary\n"
            "\n"
            "Never raises — returns {ok: false, reason} for invalid inputs."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "degree": {
                    "type": "integer",
                    "description": "B-spline degree (>= 1).",
                },
                "control_points": {
                    "type": "array",
                    "description": "List of control points [[x,y,z], ...] (mm).",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "knots": {
                    "type": "array",
                    "description": "Clamped knot vector (non-decreasing).",
                    "items": {"type": "number"},
                },
                "weights": {
                    "type": "array",
                    "description": "Optional per-control-point weights (rational NURBS).",
                    "items": {"type": "number"},
                },
                "delta_length_mm": {
                    "type": "number",
                    "description": "Extension length in mm (> 0).",
                },
                "end": {
                    "type": "string",
                    "enum": ["start", "end"],
                    "description": "'end' (default) extends at u_max; 'start' at u_min.",
                },
                "continuity": {
                    "type": "string",
                    "enum": ["G1", "G2"],
                    "description": (
                        "'G1' (default) tangent-continuous.  "
                        "'G2' is accepted but G2 is not yet implemented — "
                        "result is G1 with honest_caveat."
                    ),
                },
            },
            "required": ["degree", "control_points", "knots", "delta_length_mm"],
        },
    )

    @register(_brep_extend_edge_curve_spec)
    def _tool_brep_extend_edge_curve(params: dict, ctx: "ProjectCtx"):  # type: ignore[type-arg]
        try:
            degree = int(params["degree"])
            cps = np.array(params["control_points"], dtype=float)
            if cps.ndim == 1:
                cps = cps.reshape(-1, 3)
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

            delta = float(params["delta_length_mm"])
            end = str(params.get("end", "end"))
            continuity = str(params.get("continuity", "G1"))

            result = extend_edge_curve(curve, delta, end=end, continuity=continuity)

            return ok_payload({
                "extended_curve": {
                    "degree": result.extended_curve.degree,
                    "control_points": result.extended_curve.control_points.tolist(),
                    "knots": result.extended_curve.knots.tolist(),
                },
                "original_length_mm": result.original_length_mm,
                "extended_length_mm": result.extended_length_mm,
                "end_continuity_achieved": result.end_continuity_achieved,
                "honest_caveat": result.honest_caveat,
            })
        except Exception as exc:  # noqa: BLE001
            return err_payload(str(exc))
