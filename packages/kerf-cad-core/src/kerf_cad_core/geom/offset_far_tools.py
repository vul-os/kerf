"""
offset_far_tools.py
===================
LLM tool registration for ``nurbs_surface_offset_robust`` (GK-P Wave 4P).

Exposes the far-offset robustness layer from ``offset_far_correction.py`` via
the kerf_chat tool registry so the chat agent can:

1. Check whether a target offset distance is safe (safe_offset_distance).
2. Compute a fold-free offset even for large offsets (graceful_offset).

Registered tools
----------------
nurbs_surface_offset_robust
    Given a NURBS surface description + offset distance, returns the offset
    surface (fold-free) together with validity metadata.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    import numpy as _np
    from kerf_cad_core.geom.nurbs import NurbsSurface
    from kerf_cad_core.geom.offset_far_correction import (
        safe_offset_distance,
        graceful_offset,
    )
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


def _make_uniform_knots(n: int, deg: int) -> "_np.ndarray":
    """Open-uniform knot vector for n control points of degree deg."""
    inner = max(0, n - deg - 1)
    import numpy as np
    return np.concatenate([
        np.zeros(deg + 1),
        np.linspace(0.0, 1.0, inner + 2)[1:-1] if inner > 0 else np.array([]),
        np.ones(deg + 1),
    ])


def _build_surface_from_args(a: dict):  # type: ignore[return]
    """Build NurbsSurface from LLM tool args dict.

    Returns (surface, error_str).  error_str is "" on success.
    """
    import numpy as np

    degree_u = a.get("degree_u")
    degree_v = a.get("degree_v")
    raw_cp = a.get("control_points", [])
    num_u = a.get("num_u")
    num_v = a.get("num_v")
    knots_u = a.get("knots_u")
    knots_v = a.get("knots_v")
    weights = a.get("weights")

    if any(x is None for x in [degree_u, degree_v, num_u, num_v]) or not raw_cp:
        return None, "degree_u, degree_v, control_points, num_u, num_v are required"

    try:
        degree_u = int(degree_u)
        degree_v = int(degree_v)
        num_u = int(num_u)
        num_v = int(num_v)
    except (TypeError, ValueError) as exc:
        return None, f"degree/num must be integers: {exc}"

    if degree_u < 1 or degree_v < 1:
        return None, "degree_u and degree_v must be >= 1"
    if num_u < 2 or num_v < 2:
        return None, "num_u and num_v must be >= 2"
    if len(raw_cp) != num_u * num_v:
        return None, (
            f"control_points length {len(raw_cp)} != num_u*num_v={num_u * num_v}"
        )

    try:
        cp_flat = [np.asarray(p, dtype=float) for p in raw_cp]
        dim = cp_flat[0].size
        cp = np.array(
            [p.tolist()[:dim] for p in cp_flat], dtype=float
        ).reshape(num_u, num_v, dim)
    except Exception as exc:
        return None, f"invalid control_points: {exc}"

    try:
        ku = (
            np.asarray(knots_u, dtype=float)
            if knots_u is not None
            else _make_uniform_knots(num_u, degree_u)
        )
        kv = (
            np.asarray(knots_v, dtype=float)
            if knots_v is not None
            else _make_uniform_knots(num_v, degree_v)
        )
        w = np.asarray(weights, dtype=float).reshape(num_u, num_v) if weights is not None else None
        surface = NurbsSurface(
            degree_u=degree_u,
            degree_v=degree_v,
            control_points=cp,
            knots_u=ku,
            knots_v=kv,
            weights=w,
        )
    except Exception as exc:
        return None, f"failed to build NurbsSurface: {exc}"

    return surface, ""


if _REGISTRY_AVAILABLE:

    _robust_offset_spec = ToolSpec(
        name="nurbs_surface_offset_robust",
        description=(
            "Offset a NURBS surface by a signed distance with full curvature-aware "
            "fold prevention. Unlike the basic surface_offset tool, this handles large "
            "offset distances (> 0.5 × min_curvature_radius) where the naive "
            "Tiller-Hanson displacement produces folded or inverted surfaces.\n\n"
            "Algorithm (Maekawa 1999 §6; Hoschek-Lasser 1993 §17):\n"
            "1. Samples a curvature grid over the surface to find the global minimum "
            "   curvature radius R_min.\n"
            "2. If |distance| ≤ 0.95 * R_min, the standard analytic or Tiller-Hanson "
            "   offset is used (exact for spheres/planes).\n"
            "3. If |distance| > 0.95 * R_min, each control point's displacement is "
            "   clamped to the local safe limit — producing a fold-free approximation "
            "   and flagging the unsafe parametric regions.\n\n"
            "Returns:\n"
            "  ok           : bool\n"
            "  is_fully_safe: bool — True when the full offset is geometrically valid\n"
            "  safe_distance: float — maximum safe offset distance (0.95 × R_min)\n"
            "  R_min        : float — minimum curvature radius over the surface\n"
            "  unsafe_regions: list of {u_lo, u_hi, v_lo, v_hi} problem rectangles\n"
            "  offset_surface: {degree_u, degree_v, control_points, num_u, num_v, "
            "                   knots_u, knots_v, weights} — the offset NurbsSurface"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "distance": {
                    "type": "number",
                    "description": (
                        "Signed offset distance. Positive = outward (positive normal)."
                    ),
                },
                "degree_u": {"type": "integer", "description": "Surface degree in U."},
                "degree_v": {"type": "integer", "description": "Surface degree in V."},
                "control_points": {
                    "type": "array",
                    "description": (
                        "Flattened nu×nv control points as [[x,y,z], …] "
                        "(row-major, U outer / V inner)."
                    ),
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "num_u": {
                    "type": "integer",
                    "description": "Number of control points in U.",
                },
                "num_v": {
                    "type": "integer",
                    "description": "Number of control points in V.",
                },
                "knots_u": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": (
                        "Knot vector in U (length = num_u + degree_u + 1). "
                        "Omit to use an open-uniform knot vector."
                    ),
                },
                "knots_v": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Knot vector in V. Omit for open-uniform.",
                },
                "weights": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": (
                        "Rational weights as a flattened nu×nv array. "
                        "Omit for non-rational (uniform weights = 1)."
                    ),
                },
            },
            "required": [
                "distance", "degree_u", "degree_v",
                "control_points", "num_u", "num_v",
            ],
        },
    )

    @register(_robust_offset_spec)
    async def run_nurbs_surface_offset_robust(
        ctx: "ProjectCtx", args: bytes
    ) -> str:
        import numpy as np

        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        distance = a.get("distance")
        if distance is None:
            return err_payload("distance is required", "BAD_ARGS")
        try:
            distance = float(distance)
        except (TypeError, ValueError) as exc:
            return err_payload(f"distance must be a number: {exc}", "BAD_ARGS")

        surface, err = _build_surface_from_args(a)
        if surface is None:
            return err_payload(err, "BAD_ARGS")

        try:
            result = graceful_offset(surface, distance)
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")
        except Exception as exc:
            logger.exception("nurbs_surface_offset_robust: unexpected error")
            return err_payload(f"offset failed: {exc}", "OP_FAILED")

        # Serialise the offset NurbsSurface back to a JSON-friendly dict.
        off = result.surface
        nu, nv = off.num_control_points_u, off.num_control_points_v
        cp_list = off.control_points.reshape(nu * nv, -1).tolist()
        payload = {
            "is_fully_safe": result.is_fully_safe,
            "safe_distance": result.safe_distance,
            "unsafe_regions": [
                {
                    "u_lo": r.u_lo, "u_hi": r.u_hi,
                    "v_lo": r.v_lo, "v_hi": r.v_hi,
                }
                for r in result.unsafe_regions
            ],
            "offset_surface": {
                "degree_u": off.degree_u,
                "degree_v": off.degree_v,
                "num_u": nu,
                "num_v": nv,
                "control_points": cp_list,
                "knots_u": off.knots_u.tolist(),
                "knots_v": off.knots_v.tolist(),
                "weights": (
                    off.weights.reshape(nu * nv).tolist()
                    if off.weights is not None
                    else None
                ),
            },
        }
        return ok_payload(payload)
