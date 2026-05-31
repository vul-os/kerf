"""BREP-EDGE-CHAMFER-VARIABLE — variable-width chamfer strip along a 2D edge curve.

Generates a chamfer strip for ergonomic edge treatments (handle bevels with grip
variations) where the chamfer width interpolates linearly between two endpoint
values along the edge.

Reference
---------
  Piegl, L. & Tiller, W. (1997). The NURBS Book, 2nd ed. Springer.
      §10.5 — Variable offsets: computing offset curves at varying distances
      along a base curve.

  Mortenson, M.E. (1985). Geometric Modeling. Wiley.
      §9.3 — Edge blends: continuous blending of edge geometry with
      variable-width offset construction.

  Farin, G. (2002). Curves and Surfaces for CAGD, 5th ed. Morgan Kaufmann.
      §13.2 — Offset curves: signed perpendicular offset at sampled parameters.

Algorithm
---------
Given a 2D polyline ``edge_curve_2d`` (list of (x, y) points) and endpoint
widths ``width_start_mm``, ``width_end_mm``:

1. Arc-length-parameterise the polyline to get t ∈ [0, 1] at each sample.
2. At each sample ``t_i``, compute the tangent direction by finite differences.
3. Compute the perpendicular (normal) direction (90° CCW rotation of tangent).
4. Compute the chamfer half-width at ``t_i``:
   ``w(t) = width_start_mm + t_i * (width_end_mm - width_start_mm)``
   Both sides are offset by ``w(t)/2`` from the edge centreline.
5. Return two offset polylines (inner = edge + w/2 * normal,
   outer = edge − w/2 * normal) as the chamfer strip.

HONEST CAVEATS
--------------
* Input is a **2D edge curve** (list of (x, y) points); 3D space-curve chamfer
  that operates on a true B-rep solid edge is not yet supported — that requires
  the full B-rep topology surgery from ``chamfer.py`` generalised to curved
  edges (P2/P3 scope).
* "Inner" and "outer" are defined relative to the CCW normal; the caller must
  orient them correctly for their coordinate system.
* Very short segments (< 1e-12) are skipped when computing tangents; the
  algorithm falls back to the previous valid tangent.
* The strip is a sampled polyline approximation, not an exact NURBS offset
  curve.  For curvature-continuous offsets use Piegl-Tiller §10.5 NURBS method.

Public API
----------
ChamferVariableSpec
    edge_curve_2d    : list[(x, y)]    — input edge polyline (≥ 2 points)
    width_start_mm   : float           — chamfer half-width at t=0 (mm)
    width_end_mm     : float           — chamfer half-width at t=1 (mm)
    num_samples      : int             — number of evaluation points (default 50)

ChamferVariableResult
    chamfer_strip_points  : list[(x, y, side)] where side=0 is inner, side=1 outer
                           Actually: two interleaved sub-lists are delivered as a
                           flat list of (x, y, z) with z=0.0 for 2D (the two lines
                           concatenated: first all inner points then all outer).
    min_chamfer_width_mm  : float
    max_chamfer_width_mm  : float
    average_width_mm      : float
    honest_caveat         : str

generate_variable_chamfer(spec) -> ChamferVariableResult
    Main entry point.

LLM tool: brep_generate_variable_chamfer (registered when kerf_chat is available).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Tuple

import numpy as np

__all__ = [
    "ChamferVariableSpec",
    "ChamferVariableResult",
    "generate_variable_chamfer",
]

_HONEST_CAVEAT = (
    "HONEST: input is a 2-D edge-curve polyline; 3-D space-curve variable chamfer "
    "that modifies a B-rep solid topology is not yet supported (requires generalising "
    "chamfer.py topology surgery to curved edges — P2/P3 scope, ref. Piegl-Tiller "
    "§10.5). Strip points are a sampled polyline approximation, not an exact NURBS "
    "offset curve."
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ChamferVariableSpec:
    """Specification for a variable-width chamfer along a 2D edge curve.

    Attributes
    ----------
    edge_curve_2d : list of (float, float)
        2-D polyline representing the edge (at least 2 points).  Each entry
        is a (x, y) tuple or any 2-element sequence.
    width_start_mm : float
        Total chamfer width (both sides combined) at the start (t=0) of the
        edge, in millimetres.  Must be non-negative.
    width_end_mm : float
        Total chamfer width at the end (t=1) of the edge, in millimetres.
        Must be non-negative.  At least one of width_start_mm / width_end_mm
        must be strictly positive.
    num_samples : int
        Number of uniformly-spaced arc-length samples to evaluate along the
        edge (default 50, minimum 2, maximum 10000).
    """

    edge_curve_2d: List[Tuple[float, float]]
    width_start_mm: float
    width_end_mm: float
    num_samples: int = 50

    def __post_init__(self) -> None:
        pts = list(self.edge_curve_2d)
        if len(pts) < 2:
            raise ValueError(
                "ChamferVariableSpec.edge_curve_2d must have at least 2 points; "
                f"got {len(pts)}"
            )
        if self.width_start_mm < 0.0:
            raise ValueError(
                f"ChamferVariableSpec.width_start_mm must be non-negative; "
                f"got {self.width_start_mm}"
            )
        if self.width_end_mm < 0.0:
            raise ValueError(
                f"ChamferVariableSpec.width_end_mm must be non-negative; "
                f"got {self.width_end_mm}"
            )
        if self.width_start_mm <= 0.0 and self.width_end_mm <= 0.0:
            raise ValueError(
                "ChamferVariableSpec: at least one of width_start_mm / width_end_mm "
                "must be strictly positive"
            )
        if not (2 <= self.num_samples <= 10000):
            raise ValueError(
                f"ChamferVariableSpec.num_samples must be in [2, 10000]; "
                f"got {self.num_samples}"
            )


@dataclass
class ChamferVariableResult:
    """Result of a variable-width chamfer computation.

    Attributes
    ----------
    chamfer_strip_points : list of (float, float, float)
        Flat list of 3-D points (z=0.0 for 2-D input) representing the two
        offset lines.  The first ``num_samples`` entries are the *inner*
        offset line (CCW normal side); the next ``num_samples`` entries are
        the *outer* offset line (CW normal side).
    min_chamfer_width_mm : float
        Minimum chamfer width achieved across the strip (= min(w_start, w_end)
        when linear).
    max_chamfer_width_mm : float
        Maximum chamfer width achieved across the strip (= max(w_start, w_end)
        when linear).
    average_width_mm : float
        Mean chamfer width = (width_start_mm + width_end_mm) / 2.
    honest_caveat : str
        Plain-English statement of what this function does NOT do.
    """

    chamfer_strip_points: List[Tuple[float, float, float]]
    min_chamfer_width_mm: float
    max_chamfer_width_mm: float
    average_width_mm: float
    honest_caveat: str


# ---------------------------------------------------------------------------
# Core implementation
# ---------------------------------------------------------------------------


def _arc_length_param(pts: np.ndarray) -> np.ndarray:
    """Return arc-length parameter t ∈ [0, 1] at each point in *pts*.

    Parameters
    ----------
    pts : (n, 2) float array
        Polyline vertices.

    Returns
    -------
    t : (n,) float array
        Arc-length parameters, t[0]=0.0, t[-1]=1.0.
    """
    n = len(pts)
    diffs = np.linalg.norm(np.diff(pts, axis=0), axis=1)  # (n-1,)
    cumlen = np.concatenate([[0.0], np.cumsum(diffs)])
    total = cumlen[-1]
    if total < 1e-12:
        # Degenerate — all points coincide; return uniform param
        return np.linspace(0.0, 1.0, n)
    return cumlen / total


def _tangent_at(pts: np.ndarray, idx: int, t_arr: np.ndarray) -> np.ndarray:
    """Compute unit tangent at index *idx* by finite differences.

    Falls back to the last valid tangent for degenerate segments.
    """
    n = len(pts)
    if idx == 0:
        seg = pts[1] - pts[0]
    elif idx == n - 1:
        seg = pts[-1] - pts[-2]
    else:
        seg = pts[idx + 1] - pts[idx - 1]
    nrm = float(np.linalg.norm(seg))
    if nrm < 1e-12:
        # Try forward, then backward
        for di in [1, -1]:
            j = idx + di
            if 0 <= j < n:
                seg2 = pts[j] - pts[idx]
                nrm2 = float(np.linalg.norm(seg2))
                if nrm2 >= 1e-12:
                    return seg2 / nrm2
        # Fully degenerate — return X axis
        return np.array([1.0, 0.0])
    return seg / nrm


def _normal_ccw(tangent: np.ndarray) -> np.ndarray:
    """Return the CCW-perpendicular unit normal to a 2D unit tangent."""
    return np.array([-tangent[1], tangent[0]])


def _resample_polyline(
    pts_orig: np.ndarray,
    num_samples: int,
) -> Tuple[np.ndarray, np.ndarray]:
    """Resample *pts_orig* uniformly by arc length to *num_samples* points.

    Returns
    -------
    pts_resampled : (num_samples, 2) float array
    t_resampled   : (num_samples,) float array — arc-length params in [0,1]
    """
    t_orig = _arc_length_param(pts_orig)
    t_new = np.linspace(0.0, 1.0, num_samples)
    pts_x = np.interp(t_new, t_orig, pts_orig[:, 0])
    pts_y = np.interp(t_new, t_orig, pts_orig[:, 1])
    pts_resampled = np.column_stack([pts_x, pts_y])
    return pts_resampled, t_new


def generate_variable_chamfer(spec: ChamferVariableSpec) -> ChamferVariableResult:
    """Generate a variable-width chamfer strip along a 2D edge curve.

    At each sample point ``t_i ∈ [0, 1]`` along the edge:

    - chamfer width  ``w(t) = width_start_mm + t * (width_end_mm - width_start_mm)``
    - inner point    ``P_inner(t) = P(t) + (w(t)/2) * n_ccw(t)``
    - outer point    ``P_outer(t) = P(t) - (w(t)/2) * n_ccw(t)``

    where ``n_ccw(t)`` is the CCW-perpendicular unit normal to the edge tangent.

    Parameters
    ----------
    spec : ChamferVariableSpec
        Validated specification (edge polyline, widths, sample count).

    Returns
    -------
    ChamferVariableResult
        Strip points (inner then outer), width statistics, honest caveat.
    """
    # Convert to numpy
    pts_orig = np.array([(float(p[0]), float(p[1])) for p in spec.edge_curve_2d],
                        dtype=float)

    # Resample to num_samples uniform arc-length stations
    pts, t_arr = _resample_polyline(pts_orig, spec.num_samples)

    w_start = float(spec.width_start_mm)
    w_end = float(spec.width_end_mm)

    inner_pts: List[Tuple[float, float, float]] = []
    outer_pts: List[Tuple[float, float, float]] = []

    widths: List[float] = []

    for i in range(spec.num_samples):
        t_i = float(t_arr[i])
        # Linear width ramp: w(t) = w_start + t*(w_end - w_start)
        w_i = w_start + t_i * (w_end - w_start)
        widths.append(w_i)

        # Tangent + normal
        tang = _tangent_at(pts, i, t_arr)
        norm = _normal_ccw(tang)

        half_w = w_i * 0.5
        p = pts[i]
        p_inner = p + half_w * norm
        p_outer = p - half_w * norm

        inner_pts.append((float(p_inner[0]), float(p_inner[1]), 0.0))
        outer_pts.append((float(p_outer[0]), float(p_outer[1]), 0.0))

    all_widths = widths
    min_w = float(min(all_widths))
    max_w = float(max(all_widths))
    avg_w = float(np.mean(all_widths))

    return ChamferVariableResult(
        chamfer_strip_points=inner_pts + outer_pts,
        min_chamfer_width_mm=min_w,
        max_chamfer_width_mm=max_w,
        average_width_mm=avg_w,
        honest_caveat=_HONEST_CAVEAT,
    )


# ---------------------------------------------------------------------------
# LLM tool registration (gated — same pattern as edge_blend.py)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    _brep_generate_variable_chamfer_spec = ToolSpec(
        name="brep_generate_variable_chamfer",
        description=(
            "Generate a variable-width chamfer strip along a 2D edge curve.\n"
            "\n"
            "The chamfer width ramps linearly from width_start_mm (at t=0) to\n"
            "width_end_mm (at t=1) along the edge arc-length.  Useful for ergonomic\n"
            "edge treatments — e.g. a handle bevel that is narrow at the tip and wider\n"
            "at the grip.\n"
            "\n"
            "Reference: Piegl & Tiller §10.5 (Variable offsets); Mortenson §9.3\n"
            "(Edge blends).\n"
            "\n"
            "HONEST CAVEAT: input is a 2D polyline; 3D B-rep solid chamfer not yet\n"
            "supported.\n"
            "\n"
            "Parameters:\n"
            "  edge_curve_2d  : [[x, y], ...]  — 2D polyline, ≥ 2 points\n"
            "  width_start_mm : float           — chamfer width at t=0 (mm, > 0)\n"
            "  width_end_mm   : float           — chamfer width at t=1 (mm, ≥ 0)\n"
            "  num_samples    : int             — sample count (default 50)\n"
            "\n"
            "Returns:\n"
            "  ok                    : bool\n"
            "  inner_strip           : [[x, y, 0.0], ...]  — inner offset line\n"
            "  outer_strip           : [[x, y, 0.0], ...]  — outer offset line\n"
            "  min_chamfer_width_mm  : float\n"
            "  max_chamfer_width_mm  : float\n"
            "  average_width_mm      : float\n"
            "  honest_caveat         : str\n"
            "\n"
            "Errors: {ok: false, reason} — never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "edge_curve_2d": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 2,
                    },
                    "minItems": 2,
                    "description": "2D polyline as [[x, y], ...]",
                },
                "width_start_mm": {
                    "type": "number",
                    "description": "Chamfer width at t=0 (start of edge), mm",
                },
                "width_end_mm": {
                    "type": "number",
                    "description": "Chamfer width at t=1 (end of edge), mm",
                },
                "num_samples": {
                    "type": "integer",
                    "description": "Number of arc-length samples (default 50)",
                },
            },
            "required": ["edge_curve_2d", "width_start_mm", "width_end_mm"],
        },
    )

    @register(_brep_generate_variable_chamfer_spec)
    async def run_brep_generate_variable_chamfer(
        ctx: "ProjectCtx", args: bytes
    ) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        raw_edge = a.get("edge_curve_2d", [])
        if len(raw_edge) < 2:
            return err_payload("edge_curve_2d must have at least 2 points", "BAD_ARGS")
        try:
            edge_pts = [(float(p[0]), float(p[1])) for p in raw_edge]
        except Exception as exc:
            return err_payload(f"invalid edge_curve_2d: {exc}", "BAD_ARGS")

        try:
            w_start = float(a.get("width_start_mm", 0.0))
            w_end = float(a.get("width_end_mm", 0.0))
        except Exception as exc:
            return err_payload(f"invalid width values: {exc}", "BAD_ARGS")

        num_samples = int(a.get("num_samples", 50))

        try:
            spec = ChamferVariableSpec(
                edge_curve_2d=edge_pts,
                width_start_mm=w_start,
                width_end_mm=w_end,
                num_samples=num_samples,
            )
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")

        try:
            result = generate_variable_chamfer(spec)
        except Exception as exc:
            return err_payload(f"internal error: {exc}", "OP_FAILED")

        n = spec.num_samples
        inner = result.chamfer_strip_points[:n]
        outer = result.chamfer_strip_points[n:]

        return ok_payload({
            "inner_strip": [[p[0], p[1], p[2]] for p in inner],
            "outer_strip": [[p[0], p[1], p[2]] for p in outer],
            "min_chamfer_width_mm": result.min_chamfer_width_mm,
            "max_chamfer_width_mm": result.max_chamfer_width_mm,
            "average_width_mm": result.average_width_mm,
            "honest_caveat": result.honest_caveat,
        })
