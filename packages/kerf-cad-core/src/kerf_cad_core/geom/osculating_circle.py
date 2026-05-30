"""
NURBS-CURVE-CURVATURE-OSCULATING-CIRCLE
========================================
Osculating circle of a NURBS curve at parameter *t*.

Reference: do Carmo, "Differential Geometry of Curves and Surfaces" §1.5.

At a regular point the osculating circle is the unique circle that:
  * is tangent to C at t (same tangent line),
  * has the same curvature as C at t (lies in the osculating plane),
  * its centre is the *centre of curvature* = C(t) + (1/κ) · N(t).

Formulae used
-------------
κ(t) = |C′(t) × C″(t)| / |C′(t)|³          (standard cross-product form)
radius = 1 / κ
N(t)  = (C′(t) × C″(t)) × C′(t)             (principal normal, un-normalised)
         / |(C′(t) × C″(t)) × C′(t)|

The normal-plane normal is the unit tangent T(t) = C′(t) / |C′(t)|.

Degenerate cases
----------------
* κ = 0 (inflection point or straight segment):
    The osculating circle degenerates to a line (infinite radius).
    `OsculatingCircle.radius` is `None`, `center` is `None`.
    `curvature` is 0.0.  The `is_degenerate` flag is True.
* |C′(t)| ≈ 0 (non-regular / singular parameter):
    Same treatment — returns degenerate result with `is_degenerate=True`.

For 2-D curves (control points in ℝ²) the cross products are evaluated by
promoting to ℝ³ (z=0) and projecting back; the returned centre / normal are
still 3-D arrays so callers can treat all cases uniformly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsCurve, curve_derivative

_TANGENT_TOL = 1e-12  # |C'| below this → singular / degenerate
_CURV_TOL = 1e-12     # κ below this → degenerate (infinite radius)


@dataclass
class OsculatingCircle:
    """Result of osculating_circle().

    Attributes
    ----------
    t : float
        The curve parameter at which the circle was computed.
    point : np.ndarray
        C(t) — point on the curve.
    tangent : np.ndarray
        Unit tangent T(t) = C′/|C′|.  Also the normal of the osculating plane.
    curvature : float
        Signed curvature κ(t) ≥ 0.
    radius : float | None
        Osculating radius 1/κ.  None when curvature == 0 (degenerate).
    center : np.ndarray | None
        Centre of curvature.  None when degenerate.
    normal_plane_normal : np.ndarray
        Unit normal to the osculating plane (== tangent for plane curves).
    is_degenerate : bool
        True when κ = 0 (straight segment / inflection) or the curve is
        singular at *t*.
    """

    t: float
    point: np.ndarray
    tangent: np.ndarray
    curvature: float
    radius: Optional[float]
    center: Optional[np.ndarray]
    normal_plane_normal: np.ndarray
    is_degenerate: bool = field(default=False)


def _to_3d(v: np.ndarray) -> np.ndarray:
    """Promote a 2-D or 3-D vector to 3-D by zero-padding."""
    v = np.asarray(v, dtype=float).ravel()
    if v.shape[0] == 2:
        return np.array([v[0], v[1], 0.0])
    return v[:3].copy()


def osculating_circle(curve: NurbsCurve, t: float) -> OsculatingCircle:
    """Compute the osculating circle of *curve* at parameter *t*.

    Parameters
    ----------
    curve : NurbsCurve
        The NURBS curve (degree ≥ 1, any dimension ≤ 3).
    t : float
        Parameter value in [knots[degree], knots[n+1]].

    Returns
    -------
    OsculatingCircle
        Dataclass with centre, radius, tangent, curvature, normal_plane_normal
        and is_degenerate flag.
    """
    t = float(t)

    # Evaluate position and first two derivatives.
    pt = _to_3d(curve.evaluate(t))
    c1_raw = curve_derivative(curve, t, order=1)
    c2_raw = curve_derivative(curve, t, order=2)

    c1 = _to_3d(c1_raw)
    c2 = _to_3d(c2_raw)

    speed = float(np.linalg.norm(c1))

    if speed < _TANGENT_TOL:
        # Singular / non-regular parameter.
        tangent = np.array([1.0, 0.0, 0.0])
        return OsculatingCircle(
            t=t, point=pt, tangent=tangent, curvature=0.0,
            radius=None, center=None,
            normal_plane_normal=tangent, is_degenerate=True,
        )

    tangent = c1 / speed

    # Cross product C′ × C″ — its magnitude encodes κ · |C′|³.
    cross = np.cross(c1, c2)
    cross_mag = float(np.linalg.norm(cross))

    # Curvature κ = |C′ × C″| / |C′|³.
    kappa = cross_mag / (speed ** 3)

    if kappa < _CURV_TOL:
        # Inflection point or straight line — degenerate osculating circle.
        return OsculatingCircle(
            t=t, point=pt, tangent=tangent, curvature=0.0,
            radius=None, center=None,
            normal_plane_normal=tangent, is_degenerate=True,
        )

    # Principal normal via (C′ × C″) × C′ (do Carmo §1.5, canonical form).
    # This is well-defined when cross_mag > 0 (which we checked above).
    principal_dir = np.cross(cross, c1)
    pd_mag = float(np.linalg.norm(principal_dir))
    if pd_mag < _TANGENT_TOL:
        # Numerically degenerate (shouldn't happen if cross_mag > 0 and speed > 0).
        return OsculatingCircle(
            t=t, point=pt, tangent=tangent, curvature=0.0,
            radius=None, center=None,
            normal_plane_normal=tangent, is_degenerate=True,
        )

    principal_normal = principal_dir / pd_mag
    radius_val = 1.0 / kappa
    center = pt + radius_val * principal_normal

    # Normal-plane normal: for 3-D space curves the osculating plane normal
    # is the binormal direction (cross / |cross|).
    osc_plane_normal = cross / cross_mag

    return OsculatingCircle(
        t=t,
        point=pt,
        tangent=tangent,
        curvature=float(kappa),
        radius=radius_val,
        center=center,
        normal_plane_normal=osc_plane_normal,
        is_degenerate=False,
    )


def osculating_circles_along(
    curve: NurbsCurve,
    samples: int = 20,
) -> List[OsculatingCircle]:
    """Sample the osculating circle at *samples* uniformly-spaced parameters.

    Parameters are distributed uniformly in [t_min, t_max] where
    t_min = knots[degree] and t_max = knots[n+1] (the clamped domain).

    Parameters
    ----------
    curve : NurbsCurve
    samples : int
        Number of sample points (>= 2).

    Returns
    -------
    list[OsculatingCircle]
    """
    if samples < 2:
        raise ValueError("samples must be >= 2")
    degree = curve.degree
    n = curve.num_control_points - 1
    t_min = float(curve.knots[degree])
    t_max = float(curve.knots[n + 1])
    ts = np.linspace(t_min, t_max, samples)
    return [osculating_circle(curve, float(t)) for t in ts]


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

    _nurbs_osculating_circle_spec = ToolSpec(
        name="nurbs_osculating_circle",
        description=(
            "Compute the osculating circle of a NURBS curve at one or more "
            "parameter values (do Carmo §1.5).\n"
            "\n"
            "The osculating circle is the unique circle that:\n"
            "  * is tangent to the curve at t (same tangent line);\n"
            "  * matches the curve's curvature at t.\n"
            "\n"
            "Returns per sample:\n"
            "  t             : parameter\n"
            "  point         : [x,y,z] on the curve\n"
            "  tangent       : unit tangent [x,y,z]\n"
            "  curvature     : κ(t) ≥ 0\n"
            "  radius        : 1/κ, or null when κ=0 (straight / inflection)\n"
            "  center        : [x,y,z] centre of curvature, or null\n"
            "  normal_plane_normal : unit normal of the osculating plane\n"
            "  is_degenerate : true when κ=0 or the curve is singular at t\n"
            "\n"
            "Inputs: NURBS curve described by degree + control_points + knots "
            "(+ optional weights for rational curves).  If `samples` is given "
            "instead of `t_values`, the curve is uniformly sampled.\n"
            "\n"
            "Never raises — returns {ok:false, reason} for invalid inputs."
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
                    "description": "List of control points [[x,y,z], ...] or [[x,y], ...].",
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
                "t_values": {
                    "type": "array",
                    "description": "Parameter values at which to evaluate (overrides `samples`).",
                    "items": {"type": "number"},
                },
                "samples": {
                    "type": "integer",
                    "description": "Number of uniform samples when t_values not given (default 20).",
                },
            },
            "required": ["degree", "control_points", "knots"],
        },
    )

    @register(_nurbs_osculating_circle_spec)
    def _tool_nurbs_osculating_circle(params: dict, ctx: "ProjectCtx"):  # type: ignore[type-arg]
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

            if "t_values" in params and params["t_values"] is not None:
                ts = [float(v) for v in params["t_values"]]
                results = [osculating_circle(curve, t) for t in ts]
            else:
                n_samples = int(params.get("samples") or 20)
                results = osculating_circles_along(curve, n_samples)

            out = []
            for r in results:
                out.append({
                    "t": r.t,
                    "point": r.point.tolist(),
                    "tangent": r.tangent.tolist(),
                    "curvature": r.curvature,
                    "radius": r.radius,
                    "center": r.center.tolist() if r.center is not None else None,
                    "normal_plane_normal": r.normal_plane_normal.tolist(),
                    "is_degenerate": r.is_degenerate,
                })
            return ok_payload({"samples": out, "count": len(out)})
        except Exception as exc:  # noqa: BLE001
            return err_payload(str(exc))
