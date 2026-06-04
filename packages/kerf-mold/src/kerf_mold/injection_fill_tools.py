"""
kerf_mold.injection_fill_tools — LLM tool wrapper for injection fill simulation.

Tool: mold_injection_fill_simulate
  Run a 1.5D Hele-Shaw injection fill simulation and return fill time,
  pressure drop, weld line locations, and air trap detection.

References:
    Hieber, C.A., Shen, S.F. (1980). J. Non-Newtonian Fluid Mech. 7, 1–32.
    Cross, M.M. (1965). J. Colloid Sci. 20, 417–437.
    Autodesk Moldflow Insight User Guide (public documentation).

HONEST: Simplified 1.5D model — not a substitute for production Moldflow analysis.
"""

from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_mold._compat import ToolSpec, err_payload, ok_payload, ProjectCtx

from kerf_mold.injection_fill import (
    InjectionFillSpec,
    PolymerMelt,
    POLYMER_LIBRARY,
    simulate_injection_fill,
    cross_wlf_viscosity,
)


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

mold_injection_fill_spec = ToolSpec(
    name="mold_injection_fill_simulate",
    description=(
        "1.5D Hele-Shaw injection fill simulation (Hieber-Shen 1980). "
        "Given cavity outline, gate locations, polymer, and process conditions, "
        "returns fill time [s], max pressure drop [MPa], weld line locations, "
        "air trap locations, and short-shot risk percentage. "
        "HONEST: Simplified 1.5D model — not a substitute for full 3D Moldflow. "
        "Use for early-stage design guidance only."
    ),
    input_schema={
        "type": "object",
        "required": ["part_thickness_mm", "gate_locations", "cavity_outline_polygon", "polymer_name"],
        "properties": {
            "part_thickness_mm": {
                "type": "number",
                "description": "Nominal wall thickness of the part (mm). Hele-Shaw assumption.",
            },
            "gate_locations": {
                "type": "array",
                "description": "List of [x, y] gate positions in the same coordinate system as cavity_outline_polygon.",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "minItems": 1,
            },
            "cavity_outline_polygon": {
                "type": "array",
                "description": "Closed polygon vertices [[x,y], ...] defining the 2D cavity boundary.",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "minItems": 3,
            },
            "polymer_name": {
                "type": "string",
                "description": "Polymer name. One of: ABS_Cycolac_T, PC_Makrolon_2407, PA66_Zytel.",
                "enum": ["ABS_Cycolac_T", "PC_Makrolon_2407", "PA66_Zytel"],
            },
            "mold_temp_c": {
                "type": "number",
                "description": "Mould temperature (°C). Default 60.",
                "default": 60.0,
            },
            "injection_pressure_mpa": {
                "type": "number",
                "description": "Injection pressure (MPa). Default 100.",
                "default": 100.0,
            },
            "fill_time_target_s": {
                "type": "number",
                "description": "Target fill time (s). Simulation is scaled to this. Default 1.5.",
                "default": 1.5,
            },
            "grid_resolution": {
                "type": "integer",
                "description": "Grid resolution (N×N). Higher = more accurate, slower. Default 64.",
                "default": 64,
                "minimum": 16,
                "maximum": 128,
            },
        },
    },
)


async def run_mold_injection_fill_simulate(params: dict[str, Any], ctx: Any) -> str:
    """Execute the injection fill simulation tool."""
    try:
        thickness = float(params["part_thickness_mm"])
        gates_raw = params["gate_locations"]
        outline_raw = params["cavity_outline_polygon"]
        poly_name = params["polymer_name"]

        gates = [tuple(g) for g in gates_raw]
        outline = [tuple(v) for v in outline_raw]

        polymer = POLYMER_LIBRARY.get(poly_name)
        if polymer is None:
            return err_payload(
                f"Unknown polymer '{poly_name}'. Available: {list(POLYMER_LIBRARY.keys())}",
                "UNKNOWN_POLYMER",
            )

        spec = InjectionFillSpec(
            part_thickness_mm=thickness,
            gate_locations=gates,
            cavity_outline_polygon=outline,
            polymer=polymer,
            mold_temp_c=float(params.get("mold_temp_c", 60.0)),
            injection_pressure_mpa=float(params.get("injection_pressure_mpa", 100.0)),
            fill_time_target_s=float(params.get("fill_time_target_s", 1.5)),
        )

        resolution = int(params.get("grid_resolution", 64))
        report = simulate_injection_fill(spec, grid_resolution=resolution)

        result = {
            "fill_time_s": round(report.fill_time_s, 4),
            "max_pressure_drop_mpa": round(report.max_pressure_drop_mpa, 3),
            "last_to_fill_count": len(report.last_to_fill_locations),
            "last_to_fill_locations": [
                {"x": round(x, 3), "y": round(y, 3)}
                for x, y in report.last_to_fill_locations[:10]
            ],
            "weld_line_count": len(report.weld_lines),
            "weld_lines": [
                [{"x": round(x, 3), "y": round(y, 3)} for x, y in wl[:10]]
                for wl in report.weld_lines[:5]
            ],
            "air_trap_count": len(report.air_traps),
            "air_traps": [
                {"x": round(x, 3), "y": round(y, 3)}
                for x, y in report.air_traps[:10]
            ],
            "short_shot_risk_pct": report.short_shot_risk_pct,
            "polymer": poly_name,
            "honest_caveat": report.honest_caveat,
        }
        return ok_payload(result)

    except Exception as exc:
        return err_payload(str(exc), "FILL_SIMULATION_ERROR")


# ---------------------------------------------------------------------------
# Cross-WLF viscosity tool
# ---------------------------------------------------------------------------

mold_cross_wlf_viscosity_spec = ToolSpec(
    name="mold_cross_wlf_viscosity",
    description=(
        "Compute polymer melt viscosity using the Cross-WLF model (Cross 1965). "
        "Returns dynamic viscosity η [Pa·s] as a function of shear rate and temperature. "
        "Demonstrates shear-thinning behaviour. "
        "HONEST: isothermal thin-film approximation."
    ),
    input_schema={
        "type": "object",
        "required": ["shear_rate_1_s", "temperature_c", "polymer_name"],
        "properties": {
            "shear_rate_1_s": {
                "type": "number",
                "description": "Apparent shear rate (1/s). Must be > 0.",
            },
            "temperature_c": {
                "type": "number",
                "description": "Polymer temperature (°C).",
            },
            "polymer_name": {
                "type": "string",
                "enum": ["ABS_Cycolac_T", "PC_Makrolon_2407", "PA66_Zytel"],
            },
        },
    },
)


async def run_mold_cross_wlf_viscosity(params: dict[str, Any], ctx: Any) -> str:
    """Execute the Cross-WLF viscosity tool."""
    try:
        shear_rate = float(params["shear_rate_1_s"])
        temp_c = float(params["temperature_c"])
        poly_name = params["polymer_name"]

        polymer = POLYMER_LIBRARY.get(poly_name)
        if polymer is None:
            return err_payload(
                f"Unknown polymer '{poly_name}'.",
                "UNKNOWN_POLYMER",
            )

        eta = cross_wlf_viscosity(shear_rate, temp_c, polymer)

        return ok_payload({
            "polymer": poly_name,
            "shear_rate_1_s": shear_rate,
            "temperature_c": temp_c,
            "viscosity_pa_s": round(eta, 6),
            "honest_caveat": (
                "Isothermal Cross-WLF viscosity only. "
                "Real injection fill involves temperature gradients and "
                "frozen skin effects not modelled here."
            ),
        })

    except Exception as exc:
        return err_payload(str(exc), "VISCOSITY_ERROR")


# ---------------------------------------------------------------------------
# TOOLS registry
# ---------------------------------------------------------------------------

TOOLS = [
    ("mold_injection_fill_simulate", mold_injection_fill_spec, run_mold_injection_fill_simulate),
    ("mold_cross_wlf_viscosity", mold_cross_wlf_viscosity_spec, run_mold_cross_wlf_viscosity),
]
