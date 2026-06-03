"""
kerf_cad_core.geom.nurbs_derivative_tools — Wave 8 LLM tool for NURBS surface derivatives.

Wave 8 module
-------------
  kerf_cad_core.geom.nurbs_derivative

Tool registered
---------------
  nurbs_surface_derivative — All mixed partial derivatives ∂^(k+l)S/∂u^k∂v^l
    plus first/second fundamental forms, curvatures (K, H, κ₁, κ₂).

References
----------
Piegl & Tiller. "The NURBS Book" 2nd ed. (Springer 1997) §3.3.
    Algorithm A2.3 (DersBasisFuns), A3.6 (SurfaceDerivsAlg2), A4.4 (rational).
do Carmo, M.P. "Differential Geometry of Curves and Surfaces" §3.2.
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
from kerf_core.utils.context import ProjectCtx  # type: ignore[import]

from kerf_cad_core.geom.nurbs_derivative import (
    fundamental_forms,
    surface_derivative_single,
    surface_derivatives,
)
from kerf_cad_core.geom.nurbs import NurbsSurface

import numpy as np


# ---------------------------------------------------------------------------
# Tool: nurbs_surface_derivative
# ---------------------------------------------------------------------------

_nurbs_surface_derivative_spec = ToolSpec(
    name="nurbs_surface_derivative",
    description=(
        "Compute analytic NURBS surface derivatives up to order d at parameter (u, v).\n"
        "\n"
        "Implements Piegl & Tiller A2.3 (DersBasisFuns) + A3.6 + A4.4 (rational\n"
        "quotient rule) for all mixed partials ∂^(k+l)S/∂u^k∂v^l where k+l ≤ d.\n"
        "\n"
        "Optionally (mode='fundamental_forms') also computes:\n"
        "  E, F, G — first fundamental form coefficients\n"
        "  L, M, N — second fundamental form coefficients\n"
        "  K       — Gaussian curvature\n"
        "  H       — mean curvature\n"
        "  k1, k2  — principal curvatures\n"
        "\n"
        "Returns:\n"
        "  mode='derivatives': derivatives dict keyed by '[k,l]' → [x,y,z]\n"
        "  mode='fundamental_forms': E,F,G,L,M,N,K,H,k1,k2 + S,Su,Sv\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "control_points": {
                "type": "array",
                "description": (
                    "NURBS surface control points as nested list: "
                    "shape (n_u, n_v, 3) or (n_u, n_v, 4) with weights. "
                    "If shape is (n_u, n_v, 3), unit weights are assumed."
                ),
                "items": {"type": "array"},
            },
            "knots_u": {
                "type": "array",
                "description": "Knot vector in the u direction.",
                "items": {"type": "number"},
            },
            "knots_v": {
                "type": "array",
                "description": "Knot vector in the v direction.",
                "items": {"type": "number"},
            },
            "degree_u": {
                "type": "integer",
                "description": "Degree in u direction.",
            },
            "degree_v": {
                "type": "integer",
                "description": "Degree in v direction.",
            },
            "u": {
                "type": "number",
                "description": "Parameter u ∈ [knots_u[0], knots_u[-1]].",
            },
            "v": {
                "type": "number",
                "description": "Parameter v ∈ [knots_v[0], knots_v[-1]].",
            },
            "order": {
                "type": "integer",
                "description": "Maximum derivative order d (default 2).",
            },
            "mode": {
                "type": "string",
                "enum": ["derivatives", "fundamental_forms"],
                "description": (
                    "'derivatives' (default) — return all mixed partials up to order d. "
                    "'fundamental_forms' — also compute curvature quantities."
                ),
            },
        },
        "required": [
            "control_points", "knots_u", "knots_v", "degree_u", "degree_v", "u", "v"
        ],
    },
)


@register(_nurbs_surface_derivative_spec, write=False)
async def run_nurbs_surface_derivative(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    try:
        cp_raw = np.array(a["control_points"], dtype=np.float64)
        knots_u = list(a["knots_u"])
        knots_v = list(a["knots_v"])
        degree_u = int(a["degree_u"])
        degree_v = int(a["degree_v"])
        u = float(a["u"])
        v = float(a["v"])
        order = int(a.get("order", 2))
        mode = str(a.get("mode", "derivatives"))

        # Build NurbsSurface — control_points can be (n_u, n_v, 3) or (n_u, n_v, 4)
        if cp_raw.ndim != 3 or cp_raw.shape[2] not in (3, 4):
            return err_payload(
                "control_points must be shape (n_u, n_v, 3) or (n_u, n_v, 4)",
                "BAD_ARGS",
            )
        n_u, n_v, dim = cp_raw.shape
        if dim == 3:
            # Add unit weights
            weights = np.ones((n_u, n_v, 1), dtype=np.float64)
            cp_raw = np.concatenate([cp_raw, weights], axis=2)

        surf = NurbsSurface(
            control_points=cp_raw,
            knots_u=knots_u,
            knots_v=knots_v,
            degree_u=degree_u,
            degree_v=degree_v,
        )
    except Exception as exc:
        return err_payload(f"invalid surface data: {exc}", "BAD_ARGS")

    try:
        if mode == "fundamental_forms":
            result = fundamental_forms(surf, u, v)
            # Convert ndarray values to lists for JSON serialisation
            payload = {}
            for k, val in result.items():
                if hasattr(val, "tolist"):
                    payload[k] = val.tolist()
                else:
                    payload[k] = val
            return ok_payload(payload)
        else:
            derivs = surface_derivatives(surf, u, v, order)
            # derivs is dict {(k,l): ndarray} or similar
            serialised: dict = {}
            for key, val in derivs.items():
                str_key = f"[{key[0]},{key[1]}]"
                if hasattr(val, "tolist"):
                    serialised[str_key] = val.tolist()
                else:
                    serialised[str_key] = list(val)
            return ok_payload({"derivatives": serialised, "u": u, "v": v, "order": order})
    except Exception as exc:
        return err_payload(f"derivative computation error: {exc}", "EVAL_ERROR")


__all__ = ["run_nurbs_surface_derivative"]
