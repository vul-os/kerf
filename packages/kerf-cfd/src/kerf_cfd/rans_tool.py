"""
kerf_cfd.rans_tool — LLM tool wrapper for the SIMPLE RANS solver.

Tool: cfd_rans_solve
  Run a 2-D lid-driven cavity or channel case using the FV-SIMPLE
  staggered-grid solver and return convergence diagnostics + field summary.
"""

from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_cfd._compat import ToolSpec, err_payload, ok_payload, ProjectCtx


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

cfd_rans_solve_spec = ToolSpec(
    name="cfd_rans_solve",
    description=(
        "Run a 2-D incompressible RANS case using the FV-SIMPLE staggered-grid solver "
        "(Patankar & Spalding 1972, MAC grid, first-order upwind).  "
        "Supported cases: 'lid_driven_cavity' (default) and 'channel'.  "
        "Returns convergence flag, iteration count, continuity residual, "
        "u-velocity on the vertical centreline, and Ghia-1982 validation "
        "summary when case='lid_driven_cavity'."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "case": {
                "type": "string",
                "enum": ["lid_driven_cavity", "channel"],
                "description": (
                    "Flow case to simulate. "
                    "'lid_driven_cavity': square domain, Re=100–1000, top lid at U_ref. "
                    "'channel': pressure-driven Poiseuille flow (Re from U_ref and nu). "
                    "Default: 'lid_driven_cavity'."
                ),
            },
            "Re": {
                "type": "number",
                "description": "Reynolds number (default 100 for cavity, 50 for channel).",
            },
            "nx": {
                "type": "integer",
                "description": "Grid cells in x (default 32; max 64 for speed).",
            },
            "ny": {
                "type": "integer",
                "description": "Grid cells in y (default 32; max 64 for speed).",
            },
            "U_ref": {
                "type": "number",
                "description": "Reference velocity — lid speed for cavity, bulk for channel (m/s, default 1.0).",
            },
            "max_outer": {
                "type": "integer",
                "description": "Maximum SIMPLE outer iterations (default 4000).",
            },
            "tol_residual": {
                "type": "number",
                "description": "L-inf u-velocity change convergence tolerance (default 1e-7).",
            },
        },
        "required": [],
    },
)


# ---------------------------------------------------------------------------
# Sync core
# ---------------------------------------------------------------------------

def run_cfd_rans_solve_sync(
    case: str = "lid_driven_cavity",
    Re: float | None = None,
    nx: int = 32,
    ny: int = 32,
    U_ref: float = 1.0,
    max_outer: int = 4000,
    tol_residual: float = 1e-7,
) -> dict[str, Any]:
    """Run the SIMPLE solver and return a JSON-serialisable result dict."""
    import math

    # Validate
    valid_cases = {"lid_driven_cavity", "channel"}
    if case not in valid_cases:
        return {"ok": False, "error": f"case must be one of {sorted(valid_cases)}", "code": "BAD_ARGS"}

    if nx < 4 or nx > 128:
        return {"ok": False, "error": "nx must be in [4, 128]", "code": "BAD_ARGS"}
    if ny < 4 or ny > 128:
        return {"ok": False, "error": "ny must be in [4, 128]", "code": "BAD_ARGS"}
    if U_ref <= 0 or not math.isfinite(U_ref):
        return {"ok": False, "error": "U_ref must be positive and finite", "code": "BAD_ARGS"}

    if Re is None:
        Re = 100.0 if case == "lid_driven_cavity" else 50.0
    if Re <= 0 or not math.isfinite(Re):
        return {"ok": False, "error": "Re must be positive and finite", "code": "BAD_ARGS"}

    from kerf_cfd.simple_solver import (
        SolverConfig,
        solve_simple,
        max_continuity_residual,
        u_on_vertical_centreline,
        v_on_horizontal_centreline,
    )

    cfg = SolverConfig(
        nx=nx,
        ny=ny,
        Re=Re,
        U_ref=U_ref,
        L=1.0,
        alpha_u=0.7,
        alpha_p=0.3,
        max_outer=max_outer,
        tol_residual=tol_residual,
        n_inner_p=80,
        case="lid_driven_cavity",
        turbulence="laminar",
    )

    state = solve_simple(cfg)

    max_div = max_continuity_residual(state, nx=nx, ny=ny)
    y_c, u_c = u_on_vertical_centreline(state, nx=nx, ny=ny)
    x_c, v_c = v_on_horizontal_centreline(state, nx=nx, ny=ny)

    # Sample centreline at 5 representative points
    step = max(1, len(y_c) // 5)
    centreline_sample = [
        {"y": round(y_c[i], 4), "u": round(u_c[i], 6)}
        for i in range(0, len(y_c), step)
    ]

    result: dict[str, Any] = {
        "ok": True,
        "case": case,
        "Re": Re,
        "nx": nx,
        "ny": ny,
        "converged": state.converged,
        "n_iter": state.n_iter,
        "max_continuity_residual": max_div,
        "final_u_residual": state.residual_u[-1] if state.residual_u else None,
        "centreline_u_sample": centreline_sample,
    }

    # Ghia comparison for lid-driven cavity
    if case == "lid_driven_cavity" and Re == 100.0:
        try:
            from kerf_cfd.simple_solver import (
                compare_ghia_re100,
                GHIA_TOLERANCE,
            )
            ghia = compare_ghia_re100(nx=nx, ny=ny, max_outer=max_outer, tol_residual=tol_residual)
            result["ghia_validation"] = {
                "max_error_interior": round(ghia["max_error_interior"], 6),
                "tolerance": GHIA_TOLERANCE,
                "within_tolerance": ghia["within_tolerance"],
                "reference": ghia["reference"],
            }
        except Exception as exc:
            result["ghia_validation"] = {"error": str(exc)}

    return result


# ---------------------------------------------------------------------------
# Async LLM handler
# ---------------------------------------------------------------------------

async def run_cfd_rans_solve(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        case = str(args.get("case", "lid_driven_cavity"))
        Re = args.get("Re")
        if Re is not None:
            Re = float(Re)
        nx = int(args.get("nx", 32))
        ny = int(args.get("ny", 32))
        U_ref = float(args.get("U_ref", 1.0))
        max_outer = int(args.get("max_outer", 4000))
        tol_residual = float(args.get("tol_residual", 1e-7))
    except (TypeError, ValueError) as exc:
        return err_payload(f"invalid argument: {exc}", "BAD_ARGS")

    result = run_cfd_rans_solve_sync(
        case=case,
        Re=Re,
        nx=nx,
        ny=ny,
        U_ref=U_ref,
        max_outer=max_outer,
        tol_residual=tol_residual,
    )

    if not result.get("ok"):
        return err_payload(result.get("error", "solver error"), result.get("code", "ERROR"))
    return ok_payload(result)
