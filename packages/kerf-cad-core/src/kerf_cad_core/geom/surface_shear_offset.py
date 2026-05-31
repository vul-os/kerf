"""
NURBS-SURFACE-SHEAR-OFFSET
===========================
Apply an affine shear transform to a NurbsSurface by displacing each control
point P=(x,y,z) by a linear function of its position:

    P'_x = x + s_xy * y + s_xz * z
    P'_y = y + s_yx * x + s_yz * z
    P'_z = z + s_zx * x + s_zy * y

This is equivalent to applying the matrix (I + S) to P, where S is the
off-diagonal shear matrix with the six coefficients.  Knot vectors and
weights are preserved exactly — affine maps on control-point nets are
exact for NURBS (Piegl & Tiller §6.1 Theorem 6.1; Mortenson §4.8).

Use case
--------
Compensate for workpiece warp during finish-machining post-processing.
After measuring residual warp (e.g. via CMM), encode the measured shear
distortion as a ShearMatrix and call apply_shear_offset to pre-warp the
design surface so the machined result is nominally correct.

HONEST LIMITATIONS
------------------
* This tool applies a *global linear* shear: every control point is
  displaced by the same shear coefficients.  Non-uniform or spatially
  varying warp (common in thermal distortion, springback, gravity sag)
  cannot be corrected by a single ShearMatrix — those cases require a
  per-point deformation field (e.g. a vector displacement map).
* The shear is applied to the *control-point polygon*, not the evaluated
  surface.  For non-rational NURBS this is exact (the evaluated surface
  is the image under the same affine map).  For rational (weighted) NURBS
  the evaluated NURBS surface is also transformed exactly because affine
  maps commute with rational B-spline evaluation (P&T §6.1).
* max_displacement_mm and mean_displacement_mm measure how far the
  control points moved, expressed in the same units as the input
  control-point coordinates (assumed mm).  They are *control-point*
  displacements, not evaluated-surface pointwise deviations.

References
----------
* Piegl, L. & Tiller, W. (1997). *The NURBS Book*, 2nd ed., §6.1
  "Transformations of NURBS Curves and Surfaces".
* Mortenson, M.E. (2006). *Geometric Modeling*, 3rd ed., §4.8
  "Affine Transformations" — shear as off-diagonal linear maps.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsSurface


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ShearMatrix:
    """Six-component shear matrix (off-diagonal entries of (I+S)).

    The full 3x3 shear matrix applied to a point P=(x,y,z) is::

        | 1      s_xy   s_xz |   | x |
        | s_yx   1      s_yz | * | y |
        | s_zx   s_zy   1    |   | z |

    Setting all coefficients to 0.0 produces the identity transform.

    Attributes
    ----------
    s_xy : float
        X-component displacement per unit Y (x += s_xy * y).
    s_xz : float
        X-component displacement per unit Z (x += s_xz * z).
    s_yx : float
        Y-component displacement per unit X (y += s_yx * x).
    s_yz : float
        Y-component displacement per unit Z (y += s_yz * z).
    s_zx : float
        Z-component displacement per unit X (z += s_zx * x).
    s_zy : float
        Z-component displacement per unit Y (z += s_zy * y).
    """
    s_xy: float = 0.0
    s_xz: float = 0.0
    s_yx: float = 0.0
    s_yz: float = 0.0
    s_zx: float = 0.0
    s_zy: float = 0.0


@dataclass
class SurfaceShearOffsetResult:
    """Result of :func:`apply_shear_offset`.

    Attributes
    ----------
    sheared_surface : NurbsSurface
        The transformed surface.  Degree, knot vectors, and weights are
        identical to the input; only control-point XYZ coordinates differ.
    max_displacement_mm : float
        Maximum displacement (Euclidean norm) across all control points,
        in the same units as the input coordinates (assumed mm).
    mean_displacement_mm : float
        Mean displacement across all control points.
    honest_caveat : str
        Human-readable honesty note about the limitations of the operation.
    """
    sheared_surface: NurbsSurface
    max_displacement_mm: float
    mean_displacement_mm: float
    honest_caveat: str


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

def apply_shear_offset(
    surface: NurbsSurface,
    shear: ShearMatrix,
) -> SurfaceShearOffsetResult:
    """Apply a linear shear transform to all control points of a NurbsSurface.

    For each control point P = (x, y, z)::

        P'_x = x + shear.s_xy * y + shear.s_xz * z
        P'_y = y + shear.s_yx * x + shear.s_yz * z
        P'_z = z + shear.s_zx * x + shear.s_zy * y

    Knot vectors and weights are copied unchanged.

    Parameters
    ----------
    surface : NurbsSurface
        Input surface.  Control points must be 3-D (nu x nv x 3).
    shear : ShearMatrix
        Shear coefficients.  All-zero gives identity (no displacement).

    Returns
    -------
    SurfaceShearOffsetResult
        Contains the sheared surface plus displacement statistics.

    Raises
    ------
    ValueError
        If control points are not 3-D (last dimension != 3).
    """
    cp = np.asarray(surface.control_points, dtype=float)
    if cp.ndim != 3 or cp.shape[2] != 3:
        raise ValueError(
            f"control_points must have shape (nu, nv, 3); got {cp.shape}. "
            "apply_shear_offset supports 3-D surfaces only."
        )

    nu, nv, _ = cp.shape

    # Build the (I + S) matrix explicitly for clarity + efficiency.
    # Row i: new coord i = sum_j M[i,j] * coord_j
    #
    # M = [[1,       s_xy,   s_xz],
    #      [s_yx,    1,      s_yz],
    #      [s_zx,    s_zy,   1   ]]
    M = np.array([
        [1.0,       shear.s_xy, shear.s_xz],
        [shear.s_yx, 1.0,       shear.s_yz],
        [shear.s_zx, shear.s_zy, 1.0      ],
    ], dtype=float)

    # Reshape to (nu*nv, 3), apply M, reshape back.
    cp_flat = cp.reshape(-1, 3)           # (nu*nv, 3)
    cp_new_flat = cp_flat @ M.T           # (nu*nv, 3)  — P' = M P => row-vec @ M^T
    cp_new = cp_new_flat.reshape(nu, nv, 3)

    # Displacement magnitudes for each control point.
    diff = cp_new_flat - cp_flat          # (nu*nv, 3)
    displacements = np.linalg.norm(diff, axis=1)  # (nu*nv,)

    max_disp = float(np.max(displacements))
    mean_disp = float(np.mean(displacements))

    # Build honest caveat.
    is_identity = np.allclose(M, np.eye(3), atol=1e-15)
    if is_identity:
        caveat = (
            "All shear coefficients are zero: the output surface is identical "
            "to the input (identity transform)."
        )
    else:
        caveat = (
            "Linear (global) shear only — all control points displaced by the "
            "same shear coefficients.  Non-uniform warp (thermal distortion, "
            "springback, gravity sag) requires per-point deformation, not a "
            "single ShearMatrix.  Displacement statistics are computed over "
            "control points, not evaluated-surface points."
        )

    sheared = NurbsSurface(
        degree_u=surface.degree_u,
        degree_v=surface.degree_v,
        control_points=cp_new,
        knots_u=surface.knots_u.copy(),
        knots_v=surface.knots_v.copy(),
        weights=(
            surface.weights.copy() if surface.weights is not None else None
        ),
    )

    return SurfaceShearOffsetResult(
        sheared_surface=sheared,
        max_displacement_mm=max_disp,
        mean_displacement_mm=mean_disp,
        honest_caveat=caveat,
    )


# ---------------------------------------------------------------------------
# LLM tool registration (gated import — no hard dependency on kerf_chat)
# ---------------------------------------------------------------------------

try:
    import json as _json

    from kerf_chat.tools.registry import ToolSpec, register, ok_payload, err_payload  # type: ignore

    _SPEC = ToolSpec(
        name="nurbs_apply_surface_shear_offset",
        description=(
            "Apply a linear shear-transform offset to a NurbsSurface: each control "
            "point P=(x,y,z) is displaced by a function of its own position:\n"
            "\n"
            "  P'_x = x + s_xy*y + s_xz*z\n"
            "  P'_y = y + s_yx*x + s_yz*z\n"
            "  P'_z = z + s_zx*x + s_zy*y\n"
            "\n"
            "Equivalent to applying (I+S) to each control point where S is the "
            "off-diagonal shear matrix (Mortenson §4.8; Piegl & Tiller §6.1).\n"
            "\n"
            "Use case: compensate workpiece warp during finish-machining post-processing.\n"
            "\n"
            "Knot vectors and weights are preserved exactly (affine maps are exact "
            "for NURBS; P&T §6.1 Theorem 6.1).\n"
            "\n"
            "HONEST LIMITS: global linear shear only — non-uniform warp (thermal, "
            "springback, gravity) needs a per-point deformation field, not a ShearMatrix.\n"
            "\n"
            "Returns:\n"
            "  ok                    : bool\n"
            "  control_points        : [[[x,y,z], ...], ...]  — nu x nv grid\n"
            "  degree_u, degree_v    : int\n"
            "  knots_u, knots_v      : [float, ...]\n"
            "  weights               : [[float, ...], ...] | null\n"
            "  max_displacement_mm   : float\n"
            "  mean_displacement_mm  : float\n"
            "  honest_caveat         : str\n"
            "\n"
            "Errors: {ok: false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "required": ["control_points", "degree_u", "degree_v"],
            "properties": {
                "control_points": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3,
                            "maxItems": 3,
                        },
                    },
                    "description": (
                        "nu x nv grid of 3-D control points [[[x,y,z], ...], ...]."
                    ),
                },
                "degree_u": {
                    "type": "integer",
                    "description": "Polynomial degree in the U direction.",
                },
                "degree_v": {
                    "type": "integer",
                    "description": "Polynomial degree in the V direction.",
                },
                "knots_u": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": (
                        "Knot vector in U.  Auto-generated (uniform clamped) if omitted."
                    ),
                },
                "knots_v": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": (
                        "Knot vector in V.  Auto-generated (uniform clamped) if omitted."
                    ),
                },
                "weights": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                    },
                    "description": "nu x nv weight grid.  Null / omit for non-rational.",
                },
                "s_xy": {
                    "type": "number",
                    "default": 0.0,
                    "description": "Shear: x += s_xy * y.",
                },
                "s_xz": {
                    "type": "number",
                    "default": 0.0,
                    "description": "Shear: x += s_xz * z.",
                },
                "s_yx": {
                    "type": "number",
                    "default": 0.0,
                    "description": "Shear: y += s_yx * x.",
                },
                "s_yz": {
                    "type": "number",
                    "default": 0.0,
                    "description": "Shear: y += s_yz * z.",
                },
                "s_zx": {
                    "type": "number",
                    "default": 0.0,
                    "description": "Shear: z += s_zx * x.",
                },
                "s_zy": {
                    "type": "number",
                    "default": 0.0,
                    "description": "Shear: z += s_zy * y.",
                },
            },
        },
    )

    def _make_uniform_clamped_knots(n: int, degree: int) -> np.ndarray:
        """Build a uniform clamped knot vector for n CPs and given degree."""
        inner = max(0, n - degree - 1)
        return np.concatenate([
            np.zeros(degree + 1),
            np.linspace(0.0, 1.0, inner + 2)[1:-1] if inner > 0 else np.array([]),
            np.ones(degree + 1),
        ])

    @register(_SPEC)
    async def _run_nurbs_apply_surface_shear_offset(ctx, args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON args: {exc}", "BAD_ARGS")

        try:
            cp_raw = a["control_points"]
            degree_u = int(a["degree_u"])
            degree_v = int(a["degree_v"])
        except (KeyError, TypeError, ValueError) as exc:
            return err_payload(f"missing or bad required field: {exc}", "BAD_ARGS")

        try:
            cp_arr = np.array(cp_raw, dtype=float)
            if cp_arr.ndim != 3:
                return err_payload(
                    f"control_points must be 3-D array (nu x nv x 3); "
                    f"got ndim={cp_arr.ndim}",
                    "BAD_ARGS",
                )
            nu, nv, dim = cp_arr.shape
            if dim != 3:
                return err_payload(
                    f"control_points last dimension must be 3; got {dim}",
                    "BAD_ARGS",
                )

            # Build knot vectors.
            ku_raw = a.get("knots_u")
            kv_raw = a.get("knots_v")
            knots_u = (
                np.array(ku_raw, dtype=float)
                if ku_raw is not None
                else _make_uniform_clamped_knots(nu, degree_u)
            )
            knots_v = (
                np.array(kv_raw, dtype=float)
                if kv_raw is not None
                else _make_uniform_clamped_knots(nv, degree_v)
            )

            # Weights (optional).
            w_raw = a.get("weights")
            weights = np.array(w_raw, dtype=float) if w_raw is not None else None

            surface = NurbsSurface(
                degree_u=degree_u,
                degree_v=degree_v,
                control_points=cp_arr,
                knots_u=knots_u,
                knots_v=knots_v,
                weights=weights,
            )
        except Exception as exc:
            return err_payload(f"could not build NurbsSurface: {exc}", "BAD_ARGS")

        try:
            shear = ShearMatrix(
                s_xy=float(a.get("s_xy", 0.0)),
                s_xz=float(a.get("s_xz", 0.0)),
                s_yx=float(a.get("s_yx", 0.0)),
                s_yz=float(a.get("s_yz", 0.0)),
                s_zx=float(a.get("s_zx", 0.0)),
                s_zy=float(a.get("s_zy", 0.0)),
            )
        except (TypeError, ValueError) as exc:
            return err_payload(f"invalid shear coefficient: {exc}", "BAD_ARGS")

        try:
            result = apply_shear_offset(surface, shear)
        except Exception as exc:
            return err_payload(f"shear offset failed: {exc}", "GEOM_ERROR")

        srf = result.sheared_surface
        return ok_payload({
            "ok": True,
            "control_points": srf.control_points.tolist(),
            "degree_u": srf.degree_u,
            "degree_v": srf.degree_v,
            "knots_u": srf.knots_u.tolist(),
            "knots_v": srf.knots_v.tolist(),
            "weights": (
                srf.weights.tolist() if srf.weights is not None else None
            ),
            "max_displacement_mm": result.max_displacement_mm,
            "mean_displacement_mm": result.mean_displacement_mm,
            "honest_caveat": result.honest_caveat,
        })

except ImportError:
    # kerf_chat not installed (standalone / test mode) — skip registration.
    pass
