"""
kerf_mold.cooling_time_chen_chiang_tool
=========================================
LLM tool wrapper for the Chen-Chiang (1985) injection-mold cooling-time
calculator.

Registers:
  mold_compute_cooling_time_chen_chiang — compute cooling time for an
      injection-mold part wall using the 1-D Fourier first-term
      approximation (Chen-Chiang 1985; Menges 2001 §7.3.3; Beaumont 2007
      §10.4).

Errors returned as {"ok": false, "code": "...", "reason": "..."} — never
raises.

References
----------
Chen, C.-C. & Chiang, C.-H., "Injection Mold Cooling Time Analysis",
  ANTEC 1985, pp. 432–436.
Menges G., Michaeli W., Mohren P. "How to Make Injection Molds", 3rd ed.,
  Hanser 2001, §7.3.3.
Beaumont J.P. "Runner and Gating Design Handbook", 2nd ed., Hanser 2007,
  §10.4.
"""
from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_mold._compat import ToolSpec, err_payload, ok_payload, ProjectCtx

from kerf_mold.cooling_time_chen_chiang import (
    MaterialThermalProps,
    MATERIAL_THERMAL_DB,
    compute_cooling_time_chen_chiang,
)


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

mold_cooling_time_chen_chiang_spec = ToolSpec(
    name="mold_compute_cooling_time_chen_chiang",
    description=(
        "Compute injection-mold cooling time using the Chen-Chiang (1985) "
        "1-D Fourier thermal solution (Menges 2001 §7.3.3; Beaumont 2007 "
        "§10.4).\n\n"
        "Formula:\n"
        "  t_c = (h² / (π² · α)) · ln[(8/π²) · (T_m − T_w) / (T_e − T_w)]\n"
        "where h = wall thickness, α = thermal diffusivity, T_m = melt temp,\n"
        "T_w = mould wall temp, T_e = ejection temp.\n\n"
        "Built-in materials (Menges 2001 Table 7.3):\n"
        "  ABS  α=1.00e-7 m²/s, T_m=240°C, T_e=80°C\n"
        "  PC   α=1.50e-7 m²/s, T_m=300°C, T_e=100°C\n"
        "  PP   α=0.95e-7 m²/s, T_m=230°C, T_e=90°C\n"
        "  PA66 α=1.40e-7 m²/s, T_m=285°C, T_e=100°C\n"
        "  POM  α=0.95e-7 m²/s, T_m=210°C, T_e=90°C\n"
        "  PMMA α=1.13e-7 m²/s, T_m=240°C, T_e=80°C\n\n"
        "Returns: {ok, wall_thickness_mm, cooling_time_s, dominant_factor "
        "(thickness_squared|diffusivity|temp_window), material_used, "
        "honest_caveat}.\n\n"
        "Honest caveat: 1-D Fourier first-term approximation only — ignores "
        "cooling-channel layout and conformal-cooling effects; does NOT model "
        "crystallisation latent heat (semi-crystalline PP/PA66/POM times may "
        "be 15–30% longer), contact resistance, or hot-spot effects. Use "
        "Moldflow/Moldex3D/SigmaSoft for a full cooling-circuit simulation."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "wall_thickness_mm": {
                "type": "number",
                "description": (
                    "Total part wall thickness [mm]. Must be > 0. "
                    "This is the full section thickness, not the half-thickness."
                ),
            },
            "material_name": {
                "type": "string",
                "description": (
                    "Material grade (case-insensitive). "
                    "Built-in: ABS, PC, PP, PA66, POM, PMMA. "
                    "Default: ABS."
                ),
            },
            "T_wall_C": {
                "type": "number",
                "description": (
                    "Mould wall (coolant) temperature [°C]. Default: 40 °C."
                ),
            },
            "material_db_override": {
                "type": "object",
                "description": (
                    "Optional custom material entry. "
                    "Each key is a grade string; value is an object with: "
                    "{thermal_diffusivity_m2_per_s, T_melt_C, T_ejection_C}."
                ),
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "thermal_diffusivity_m2_per_s": {"type": "number"},
                        "T_melt_C": {"type": "number"},
                        "T_ejection_C": {"type": "number"},
                    },
                    "required": [
                        "thermal_diffusivity_m2_per_s",
                        "T_melt_C",
                        "T_ejection_C",
                    ],
                },
            },
        },
        "required": ["wall_thickness_mm"],
    },
)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

async def run_mold_compute_cooling_time_chen_chiang(
    ctx: "ProjectCtx",
    args: bytes,
) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    # wall_thickness_mm
    raw_h = a.get("wall_thickness_mm")
    if raw_h is None:
        return err_payload("wall_thickness_mm is required", "BAD_ARGS")
    try:
        wall_thickness_mm = float(raw_h)
    except (TypeError, ValueError) as exc:
        return err_payload(f"wall_thickness_mm: {exc}", "BAD_ARGS")

    # material_name
    material_name = str(a.get("material_name", "ABS"))

    # T_wall_C
    try:
        T_wall_C = float(a.get("T_wall_C", 40.0))
    except (TypeError, ValueError) as exc:
        return err_payload(f"T_wall_C: {exc}", "BAD_ARGS")

    # material_db_override
    material_db_override = None
    raw_override = a.get("material_db_override")
    if raw_override is not None:
        if not isinstance(raw_override, dict):
            return err_payload(
                "material_db_override must be a JSON object {grade: {props}}",
                "BAD_ARGS",
            )
        material_db_override = {}
        for grade, props_dict in raw_override.items():
            if not isinstance(props_dict, dict):
                return err_payload(
                    f"material_db_override['{grade}'] must be an object",
                    "BAD_ARGS",
                )
            try:
                material_db_override[grade] = MaterialThermalProps(
                    name=grade,
                    thermal_diffusivity_m2_per_s=float(
                        props_dict["thermal_diffusivity_m2_per_s"]
                    ),
                    T_melt_C=float(props_dict["T_melt_C"]),
                    T_ejection_C=float(props_dict["T_ejection_C"]),
                )
            except (KeyError, TypeError) as exc:
                return err_payload(
                    f"material_db_override['{grade}']: missing or wrong-type "
                    f"field: {exc}",
                    "BAD_ARGS",
                )
            except ValueError as exc:
                return err_payload(
                    f"material_db_override['{grade}']: {exc}", "BAD_ARGS"
                )

    try:
        report = compute_cooling_time_chen_chiang(
            wall_thickness_mm=wall_thickness_mm,
            material_name=material_name,
            T_wall_C=T_wall_C,
            material_db_override=material_db_override,
        )
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "OP_FAILED")

    return ok_payload({
        "ok": True,
        "wall_thickness_mm": report.wall_thickness_mm,
        "cooling_time_s": report.cooling_time_s,
        "dominant_factor": report.dominant_factor,
        "material_used": report.material_used,
        "honest_caveat": report.honest_caveat,
    })
