"""
kerf_cad_core.geom.reparam_tools — LLM tool wrapper for NURBS reparametrisation.

Registers:
  nurbs_reparametrize — compute chord-length / centripetal / Foley-Nielsen
                        parameter sequence for a list of 3D points.

The tool is stateless: it accepts a JSON array of 3D points and returns
the parameter values.  Callers can use the result with any NURBS fitting
function that accepts a ``parameterisation`` kwarg.

Author: imranparuk
"""
from __future__ import annotations

import json

import numpy as np

from kerf_cad_core._compat import ToolSpec, err_payload, ok_payload, register
from kerf_cad_core._compat import ProjectCtx  # noqa: F401

from kerf_cad_core.geom.reparam import (
    parametrize_chord_length,
    parametrize_centripetal,
    parametrize_foley_nielsen,
)


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

_reparam_spec = ToolSpec(
    name="nurbs_reparametrize",
    description=(
        "Compute a parameter sequence for an ordered list of 3D points using "
        "one of three canonical NURBS reparametrisation schemes.\n\n"
        "Schemes\n"
        "-------\n"
        "- **chord_length** (Piegl-Tiller §9.2.2 eq. 9.4): u_i proportional to "
        "cumulative Euclidean chord lengths.  Best for uniformly-spaced data.\n"
        "- **centripetal** (default, α=0.5; P&T eq. 9.5): u_i proportional to "
        "chord-length^α.  Industry standard for noisy point-cloud fitting — "
        "prevents oscillation near high-curvature regions.\n"
        "- **foley_nielsen** (Foley-Nielsen 1989): chord-length weighted by local "
        "turning angle.  Produces denser parameters at sharp bends, yielding "
        "smoother fitted curves with the same control-point count.\n\n"
        "Returns `u_values` (list of n floats in [0, 1], monotonically "
        "increasing, u[0]=0, u[-1]=1).\n\n"
        "Never raises; invalid inputs return `{ok: false, reason}`."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "points": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                },
                "description": (
                    "Ordered list of 3D (or nD) points, each a list of floats.  "
                    "Minimum 2 points."
                ),
            },
            "method": {
                "type": "string",
                "enum": ["chord_length", "centripetal", "foley_nielsen"],
                "description": (
                    "Parametrisation scheme.  Default: 'centripetal'."
                ),
            },
            "alpha": {
                "type": "number",
                "description": (
                    "Exponent for centripetal scheme.  0=uniform, 0.5=centripetal "
                    "(default), 1=chord-length.  Ignored for other methods."
                ),
            },
        },
        "required": ["points"],
    },
)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

@register(_reparam_spec, write=False)
async def run_nurbs_reparametrize(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    raw_points = a.get("points")
    if raw_points is None:
        return json.dumps({"ok": False, "reason": "points is required"})

    try:
        pts = np.asarray(raw_points, dtype=float)
    except Exception as exc:
        return json.dumps({"ok": False, "reason": f"could not convert points to array: {exc}"})

    if pts.ndim == 1:
        pts = pts.reshape(-1, 1)
    if pts.ndim != 2 or len(pts) < 2:
        return json.dumps(
            {"ok": False, "reason": "points must be a 2D array of at least 2 rows"}
        )

    method = a.get("method", "centripetal")
    alpha = float(a.get("alpha", 0.5))

    try:
        if method == "chord_length":
            u = parametrize_chord_length(pts)
        elif method == "centripetal":
            u = parametrize_centripetal(pts, alpha=alpha)
        elif method == "foley_nielsen":
            u = parametrize_foley_nielsen(pts)
        else:
            return json.dumps(
                {"ok": False, "reason": f"unknown method {method!r}; "
                 "choose chord_length, centripetal, or foley_nielsen"}
            )
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})

    return ok_payload({
        "ok": True,
        "method": method,
        "u_values": u.tolist(),
        "n_points": len(u),
    })
