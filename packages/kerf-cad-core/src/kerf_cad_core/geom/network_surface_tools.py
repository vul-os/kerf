"""
kerf_cad_core.geom.network_surface_tools
========================================
LLM tool wrappers for N-sided Coons + Gregory + Hosaka-Kimura patch fit.

Registers the tool:
  nurbs_n_sided_patch — fit an N-sided surface patch from a closed boundary
                        loop of N curves (N >= 3) using Coons-Gregory blending.

Pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
Gregory (1974) "Smooth interpolation without twist constraints."
Hosaka-Kimura (1984) "Non-four-sided patch expressions."
Coons (1967) "Surfaces for computer-aided design of space forms."
Várady-Salvi-Karikó-Sipos (2003) "Curve network-based design."
"""
from __future__ import annotations

import json
import math

import numpy as np

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

_nsided_patch_spec = ToolSpec(
    name="nurbs_n_sided_patch",
    description=(
        "Fit a single N-sided NURBS surface patch from a closed boundary loop of N curves.\n"
        "\n"
        "N must be ≥ 3.  The method adapts automatically:\n"
        "  N = 3 → Hosaka-Kimura triangular Coons patch (1984) — degenerate Coons,\n"
        "          barycentric blending of three boundary curves.  For planar\n"
        "          straight-line boundaries the result is the exact flat triangle.\n"
        "  N = 4 → Gregory (1974) twist-corrected Coons patch.  For four straight-line\n"
        "          boundaries this collapses to an exact bilinear (degree-1) NURBS\n"
        "          patch matching the Coons formula within machine precision.\n"
        "  N ≥ 5 → General N-sided polygon-domain blend (Várady / Hosaka-Kimura):\n"
        "          Wachspress rational weights + ruled-surface boundary contributions\n"
        "          fill the patch interior with G0 boundary interpolation.\n"
        "\n"
        "Boundary curves are auto-oriented (endpoint chaining, with optional flip)\n"
        "and the closure is verified within tol.\n"
        "\n"
        "Returns the surface as a serialized NurbsSurface descriptor:\n"
        "  {\n"
        "    'ok': true,\n"
        "    'degree_u': int,\n"
        "    'degree_v': int,\n"
        "    'num_control_points_u': int,\n"
        "    'num_control_points_v': int,\n"
        "    'n_sides': int,\n"
        "    'method': str,\n"
        "    'bending_energy': float   (0 for flat patches),\n"
        "  }\n"
        "\n"
        "Errors: {'ok': false, 'reason': '...'} — never raises.\n"
        "\n"
        "Parameters\n"
        "----------\n"
        "boundary_curves : list of {points: [[x,y,z], ...]} objects, or list of\n"
        "    {p0: [x,y,z], p1: [x,y,z]} line-segment objects.  Each curve must\n"
        "    connect end-to-end with the next (auto-flip applied if needed).\n"
        "internal_curves : optional list of cross-curves (same format) for shape\n"
        "    control.  Currently used only with N=4 (Gordon network surface).\n"
        "method : 'coons_gregory' (default, recommended).\n"
        "tol : endpoint chain tolerance (default 1e-6).\n"
        "grid_n : sample grid size per direction (default 24; higher = smoother).\n"
        "compute_fairness : if true, compute and return the bending-energy metric.\n"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "boundary_curves": {
                "type": "array",
                "description": (
                    "List of N boundary curves (N >= 3) forming a closed loop. "
                    "Each entry is either: "
                    "{\"points\": [[x,y,z], ...]} — polyline, "
                    "or {\"p0\": [x,y,z], \"p1\": [x,y,z]} — line segment."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "points": {
                            "type": "array",
                            "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                            "description": "Polyline control points [[x,y,z], ...].",
                        },
                        "p0": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3,
                            "maxItems": 3,
                            "description": "Start point of a line segment.",
                        },
                        "p1": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3,
                            "maxItems": 3,
                            "description": "End point of a line segment.",
                        },
                    },
                },
            },
            "internal_curves": {
                "type": "array",
                "description": "Optional internal cross-curves for shape control.",
                "items": {
                    "type": "object",
                    "properties": {
                        "points": {
                            "type": "array",
                            "items": {"type": "array", "items": {"type": "number"}},
                        },
                        "p0": {"type": "array", "items": {"type": "number"}},
                        "p1": {"type": "array", "items": {"type": "number"}},
                    },
                },
            },
            "method": {
                "type": "string",
                "enum": ["coons_gregory"],
                "description": "Patch fit method. Default: 'coons_gregory'.",
            },
            "tol": {
                "type": "number",
                "description": "Endpoint chain closure tolerance (default 1e-6).",
            },
            "grid_n": {
                "type": "integer",
                "description": "Sample grid size per direction (default 24). Range: 6..64.",
            },
            "compute_fairness": {
                "type": "boolean",
                "description": "If true, compute and return the bending-energy fairness metric.",
            },
        },
        "required": ["boundary_curves"],
    },
)


# ---------------------------------------------------------------------------
# Input parsing helpers
# ---------------------------------------------------------------------------

def _parse_curve(entry: dict):
    """Parse a curve entry dict to a NurbsCurve.

    Accepts:
      {"p0": [x,y,z], "p1": [x,y,z]} → line segment
      {"points": [[x,y,z], ...]}      → polyline (degree 1 or higher)
    """
    from kerf_cad_core.geom.nurbs import NurbsCurve, make_line_nurbs
    import numpy as np

    if not isinstance(entry, dict):
        raise ValueError(f"Expected dict for curve, got {type(entry).__name__}")

    if "p0" in entry and "p1" in entry:
        p0 = np.asarray(entry["p0"], dtype=float).ravel()
        p1 = np.asarray(entry["p1"], dtype=float).ravel()
        if p0.shape[0] < 3:
            p0 = np.concatenate([p0, np.zeros(3 - p0.shape[0])])
        if p1.shape[0] < 3:
            p1 = np.concatenate([p1, np.zeros(3 - p1.shape[0])])
        return make_line_nurbs(p0[:3], p1[:3])

    if "points" in entry:
        pts = np.asarray(entry["points"], dtype=float)
        if pts.ndim != 2 or pts.shape[1] < 3:
            raise ValueError(
                f"'points' must be an (N>=2, 3) array; got shape {pts.shape}"
            )
        if pts.shape[0] < 2:
            raise ValueError("'points' must have at least 2 points")
        pts = pts[:, :3]
        n = pts.shape[0]
        # Build a degree-1 polyline NURBS curve.
        degree = 1
        # Clamped knot vector for n control points of degree 1:
        # [0, 0, 1/(n-1), 2/(n-1), ..., 1, 1]
        knots = np.zeros(n + degree + 1)
        knots[:degree + 1] = 0.0
        knots[-(degree + 1):] = 1.0
        if n > 2:
            inner = np.linspace(0.0, 1.0, n)[1:-1]
            knots[degree + 1:degree + 1 + (n - 2)] = inner
        return NurbsCurve(degree=degree, control_points=pts, knots=knots)

    raise ValueError(
        "Curve entry must have 'p0'+'p1' (line) or 'points' (polyline). "
        f"Got keys: {list(entry.keys())}"
    )


# ---------------------------------------------------------------------------
# Tool handler
# ---------------------------------------------------------------------------

@register(_nsided_patch_spec, write=False)
async def run_nurbs_n_sided_patch(ctx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    boundary_raw = a.get("boundary_curves")
    if not boundary_raw:
        return json.dumps({"ok": False, "reason": "'boundary_curves' is required"})

    if not isinstance(boundary_raw, list) or len(boundary_raw) < 3:
        return json.dumps({"ok": False, "reason": "'boundary_curves' must be a list of >= 3 curves"})

    # Parse boundary curves.
    try:
        boundary_curves = [_parse_curve(entry) for entry in boundary_raw]
    except Exception as exc:
        return json.dumps({"ok": False, "reason": f"parsing boundary_curves: {exc}"})

    # Parse optional internal curves.
    internal_curves = None
    if a.get("internal_curves"):
        try:
            internal_curves = [_parse_curve(entry) for entry in a["internal_curves"]]
        except Exception as exc:
            return json.dumps({"ok": False, "reason": f"parsing internal_curves: {exc}"})

    method = a.get("method", "coons_gregory")
    tol = float(a.get("tol", 1e-6))
    grid_n = int(a.get("grid_n", 24))
    grid_n = max(6, min(64, grid_n))
    compute_fairness = bool(a.get("compute_fairness", False))

    try:
        from kerf_cad_core.geom.network_surface import (
            fit_network_patch,
            fairness_metric,
        )
        surf = fit_network_patch(
            boundary_curves=boundary_curves,
            internal_curves=internal_curves,
            method=method,
            tol=tol,
            grid_n=grid_n,
        )
    except ValueError as exc:
        return json.dumps({"ok": False, "reason": str(exc)})
    except Exception as exc:
        return json.dumps({"ok": False, "reason": f"fit_network_patch error: {exc}"})

    result = {
        "ok": True,
        "n_sides": len(boundary_curves),
        "method": method,
        "degree_u": int(surf.degree_u),
        "degree_v": int(surf.degree_v),
        "num_control_points_u": int(surf.num_control_points_u),
        "num_control_points_v": int(surf.num_control_points_v),
    }

    if compute_fairness:
        try:
            energy = fairness_metric(surf, n_samples=12)
            result["bending_energy"] = float(energy)
        except Exception as exc:
            result["bending_energy"] = None
            result["fairness_warning"] = f"Could not compute bending energy: {exc}"

    return ok_payload(result)
