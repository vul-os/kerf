"""
kerf_cad_core.scan.nurbs_fit_tools — LLM tool wrapper for NURBS freeform
surface fitting from segmented point clouds.

Registers one tool:

  scan_fit_nurbs_surface — fit a NURBS B-spline surface to a segmented
                           point cluster returned by scan_segment (the
                           non-primitive / freeform branch).

Algorithm: centripetal parameterisation + P&T §9.2 averaging knot placement
+ damped least-squares; see kerf_cad_core.geom.nurbs_surface_fit for details.

Output: {ok, primitive:"nurbs_surface", n_ctrl_u, n_ctrl_v, degree_u,
         degree_v, rms_residual, max_residual, condition_number,
         control_points: [[[x,y,z], ...], ...], knots_u:[...], knots_v:[...]}

Errors: {ok:false, reason:"..."} — tool never raises.

Author: imranparuk
"""
from __future__ import annotations

import json
from typing import Any

import numpy as np

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.geom.nurbs_surface_fit import FitError, nurbs_surface_fit


# ---------------------------------------------------------------------------
# ToolSpec
# ---------------------------------------------------------------------------

_scan_fit_nurbs_surface_spec = ToolSpec(
    name="scan_fit_nurbs_surface",
    description=(
        "Fit a NURBS B-spline surface to a freeform point cluster from a "
        "scan_segment result (the non-primitive / organic-shape branch).\n"
        "\n"
        "Algorithm:\n"
        "  1. Centripetal parameterisation (robust for noisy, irregular clouds).\n"
        "  2. Knot-vector placement via the averaging method (Piegl & Tiller "
        "§9.2.2).\n"
        "  3. Damped linear least-squares:\n"
        "       min ||N·P - Q||² + λ·||D·P||²\n"
        "     where N is the tensor-product basis matrix and D is a "
        "second-difference smoothness operator.\n"
        "\n"
        "Input: a list of [x, y, z] points (the freeform cluster). At least "
        "(u_degree+1)*(v_degree+1) points are required.\n"
        "\n"
        "Output: {ok, primitive:'nurbs_surface', degree_u, degree_v, n_ctrl_u, "
        "n_ctrl_v, rms_residual, max_residual, condition_number, "
        "control_points:[[[x,y,z],...]], knots_u:[...], knots_v:[...]}.\n"
        "\n"
        "Errors: {ok:false, reason} for degenerate/insufficient input. "
        "Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "points": {
                "type": "array",
                "description": (
                    "List of 3-D points as [[x,y,z], ...]. "
                    "Minimum (u_degree+1)*(v_degree+1) points required."
                ),
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
            },
            "u_degree": {
                "type": "integer",
                "description": (
                    "B-spline degree in the U direction (1–7). "
                    "Cubic (3) is standard. Default 3."
                ),
            },
            "v_degree": {
                "type": "integer",
                "description": "B-spline degree in the V direction. Default 3.",
            },
            "n_u_ctrl": {
                "type": "integer",
                "description": (
                    "Number of control points in U. Must be >= u_degree+1. "
                    "Default 8."
                ),
            },
            "n_v_ctrl": {
                "type": "integer",
                "description": "Number of control points in V. Default 8.",
            },
            "lambda_smooth": {
                "type": "number",
                "description": (
                    "Smoothness regularisation weight (>= 0). Higher values "
                    "produce smoother but less accurate surfaces. Default 1e-3."
                ),
            },
        },
        "required": ["points"],
    },
)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

@register(_scan_fit_nurbs_surface_spec, write=False)
async def run_scan_fit_nurbs_surface(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    raw_pts = a.get("points")
    if not isinstance(raw_pts, list) or len(raw_pts) == 0:
        return json.dumps({"ok": False, "reason": "points must be a non-empty list"})

    pts_list: list[list[float]] = []
    for i, item in enumerate(raw_pts):
        if not isinstance(item, (list, tuple)) or len(item) != 3:
            return json.dumps(
                {"ok": False, "reason": f"point[{i}] must be an array of 3 numbers"}
            )
        try:
            pts_list.append([float(item[0]), float(item[1]), float(item[2])])
        except (TypeError, ValueError):
            return json.dumps(
                {"ok": False, "reason": f"point[{i}] contains non-numeric value"}
            )

    pts_np = np.array(pts_list, dtype=float)

    u_degree = int(a.get("u_degree", 3))
    v_degree = int(a.get("v_degree", 3))
    n_u_ctrl = int(a.get("n_u_ctrl", 8))
    n_v_ctrl = int(a.get("n_v_ctrl", 8))
    lambda_smooth = float(a.get("lambda_smooth", 1e-3))

    # Guard degrees
    if u_degree < 1 or u_degree > 7:
        return json.dumps({"ok": False, "reason": f"u_degree must be 1–7; got {u_degree}"})
    if v_degree < 1 or v_degree > 7:
        return json.dumps({"ok": False, "reason": f"v_degree must be 1–7; got {v_degree}"})
    if lambda_smooth < 0:
        return json.dumps({"ok": False, "reason": "lambda_smooth must be >= 0"})

    try:
        srf, report = nurbs_surface_fit(
            pts_np,
            u_degree=u_degree,
            v_degree=v_degree,
            n_u_ctrl=n_u_ctrl,
            n_v_ctrl=n_v_ctrl,
            lambda_smooth=lambda_smooth,
        )
    except FitError as exc:
        return json.dumps({"ok": False, "reason": str(exc)})
    except Exception as exc:
        return json.dumps({"ok": False, "reason": f"unexpected error: {exc}"})

    result: dict[str, Any] = {
        "ok": True,
        "primitive": "nurbs_surface",
        "degree_u": srf.degree_u,
        "degree_v": srf.degree_v,
        "n_ctrl_u": srf.num_control_points_u,
        "n_ctrl_v": srf.num_control_points_v,
        "rms_residual": report.rms_residual,
        "max_residual": report.max_residual,
        "condition_number": report.condition_number,
        # Control points as nested list [[[x,y,z], ...], ...]
        "control_points": srf.control_points.tolist(),
        "knots_u": srf.knots_u.tolist(),
        "knots_v": srf.knots_v.tolist(),
    }
    return ok_payload(result)
