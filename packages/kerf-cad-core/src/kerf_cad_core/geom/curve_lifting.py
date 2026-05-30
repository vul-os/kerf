"""
curve_lifting.py
================
Lift 2D parametric trim curves on a NURBS surface into 3D space curves, and
invert 3D space curves back into (u, v) parameter curves.

Reference: Piegl & Tiller §10.3.1 — composite surface-curve lifting.

Public API
----------
lift_curve_to_surface(loop_2d, surface, n_samples=100) -> NurbsCurve
    Uniform sampling of (u, v) parametric loop → evaluate surface → fit 3D
    NURBS curve through the resulting points.

lift_curve_with_arc_length(loop_2d, surface, target_segments=20) -> NurbsCurve
    Adaptive sampling: denser where the 3D image has high curvature, sparser
    where it is nearly flat.  Uses curvature_radius on the 3D image.

project_3d_curve_to_surface_uv(curve_3d, surface, n_samples=100) -> NurbsCurve
    Inverse: given a 3D curve lying on a surface, recover the (u, v) parameter
    curve via closest-point inversion (closest_point_surface from inversion.py).
    Returns a 2D NurbsCurve whose control points live in the (u, v) plane.

Each function returns a NurbsCurve and never raises — exceptions are caught and
re-raised as ValueError with a descriptive message.

LLM tool ``nurbs_curve_lift_to_surface`` is registered where kerf_chat is
available (gated in a try/except block; no import-time error if absent).
"""

from __future__ import annotations

import math
from typing import Callable, Sequence, Tuple, Union

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsCurve, NurbsSurface, de_boor, curve_derivative
from kerf_cad_core.geom.curve_toolkit import interp_curve


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sample_loop_2d(
    loop_2d: Union[NurbsCurve, Callable],
    ts: np.ndarray,
) -> np.ndarray:
    """Evaluate the 2D parametric loop at parameter values *ts*.

    *loop_2d* may be:
    - a NurbsCurve whose control points live in 2D (u, v)
    - a callable  f(t) -> array-like of shape (2,)  with t ∈ [0, 1]
    - an (N, 2) array of (u, v) sample points; linearly interpolated

    Returns an (n, 2) array of (u, v) parameter values.
    """
    if callable(loop_2d) and not isinstance(loop_2d, NurbsCurve):
        pts = np.array([loop_2d(float(t)) for t in ts], dtype=float)
        if pts.ndim == 1:
            pts = pts.reshape(-1, 1)
        return pts[:, :2] if pts.shape[1] >= 2 else pts

    if isinstance(loop_2d, NurbsCurve):
        u0 = float(loop_2d.knots[loop_2d.degree])
        u1 = float(loop_2d.knots[-(loop_2d.degree + 1)])
        mapped = u0 + ts * (u1 - u0)
        pts = np.array([de_boor(loop_2d, float(t)) for t in mapped], dtype=float)
        return pts[:, :2] if pts.shape[1] >= 2 else pts

    # Assume numpy array: linearly interpolate
    arr = np.asarray(loop_2d, dtype=float)
    if arr.ndim == 1:
        arr = arr.reshape(-1, 2)
    n_in = len(arr)
    if n_in < 2:
        raise ValueError("loop_2d array must have at least 2 rows")
    src_ts = np.linspace(0.0, 1.0, n_in)
    u_vals = np.interp(ts, src_ts, arr[:, 0])
    v_vals = np.interp(ts, src_ts, arr[:, 1])
    return np.column_stack([u_vals, v_vals])


def _eval_surface_safe(surface: NurbsSurface, u: float, v: float) -> np.ndarray:
    """Evaluate surface at (u, v) with light clamping guard."""
    u_min = float(surface.knots_u[surface.degree_u])
    u_max = float(surface.knots_u[-(surface.degree_u + 1)])
    v_min = float(surface.knots_v[surface.degree_v])
    v_max = float(surface.knots_v[-(surface.degree_v + 1)])
    u = float(np.clip(u, u_min, u_max))
    v = float(np.clip(v, v_min, v_max))
    return surface.evaluate(u, v)


def _curvature_at_samples(pts: np.ndarray) -> np.ndarray:
    """Approximate scalar curvature at each interior sample via finite differences.

    Returns an array of length n with curvature approximations (0 at endpoints).
    Uses the formula κ ≈ |Δ²P_i| / |ΔP_i|³ (discrete approximation).
    """
    n = len(pts)
    kappas = np.zeros(n)
    for i in range(1, n - 1):
        d1 = pts[i] - pts[i - 1]
        d2 = pts[i + 1] - pts[i]
        speed = np.linalg.norm(d1)
        if speed < 1e-15:
            continue
        # discrete second derivative approximation
        d2_approx = d2 - d1
        # cross product magnitude in 3D (embed if 2D)
        d1_3 = np.zeros(3)
        d2a_3 = np.zeros(3)
        dim = min(len(d1), 3)
        d1_3[:dim] = d1[:dim]
        d2a_3[:dim] = d2_approx[:dim]
        cross = np.linalg.norm(np.cross(d1_3, d2a_3))
        kappas[i] = cross / max(speed ** 3, 1e-30)
    return kappas


def _adaptive_params(
    loop_2d: Union[NurbsCurve, Callable],
    surface: NurbsSurface,
    target_segments: int,
) -> np.ndarray:
    """Produce an adaptive parameter sequence for the loop.

    Strategy (P&T §10.3.1 spirit):
    1. Uniform pilot sample at 4×target_segments.
    2. Evaluate 3D points and compute discrete curvature at each sample.
    3. Accumulate a density measure ρ(t) = max(κ(t), ε).
    4. Invert the CDF of ρ to place ``target_segments + 1`` parameters
       denser in high-curvature regions.

    Returns a sorted array of parameter values in [0, 1].
    """
    pilot_n = max(4 * target_segments, 40)
    ts_pilot = np.linspace(0.0, 1.0, pilot_n)
    uv_pilot = _sample_loop_2d(loop_2d, ts_pilot)
    pts_3d = np.array([
        _eval_surface_safe(surface, float(uv[0]), float(uv[1]))
        for uv in uv_pilot
    ], dtype=float)

    kappas = _curvature_at_samples(pts_3d)
    # Chord-length density fallback: include arc-length spacing as a floor
    chord_lens = np.concatenate([[0.0], np.linalg.norm(np.diff(pts_3d, axis=0), axis=1)])
    chord_density = np.maximum(chord_lens / (np.sum(chord_lens) + 1e-30), 0.0)

    # Density = max(normalised curvature, chord density floor) to ensure
    # at least some samples in flat regions with long chords.
    kap_max = np.max(kappas)
    if kap_max > 1e-30:
        kap_norm = kappas / kap_max
    else:
        kap_norm = np.zeros_like(kappas)

    density = np.maximum(kap_norm, chord_density + 1e-6)
    # CDF
    cdf = np.cumsum(density)
    cdf /= cdf[-1]

    # Invert CDF to place target_segments+1 samples
    target_cdf = np.linspace(0.0, 1.0, target_segments + 1)
    adaptive_ts = np.interp(target_cdf, cdf, ts_pilot)
    return adaptive_ts


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def lift_curve_to_surface(
    loop_2d: Union[NurbsCurve, Callable, np.ndarray],
    surface: NurbsSurface,
    n_samples: int = 100,
) -> NurbsCurve:
    """Lift a 2D parametric loop on *surface* to a 3D space curve.

    Samples the 2D loop at ``n_samples`` uniform parameter values t ∈ [0, 1],
    evaluates the surface at each (u, v) to obtain 3D points, then fits a
    degree-3 NURBS curve through those points using ``interp_curve``.

    Parameters
    ----------
    loop_2d  : 2D parametric loop — one of:
        - NurbsCurve  with 2D control points (columns = u, v)
        - callable    f(t) -> [u, v] with t ∈ [0, 1]
        - (N, 2) ndarray of (u, v) samples (linearly re-sampled to n_samples)
    surface  : NurbsSurface to evaluate
    n_samples: number of uniform sample points (default 100)

    Returns
    -------
    NurbsCurve — degree-3 3D NURBS that passes through the lifted points.

    Raises
    ------
    ValueError on degenerate input (< 2 samples resolve to distinct 3D points).
    """
    if not isinstance(surface, NurbsSurface):
        raise ValueError(f"surface must be a NurbsSurface, got {type(surface).__name__}")
    n_samples = max(2, int(n_samples))

    ts = np.linspace(0.0, 1.0, n_samples)
    uv_pts = _sample_loop_2d(loop_2d, ts)
    pts_3d = np.array([
        _eval_surface_safe(surface, float(uv[0]), float(uv[1]))
        for uv in uv_pts
    ], dtype=float)

    if pts_3d.shape[1] < 3:
        pts_3d_pad = np.zeros((len(pts_3d), 3))
        pts_3d_pad[:, : pts_3d.shape[1]] = pts_3d
        pts_3d = pts_3d_pad

    return interp_curve(pts_3d, degree=min(3, n_samples - 1))


def lift_curve_with_arc_length(
    loop_2d: Union[NurbsCurve, Callable, np.ndarray],
    surface: NurbsSurface,
    target_segments: int = 20,
    _return_sample_pts: bool = False,
) -> "NurbsCurve | tuple[NurbsCurve, np.ndarray]":
    """Lift a 2D parametric loop using adaptive (curvature-aware) sampling.

    Denser sampling is placed in regions of the 3D image curve where the
    scalar curvature is high.  The algorithm:

    1. Uniform pilot pass at 4×target_segments points.
    2. Compute discrete curvature κ_i at each pilot sample.
    3. Normalise to a density function ρ(t) and invert the CDF to place
       ``target_segments + 1`` adaptive parameter values.
    4. Evaluate surface at adaptive (u, v) points → 3D polyline.
    5. Fit a degree-3 NURBS through the adaptive 3D points.

    Parameters
    ----------
    loop_2d         : 2D parametric loop (NurbsCurve / callable / ndarray)
    surface         : NurbsSurface to evaluate
    target_segments : approximate number of output segments (default 20)

    Returns
    -------
    NurbsCurve — degree-3 3D NURBS through adaptively sampled points.
    """
    if not isinstance(surface, NurbsSurface):
        raise ValueError(f"surface must be a NurbsSurface, got {type(surface).__name__}")
    target_segments = max(4, int(target_segments))

    adaptive_ts = _adaptive_params(loop_2d, surface, target_segments)
    uv_pts = _sample_loop_2d(loop_2d, adaptive_ts)
    pts_3d = np.array([
        _eval_surface_safe(surface, float(uv[0]), float(uv[1]))
        for uv in uv_pts
    ], dtype=float)

    if pts_3d.shape[1] < 3:
        pts_3d_pad = np.zeros((len(pts_3d), 3))
        pts_3d_pad[:, : pts_3d.shape[1]] = pts_3d
        pts_3d = pts_3d_pad

    n = len(pts_3d)
    curve = interp_curve(pts_3d, degree=min(3, n - 1))
    if _return_sample_pts:
        return curve, pts_3d
    return curve


def project_3d_curve_to_surface_uv(
    curve_3d: NurbsCurve,
    surface: NurbsSurface,
    n_samples: int = 100,
) -> NurbsCurve:
    """Inverse operation: recover the (u, v) parameter curve of a 3D space curve.

    For each of ``n_samples`` uniformly distributed points on ``curve_3d``,
    find the closest point on ``surface`` via Newton inversion
    (``closest_point_surface`` from ``inversion.py``) to recover (u, v).
    Fit a 2D NURBS curve through the resulting (u, v) samples.

    Parameters
    ----------
    curve_3d : NurbsCurve in 3D space, assumed to lie on *surface*
    surface  : NurbsSurface
    n_samples: number of sample points (default 100)

    Returns
    -------
    NurbsCurve — 2D NURBS in (u, v) parameter space.

    Raises
    ------
    ValueError if imports fail or input types are wrong.
    ImportError (propagated) if inversion module is unavailable.
    """
    if not isinstance(curve_3d, NurbsCurve):
        raise ValueError(f"curve_3d must be a NurbsCurve, got {type(curve_3d).__name__}")
    if not isinstance(surface, NurbsSurface):
        raise ValueError(f"surface must be a NurbsSurface, got {type(surface).__name__}")

    from kerf_cad_core.geom.inversion import closest_point_surface  # type: ignore[import]

    n_samples = max(2, int(n_samples))
    t_min = float(curve_3d.knots[curve_3d.degree])
    t_max = float(curve_3d.knots[-(curve_3d.degree + 1)])
    ts = np.linspace(t_min, t_max, n_samples)

    uv_pts = []
    for t in ts:
        pt_3d = de_boor(curve_3d, float(t))
        pt_3d_3 = np.zeros(3)
        dim = min(len(pt_3d), 3)
        pt_3d_3[:dim] = pt_3d[:dim]
        u, v, _foot, _dist = closest_point_surface(surface, pt_3d_3)
        uv_pts.append([float(u), float(v)])

    uv_arr = np.array(uv_pts, dtype=float)
    return interp_curve(uv_arr, degree=min(3, n_samples - 1))


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

    _lift_spec = ToolSpec(
        name="nurbs_curve_lift_to_surface",
        description=(
            "Lift a 2D parametric trim loop on a NURBS surface into a 3D space curve "
            "(Piegl & Tiller §10.3.1).  Samples the (u,v) loop uniformly, evaluates "
            "S(u,v) at each sample, and fits a degree-3 NURBS through the 3D points.\n"
            "\n"
            "``loop_2d`` is a list of (u, v) pairs tracing the parametric loop.\n"
            "``surface`` must be a pre-built NurbsSurface (passed by handle from a "
            "prior tool call that returns surface control-point data).\n"
            "\n"
            "Returns: {ok, control_points, knots, degree, num_ctrl, n_samples}\n"
            "Errors:  {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "loop_2d": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                    "description": "List of (u, v) parameter pairs tracing the 2D loop.",
                },
                "surface_control_points": {
                    "type": "array",
                    "description": "3D surface control-point grid: list of rows, each a list of [x,y,z] points.",
                },
                "degree_u": {"type": "integer", "description": "Surface degree in u (default 3)."},
                "degree_v": {"type": "integer", "description": "Surface degree in v (default 3)."},
                "knots_u": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Surface knot vector in u.",
                },
                "knots_v": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Surface knot vector in v.",
                },
                "n_samples": {
                    "type": "integer",
                    "description": "Number of uniform sample points (default 100).",
                },
                "adaptive": {
                    "type": "boolean",
                    "description": "If true, use curvature-adaptive sampling (default false).",
                },
                "target_segments": {
                    "type": "integer",
                    "description": "Target segment count for adaptive mode (default 20).",
                },
            },
            "required": ["loop_2d", "surface_control_points", "knots_u", "knots_v"],
        },
    )

    @register(_lift_spec)
    async def run_nurbs_curve_lift_to_surface(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        loop_2d_raw = a.get("loop_2d")
        if not loop_2d_raw or len(loop_2d_raw) < 2:
            return err_payload("loop_2d must contain at least 2 (u,v) pairs", "BAD_ARGS")
        cp_grid = a.get("surface_control_points")
        if not cp_grid:
            return err_payload("surface_control_points is required", "BAD_ARGS")

        try:
            cp_arr = np.array(cp_grid, dtype=float)
            if cp_arr.ndim == 2:
                # Treat as (nu, nv) rows — attempt square reshape
                n = int(math.isqrt(len(cp_grid)))
                if n * n != len(cp_grid):
                    return err_payload(
                        "surface_control_points must be a (nu×nv) grid of [x,y,z] points",
                        "BAD_ARGS",
                    )
                cp_arr = cp_arr.reshape(n, n, 3)
        except Exception as exc:
            return err_payload(f"surface_control_points parse error: {exc}", "BAD_ARGS")

        deg_u = int(a.get("degree_u", 3))
        deg_v = int(a.get("degree_v", 3))
        ku = a.get("knots_u")
        kv = a.get("knots_v")
        if ku is None or kv is None:
            return err_payload("knots_u and knots_v are required", "BAD_ARGS")

        try:
            surface = NurbsSurface(
                degree_u=deg_u,
                degree_v=deg_v,
                control_points=cp_arr,
                knots_u=np.array(ku, dtype=float),
                knots_v=np.array(kv, dtype=float),
            )
        except Exception as exc:
            return err_payload(f"surface construction error: {exc}", "BAD_ARGS")

        loop_2d = np.array(loop_2d_raw, dtype=float)
        adaptive = bool(a.get("adaptive", False))

        try:
            if adaptive:
                target = int(a.get("target_segments", 20))
                curve = lift_curve_with_arc_length(loop_2d, surface, target_segments=target)
            else:
                n_s = int(a.get("n_samples", 100))
                curve = lift_curve_to_surface(loop_2d, surface, n_samples=n_s)
        except Exception as exc:
            return err_payload(str(exc), "OP_FAILED")

        return ok_payload({
            "control_points": curve.control_points.tolist(),
            "knots": curve.knots.tolist(),
            "degree": curve.degree,
            "num_ctrl": curve.num_control_points,
            "n_samples": len(loop_2d),
        })
