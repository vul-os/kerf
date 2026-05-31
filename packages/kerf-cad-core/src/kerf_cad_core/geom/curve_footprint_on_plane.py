"""
NURBS-CURVE-FOOTPRINT-ON-PLANE
===============================
Project a 3-D NurbsCurve perpendicularly (orthographically) onto an arbitrary
plane, producing a planar 2-D NurbsCurve in plane-local UV coordinates.

Use cases
---------
* Drawing-view projection (shadow on the projection plane).
* CNC engraving toolpath flattening (collapse a 3-D path onto the workplane).
* PV-array layout (project panel edges onto the roof plane).

References
----------
* Piegl & Tiller, "The NURBS Book" 2nd ed., §6.1 — curve transformations.
  The orthographic projection is a linear map on the homogeneous control-point
  matrix; knots and weights are preserved exactly (P&T §6.1, Theorem 6.1).
* Mortenson, "Geometric Modeling" 3rd ed., §4.4 — orthographic projection.
  P' = P - ((P - O) · n̂) n̂   (foot of perpendicular from P to plane).

Algorithm
---------
1.  Normalise the plane normal n̂.
2.  Build an orthonormal frame {u_axis, v_axis, n̂} anchored at `plane_point`.
3.  For each 3-D control point P project onto the plane:
        depth = (P - O) · n̂
        P'    = P - depth * n̂            (3-D foot on plane)
4.  Express P' in plane UV coordinates:
        u_coord = (P' - O) · u_axis
        v_coord = (P' - O) · v_axis
5.  Return a NurbsCurve with the same degree, knot vector, and weights but
    2-D control points in the UV frame.

Degenerate case: if every control-point depth is the same (the curve is
already planar and parallel to the projection direction) the footprint
degenerates to a point-like curve.  The `honest_caveat` field names this.

HONEST LIMITATIONS
------------------
* Orthographic (linear) projection only — no perspective.
* The footprint is a control-point projection; for rational (weighted) NURBS
  curves the Euclidean curve shape is NOT simply a projection of the Euclidean
  curve — only the weighted (homogeneous) CPs map linearly.  For non-rational
  (weights=None or all-one) curves this is exact.  For rational curves the
  result is a correct rational NURBS footprint because the homogeneous image
  of an affine map preserves NURBS rationality (P&T §6.1).
* Degenerate (vertical-line) curves produce a zero-length footprint; callers
  should check `max_orig_depth` and `honest_caveat`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Tuple

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsCurve

# ---------------------------------------------------------------------------
# Tolerance for degenerate-detection
# ---------------------------------------------------------------------------
_DEGEN_TOL: float = 1e-10


# ---------------------------------------------------------------------------
# Public result dataclass
# ---------------------------------------------------------------------------

@dataclass
class FootprintResult:
    """Result of :func:`project_curve_to_plane`.

    Attributes
    ----------
    footprint_curve_2d : NurbsCurve
        The projected curve in plane-local (U, V) coordinates.
        Control points are 2-D ``[u, v]`` arrays.
        Degree, knot vector and weights are identical to the input curve.
    projection_axis : tuple[float, float, float]
        Unit normal of the projection plane (the "shadow direction").
    max_orig_depth : float
        Maximum signed depth of any control point along ``projection_axis``
        measured from ``plane_point``.  Near-zero ⇒ the input was already
        planar; a large value means significant 3-D relief was collapsed.
    honest_caveat : str
        Human-readable honesty note describing any limitations or degenerate
        conditions encountered.
    """

    footprint_curve_2d: NurbsCurve
    projection_axis: Tuple[float, float, float]
    max_orig_depth: float
    honest_caveat: str


# ---------------------------------------------------------------------------
# Core projection function
# ---------------------------------------------------------------------------

def project_curve_to_plane(
    curve: NurbsCurve,
    plane_point,
    plane_normal,
) -> FootprintResult:
    """Project a 3-D NurbsCurve perpendicularly onto a plane.

    Parameters
    ----------
    curve : NurbsCurve
        Input curve.  Control points must be 3-D (shape (n, 3)).
        2-D control points are promoted to 3-D by padding z=0.
    plane_point : array-like, shape (3,)
        A point O on the projection plane (the "origin" of the UV frame).
    plane_normal : array-like, shape (3,)
        Normal to the projection plane.  Need not be unit-length.  The
        projection direction is -n̂ (perpendicular drop onto the plane).

    Returns
    -------
    FootprintResult
        ``footprint_curve_2d`` is a NurbsCurve with 2-D control points in
        plane-local (U, V) coordinates; all other curve parameters
        (degree, knots, weights) are identical to the input.

    Raises
    ------
    ValueError
        If ``plane_normal`` has zero magnitude, or ``curve`` has no control
        points, or control points have unsupported dimensionality (> 3).
    """
    # -----------------------------------------------------------------------
    # Validate and normalise inputs
    # -----------------------------------------------------------------------
    O = np.asarray(plane_point, dtype=float).ravel()
    n_raw = np.asarray(plane_normal, dtype=float).ravel()

    if O.shape[0] < 3:
        O = np.concatenate([O, np.zeros(3 - O.shape[0])])
    O = O[:3]

    if n_raw.shape[0] < 3:
        n_raw = np.concatenate([n_raw, np.zeros(3 - n_raw.shape[0])])
    n_raw = n_raw[:3]

    n_len = float(np.linalg.norm(n_raw))
    if n_len < _DEGEN_TOL:
        raise ValueError(
            f"plane_normal has near-zero magnitude ({n_len:.3e}); "
            "cannot define a projection plane."
        )
    n_hat = n_raw / n_len  # unit normal

    # -----------------------------------------------------------------------
    # Control points: ensure 3-D
    # -----------------------------------------------------------------------
    cp = np.asarray(curve.control_points, dtype=float)
    if cp.ndim == 1:
        cp = cp.reshape(-1, 1)
    n_pts, dim = cp.shape

    if dim < 2:
        raise ValueError(f"Control points must be at least 2-D; got dim={dim}.")
    if dim > 3:
        raise ValueError(
            f"Control points are {dim}-D; project_curve_to_plane supports up to 3-D."
        )
    if dim == 2:
        # Promote 2-D to 3-D by padding z=0.
        cp = np.column_stack([cp, np.zeros(n_pts)])

    # -----------------------------------------------------------------------
    # Build a right-handed orthonormal UV frame on the plane
    # -----------------------------------------------------------------------
    # Choose u_axis: pick any vector not parallel to n_hat.
    if abs(n_hat[0]) < 0.9:
        candidate = np.array([1.0, 0.0, 0.0])
    else:
        candidate = np.array([0.0, 1.0, 0.0])

    u_axis = candidate - np.dot(candidate, n_hat) * n_hat
    u_norm = float(np.linalg.norm(u_axis))
    if u_norm < _DEGEN_TOL:
        # Fallback if candidate was already parallel to n_hat (shouldn't happen
        # with the guard above, but be safe).
        candidate = np.array([0.0, 0.0, 1.0])
        u_axis = candidate - np.dot(candidate, n_hat) * n_hat
        u_norm = float(np.linalg.norm(u_axis))
    u_axis = u_axis / u_norm

    v_axis = np.cross(n_hat, u_axis)
    v_axis = v_axis / float(np.linalg.norm(v_axis))

    # -----------------------------------------------------------------------
    # Project each control point onto the plane, then into UV coords
    # -----------------------------------------------------------------------
    # depth_i = (P_i - O) · n̂   (signed distance along normal)
    # P'_i   = P_i - depth_i * n̂  (3-D foot on plane)
    # u_i    = (P'_i - O) · u_axis
    # v_i    = (P'_i - O) · v_axis
    #
    # Equivalently:
    #   u_i = (P_i - O) · u_axis   (since u_axis ⊥ n̂, depth term vanishes)
    #   v_i = (P_i - O) · v_axis

    shifted = cp - O[np.newaxis, :]          # (n_pts, 3)
    depths = shifted @ n_hat                 # (n_pts,)  signed depths
    u_coords = shifted @ u_axis              # (n_pts,)
    v_coords = shifted @ v_axis              # (n_pts,)

    cp_2d = np.column_stack([u_coords, v_coords])  # (n_pts, 2)

    # -----------------------------------------------------------------------
    # Degenerate-depth check
    # -----------------------------------------------------------------------
    max_depth = float(np.max(np.abs(depths)))
    depth_range = float(np.max(depths) - np.min(depths))

    caveats: list[str] = []

    # Check if curve is perpendicular to the plane (all points project to
    # the same UV location — a degenerate "point" footprint).
    uv_spread = float(np.max(
        np.linalg.norm(cp_2d - cp_2d.mean(axis=0), axis=1)
    ))
    is_point_degen = uv_spread < _DEGEN_TOL

    if is_point_degen:
        caveats.append(
            "DEGENERATE: curve is perpendicular to the plane; "
            "footprint collapses to a single point."
        )
    elif depth_range < _DEGEN_TOL:
        caveats.append(
            "Curve is already co-planar with the projection plane; "
            "footprint is identical to the original (no depth collapsed)."
        )
    else:
        caveats.append(
            "Orthographic (linear) projection only — no perspective. "
            "For rational (weighted) NURBS the footprint is a correct rational "
            "NURBS curve but the Euclidean shape may differ from a naive "
            "point-by-point projection of the evaluated curve."
        )

    honest_caveat = " ".join(caveats)

    # -----------------------------------------------------------------------
    # Build the 2-D output NurbsCurve
    # -----------------------------------------------------------------------
    footprint = NurbsCurve(
        degree=curve.degree,
        control_points=cp_2d,
        knots=curve.knots.copy(),
        weights=curve.weights.copy() if curve.weights is not None else None,
    )

    return FootprintResult(
        footprint_curve_2d=footprint,
        projection_axis=(float(n_hat[0]), float(n_hat[1]), float(n_hat[2])),
        max_orig_depth=max_depth,
        honest_caveat=honest_caveat,
    )


# ---------------------------------------------------------------------------
# Convenience: project back to 3-D (lift UV footprint into world space)
# ---------------------------------------------------------------------------

def lift_footprint_to_3d(
    footprint_2d: NurbsCurve,
    plane_point,
    plane_normal,
    u_axis=None,
    v_axis=None,
) -> NurbsCurve:
    """Lift a 2-D footprint curve back to 3-D world coordinates.

    This is the inverse of :func:`project_curve_to_plane` (when the same
    ``plane_point``, ``plane_normal``, and UV frame are used).

    Primarily useful for generating engraving toolpaths: project the 3-D
    curve onto the plane, optionally modify it in 2-D, then lift it back.

    Parameters
    ----------
    footprint_2d : NurbsCurve
        A NurbsCurve with 2-D control points in plane UV coordinates.
    plane_point : array-like, shape (3,)
        The UV-frame origin used during the original projection.
    plane_normal : array-like, shape (3,)
        Normal to the projection plane.
    u_axis : array-like or None
        The U-axis of the UV frame.  Must match what was used during
        projection.  If None, a default frame is rebuilt from ``plane_normal``
        using the same deterministic rule as :func:`project_curve_to_plane`.
    v_axis : array-like or None
        The V-axis.  Rebuilt deterministically if None.

    Returns
    -------
    NurbsCurve
        3-D curve with control points in world coordinates.
    """
    O = np.asarray(plane_point, dtype=float).ravel()[:3]
    n_raw = np.asarray(plane_normal, dtype=float).ravel()[:3]
    n_hat = n_raw / (np.linalg.norm(n_raw) + 1e-300)

    if u_axis is None:
        if abs(n_hat[0]) < 0.9:
            candidate = np.array([1.0, 0.0, 0.0])
        else:
            candidate = np.array([0.0, 1.0, 0.0])
        u_ax = candidate - np.dot(candidate, n_hat) * n_hat
        u_ax = u_ax / (np.linalg.norm(u_ax) + 1e-300)
    else:
        u_ax = np.asarray(u_axis, dtype=float).ravel()[:3]
        u_ax = u_ax / (np.linalg.norm(u_ax) + 1e-300)

    if v_axis is None:
        v_ax = np.cross(n_hat, u_ax)
        v_ax = v_ax / (np.linalg.norm(v_ax) + 1e-300)
    else:
        v_ax = np.asarray(v_axis, dtype=float).ravel()[:3]
        v_ax = v_ax / (np.linalg.norm(v_ax) + 1e-300)

    cp_2d = np.asarray(footprint_2d.control_points, dtype=float)
    if cp_2d.ndim == 1:
        cp_2d = cp_2d.reshape(-1, 2)
    n_pts = cp_2d.shape[0]

    cp_3d = (
        O[np.newaxis, :]
        + cp_2d[:, 0:1] * u_ax[np.newaxis, :]
        + cp_2d[:, 1:2] * v_ax[np.newaxis, :]
    )

    return NurbsCurve(
        degree=footprint_2d.degree,
        control_points=cp_3d,
        knots=footprint_2d.knots.copy(),
        weights=footprint_2d.weights.copy() if footprint_2d.weights is not None else None,
    )


# ---------------------------------------------------------------------------
# LLM tool registration (gated import — no hard dependency on kerf_chat)
# ---------------------------------------------------------------------------

try:
    import json as _json

    from kerf_chat.tools.registry import ToolSpec, register, ok_payload, err_payload  # type: ignore

    _SPEC = ToolSpec(
        name="nurbs_curve_project_to_plane",
        description=(
            "Project a 3-D NURBS curve perpendicularly onto a plane, producing "
            "a planar 2-D NURBS curve (footprint / shadow) in plane UV coordinates.\n"
            "\n"
            "Algorithm: orthographic (linear) projection — each control point P is "
            "dropped onto the plane along the plane normal:\n"
            "  P' = P − ((P−O)·n̂) n̂   (Mortenson §4.4; Piegl & Tiller §6.1)\n"
            "Knots, degree and weights are preserved exactly.\n"
            "\n"
            "Use cases: drawing-view projection, CNC engraving toolpath flattening, "
            "PV-array layout.\n"
            "\n"
            "HONEST LIMITS: orthographic only (no perspective); for rational NURBS the "
            "footprint control-points are correct homogeneous images, but the Euclidean "
            "evaluated curve does not equal a point-by-point projection.\n"
            "\n"
            "Returns:\n"
            "  ok                  : bool\n"
            "  footprint_cp        : [[u, v], ...]  — 2-D control points in plane UV frame\n"
            "  knots               : [float, ...]   — unchanged knot vector\n"
            "  weights             : [float, ...] | null\n"
            "  degree              : int\n"
            "  projection_axis     : [nx, ny, nz]   — unit normal\n"
            "  max_orig_depth      : float\n"
            "  is_degenerate       : bool           — true if footprint collapses to a point\n"
            "  honest_caveat       : str\n"
            "\n"
            "Errors: {ok: false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "required": ["control_points", "degree", "plane_point", "plane_normal"],
            "properties": {
                "control_points": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                    "description": "3-D control points [[x, y, z], ...] of the input curve.",
                },
                "degree": {
                    "type": "integer",
                    "description": "Polynomial degree of the curve.",
                },
                "knots": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": (
                        "Knot vector.  If omitted, a uniform clamped knot vector is "
                        "generated automatically."
                    ),
                },
                "weights": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Per-CP weights (rational NURBS).  Null / omit for non-rational.",
                },
                "plane_point": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "A point on the projection plane [x, y, z] (UV-frame origin).",
                },
                "plane_normal": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Normal to the projection plane [nx, ny, nz] (need not be unit).",
                },
            },
        },
    )

    def _make_knots(n: int, degree: int) -> np.ndarray:
        """Build a uniform clamped knot vector for n CPs and given degree."""
        inner = max(0, n - degree - 1)
        return np.concatenate([
            np.zeros(degree + 1),
            np.linspace(0.0, 1.0, inner + 2)[1:-1] if inner > 0 else np.array([]),
            np.ones(degree + 1),
        ])

    @register(_SPEC)
    async def _run_nurbs_curve_project_to_plane(ctx, args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON args: {exc}", "BAD_ARGS")

        try:
            cp_raw = a["control_points"]
            degree = int(a["degree"])
            plane_pt = list(a["plane_point"])
            plane_nrm = list(a["plane_normal"])
        except (KeyError, TypeError, ValueError) as exc:
            return err_payload(f"missing or bad required field: {exc}", "BAD_ARGS")

        try:
            cp_arr = np.array(cp_raw, dtype=float)
            if cp_arr.ndim == 1:
                cp_arr = cp_arr.reshape(-1, 1)
            n_pts = cp_arr.shape[0]

            knots_raw = a.get("knots")
            if knots_raw is not None:
                knots = np.array(knots_raw, dtype=float)
            else:
                knots = _make_knots(n_pts, degree)

            weights_raw = a.get("weights")
            weights = np.array(weights_raw, dtype=float) if weights_raw is not None else None

            curve = NurbsCurve(
                degree=degree,
                control_points=cp_arr,
                knots=knots,
                weights=weights,
            )
        except Exception as exc:
            return err_payload(f"could not build NurbsCurve: {exc}", "BAD_ARGS")

        try:
            result = project_curve_to_plane(curve, plane_pt, plane_nrm)
        except Exception as exc:
            return err_payload(f"projection failed: {exc}", "GEOM_ERROR")

        cp_2d = result.footprint_curve_2d.control_points
        uv_spread = float(np.max(
            np.linalg.norm(cp_2d - cp_2d.mean(axis=0), axis=1)
        )) if len(cp_2d) > 0 else 0.0

        return ok_payload({
            "ok": True,
            "footprint_cp": cp_2d.tolist(),
            "knots": result.footprint_curve_2d.knots.tolist(),
            "weights": (
                result.footprint_curve_2d.weights.tolist()
                if result.footprint_curve_2d.weights is not None
                else None
            ),
            "degree": result.footprint_curve_2d.degree,
            "projection_axis": list(result.projection_axis),
            "max_orig_depth": result.max_orig_depth,
            "is_degenerate": uv_spread < _DEGEN_TOL,
            "honest_caveat": result.honest_caveat,
        })

except ImportError:
    # kerf_chat not installed (standalone / test mode) — skip registration.
    pass
