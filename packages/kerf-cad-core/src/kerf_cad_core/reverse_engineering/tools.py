"""
kerf_cad_core.reverse_engineering.tools — LLM tool: re_fit_freeform_nurbs.
===========================================================================

Registers one LLM-callable tool:

  re_fit_freeform_nurbs — Given a segmented point cloud (as returned by the
    reverse-engineering pipeline), extract the freeform residual clusters and
    fit a NURBS B-spline surface to each.

Algorithm
---------
For each freeform cluster (label == "freeform" or -1):

1. Ordered-grid detection: if the projected parameters form a near-regular
   grid, use P&T §9.4 row-by-row interpolation.
2. Otherwise: centripetal PCA parameterisation + knot averaging (P&T §9.2.2)
   + damped LS + adaptive Boehm knot insertion.
3. Hausdorff validation: reports max_hausdorff_mm (one-sided, 50×50 dense
   surface sample) alongside rms_error_mm and a converged flag.

Output shape (per surface)
--------------------------
{
  "ok": true,
  "primitive": "nurbs_surface",
  "degree_u": int,
  "degree_v": int,
  "n_ctrl_u": int,
  "n_ctrl_v": int,
  "rms_error_mm": float,
  "max_hausdorff_mm": float,
  "converged": bool,
  "iterations": int,
  "n_control_points": int,
  "control_points": [[[x,y,z], ...], ...],
  "knots_u": [...],
  "knots_v": [...]
}

Error shape: {"ok": false, "reason": "..."}

References
----------
- Piegl & Tiller §9.2 — Global Surface Approximation
- Piegl & Tiller §9.4 — Global Surface Interpolation
- Hoschek & Lasser §8 — Approximation of point sets by surfaces

Author: imranparuk
"""
from __future__ import annotations

import json
from typing import Any

import numpy as np

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx  # noqa: F401
    _REGISTRY_AVAILABLE = True
except ImportError:  # pragma: no cover — not available in pure-Python test runs
    _REGISTRY_AVAILABLE = False
    ToolSpec = None  # type: ignore[assignment,misc]

from kerf_cad_core.reverse_engineering.freeform_fit import (
    FreeformFitRequest,
    fit_freeform_from_segmentation,
    fit_freeform_to_cluster,
)

# ---------------------------------------------------------------------------
# ToolSpec definition
# ---------------------------------------------------------------------------

_SPEC_DICT: dict[str, Any] = {
    "name": "re_fit_freeform_nurbs",
    "description": (
        "Fit NURBS B-spline surface(s) to the freeform residual clusters from "
        "a reverse-engineering segmentation result.\n"
        "\n"
        "Accepts either:\n"
        "  (a) A raw point cloud + per-point segmentation labels, or\n"
        "  (b) A flat list of 3-D points that are all 'freeform'.\n"
        "\n"
        "For each cluster the fitter:\n"
        "  1. Detects ordered-grid topology (P&T §9.4) and uses row-by-row "
        "interpolation if possible.\n"
        "  2. Falls back to centripetal PCA parameterisation + averaged knot "
        "placement + damped LS + adaptive Boehm knot insertion (P&T §9.2).\n"
        "  3. Reports RMS + one-sided Hausdorff distance + convergence flag.\n"
        "\n"
        "Returns a list of surface records (one per cluster) inside "
        "``surfaces``."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "point_cloud": {
                "type": "array",
                "description": (
                    "List of 3-D points [[x,y,z], ...]. "
                    "Required if using segmentation_labels."
                ),
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
            },
            "segmentation": {
                "type": "array",
                "description": (
                    "Per-point segmentation labels (same length as point_cloud). "
                    "Use 'freeform' or -1 for residual/freeform points. "
                    "If omitted, all points in point_cloud are treated as freeform."
                ),
            },
            "points": {
                "type": "array",
                "description": (
                    "Shorthand: a flat list [[x,y,z], ...] where every point is "
                    "already known to be freeform.  Mutually exclusive with "
                    "point_cloud / segmentation."
                ),
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
            },
            "target_rms_mm": {
                "type": "number",
                "description": (
                    "Convergence target in millimetres.  The fitter uses adaptive "
                    "knot insertion until rms_error_mm ≤ target_rms_mm. "
                    "Default 0.05 mm."
                ),
            },
            "initial_grid": {
                "type": "array",
                "description": (
                    "[n_u_ctrl, n_v_ctrl] — initial control-point grid for the "
                    "unordered path.  Default [8, 8]."
                ),
                "items": {"type": "integer"},
                "minItems": 2,
                "maxItems": 2,
            },
            "max_knot_insertions": {
                "type": "integer",
                "description": (
                    "Maximum adaptive Boehm knot-insertion iterations.  Default 5."
                ),
            },
        },
        "required": [],
    },
}

# ---------------------------------------------------------------------------
# Handler (also callable directly without the registry)
# ---------------------------------------------------------------------------

def _parse_points(raw: list) -> np.ndarray:
    """Parse a list-of-lists into a (N, 3) float array."""
    pts: list[list[float]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, (list, tuple)) or len(item) < 3:
            raise ValueError(f"point[{i}] must be [x, y, z]; got {item!r}")
        pts.append([float(item[0]), float(item[1]), float(item[2])])
    return np.array(pts, dtype=float)


def _result_to_dict(res) -> dict[str, Any]:
    """Serialise a FreeformFitResult to a JSON-compatible dict."""
    srf = res.nurbs_surface
    return {
        "ok": True,
        "primitive": "nurbs_surface",
        "degree_u": srf.degree_u,
        "degree_v": srf.degree_v,
        "n_ctrl_u": srf.num_control_points_u,
        "n_ctrl_v": srf.num_control_points_v,
        "rms_error_mm": res.rms_error_mm,
        "max_hausdorff_mm": res.max_hausdorff_mm,
        "converged": res.converged,
        "iterations": res.iterations,
        "n_control_points": res.n_control_points,
        "control_points": srf.control_points.tolist(),
        "knots_u": srf.knots_u.tolist(),
        "knots_v": srf.knots_v.tolist(),
    }


def handle_re_fit_freeform_nurbs(args: dict[str, Any]) -> dict[str, Any]:
    """Pure-Python handler for re_fit_freeform_nurbs.

    Parameters
    ----------
    args : dict
        Parsed arguments (already deserialized from JSON).

    Returns
    -------
    dict with "ok", "surfaces", and per-surface fit data.
    """
    target_rms = float(args.get("target_rms_mm", 0.05))
    raw_grid = args.get("initial_grid", [8, 8])
    initial_grid = (int(raw_grid[0]), int(raw_grid[1]))
    max_knot_insertions = int(args.get("max_knot_insertions", 5))

    # Determine input mode
    if "points" in args and args["points"] is not None:
        # Shorthand mode: all points are freeform
        try:
            pts = _parse_points(args["points"])
        except ValueError as exc:
            return {"ok": False, "reason": str(exc)}

        if len(pts) == 0:
            return {"ok": False, "reason": "points list is empty"}

        req = FreeformFitRequest(
            cluster_points=pts,
            target_rms_mm=target_rms,
            initial_grid=initial_grid,
            max_knot_insertions=max_knot_insertions,
        )
        try:
            result = fit_freeform_to_cluster(req)
        except (ValueError, Exception) as exc:
            return {"ok": False, "reason": str(exc)}

        return {
            "ok": True,
            "surfaces": [_result_to_dict(result)],
        }

    elif "point_cloud" in args and args["point_cloud"] is not None:
        # Segmentation mode
        try:
            pts = _parse_points(args["point_cloud"])
        except ValueError as exc:
            return {"ok": False, "reason": str(exc)}

        raw_labels = args.get("segmentation")
        if raw_labels is None:
            # No labels → all freeform
            labels = np.full(len(pts), "freeform", dtype=object)
        else:
            labels = np.asarray(raw_labels)
            if len(labels) != len(pts):
                return {
                    "ok": False,
                    "reason": (
                        f"segmentation length ({len(labels)}) != "
                        f"point_cloud length ({len(pts)})"
                    ),
                }

        try:
            results = fit_freeform_from_segmentation(pts, labels, target_rms)
        except (ValueError, Exception) as exc:
            return {"ok": False, "reason": str(exc)}

        return {
            "ok": True,
            "surfaces": [_result_to_dict(r) for r in results],
        }

    else:
        return {
            "ok": False,
            "reason": (
                "Provide either 'points' (flat freeform list) or "
                "'point_cloud' + optional 'segmentation'."
            ),
        }


# ---------------------------------------------------------------------------
# Registry wiring (only when kerf_chat is available)
# ---------------------------------------------------------------------------

if _REGISTRY_AVAILABLE and ToolSpec is not None:
    _re_fit_spec = ToolSpec(
        name=_SPEC_DICT["name"],
        description=_SPEC_DICT["description"],
        input_schema=_SPEC_DICT["input_schema"],
    )

    @register(_re_fit_spec, write=False)
    async def run_re_fit_freeform_nurbs(ctx, args_bytes: bytes) -> str:  # type: ignore[no-untyped-def]
        try:
            a = json.loads(args_bytes)
        except Exception as exc:
            return json.dumps({"ok": False, "reason": f"invalid args JSON: {exc}"})
        result = handle_re_fit_freeform_nurbs(a)
        if result.get("ok"):
            return ok_payload(result)
        return err_payload(result.get("reason", "unknown error"), "FIT_ERROR")


# ---------------------------------------------------------------------------
# TOOLS list (consumed by plugin introspection + tests)
# ---------------------------------------------------------------------------

TOOLS = [
    ("re_fit_freeform_nurbs", _SPEC_DICT, handle_re_fit_freeform_nurbs),
]
