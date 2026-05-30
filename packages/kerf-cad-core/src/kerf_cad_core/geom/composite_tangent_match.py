"""
NURBS-COMPOSITE-TANGENT-MATCH
==============================
Adjust the seam control points of a composite NURBS curve chain so that
neighboring segments share a common tangent direction (G1 continuity) or
both tangent direction and curvature (G2 continuity) at each joint.

Theory
------
For a chain of NURBS segments C^(0)(t), C^(1)(t), ..., C^(n-1)(t) meeting
at joints p_i = C^(i)(t_end^i) = C^(i+1)(t_start^(i+1)):

**G1 (tangent continuity) — Klass 1980 §3 / Farin §8.4**
  Two segments meet with G1 at a joint iff their end/start tangents are
  parallel (same direction, possibly different magnitude).  The seam
  control points CP_{n-1}^(i) (second-to-last) and CP_1^(i+1) (second)
  must be *collinear* with the shared endpoint CP_n^(i) = CP_0^(i+1).

  The Klass / Farin bisector construction moves CP_{n-1}^(i) and CP_1^(i+1)
  along the bisector of the two segment endpoint tangents so the joint
  tangent becomes the bisector direction:

      T_bisect = (T_left/|T_left| + T_right/|T_right|) / 2   [normalised]

  where T_left  = CP_n^(i) - CP_{n-1}^(i)   (last chord of segment i)
        T_right = CP_1^(i+1) - CP_0^(i+1)   (first chord of segment i+1)

  The chord lengths are preserved: only directions change.

**G2 (curvature continuity) — Piegl-Tiller §7.3**
  G2 additionally requires that the second derivatives match in magnitude
  (up to a common positive scalar).  After G1 is imposed, the second
  derivative at the end of segment i is proportional to the net force on
  the third-to-last CP.  We adjust the third CP row of each segment to
  satisfy the G2 cross-derivative constraint:

      C''_left(t_end) ∝ C''_right(t_start)

  Specifically, for degree-p segments with uniform normalised knots the
  second derivative uses the relation (Piegl-Tiller §7.3, Eq. 7.2):

      Δ²P_{n-p} = p(p-1)/Δu² · (end second difference of CPs)

  We solve for the third-row displacement that equalises curvature vectors
  via a scalar stretch.  Convergence is not guaranteed when the curvature
  magnitudes differ by more than a factor of 10; in that case we set
  `g2_converged[i] = False` and return the best G1 result unchanged.

References
----------
- Klass, R. (1980). "An offset spline approximation for plane cubic splines."
  Computer-Aided Design, 12(1), 33–36. (§3 — bisector tangent matching)
- Farin, G. (2002). "Curves and Surfaces for CAGD", 5th ed., §8.4
  (geometric continuity conditions for composite Bézier / NURBS curves).
- Piegl, L. & Tiller, W. (1997). "The NURBS Book", 2nd ed., §7.3
  (continuity conditions and knot insertion for composite NURBS).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsCurve, curve_derivative

__all__ = [
    "CompositeMatchResult",
    "match_composite_tangents",
]

_TOL_PARALLEL = 1e-10   # tangent vectors considered parallel below this cross-product norm
_TOL_SPEED    = 1e-12   # |C'| considered zero below this
_G2_CURV_RATIO_LIMIT = 10.0  # if |κ_left/κ_right| > this, G2 declared non-converged


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class CompositeMatchResult:
    """Result returned by :func:`match_composite_tangents`.

    Attributes
    ----------
    adjusted_curves : list[NurbsCurve]
        New list of NurbsCurve objects with adjusted seam control points.
        Curves not adjacent to any seam are returned unchanged (same object).
    max_cp_displacement : float
        Maximum Euclidean displacement applied to any single control point
        across all segments and all seams.  Zero when the composite is
        already G1/G2.
    residual_tangent_error_per_seam : list[float]
        Per-seam residual tangent error after matching (rad).  Angle between
        left and right tangent directions at each joint.  Should be close to
        zero after G1 matching (numerical noise only).
    g2_converged : list[bool]
        One flag per seam.  True when G2 was requested AND the curvature
        matching converged; True (vacuously) for seams where target == "G1".
        Only meaningful when ``target="G2"``; all True when ``target="G1"``.
    target : str
        The continuity target used ("G1" or "G2").
    """

    adjusted_curves: List[NurbsCurve]
    max_cp_displacement: float
    residual_tangent_error_per_seam: List[float]
    g2_converged: List[bool] = field(default_factory=list)
    target: str = "G1"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _curve_domain(curve: NurbsCurve):
    """Return (t_start, t_end) for the parametric domain of *curve*."""
    p = curve.degree
    n = curve.num_control_points - 1
    return float(curve.knots[p]), float(curve.knots[n + 1])


def _safe_normalize(v: np.ndarray) -> Optional[np.ndarray]:
    """Return unit vector or None if |v| < _TOL_SPEED."""
    mag = float(np.linalg.norm(v))
    if mag < _TOL_SPEED:
        return None
    return v / mag


def _tangent_at_end(curve: NurbsCurve) -> np.ndarray:
    """Raw (un-normalised) tangent C'(t_end)."""
    _, t_end = _curve_domain(curve)
    return curve_derivative(curve, t_end, order=1)


def _tangent_at_start(curve: NurbsCurve) -> np.ndarray:
    """Raw (un-normalised) tangent C'(t_start)."""
    t_start, _ = _curve_domain(curve)
    return curve_derivative(curve, t_start, order=1)


def _second_deriv_at_end(curve: NurbsCurve) -> np.ndarray:
    """Raw second derivative C''(t_end)."""
    _, t_end = _curve_domain(curve)
    return curve_derivative(curve, t_end, order=2)


def _second_deriv_at_start(curve: NurbsCurve) -> np.ndarray:
    """Raw second derivative C''(t_start)."""
    t_start, _ = _curve_domain(curve)
    return curve_derivative(curve, t_start, order=2)


def _copy_curve(curve: NurbsCurve) -> NurbsCurve:
    """Return a deep copy of *curve* (new CP array, shared knots/weights)."""
    return NurbsCurve(
        degree=curve.degree,
        control_points=curve.control_points.copy(),
        knots=curve.knots,
        weights=curve.weights,
    )


def _bisector_tangent(t_left: np.ndarray, t_right: np.ndarray) -> Optional[np.ndarray]:
    """Compute the unit bisector of two endpoint tangents.

    Implements the Klass 1980 §3 / Farin §8.4 bisector construction:
        T_bisect = (T_left/|T_left| + T_right/|T_right|) / normalise

    Returns None when either tangent is near-zero or the bisector is
    zero (anti-parallel tangents — 180° kink, G1 is impossible without
    moving the joint point itself).
    """
    t_l_unit = _safe_normalize(t_left)
    t_r_unit = _safe_normalize(t_right)
    if t_l_unit is None or t_r_unit is None:
        return None
    bisect = t_l_unit + t_r_unit
    return _safe_normalize(bisect)


def _apply_g1_seam(
    left: NurbsCurve,
    right: NurbsCurve,
    preserve_endpoint: bool,
) -> tuple[NurbsCurve, NurbsCurve, float, float]:
    """
    Adjust seam CPs of *left* and *right* for G1 tangent continuity.

    The joint point is ``left.control_points[-1]`` == ``right.control_points[0]``.
    We move the *second-to-last* CP of left and the *second* CP of right so
    that both chords point along the bisector of the old endpoint tangents,
    preserving chord lengths (only direction changes).

    Parameters
    ----------
    left, right : NurbsCurve
        Deep copies are returned; originals are not modified.
    preserve_endpoint : bool
        When True the shared joint point (left[-1] = right[0]) is not moved.
        Currently this is always True for G1 (the endpoint is the seam; we
        only move the adjacent CPs, not the endpoint itself).

    Returns
    -------
    (new_left, new_right, max_displacement, residual_angle)
    """
    new_left  = _copy_curve(left)
    new_right = _copy_curve(right)

    joint = new_left.control_points[-1].copy()   # shared endpoint

    # Chord vectors from joint to adjacent CPs (before matching).
    # For a clamped NURBS, C'(t_end)  ∝  (CP[-1] - CP[-2])
    #                       C'(t_start) ∝  (CP[1]  - CP[0])
    chord_left  = joint - new_left.control_points[-2]   # direction: end tangent
    chord_right = new_right.control_points[1] - joint   # direction: start tangent

    bisect = _bisector_tangent(chord_left, chord_right)

    if bisect is None:
        # Anti-parallel or zero chord — cannot bisect without moving joint;
        # return curves unchanged, report residual = π.
        residual = math.pi
        return new_left, new_right, 0.0, residual

    len_left  = float(np.linalg.norm(chord_left))
    len_right = float(np.linalg.norm(chord_right))

    # New positions: keep chord lengths, redirect along bisector.
    new_cp_left_prev  = joint - bisect * len_left
    new_cp_right_next = joint + bisect * len_right

    disp_left  = float(np.linalg.norm(new_cp_left_prev  - new_left.control_points[-2]))
    disp_right = float(np.linalg.norm(new_cp_right_next - new_right.control_points[1]))

    new_left.control_points[-2]  = new_cp_left_prev
    new_right.control_points[1]  = new_cp_right_next

    max_disp = max(disp_left, disp_right)

    # Residual angle: should be ~0 after matching.
    t_l_after = new_left.control_points[-1] - new_left.control_points[-2]
    t_r_after = new_right.control_points[1] - new_right.control_points[0]
    cross_after = np.cross(
        np.append(t_l_after, 0.0) if t_l_after.shape[0] == 2 else t_l_after,
        np.append(t_r_after, 0.0) if t_r_after.shape[0] == 2 else t_r_after,
    )
    cross_mag = float(np.linalg.norm(cross_after))
    dot_after = float(np.dot(
        t_l_after / (np.linalg.norm(t_l_after) + 1e-300),
        t_r_after / (np.linalg.norm(t_r_after) + 1e-300),
    ))
    residual = float(math.atan2(cross_mag, max(dot_after, -1.0 + 1e-15)))

    return new_left, new_right, max_disp, residual


def _apply_g2_seam(
    left: NurbsCurve,
    right: NurbsCurve,
) -> tuple[NurbsCurve, NurbsCurve, float, bool]:
    """
    Adjust the third-row CPs for G2 curvature continuity (Piegl-Tiller §7.3).

    Assumes G1 has already been imposed (left[-2], right[1] aligned along
    the bisector tangent).  We then move left[-3] and right[2] to equalise
    the curvature magnitude at the seam.

    The G2 constraint for a clamped, uniform knot-vector degree-p segment is:

        C''_left(t_end)  = p*(p-1)/Δu_left²  * (CP[-1] - 2*CP[-2] + CP[-3])
        C''_right(t_start) = p*(p-1)/Δu_right² * (CP[2] - 2*CP[1] + CP[0])

    Setting C''_left = α * C''_right with α > 0 (Piegl-Tiller §7.3, Eq. 7.2),
    we solve for the scalar α via least-squares minimisation on the bisector
    direction, then adjust CP[-3] and CP[2] symmetrically.

    Returns
    -------
    (new_left, new_right, max_cp_disp, converged)
    """
    if left.degree < 2 or right.degree < 2:
        # G2 requires at least degree 2.
        return left, right, 0.0, False
    if left.num_control_points < 4 or right.num_control_points < 4:
        # Need at least 4 CPs per segment for independent G2 adjustment.
        return left, right, 0.0, False

    # Knot-span widths at endpoint (non-zero span adjacent to boundary).
    def _endpoint_knot_span(curve: NurbsCurve, end: str) -> float:
        p = curve.degree
        n = curve.num_control_points - 1
        knots = curve.knots
        if end == "end":
            # Last non-zero span: knots[n+1] - knots[n]
            for k in range(len(knots) - 1, 0, -1):
                if knots[k] - knots[k - 1] > 1e-14:
                    return float(knots[k] - knots[k - 1])
        else:
            for k in range(len(knots) - 1):
                if knots[k + 1] - knots[k] > 1e-14:
                    return float(knots[k + 1] - knots[k])
        return 1.0  # fallback (shouldn't happen for valid clamped NURBS)

    p_l = left.degree
    p_r = right.degree
    du_l = _endpoint_knot_span(left, "end")
    du_r = _endpoint_knot_span(right, "start")

    # Second differences (CP second derivatives, up to scalar p*(p-1)/du²)
    sd_left  = (left.control_points[-1]
                - 2 * left.control_points[-2]
                + left.control_points[-3])
    sd_right = (right.control_points[2]
                - 2 * right.control_points[1]
                + right.control_points[0])

    coeff_l = p_l * (p_l - 1) / (du_l ** 2)
    coeff_r = p_r * (p_r - 1) / (du_r ** 2)

    c2_left  = coeff_l * sd_left
    c2_right = coeff_r * sd_right

    mag_l = float(np.linalg.norm(c2_left))
    mag_r = float(np.linalg.norm(c2_right))

    if mag_l < _TOL_SPEED or mag_r < _TOL_SPEED:
        # One segment is straight; G2 is degenerate — flag non-converged.
        return left, right, 0.0, False

    ratio = mag_l / mag_r
    if ratio > _G2_CURV_RATIO_LIMIT or ratio < 1.0 / _G2_CURV_RATIO_LIMIT:
        # Wildly different curvature magnitudes — G2 matching may distort
        # the curves; flag non-converged and return G1 result as-is.
        # (Honest flag per spec: document and return non-converged.)
        return left, right, 0.0, False

    # We want: C''_left = α * C''_right (same direction and same magnitude
    # scaled by α).  We pick α = sqrt(mag_l / mag_r) and adjust each
    # segment's third CP by half the required delta so the seam is
    # equi-distributed.
    #
    # Target second difference for left: sd_left_target = (1/coeff_l) * α * c2_right
    alpha = math.sqrt(ratio)   # geometric mean — symmetric split
    c2_target = alpha * c2_right        # target C'' at seam (both agree on this)
    sd_left_target  = c2_target  / coeff_l
    sd_right_target = c2_target  / coeff_r

    # Solve for new CP[-3] from the second difference:
    # sd_left_target = CP[-1] - 2*CP[-2] + CP[-3]  => CP[-3] = sd_left_target - CP[-1] + 2*CP[-2]
    new_cp_left_3  = sd_left_target  - left.control_points[-1]  + 2 * left.control_points[-2]
    # sd_right_target = CP[2] - 2*CP[1] + CP[0]    => CP[2]  = sd_right_target - CP[0] + 2*CP[1]
    new_cp_right_2 = sd_right_target - right.control_points[0] + 2 * right.control_points[1]

    new_left  = _copy_curve(left)
    new_right = _copy_curve(right)

    disp_l = float(np.linalg.norm(new_cp_left_3  - new_left.control_points[-3]))
    disp_r = float(np.linalg.norm(new_cp_right_2 - new_right.control_points[2]))

    new_left.control_points[-3]  = new_cp_left_3
    new_right.control_points[2]  = new_cp_right_2

    return new_left, new_right, max(disp_l, disp_r), True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def match_composite_tangents(
    curves: List[NurbsCurve],
    target: str = "G1",
    preserve_endpoint: bool = True,
) -> CompositeMatchResult:
    """Impose G1 or G2 continuity at every seam of a composite NURBS curve.

    For each pair of adjacent segments (curves[i], curves[i+1]) the seam
    control points are adjusted using the Klass 1980 §3 / Farin §8.4
    bisector construction for G1, extended by the Piegl-Tiller §7.3
    second-derivative constraint for G2.

    Parameters
    ----------
    curves : list[NurbsCurve]
        Ordered chain of NURBS segments.  The last CP of curves[i] must equal
        (or be very close to) the first CP of curves[i+1].  At least 2
        segments required.
    target : {"G1", "G2"}
        Continuity target.  "G1" enforces tangent direction continuity.
        "G2" additionally enforces curvature continuity (may not converge for
        wildly mismatched curvature magnitudes — see ``g2_converged`` flags).
    preserve_endpoint : bool
        Reserved for future use (the shared joint point is never moved by the
        bisector construction; only adjacent CPs are adjusted).  Always True.

    Returns
    -------
    CompositeMatchResult
        - ``adjusted_curves`` — new list of NurbsCurve with adjusted seam CPs.
        - ``max_cp_displacement`` — max Euclidean CP displacement (all seams).
        - ``residual_tangent_error_per_seam`` — per-seam angle residual (rad).
        - ``g2_converged`` — per-seam G2 convergence flag (all True for G1).
        - ``target`` — the requested target string.

    Raises
    ------
    ValueError
        If fewer than 2 curves are supplied, or ``target`` is not "G1"/"G2".

    References
    ----------
    Klass 1980 §3; Farin §8.4; Piegl-Tiller §7.3.
    """
    if len(curves) < 2:
        raise ValueError("match_composite_tangents requires at least 2 curves")
    if target not in ("G1", "G2"):
        raise ValueError(f"target must be 'G1' or 'G2', got {target!r}")

    # Work on copies throughout.
    adjusted: List[NurbsCurve] = [_copy_curve(c) for c in curves]

    n_seams = len(curves) - 1
    residuals: List[float]     = []
    g2_flags:  List[bool]      = []
    max_disp: float             = 0.0

    for i in range(n_seams):
        left  = adjusted[i]
        right = adjusted[i + 1]

        # ── G1 ──────────────────────────────────────────────────────────────
        new_left, new_right, disp_g1, resid = _apply_g1_seam(
            left, right, preserve_endpoint
        )
        max_disp = max(max_disp, disp_g1)
        residuals.append(resid)

        converged_g2 = True   # vacuously True for G1-only

        # ── G2 ──────────────────────────────────────────────────────────────
        if target == "G2":
            new_left, new_right, disp_g2, converged_g2 = _apply_g2_seam(
                new_left, new_right
            )
            max_disp = max(max_disp, disp_g2)

        g2_flags.append(converged_g2)
        adjusted[i]     = new_left
        adjusted[i + 1] = new_right

    return CompositeMatchResult(
        adjusted_curves=adjusted,
        max_cp_displacement=max_disp,
        residual_tangent_error_per_seam=residuals,
        g2_converged=g2_flags,
        target=target,
    )


# ---------------------------------------------------------------------------
# LLM tool registration
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False

if _REGISTRY_AVAILABLE:

    _spec = ToolSpec(
        name="nurbs_match_composite_tangents",
        description=(
            "Impose G1 (tangent) or G2 (curvature) continuity at every seam of a "
            "composite NURBS curve chain.\n"
            "\n"
            "For each adjacent pair of segments the seam control points are adjusted "
            "using the Klass 1980 §3 / Farin §8.4 bisector construction (G1) extended "
            "by the Piegl-Tiller §7.3 second-derivative constraint (G2).\n"
            "\n"
            "Returns:\n"
            "  adjusted_curves : list of NURBS curves (degree + control_points + knots)\n"
            "  max_cp_displacement : max CP displacement across all seams (float)\n"
            "  residual_tangent_error_per_seam : per-seam residual angle (rad)\n"
            "  g2_converged : per-seam G2 convergence flag (array of bool)\n"
            "  target : the continuity target used\n"
            "\n"
            "G2 may not converge when segment curvature magnitudes differ by more "
            "than 10×; the g2_converged flag is False for those seams.\n"
            "\n"
            "Never raises — returns {ok:false, reason} for invalid inputs."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "curves": {
                    "type": "array",
                    "description": (
                        "Ordered list of NURBS segment descriptors. "
                        "Each segment: {degree, control_points, knots, weights?}."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "degree": {"type": "integer"},
                            "control_points": {
                                "type": "array",
                                "items": {"type": "array", "items": {"type": "number"}},
                            },
                            "knots": {
                                "type": "array",
                                "items": {"type": "number"},
                            },
                            "weights": {
                                "type": "array",
                                "items": {"type": "number"},
                            },
                        },
                        "required": ["degree", "control_points", "knots"],
                    },
                },
                "target": {
                    "type": "string",
                    "description": "'G1' (tangent continuity) or 'G2' (curvature continuity).",
                    "enum": ["G1", "G2"],
                    "default": "G1",
                },
            },
            "required": ["curves"],
        },
    )

    @register(_spec)
    def _tool_nurbs_match_composite_tangents(
        params: dict,
        ctx: "ProjectCtx",  # type: ignore[type-arg]
    ):
        try:
            raw_curves = params["curves"]
            target = str(params.get("target") or "G1")

            nurbs_list: List[NurbsCurve] = []
            for seg in raw_curves:
                cps = np.array(seg["control_points"], dtype=float)
                if cps.ndim == 1:
                    cps = cps.reshape(-1, 3)
                knots = np.array(seg["knots"], dtype=float)
                weights = seg.get("weights")
                if weights is not None:
                    weights = np.array(weights, dtype=float)
                nurbs_list.append(
                    NurbsCurve(
                        degree=int(seg["degree"]),
                        control_points=cps,
                        knots=knots,
                        weights=weights,
                    )
                )

            result = match_composite_tangents(nurbs_list, target=target)

            curves_out = []
            for c in result.adjusted_curves:
                entry: dict = {
                    "degree": c.degree,
                    "control_points": c.control_points.tolist(),
                    "knots": c.knots.tolist(),
                }
                if c.weights is not None:
                    entry["weights"] = c.weights.tolist()
                curves_out.append(entry)

            return ok_payload({
                "adjusted_curves": curves_out,
                "max_cp_displacement": result.max_cp_displacement,
                "residual_tangent_error_per_seam": result.residual_tangent_error_per_seam,
                "g2_converged": result.g2_converged,
                "target": result.target,
            })
        except Exception as exc:  # noqa: BLE001
            return err_payload(str(exc))
